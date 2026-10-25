package app.griffonote.scan

import android.graphics.Bitmap
import android.graphics.Color
import android.graphics.pdf.PdfRenderer
import android.os.ParcelFileDescriptor
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext

/** Renders the pages of a PDF with Android's own renderer (one page at a time: it is not thread-safe). */
class PdfPages(fd: ParcelFileDescriptor) : AutoCloseable {
    private val renderer = PdfRenderer(fd)
    private val lock = Mutex()

    /** Width / height of every page, in PDF points, read once so the layout does not jump while rendering. */
    val sizes: List<Pair<Int, Int>> = (0 until renderer.pageCount).map { i ->
        renderer.openPage(i).use { it.width to it.height }
    }

    suspend fun render(index: Int, widthPx: Int): Bitmap = lock.withLock {
        withContext(Dispatchers.IO) {
            renderer.openPage(index).use { page ->
                val height = (widthPx.toLong() * page.height / page.width).toInt().coerceAtLeast(1)
                Bitmap.createBitmap(widthPx, height, Bitmap.Config.ARGB_8888).also { bitmap ->
                    bitmap.eraseColor(Color.WHITE) // PDF pages are transparent where nothing is drawn
                    page.render(bitmap, null, null, PdfRenderer.Page.RENDER_MODE_FOR_DISPLAY)
                }
            }
        }
    }

    override fun close() = renderer.close()
}
