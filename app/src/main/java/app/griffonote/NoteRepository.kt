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
        for (entry in fs.list("")) {
            if (entry.isDir || !isNoteFile(entry.name) || entry.name.startsWith(".")) continue
            val path = entry.name
            seen.add(path)
            val cached = parsed[path]
            val note = if (cached != null && cached.first == entry.lastModified) {
                cached.second
            } else {
                val text = fs.readText(path) ?: continue
                NoteFormat.parse(path, text, entry.lastModified).also { parsed[path] = entry.lastModified to it }
            }
            result.add(note)
        }
        parsed.keys.retainAll(seen)
        _notes.value = result
    }

    fun startWatching() {
        stopWatching()
        val fileFs = fs as? FileFs ?: return
        val mask = FileObserver.CREATE or FileObserver.DELETE or FileObserver.MODIFY or
            FileObserver.MOVED_FROM or FileObserver.MOVED_TO or FileObserver.CLOSE_WRITE
        val dir = fileFs.root
        if (!dir.isDirectory) return
        observers = listOf(
            object : FileObserver(dir.absolutePath, mask) {
                override fun onEvent(event: Int, path: String?) {
                    if (path != null && isNoteFile(path)) onExternalChange?.invoke()
                }
            }.also { it.startWatching() },
        )
    }

    fun stopWatching() {
        observers.forEach { it.stopWatching() }
        observers = emptyList()
    }

    /** Called (from an arbitrary thread) when a `.md` file changed on disk. */
    var onExternalChange: (() -> Unit)? = null

    /** A note, or a conflict copy left by the sync tool (`name.md.conflict1`, `name.md.conflict2`). */
    private fun isNoteFile(name: String) = name.endsWith(".md") || CONFLICT_COPY.matches(name)

    fun existingLabels(): List<String> =
        _notes.value.flatMap { it.labels }.distinct().sortedBy { it.fold() }

    // ---- writes ----

    /** Writes [note] to disk (creating its file on first save) and updates the index. */
    fun save(note: Note): Note {
        var n = note
        if (n.path.isEmpty()) {
            val ids = _notes.value.map { it.id }.toSet()
            var id = n.id
            while (id in ids || id.isEmpty()) id = NoteFormat.generateId()
            n = n.copy(id = id, path = NoteFormat.fileNameFor(n.title, id), hasId = true)
        }
        n = n.copy(hasId = true)
        fs.writeText(n.path, NoteFormat.serialize(n))
        val modified = fs.lastModified(n.path)
        parsed[n.path] = modified to n
        _notes.value = _notes.value.filter { it.path != n.path } + n
        return n
    }

    fun readRaw(path: String): String? = fs.readText(path)

    fun delete(note: Note) {
        fs.delete(note.path)
        note.pdf?.let { fs.delete(it) }
        parsed.remove(note.path)
        _notes.value = _notes.value.filter { it.path != note.path }
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
        // Synchrotron leaves one copy per side (.conflict1 / .conflict2): resolving keeps one, drops the others.
        _notes.value.filter { it.conflict && it.id == copy.id && it.path != copy.path }.forEach {
            fs.delete(it.path)
            parsed.remove(it.path)
        }
        parsed.remove(copy.path)
        parsed[targetPath] = fs.lastModified(targetPath) to kept
        _notes.value = _notes.value.filter { it.path != copy.path && it.path != targetPath && !(it.conflict && it.id == copy.id) } + kept
        return kept
    }

    /** Copies every file of the current storage into [target] and optionally empties the source. */
    fun migrateTo(target: Fs, deleteSource: Boolean) {
        fun walk(dir: String) {
            for (e in fs.list(dir)) {
                val p = if (dir.isEmpty()) e.name else "$dir/${e.name}"
                if (e.isDir) walk(p)
                else if (!isTempName(e.name)) {
                    fs.readBytes(p)?.let { target.writeBytes(p, it) }
                    if (deleteSource) fs.delete(p)
                }
            }
        }
        walk("")
    }

    fun buildFsFor(config: StorageConfig): Fs = buildFs(config)

    private companion object {
        val CONFLICT_COPY = Regex(""".+\.md\.conflict\d+""")
    }
}
