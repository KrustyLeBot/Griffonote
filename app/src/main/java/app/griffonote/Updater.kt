package app.griffonote

import android.content.Context
import android.content.Intent
import android.net.Uri
import android.provider.Settings as AndroidSettings
import androidx.core.content.FileProvider
import org.json.JSONObject
import java.io.File
import java.net.HttpURLConnection
import java.net.URL

/** Self-update from the rolling `latest` GitHub release. */
object Updater {
    private const val REPO = "krustylebot/griffonote"

    data class Info(val build: Int, val name: String, val apkUrl: String)

    sealed class State {
        data object Idle : State()
        data object Checking : State()
        data object UpToDate : State()
        data class Available(val info: Info) : State()
        data class Downloading(val percent: Int) : State()
        data class Error(val message: String) : State()
    }

    private fun updatesDir(context: Context) = File(context.cacheDir, "updates")

    /** Removes APKs left over from a previous update. Call at startup. */
    fun cleanup(context: Context) {
        updatesDir(context).deleteRecursively()
    }

    /** Blocking; returns null when the installed build is already the latest. */
    fun check(): Info? {
        val conn = open("https://api.github.com/repos/$REPO/releases/tags/latest")
        try {
            conn.setRequestProperty("Accept", "application/vnd.github+json")
            if (conn.responseCode != 200) throw java.io.IOException("HTTP ${conn.responseCode}")
            val json = JSONObject(conn.inputStream.bufferedReader().use { it.readText() })
            val name = json.optString("name")
            val build = Regex("(\\d+)\\s*$").find(name.trim())?.groupValues?.get(1)?.toIntOrNull()
                ?: throw java.io.IOException("Unreadable release title")
            val assets = json.getJSONArray("assets")
            var url: String? = null
            for (i in 0 until assets.length()) {
                val a = assets.getJSONObject(i)
                if (a.optString("name").endsWith(".apk")) { url = a.getString("browser_download_url"); break }
            }
            if (url == null) throw java.io.IOException("No APK in release")
            return if (build > BuildConfig.VERSION_CODE) Info(build, name, url) else null
        } finally {
            conn.disconnect()
        }
    }

    /** Blocking; downloads the APK into the cache and returns it. */
    fun download(context: Context, info: Info, onProgress: (Int) -> Unit): File {
        val dir = updatesDir(context).apply { deleteRecursively(); mkdirs() }
        val out = File(dir, "griffonote-${info.build}.apk")
        val conn = open(info.apkUrl)
        try {
            if (conn.responseCode != 200) throw java.io.IOException("HTTP ${conn.responseCode}")
            val total = conn.contentLengthLong
            var done = 0L
            var lastPercent = -1
            conn.inputStream.use { input ->
                out.outputStream().use { output ->
                    val buf = ByteArray(64 * 1024)
                    while (true) {
                        val n = input.read(buf)
                        if (n < 0) break
                        output.write(buf, 0, n)
                        done += n
                        if (total > 0) {
                            val p = (done * 100 / total).toInt()
                            if (p != lastPercent) { lastPercent = p; onProgress(p) }
                        }
                    }
                }
            }
        } catch (e: Exception) {
            out.delete()
            throw e
        } finally {
            conn.disconnect()
        }
        return out
    }

    /** Hands the APK to Android's package installer, asking for the install permission first if needed. */
    fun install(context: Context, apk: File) {
        if (!context.packageManager.canRequestPackageInstalls()) {
            context.startActivity(
                Intent(AndroidSettings.ACTION_MANAGE_UNKNOWN_APP_SOURCES, Uri.parse("package:${context.packageName}"))
                    .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK),
            )
            throw java.io.IOException("Autorisez l'installation depuis Griffonote, puis réessayez.")
        }
        val uri = FileProvider.getUriForFile(context, "${context.packageName}.fileprovider", apk)
        context.startActivity(
            Intent(Intent.ACTION_VIEW)
                .setDataAndType(uri, "application/vnd.android.package-archive")
                .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_ACTIVITY_NEW_TASK),
        )
    }

    private fun open(url: String): HttpURLConnection =
        (URL(url).openConnection() as HttpURLConnection).apply {
            connectTimeout = 15_000
            readTimeout = 30_000
            instanceFollowRedirects = true
            setRequestProperty("User-Agent", "Griffonote/${BuildConfig.VERSION_NAME}")
        }
}
