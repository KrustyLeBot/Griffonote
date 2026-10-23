package app.griffonote

import android.content.Context
import android.os.FileObserver
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import java.io.File

/**
 * The storage folder is the source of truth; [notes] is only an in-memory index
 * rebuilt by [scan]. Every method here does blocking I/O: call from Dispatchers.IO.
 */
class NoteRepository(private val context: Context, private val settings: Settings) {
    private val _notes = MutableStateFlow<List<Note>>(emptyList())
    val notes: StateFlow<List<Note>> = _notes

    private val parsed = HashMap<String, Pair<Long, Note>>() // path -> (lastModified, note)
    private var observers: List<FileObserver> = emptyList()
    var fs: Fs = buildFs(settings.storage)
        private set

    private fun buildFs(config: StorageConfig): Fs = when (config) {
        StorageConfig.Default -> FileFs(Settings.defaultDir())
        is StorageConfig.Tree -> SafFs(context, config.uri)
    }

    fun reconfigure() {
        fs = buildFs(settings.storage)
        parsed.clear()
        _notes.value = emptyList()
    }

    /** Full rescan: reads only files whose modification time changed. */
    fun scan() {
        val result = ArrayList<Note>()
        val seen = HashSet<String>()
        val purgeBefore = System.currentTimeMillis() - settings.trashDays * 86_400_000L
        for (folder in Folder.entries) {
            for (entry in fs.list(folder.dir)) {
                if (entry.isDir || !entry.name.endsWith(".md") || entry.name.startsWith(".")) continue
                val path = if (folder.dir.isEmpty()) entry.name else "${folder.dir}/${entry.name}"
                seen.add(path)
                val cached = parsed[path]
                val note = if (cached != null && cached.first == entry.lastModified) {
                    cached.second
                } else {
                    val text = fs.readText(path) ?: continue
                    NoteFormat.parse(path, folder, text, entry.lastModified).also {
                        parsed[path] = entry.lastModified to it
                    }
                }
                if (folder == Folder.TRASH && (note.trashed ?: entry.lastModified) < purgeBefore) {
                    fs.delete(path)
                    parsed.remove(path)
                    continue
                }
                result.add(note)
            }
        }
        parsed.keys.retainAll(seen)
        _notes.value = result
    }

    fun startWatching() {
        stopWatching()
        val fileFs = fs as? FileFs ?: return
        val mask = FileObserver.CREATE or FileObserver.DELETE or FileObserver.MODIFY or
            FileObserver.MOVED_FROM or FileObserver.MOVED_TO or FileObserver.CLOSE_WRITE
        observers = Folder.entries.mapNotNull { folder ->
            val dir = if (folder.dir.isEmpty()) fileFs.root else File(fileFs.root, folder.dir)
            if (!dir.isDirectory) return@mapNotNull null
            object : FileObserver(dir.absolutePath, mask) {
                override fun onEvent(event: Int, path: String?) {
                    if (path != null && path.endsWith(".md")) onExternalChange?.invoke()
                }
            }.also { it.startWatching() }
        }
    }

    fun stopWatching() {
        observers.forEach { it.stopWatching() }
        observers = emptyList()
    }

    /** Called (from an arbitrary thread) when a `.md` file changed on disk. */
    var onExternalChange: (() -> Unit)? = null

    fun existingLabels(): List<String> =
        _notes.value.filter { it.folder != Folder.TRASH }.flatMap { it.labels }.distinct().sortedBy { it.fold() }

    // ---- writes ----

    /** Writes [note] to disk (creating its file on first save) and updates the index. */
    fun save(note: Note): Note {
        var n = note
        if (n.path.isEmpty()) {
            val ids = _notes.value.map { it.id }.toSet()
            var id = n.id
            while (id in ids || id.isEmpty()) id = NoteFormat.generateId()
            val dir = n.folder.dir
            val name = NoteFormat.fileNameFor(n.title, id)
            n = n.copy(id = id, path = if (dir.isEmpty()) name else "$dir/$name", hasId = true)
        }
        n = n.copy(hasId = true)
        fs.writeText(n.path, NoteFormat.serialize(n))
        val modified = fs.lastModified(n.path)
        parsed[n.path] = modified to n
        _notes.value = _notes.value.filter { it.path != n.path } + n
        return n
    }

    fun readRaw(path: String): String? = fs.readText(path)

    fun moveTo(note: Note, folder: Folder): Note {
        if (note.folder == folder) return note
        val name = note.fileName
        var target = if (folder.dir.isEmpty()) name else "${folder.dir}/$name"
        if (fs.exists(target)) {
            target = target.removeSuffix(".md").let { "$it-${NoteFormat.generateId()}.md" }
        }
        val moved = note.copy(
            path = target,
            folder = folder,
            trashed = if (folder == Folder.TRASH) System.currentTimeMillis() else null,
            pinned = if (folder == Folder.NOTES) note.pinned else false,
        )
        fs.writeText(target, NoteFormat.serialize(moved))
        fs.delete(note.path)
        parsed.remove(note.path)
        parsed[target] = fs.lastModified(target) to moved
        _notes.value = _notes.value.filter { it.path != note.path } + moved
        return moved
    }

    fun deleteForever(note: Note) {
        fs.delete(note.path)
        parsed.remove(note.path)
        _notes.value = _notes.value.filter { it.path != note.path }
    }

    fun emptyTrash() {
        _notes.value.filter { it.folder == Folder.TRASH }.forEach { deleteForever(it) }
    }

    /**
     * Conflict resolution: this copy replaces the original (same id, no "conflict" in its name).
     */
    fun keepConflictCopy(copy: Note): Note {
        val original = _notes.value.firstOrNull { it.id == copy.id && !it.conflict && it.path != copy.path }
        val targetPath = original?.path ?: copy.path.replace(Regex("(?i)[ ._-]*conflict[^.]*"), "")
        val kept = copy.copy(path = targetPath, conflict = false, updated = System.currentTimeMillis())
        fs.writeText(targetPath, NoteFormat.serialize(kept))
        if (targetPath != copy.path) fs.delete(copy.path)
        parsed.remove(copy.path)
        parsed[targetPath] = fs.lastModified(targetPath) to kept
        _notes.value = _notes.value.filter { it.path != copy.path && it.path != targetPath } + kept
        return kept
    }

    /** Copies every file of the current storage into [target] and optionally empties the source. */
    fun migrateTo(target: Fs, deleteSource: Boolean) {
        fun walk(dir: String) {
            for (e in fs.list(dir)) {
                val p = if (dir.isEmpty()) e.name else "$dir/${e.name}"
                if (e.isDir) walk(p)
                else if (!(e.name.startsWith(".") && e.name.endsWith(".tmp"))) {
                    fs.readBytes(p)?.let { target.writeBytes(p, it) }
                    if (deleteSource) fs.delete(p)
                }
            }
        }
        walk("")
    }

    fun buildFsFor(config: StorageConfig): Fs = buildFs(config)
}
