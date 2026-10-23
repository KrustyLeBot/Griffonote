package app.griffonote

/** Where a note lives on disk. Archive and trash are real folders, not flags. */
enum class Folder(val dir: String) {
    NOTES(""),
    ARCHIVE(".archive"),
    TRASH(".trash"),
}

const val DEFAULT_COLOR = "default"

data class Note(
    /** Path relative to the storage root, e.g. `.trash/courses-k3f9a2.md`. */
    val path: String,
    val folder: Folder,
    val id: String,
    /** False for `.md` files created elsewhere (no frontmatter id yet). */
    val hasId: Boolean = true,
    val title: String,
    val color: String = DEFAULT_COLOR,
    val pinned: Boolean = false,
    val labels: List<String> = emptyList(),
    /** Epoch millis, preserved untouched until the reminders milestone. */
    val reminder: Long? = null,
    val created: Long,
    val updated: Long,
    val trashed: Long? = null,
    val body: String = "",
    /** Unknown frontmatter lines, kept verbatim for Obsidian compatibility. */
    val extra: List<String> = emptyList(),
    val conflict: Boolean = false,
) {
    val fileName: String get() = path.substringAfterLast('/')

    /** Plain-text version used for sharing and previews: checklists as ☐ / ☑. */
    fun plainBody(): String = body.lines().joinToString("\n") { line ->
        val m = CHECK_REGEX.matchEntire(line)
        if (m == null) line else (if (m.groupValues[1] == " ") "☐ " else "☑ ") + m.groupValues[2]
    }

    fun shareText(): String = listOf(title, plainBody()).filter { it.isNotBlank() }.joinToString("\n\n")
}

val CHECK_REGEX = Regex("""^\s*[-*+] \[( |x|X)\] ?(.*)$""")
