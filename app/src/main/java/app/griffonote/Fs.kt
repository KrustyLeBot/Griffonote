package app.griffonote

import android.content.Context
import android.net.Uri
import androidx.documentfile.provider.DocumentFile
import java.io.File
import java.io.FileOutputStream

/**
 * Minimal file-system abstraction over the storage root, so the app can work on
 * a plain directory (default) or a SAF tree chosen by the user. Paths are relative
 * to the root and use `/` (empty string = root).
 */
interface Fs {
    data class Entry(val name: String, val isDir: Boolean, val lastModified: Long)

    fun list(dir: String): List<Entry>
    fun readBytes(path: String): ByteArray?
    /** Atomic: never exposes a half-written file to the sync app. */
    fun writeBytes(path: String, bytes: ByteArray)
    fun delete(path: String)
    fun exists(path: String): Boolean
    fun lastModified(path: String): Long
    /** Human-readable location, for the settings screen. */
    fun describe(): String

    fun readText(path: String): String? = readBytes(path)?.toString(Charsets.UTF_8)
    fun writeText(path: String, text: String) = writeBytes(path, text.toByteArray(Charsets.UTF_8))

    fun move(from: String, to: String) {
        val bytes = readBytes(from) ?: return
        writeBytes(to, bytes)
        delete(from)
    }
}

class FileFs(val root: File) : Fs {
    private fun file(path: String) = if (path.isEmpty()) root else File(root, path)

    override fun list(dir: String): List<Fs.Entry> =
        file(dir).listFiles().orEmpty().map { Fs.Entry(it.name, it.isDirectory, it.lastModified()) }

    override fun readBytes(path: String): ByteArray? = try {
        file(path).takeIf { it.isFile }?.readBytes()
    } catch (_: Exception) {
        null
    }

    override fun writeBytes(path: String, bytes: ByteArray) {
        val target = file(path)
        target.parentFile?.mkdirs()
        val tmp = File(target.parentFile, ".${target.name}.tmp")
        FileOutputStream(tmp).use { out ->
            out.write(bytes)
            out.fd.sync()
        }
        if (!tmp.renameTo(target)) {
            target.delete()
            if (!tmp.renameTo(target)) {
                tmp.delete()
                throw java.io.IOException("Cannot write $path")
            }
        }
    }

    override fun delete(path: String) {
        file(path).delete()
    }

    override fun exists(path: String) = file(path).exists()
    override fun lastModified(path: String) = file(path).lastModified()
    override fun describe(): String = root.absolutePath

    override fun move(from: String, to: String) {
        val src = file(from)
        val dst = file(to)
        dst.parentFile?.mkdirs()
        if (!src.renameTo(dst)) super.move(from, to)
    }
}

class SafFs(private val context: Context, private val treeUri: Uri) : Fs {
    private val resolver = context.contentResolver
    private val rootDoc: DocumentFile? get() = DocumentFile.fromTreeUri(context, treeUri)
    private val cache = HashMap<String, DocumentFile>()

    private fun resolve(path: String): DocumentFile? {
        if (path.isEmpty()) return rootDoc
        cache[path]?.let { return it }
        val parent = resolve(path.substringBeforeLast('/', ""))
        val doc = parent?.findFile(path.substringAfterLast('/')) ?: return null
        cache[path] = doc
        return doc
    }

    private fun ensureDir(path: String): DocumentFile? {
        if (path.isEmpty()) return rootDoc
        resolve(path)?.let { return it }
        val parent = ensureDir(path.substringBeforeLast('/', "")) ?: return null
        val doc = parent.createDirectory(path.substringAfterLast('/')) ?: return null
        cache[path] = doc
        return doc
    }

    override fun list(dir: String): List<Fs.Entry> {
        val doc = resolve(dir) ?: return emptyList()
        return try {
            doc.listFiles().mapNotNull { child ->
                val name = child.name ?: return@mapNotNull null
                cache[if (dir.isEmpty()) name else "$dir/$name"] = child
                Fs.Entry(name, child.isDirectory, child.lastModified())
            }
        } catch (_: Exception) {
            emptyList()
        }
    }

    override fun readBytes(path: String): ByteArray? = try {
        resolve(path)?.takeIf { it.isFile }?.let { doc ->
            resolver.openInputStream(doc.uri)?.use { it.readBytes() }
        }
    } catch (_: Exception) {
        cache.remove(path)
        null
    }

    override fun writeBytes(path: String, bytes: ByteArray) {
        val dirPath = path.substringBeforeLast('/', "")
        val name = path.substringAfterLast('/')
        val dir = ensureDir(dirPath) ?: throw java.io.IOException("Cannot open folder $dirPath")
        val tmpName = ".$name.tmp"
        dir.findFile(tmpName)?.delete()
        val tmp = dir.createFile("application/octet-stream", tmpName)
            ?: throw java.io.IOException("Cannot create $tmpName")
        try {
            resolver.openOutputStream(tmp.uri, "wt")!!.use { it.write(bytes) }
            resolve(path)?.delete()
            cache.remove(path)
            if (!tmp.renameTo(name)) throw java.io.IOException("Cannot rename to $name")
        } catch (e: Exception) {
            tmp.delete()
            throw e
        }
        cache.remove(path)
    }

    override fun delete(path: String) {
        resolve(path)?.delete()
        cache.remove(path)
        cache.keys.removeAll { it.startsWith("$path/") }
    }

    override fun exists(path: String) = try { resolve(path)?.exists() == true } catch (_: Exception) { false }
    override fun lastModified(path: String) = try { resolve(path)?.lastModified() ?: 0L } catch (_: Exception) { 0L }

    override fun describe(): String = try {
        rootDoc?.name ?: treeUri.toString()
    } catch (_: Exception) {
        treeUri.toString()
    }
}
