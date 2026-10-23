package app.griffonote

import android.Manifest
import android.app.Application
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.os.Environment
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.ui.text.TextRange
import androidx.compose.ui.text.input.TextFieldValue
import androidx.core.content.ContextCompat
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.asCoroutineDispatcher
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext
import java.util.concurrent.Executors

enum class Screen { LIST, EDITOR, SETTINGS }
enum class Section { NOTES, ARCHIVE, TRASH }

data class Snack(val text: String, val undo: (() -> Unit)? = null)

/** Everything the editor can change, for change detection and autosave. */
data class EditorSnapshot(
    val title: String,
    val text: String,
    val items: List<CheckItem>,
    val after: String,
    val color: String,
    val pinned: Boolean,
    val labels: List<String>,
)

class EditorState(note: Note?, val isNew: Boolean) {
    /** Last version known to be on disk (carries id, dates, extra frontmatter, reminder...). */
    var base: Note? = note

    var title by mutableStateOf(note?.title.orEmpty())
    var text by mutableStateOf(TextFieldValue(""))
    val items = mutableStateListOf<CheckItem>()
    var after by mutableStateOf("")
    var color by mutableStateOf(note?.color ?: DEFAULT_COLOR)
    var pinned by mutableStateOf(note?.pinned ?: false)
    var labels by mutableStateOf(note?.labels.orEmpty())
    var checkedExpanded by mutableStateOf(false)
    var pendingFocusId by mutableStateOf<Long?>(null)
    var focusTitle by mutableStateOf(false)
    var externalConflict by mutableStateOf(false)

    var lastSnapshot: EditorSnapshot? = null
    var loadedRaw: String? = null

    val folder: Folder get() = base?.folder ?: Folder.NOTES
    val readOnly: Boolean get() = folder == Folder.TRASH
    val conflict: Boolean get() = base?.conflict == true

    init {
        if (note != null) applyBody(note.body)
        lastSnapshot = if (note != null) snapshot() else null
    }

    fun applyBody(body: String) {
        val parts = BodyFormat.parse(body)
        text = TextFieldValue(parts.before, TextRange(parts.before.length))
        items.clear()
        items.addAll(parts.items)
        after = parts.after
    }

    fun body(): String = BodyFormat.build(BodyParts(text.text, items.toList(), after))

    fun snapshot() = EditorSnapshot(title, text.text, items.toList(), after, color, pinned, labels)

    fun reloadFrom(note: Note) {
        base = note
        title = note.title
        color = note.color
        pinned = note.pinned
        labels = note.labels
        applyBody(note.body)
        lastSnapshot = snapshot()
    }

    val isEmpty: Boolean get() = title.isBlank() && body().isBlank()
}

class MainViewModel(app: Application) : AndroidViewModel(app) {
    val settings = Settings(app)
    val repo = NoteRepository(app, settings)
    val notes = repo.notes

    private val io = Executors.newSingleThreadExecutor().asCoroutineDispatcher()
    private val persistLock = Mutex()

    var screen by mutableStateOf(Screen.LIST)
    var editor by mutableStateOf<EditorState?>(null)
    var section by mutableStateOf(Section.NOTES)
    var labelFilter by mutableStateOf<String?>(null)
    var query by mutableStateOf("")
    var searching by mutableStateOf(false)
    var snack by mutableStateOf<Snack?>(null)

    var gridView by mutableStateOf(settings.gridView)
    var theme by mutableStateOf(settings.theme)
    var trashDays by mutableStateOf(settings.trashDays)
    var storageLabel by mutableStateOf("")
    var storageReady by mutableStateOf(false)
    var pendingStorage by mutableStateOf<StorageConfig?>(null)
    var updateState by mutableStateOf<Updater.State>(Updater.State.Idle)

    private var scanJob: Job? = null

    init {
        Updater.cleanup(app)
        repo.onExternalChange = { viewModelScope.launch { delay(400); refresh() } }
        storageReady = checkStorageReady()
        if (storageReady) refresh()
    }

    // ---- storage ----

    fun checkStorageReady(): Boolean = when (val c = settings.storage) {
        StorageConfig.Default ->
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) Environment.isExternalStorageManager()
            else ContextCompat.checkSelfPermission(
                getApplication(), Manifest.permission.WRITE_EXTERNAL_STORAGE,
            ) == PackageManager.PERMISSION_GRANTED
        is StorageConfig.Tree ->
            getApplication<Application>().contentResolver.persistedUriPermissions
                .any { it.uri == c.uri && it.isWritePermission }
    }

    fun onResume() {
        val ready = checkStorageReady()
        if (ready != storageReady) storageReady = ready
        if (ready) {
            refresh()
            repo.startWatching()
            checkExternal()
        }
    }

    fun onPause() {
        repo.stopWatching()
        flushEditor()
    }

    fun refresh() {
        if (!storageReady) return
        scanJob?.cancel()
        scanJob = viewModelScope.launch {
            withContext(io) {
                (repo.fs as? FileFs)?.root?.mkdirs()
                repo.scan()
                storageLabel = repo.fs.describe()
            }
        }
    }

    fun requestStorageChange(config: StorageConfig) {
        pendingStorage = config
    }

    fun confirmStorageChange(move: Boolean) {
        val target = pendingStorage ?: return
        pendingStorage = null
        viewModelScope.launch {
            withContext(io) {
                if (move) repo.migrateTo(repo.buildFsFor(target), deleteSource = true)
                settings.storageUri = (target as? StorageConfig.Tree)?.uri?.toString()
                repo.stopWatching()
                repo.reconfigure()
            }
            storageReady = checkStorageReady()
            refresh()
            repo.startWatching()
        }
    }

    // ---- settings ----

    fun changeGridView(v: Boolean) { gridView = v; settings.gridView = v }
    fun changeTheme(v: ThemeMode) { theme = v; settings.theme = v }
    fun changeTrashDays(v: Int) { trashDays = v; settings.trashDays = v }

    // ---- navigation ----

    fun selectSection(s: Section, label: String? = null) {
        section = s
        labelFilter = label
        query = ""
        searching = false
        screen = Screen.LIST
    }

    fun openSettings() { screen = Screen.SETTINGS }

    fun back() {
        when (screen) {
            Screen.EDITOR -> closeEditor()
            Screen.SETTINGS -> screen = Screen.LIST
            Screen.LIST -> when {
                searching -> { searching = false; query = "" }
                section != Section.NOTES || labelFilter != null -> selectSection(Section.NOTES)
            }
        }
    }

    // ---- editor ----

    fun newNote(title: String = "", text: String = "", checklist: Boolean = false) {
        val ed = EditorState(null, isNew = true)
        ed.title = title
        if (checklist) {
            val lines = text.lines().filter { it.isNotBlank() }
            if (lines.isEmpty()) ed.items.add(CheckItem(ItemIds.next(), "", false).also { ed.pendingFocusId = it.id })
            else lines.forEach { ed.items.add(CheckItem(ItemIds.next(), it.trim(), false)) }
        } else {
            ed.text = TextFieldValue(text, TextRange(text.length))
            ed.focusTitle = title.isEmpty() && text.isEmpty()
        }
        editor = ed
        screen = Screen.EDITOR
    }

    fun openNote(note: Note) {
        val ed = EditorState(note, isNew = false)
        ed.loadedRaw = note.let { repo.fs.readText(it.path) }
        editor = ed
        screen = Screen.EDITOR
    }

    fun handleShare(subject: String?, text: String?) {
        if (text.isNullOrBlank() && subject.isNullOrBlank()) return
        newNote(title = subject.orEmpty(), text = text.orEmpty())
    }

    private fun buildNote(ed: EditorState, snap: EditorSnapshot, body: String): Note {
        val now = System.currentTimeMillis()
        val b = ed.base
        return if (b == null) {
            Note(
                path = "", folder = Folder.NOTES, id = NoteFormat.generateId(), title = snap.title,
                color = snap.color, pinned = snap.pinned, labels = snap.labels,
                created = now, updated = now, body = body,
            )
        } else {
            b.copy(
                title = snap.title, color = snap.color, pinned = snap.pinned,
                labels = snap.labels, body = body, updated = now,
            )
        }
    }

    /** Writes the editor to disk if something changed. */
    suspend fun persist(ed: EditorState) {
        val snap = ed.snapshot()
        val body = ed.body()
        if (ed.readOnly || snap == ed.lastSnapshot) return
        if (ed.base == null && snap.title.isBlank() && body.isBlank()) return
        persistLock.withLock {
            val note = buildNote(ed, snap, body)
            try {
                val saved = withContext(io) {
                    repo.save(note).also { ed.loadedRaw = repo.readRaw(it.path) }
                }
                ed.base = saved
                ed.lastSnapshot = snap
            } catch (e: Exception) {
                snack = Snack("Échec de l'enregistrement : ${e.message}")
            }
        }
    }

    fun flushEditor() {
        val ed = editor ?: return
        if (screen != Screen.EDITOR) return
        viewModelScope.launch { persist(ed) }
    }

    fun closeEditor() {
        val ed = editor
        screen = Screen.LIST
        editor = null
        if (ed != null) viewModelScope.launch { persist(ed) }
    }

    /** Called on resume and when a file changed: reload or ask, never overwrite silently. */
    fun checkExternal() {
        val ed = editor ?: return
        val path = ed.base?.path ?: return
        viewModelScope.launch {
            val raw = withContext(io) { repo.readRaw(path) } ?: return@launch
            if (raw == ed.loadedRaw) return@launch
            val dirty = ed.snapshot() != ed.lastSnapshot
            val modified = withContext(io) { repo.fs.lastModified(path) }
            val note = NoteFormat.parse(path, ed.folder, raw, modified)
            if (!dirty) {
                ed.reloadFrom(note)
                ed.loadedRaw = raw
            } else {
                ed.externalConflict = true
            }
        }
    }

    fun resolveExternal(keepMine: Boolean) {
        val ed = editor ?: return
        ed.externalConflict = false
        viewModelScope.launch {
            val path = ed.base?.path ?: return@launch
            val raw = withContext(io) { repo.readRaw(path) } ?: return@launch
            if (keepMine) {
                ed.loadedRaw = raw
                ed.base = ed.base?.let { b ->
                    NoteFormat.parse(path, ed.folder, raw, 0L).let { disk -> b.copy(extra = disk.extra) }
                }
                ed.lastSnapshot = null // force the write
                persist(ed)
            } else {
                val modified = withContext(io) { repo.fs.lastModified(path) }
                ed.reloadFrom(NoteFormat.parse(path, ed.folder, raw, modified))
                ed.loadedRaw = raw
            }
        }
    }

    private fun moveEditorNote(target: Folder, message: String) {
        val ed = editor ?: return
        viewModelScope.launch {
            persist(ed)
            val note = ed.base
            if (note == null) { closeEditor(); return@launch }
            val previous = note.folder
            val moved = withContext(io) { repo.moveTo(note, target) }
            screen = Screen.LIST
            editor = null
            snack = Snack(message) {
                viewModelScope.launch { withContext(io) { repo.moveTo(moved, previous) } }
            }
        }
    }

    fun archiveEditorNote() = moveEditorNote(Folder.ARCHIVE, "Note archivée")
    fun unarchiveEditorNote() = moveEditorNote(Folder.NOTES, "Note désarchivée")
    fun trashEditorNote() = moveEditorNote(Folder.TRASH, "Note placée dans la corbeille")
    fun restoreEditorNote() = moveEditorNote(Folder.NOTES, "Note restaurée")

    fun deleteEditorNoteForever() {
        val note = editor?.base
        screen = Screen.LIST
        editor = null
        if (note != null) viewModelScope.launch { withContext(io) { repo.deleteForever(note) } }
    }

    fun emptyTrash() {
        viewModelScope.launch { withContext(io) { repo.emptyTrash() } }
    }

    fun keepConflictCopy() {
        val ed = editor ?: return
        viewModelScope.launch {
            persist(ed)
            val note = ed.base ?: return@launch
            val kept = withContext(io) { repo.keepConflictCopy(note) }
            ed.reloadFrom(kept)
            snack = Snack("Cette version a remplacé l'originale")
        }
    }

    fun convertToChecklist() {
        val ed = editor ?: return
        if (ed.items.isEmpty()) {
            val lines = ed.text.text.lines().map { it.trim().removePrefix("- ").trim() }.filter { it.isNotEmpty() }
            ed.text = TextFieldValue("")
            if (lines.isEmpty()) {
                ed.items.add(CheckItem(ItemIds.next(), "", false).also { ed.pendingFocusId = it.id })
            } else {
                lines.forEach { ed.items.add(CheckItem(ItemIds.next(), it, false)) }
            }
        } else {
            val asText = ed.items.joinToString("\n") { "- ${it.text}" }
            val merged = listOf(ed.text.text.trimEnd(), asText).filter { it.isNotEmpty() }.joinToString("\n\n")
            ed.items.clear()
            ed.text = TextFieldValue(merged, TextRange(merged.length))
        }
    }

    fun allLabels(): List<String> =
        notes.value.filter { it.folder != Folder.TRASH }.flatMap { it.labels }.distinct().sortedBy { it.fold() }

    // ---- updates ----

    fun checkUpdate() {
        if (updateState is Updater.State.Checking || updateState is Updater.State.Downloading) return
        updateState = Updater.State.Checking
        viewModelScope.launch {
            updateState = try {
                val info = withContext(Dispatchers.IO) { Updater.check() }
                if (info == null) Updater.State.UpToDate else Updater.State.Available(info)
            } catch (e: Exception) {
                Updater.State.Error(e.message ?: "Erreur réseau")
            }
        }
    }

    /** Silent check at launch: stays quiet unless an update exists. */
    fun checkUpdateSilently() {
        viewModelScope.launch {
            val info = try { withContext(Dispatchers.IO) { Updater.check() } } catch (_: Exception) { null }
            if (info != null && updateState is Updater.State.Idle) updateState = Updater.State.Available(info)
        }
    }

    fun downloadAndInstall() {
        val info = (updateState as? Updater.State.Available)?.info ?: return
        val ctx = getApplication<Application>()
        updateState = Updater.State.Downloading(0)
        viewModelScope.launch {
            try {
                val apk = withContext(Dispatchers.IO) {
                    Updater.download(ctx, info) { p -> updateState = Updater.State.Downloading(p) }
                }
                updateState = Updater.State.Available(info)
                Updater.install(ctx, apk)
            } catch (e: Exception) {
                updateState = Updater.State.Error(e.message ?: "Échec du téléchargement")
            }
        }
    }

    fun pickedTree(uri: Uri) {
        requestStorageChange(StorageConfig.Tree(uri))
    }
}
