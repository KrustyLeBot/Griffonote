package app.griffonote.ui

import android.graphics.Bitmap
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.gestures.awaitEachGesture
import androidx.compose.foundation.gestures.awaitFirstDown
import androidx.compose.foundation.gestures.calculatePan
import androidx.compose.foundation.gestures.calculateZoom
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.automirrored.filled.OpenInNew
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.produceState
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.unit.dp
import app.griffonote.MainViewModel
import app.griffonote.scan.PdfPages

/**
 * In-app viewer of a scanned PDF: pages one under the other, one-finger scroll, two-finger zoom and
 * pan, double tap to go back to the normal size. "Open with" hands the file to another app.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun PdfViewerScreen(vm: MainViewModel, path: String) {
    var error by remember { mutableStateOf<String?>(null) }
    val pages by produceState<PdfPages?>(null, path) {
        value = try {
            vm.openPdfPages(path)
        } catch (e: Exception) {
            error = e.message ?: "PDF illisible"
            null
        }
    }
    // Capture the document: reading `pages` inside onDispose would give the newest one, not this one.
    val opened = pages
    DisposableEffect(opened) { onDispose { opened?.close() } }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text(vm.editor?.title?.ifBlank { null } ?: "Document scanné") },
                navigationIcon = { IconButton(onClick = { vm.back() }) { Icon(Icons.AutoMirrored.Filled.ArrowBack, "Retour") } },
                actions = {
                    IconButton(onClick = { vm.openPdf(path) }) {
                        Icon(Icons.AutoMirrored.Filled.OpenInNew, "Ouvrir avec une autre application")
                    }
                },
            )
        },
    ) { padding ->
        Box(Modifier.padding(padding).fillMaxSize().background(MaterialTheme.colorScheme.surfaceContainer)) {
            val doc = pages
            when {
                error != null -> Text(error!!, Modifier.align(Alignment.Center), color = MaterialTheme.colorScheme.error)
                doc == null -> CircularProgressIndicator(Modifier.align(Alignment.Center))
                else -> ZoomablePages(doc)
            }
        }
    }
}

@Composable
private fun ZoomablePages(doc: PdfPages) {
    var scale by remember { mutableFloatStateOf(1f) }
    var offset by remember { mutableStateOf(Offset.Zero) }
    BoxWithConstraints(
        Modifier.fillMaxSize()
            // Two fingers zoom and pan; one finger is left to the list, which scrolls.
            .pointerInput(Unit) {
                awaitEachGesture {
                    awaitFirstDown(requireUnconsumed = false)
                    do {
                        val event = awaitPointerEvent()
                        if (event.changes.count { it.pressed } >= 2) {
                            val newScale = (scale * event.calculateZoom()).coerceIn(1f, 4f)
                            val maxX = size.width * (newScale - 1) / 2
                            val pan = event.calculatePan()
                            offset = Offset((offset.x + pan.x).coerceIn(-maxX, maxX), 0f)
                            scale = newScale
                            event.changes.forEach { it.consume() }
                        }
                    } while (event.changes.any { it.pressed })
                }
            }
            .pointerInput(Unit) {
                detectTapGestures(onDoubleTap = { scale = 1f; offset = Offset.Zero })
            },
    ) {
        val widthPx = with(LocalDensity.current) { maxWidth.roundToPx() }
        LazyColumn(
            Modifier.fillMaxSize().graphicsLayer {
                scaleX = scale; scaleY = scale; translationX = offset.x
            },
            contentPadding = PaddingValues(12.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            itemsIndexed(doc.sizes) { index, (w, h) ->
                Page(doc, index, w.toFloat() / h, widthPx)
            }
        }
    }
}

@Composable
private fun Page(doc: PdfPages, index: Int, aspect: Float, widthPx: Int) {
    // Rendered a bit larger than the screen so that zoomed text stays readable.
    // Bitmaps are left to the garbage collector: recycling one Compose may still draw crashes the app.
    val bitmap by produceState<Bitmap?>(null, index, widthPx) {
        value = runCatching { doc.render(index, (widthPx * 1.5f).toInt()) }.getOrNull()
    }
    Box(Modifier.fillMaxWidth().aspectRatio(aspect).background(Color.White)) {
        bitmap?.let {
            Image(it.asImageBitmap(), "Page ${index + 1}", Modifier.fillMaxSize(), contentScale = ContentScale.Fit)
        }
    }
}
