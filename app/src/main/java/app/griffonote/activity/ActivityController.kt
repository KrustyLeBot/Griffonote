package app.griffonote.activity

import android.app.Application
import android.net.Uri
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import app.griffonote.Note
import app.griffonote.NoteFormat
import app.griffonote.NoteRepository
import app.griffonote.Snack
import app.griffonote.record.Recorder
import kotlinx.coroutines.CoroutineDispatcher
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/** A file read from the picker, waiting for the user to confirm its name and sport. */
class PendingImport(val bytes: ByteArray, val extension: String, val track: Track, val sport: Sport, val title: String)

/** An opened activity: its note and what the track file says. */
class ActivityDetail(val note: Note, val track: Track?, val analysis: Analysis?, val error: String? = null) {
    val sport: Sport get() = note.activity?.sport ?: Sport.GPS
}

/** Everything the "Activités" folder does besides drawing: import, open, edit, delete, save a recording. */
class ActivityController(
    private val app: Application,
    private val repo: NoteRepository,
    private val scope: CoroutineScope,
    private val io: CoroutineDispatcher,
    private val say: (Snack) -> Unit,
    private val copyIn: (Uri) -> String,
) {
    val activities = repo.activities

    var pending by mutableStateOf<PendingImport?>(null)
        private set
    var detail by mutableStateOf<ActivityDetail?>(null)
        private set
    var busy by mutableStateOf(false)
        private set

    /** Called when an activity is opened, so the app can show its screen. */
    var onOpen: (() -> Unit)? = null

    // ---- import ----

    /** Reads a FIT or GPX file and asks the user to confirm. Nothing is written yet. */
    fun startImport(uri: Uri) {
        if (busy) return
        busy = true
        scope.launch {
            try {
                val p = withContext(io) {
                    val bytes = app.contentResolver.openInputStream(uri)?.use { it.readBytes() }
                        ?: throw java.io.IOException("Fichier illisible")
                    if (bytes.size > 50_000_000) throw java.io.IOException("Fichier trop gros")
                    val track: Track
                    val ext: String
                    if (Fit.looksLikeFit(bytes)) {
                        track = Fit.read(bytes); ext = "fit"
                    } else {
                        val text = String(bytes, Charsets.UTF_8)
                        if (!Gpx.looksLikeGpx(text)) throw Fit.FitException("Format non reconnu : il faut un fichier FIT ou GPX")
                        track = Gpx.read(text); ext = "gpx"
                    }
                    if (track.points.isEmpty() && track.sessionDistance == null) throw Fit.FitException("Aucune position dans ce fichier")
                    val sport = if (ext == "fit") Sport.fromFit(track.fitSport) else Sport.WALK
                    PendingImport(bytes, ext, track, sport, defaultTitle(sport, track.startTime ?: System.currentTimeMillis(), track.name))
                }
                pending = p
            } catch (e: Exception) {
                say(Snack("Import impossible : ${e.message}"))
            } finally {
                busy = false
            }
        }
    }

    fun cancelImport() { pending = null }

    fun confirmImport(title: String, sport: Sport) {
        val p = pending ?: return
        pending = null
        busy = true
        scope.launch {
            try {
                val note = withContext(io) { saveNew(p.track, sport, title.trim().ifEmpty { p.title }, p.bytes, p.extension) }
                open(note)
            } catch (e: Exception) {
                say(Snack("Import impossible : ${e.message}"))
            } finally {
                busy = false
            }
        }
    }

    /** Writes the track file and the note. Blocking: call from the IO dispatcher. */
    fun saveNew(track: Track, sport: Sport, title: String, bytes: ByteArray, extension: String): Note {
        val a = Analyzer.analyze(track, sport)
        val now = System.currentTimeMillis()
        val ids = (repo.notes.value + repo.activities.value).map { it.id }.toSet()
        var id = NoteFormat.generateId()
        while (id in ids) id = NoteFormat.generateId()
        val file = "attachments/" + NoteFormat.slug(title) + "-$id.$extension"
        repo.fs.writeBytes(file, bytes)
        val info = ActivityInfo.from(sport, a, track, file)
        return repo.save(
            Note(
                path = NoteRepository.ACTIVITIES_DIR + "/" + NoteFormat.fileNameFor(title, id), id = id, title = title,
                created = now, updated = now, activity = info, attachments = listOf(file),
            ),
        )
    }

    /** A time-only activity (treadmill, gym…), possibly with a distance typed by hand. Blocking. */
    private fun saveManualNow(title: String, sport: Sport, start: Long, seconds: Long, distance: Double): Note {
        val now = System.currentTimeMillis()
        val ids = (repo.notes.value + repo.activities.value).map { it.id }.toSet()
        var id = NoteFormat.generateId()
        while (id in ids) id = NoteFormat.generateId()
        return repo.save(
            Note(
                path = NoteRepository.ACTIVITIES_DIR + "/" + NoteFormat.fileNameFor(title, id), id = id, title = title,
                created = now, updated = now,
                activity = ActivityInfo(sport, start, seconds, seconds, distance),
            ),
        )
    }

    /** Edits the distance of an activity without a track (typed after the fact). */
    fun setManualDistance(note: Note, meters: Double) {
        val info = note.activity ?: return
        if (info.file != null) return
        scope.launch {
            val saved = withContext(io) {
                repo.save(note.copy(activity = info.copy(distance = meters), updated = System.currentTimeMillis()))
            }
            detail = ActivityDetail(saved, null, null)
        }
    }

    // ---- recordings ----

    /** Turns the recording log into an activity (FIT file + note). [distance] is for activities without GPS. */
    fun saveRecording(log: String, title: String, distance: Double?) {
        busy = true
        scope.launch {
            try {
                val note = withContext(io) {
                    val rec = RecordingLog.parse(log) ?: throw java.io.IOException("Enregistrement illisible")
                    val name = title.trim().ifEmpty { defaultTitle(rec.sport, rec.start) }
                    val end = rec.track.points.lastOrNull()?.time ?: System.currentTimeMillis()
                    if (rec.sport.hasGps && rec.track.points.size >= 2) {
                        val analysis = Analyzer.analyze(rec.track, rec.sport)
                        val bytes = Fit.write(rec.track, rec.sport, analysis.stats.distance)
                        saveNew(rec.track, rec.sport, name, bytes, "fit")
                    } else {
                        val seconds = ((end - rec.start - rec.track.pauses.sumOf { it.end - it.start }) / 1000).coerceAtLeast(0)
                        saveManualNow(name, rec.sport, rec.start, seconds, distance ?: 0.0)
                    }
                }
                Recorder.discard()
                open(note)
            } catch (e: Exception) {
                say(Snack("Enregistrement impossible : ${e.message}. L'activité reste à enregistrer."))
            } finally {
                busy = false
            }
        }
    }

    // ---- open / edit / delete ----

    fun open(note: Note) {
        detail = ActivityDetail(note, null, null)
        onOpen?.invoke()
        val info = note.activity ?: return
        val file = info.file ?: return
        scope.launch {
            val loaded = withContext(io) {
                try {
                    val bytes = repo.fs.readBytes(file) ?: throw java.io.IOException("Fichier introuvable (pas encore synchronisé ?)")
                    val track = if (Fit.looksLikeFit(bytes)) Fit.read(bytes) else Gpx.read(String(bytes, Charsets.UTF_8))
                    ActivityDetail(note, track, Analyzer.analyze(track, info.sport))
                } catch (e: Exception) {
                    ActivityDetail(note, null, null, e.message ?: "Lecture impossible")
                }
            }
            if (detail?.note?.path == note.path) detail = loaded
        }
    }

    fun close() { detail = null }

    /** Title, description and sport; a new sport recomputes the figures from the track. */
    fun update(note: Note, title: String, description: String, sport: Sport) {
        scope.launch {
            val saved = withContext(io) {
                var info = note.activity
                val current = detail?.takeIf { it.note.path == note.path }
                if (info != null && info.sport != sport) {
                    val track = current?.track
                    info = if (track != null) ActivityInfo.from(sport, Analyzer.analyze(track, sport), track, info.file) else info.copy(sport = sport)
                }
                repo.save(note.copy(title = title.trim().ifEmpty { note.title }, body = description.trim(), activity = info, updated = System.currentTimeMillis()))
            }
            val track = detail?.track
            detail = ActivityDetail(saved, track, track?.let { Analyzer.analyze(it, saved.activity?.sport ?: sport) }, detail?.error)
        }
    }

    fun delete(note: Note) {
        detail = null
        scope.launch { withContext(io) { repo.delete(note) } }
    }

    fun addPhoto(note: Note, uri: Uri) {
        scope.launch {
            try {
                val saved = withContext(io) {
                    val fresh = repo.activities.value.firstOrNull { it.path == note.path } ?: note
                    repo.save(fresh.copy(attachments = fresh.attachments + copyIn(uri), updated = System.currentTimeMillis()))
                }
                detail = detail?.let { ActivityDetail(saved, it.track, it.analysis, it.error) }
            } catch (e: Exception) {
                say(Snack("Photo impossible : ${e.message}"))
            }
        }
    }

    fun removePhoto(note: Note, path: String) {
        scope.launch {
            val saved = withContext(io) {
                val fresh = repo.activities.value.firstOrNull { it.path == note.path } ?: note
                repo.fs.delete(path)
                repo.save(fresh.copy(attachments = fresh.attachments - path, updated = System.currentTimeMillis()))
            }
            detail = detail?.let { ActivityDetail(saved, it.track, it.analysis, it.error) }
        }
    }

    companion object {
        fun defaultTitle(sport: Sport, time: Long, name: String? = null): String {
            if (!name.isNullOrBlank()) return name.trim()
            val date = SimpleDateFormat("d MMM yyyy", Locale.FRANCE).format(Date(time))
            return "${sport.label.substringBefore(" (")} du $date"
        }
    }
}
