package app.griffonote

import android.content.Context
import android.net.Uri
import android.os.Environment
import java.io.File

enum class ThemeMode { SYSTEM, LIGHT, DARK }

/** Where notes are stored: the shared Documents folder, or a SAF tree picked by the user. */
sealed class StorageConfig {
    data object Default : StorageConfig()
    data class Tree(val uri: Uri) : StorageConfig()
}

class Settings(context: Context) {
    private val prefs = context.getSharedPreferences("settings", Context.MODE_PRIVATE)

    var storageUri: String?
        get() = prefs.getString("storage_uri", null)
        set(v) = prefs.edit().putString("storage_uri", v).apply()

    var gridView: Boolean
        get() = prefs.getBoolean("grid_view", true)
        set(v) = prefs.edit().putBoolean("grid_view", v).apply()

    var theme: ThemeMode
        get() = runCatching { ThemeMode.valueOf(prefs.getString("theme", "SYSTEM")!!) }.getOrDefault(ThemeMode.SYSTEM)
        set(v) = prefs.edit().putString("theme", v.name).apply()

    var trashDays: Int
        get() = prefs.getInt("trash_days", 30)
        set(v) = prefs.edit().putInt("trash_days", v).apply()

    val storage: StorageConfig
        get() = storageUri?.let { StorageConfig.Tree(Uri.parse(it)) } ?: StorageConfig.Default

    companion object {
        fun defaultDir(): File =
            File(Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_DOCUMENTS), "Griffonote")
    }
}
