package app.griffonote.ui

import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.staggeredgrid.LazyVerticalStaggeredGrid
import androidx.compose.foundation.lazy.staggeredgrid.StaggeredGridCells
import androidx.compose.foundation.lazy.staggeredgrid.StaggeredGridItemSpan
import androidx.compose.foundation.lazy.staggeredgrid.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Archive
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.DeleteForever
import androidx.compose.material.icons.filled.Label
import androidx.compose.material.icons.filled.Lightbulb
import androidx.compose.material.icons.filled.Menu
import androidx.compose.material.icons.filled.PushPin
import androidx.compose.material.icons.filled.Search
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material.icons.filled.ViewAgenda
import androidx.compose.material.icons.filled.ViewModule
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FloatingActionButton
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalDrawerSheet
import androidx.compose.material3.ModalNavigationDrawer
import androidx.compose.material3.NavigationDrawerItem
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.SnackbarResult
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.rememberDrawerState
import androidx.compose.material3.DrawerValue
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.griffonote.CHECK_REGEX
import app.griffonote.Folder
import app.griffonote.MainViewModel
import app.griffonote.Note
import app.griffonote.Section
import app.griffonote.Updater
import app.griffonote.fold
import kotlinx.coroutines.launch

private fun filterNotes(notes: List<Note>, section: Section, label: String?, query: String): List<Note> {
    val folder = when (section) {
        Section.NOTES -> Folder.NOTES
        Section.ARCHIVE -> Folder.ARCHIVE
        Section.TRASH -> Folder.TRASH
    }
    val q = query.trim().fold()
    return notes
        .filter { it.folder == folder }
        .filter { label == null || label in it.labels }
        .filter {
            q.isEmpty() || it.title.fold().contains(q) || it.body.fold().contains(q) ||
                it.labels.any { l -> l.fold().contains(q) }
        }
        .sortedWith(compareByDescending<Note> { it.pinned }.thenByDescending { it.updated })
}

private fun previewText(note: Note): String =
    note.plainBody().lines()
        .filter { it.isNotBlank() && !it.trimStart().startsWith("![") }
        .take(8)
        .joinToString("\n") { it.replace("**", "").replace(Regex("^#{1,3} "), "") }
        .take(300)

@OptIn(ExperimentalMaterial3Api::class, ExperimentalFoundationApi::class)
@Composable
fun ListScreen(vm: MainViewModel) {
    val notes by vm.notes.collectAsState()
    val drawerState = rememberDrawerState(DrawerValue.Closed)
    val scope = rememberCoroutineScope()
    val snackbar = remember { SnackbarHostState() }
    val visible = remember(notes, vm.section, vm.labelFilter, vm.query) {
        filterNotes(notes, vm.section, vm.labelFilter, vm.query)
    }
    val labels = remember(notes) {
        notes.filter { it.folder != Folder.TRASH }.flatMap { it.labels }.distinct().sortedBy { it.fold() }
    }

    LaunchedEffect(vm.snack) {
        val s = vm.snack ?: return@LaunchedEffect
        val result = snackbar.showSnackbar(s.text, actionLabel = if (s.undo != null) "Annuler" else null)
        if (result == SnackbarResult.ActionPerformed) s.undo?.invoke()
        vm.snack = null
    }

    ModalNavigationDrawer(
        drawerState = drawerState,
        drawerContent = {
            ModalDrawerSheet {
                Text("Griffonote", style = MaterialTheme.typography.titleLarge, modifier = Modifier.padding(24.dp))
                NavigationDrawerItem(
                    label = { Text("Notes") }, icon = { Icon(Icons.Default.Lightbulb, null) },
                    selected = vm.section == Section.NOTES && vm.labelFilter == null,
                    onClick = { vm.selectSection(Section.NOTES); scope.launch { drawerState.close() } },
                    modifier = Modifier.padding(horizontal = 12.dp),
                )
                labels.forEach { label ->
                    NavigationDrawerItem(
                        label = { Text(label) }, icon = { Icon(Icons.Default.Label, null) },
                        selected = vm.section == Section.NOTES && vm.labelFilter == label,
                        onClick = { vm.selectSection(Section.NOTES, label); scope.launch { drawerState.close() } },
                        modifier = Modifier.padding(horizontal = 12.dp),
                    )
                }
                HorizontalDivider(Modifier.padding(vertical = 8.dp))
                NavigationDrawerItem(
                    label = { Text("Archive") }, icon = { Icon(Icons.Default.Archive, null) },
                    selected = vm.section == Section.ARCHIVE,
                    onClick = { vm.selectSection(Section.ARCHIVE); scope.launch { drawerState.close() } },
                    modifier = Modifier.padding(horizontal = 12.dp),
                )
                NavigationDrawerItem(
                    label = { Text("Corbeille") }, icon = { Icon(Icons.Default.Delete, null) },
                    selected = vm.section == Section.TRASH,
                    onClick = { vm.selectSection(Section.TRASH); scope.launch { drawerState.close() } },
                    modifier = Modifier.padding(horizontal = 12.dp),
                )
                HorizontalDivider(Modifier.padding(vertical = 8.dp))
                NavigationDrawerItem(
                    label = { Text("Paramètres") }, icon = { Icon(Icons.Default.Settings, null) },
                    selected = false,
                    onClick = { vm.openSettings(); scope.launch { drawerState.close() } },
                    modifier = Modifier.padding(horizontal = 12.dp),
                )
            }
        },
    ) {
        Scaffold(
            snackbarHost = { SnackbarHost(snackbar) },
            topBar = {
                TopAppBar(
                    navigationIcon = {
                        if (vm.searching) {
                            IconButton(onClick = { vm.searching = false; vm.query = "" }) {
                                Icon(Icons.AutoMirrored.Filled.ArrowBack, "Retour")
                            }
                        } else {
                            IconButton(onClick = { scope.launch { drawerState.open() } }) {
                                Icon(Icons.Default.Menu, "Menu")
                            }
                        }
                    },
                    title = {
                        if (vm.searching) {
                            val focus = remember { FocusRequester() }
                            LaunchedEffect(Unit) { focus.requestFocus() }
                            BasicTextField(
                                value = vm.query,
                                onValueChange = { vm.query = it },
                                singleLine = true,
                                textStyle = MaterialTheme.typography.bodyLarge.copy(color = MaterialTheme.colorScheme.onSurface),
                                keyboardOptions = KeyboardOptions(imeAction = androidx.compose.ui.text.input.ImeAction.Search),
                                modifier = Modifier.fillMaxWidth().focusRequester(focus),
                                decorationBox = { inner ->
                                    Box {
                                        if (vm.query.isEmpty()) {
                                            Text("Rechercher", color = MaterialTheme.colorScheme.onSurfaceVariant)
                                        }
                                        inner()
                                    }
                                },
                            )
                        } else {
                            Text(
                                when {
                                    vm.section == Section.ARCHIVE -> "Archive"
                                    vm.section == Section.TRASH -> "Corbeille"
                                    vm.labelFilter != null -> vm.labelFilter!!
                                    else -> "Griffonote"
                                },
                            )
                        }
                    },
                    actions = {
                        if (vm.searching) {
                            if (vm.query.isNotEmpty()) {
                                IconButton(onClick = { vm.query = "" }) { Icon(Icons.Default.Close, "Effacer") }
                            }
                        } else {
                            IconButton(onClick = { vm.searching = true }) { Icon(Icons.Default.Search, "Rechercher") }
                            if (vm.section == Section.TRASH && visible.isNotEmpty()) {
                                IconButton(onClick = { vm.emptyTrash() }) {
                                    Icon(Icons.Default.DeleteForever, "Vider la corbeille")
                                }
                            } else {
                                IconButton(onClick = { vm.changeGridView(!vm.gridView) }) {
                                    Icon(
                                        if (vm.gridView) Icons.Default.ViewAgenda else Icons.Default.ViewModule,
                                        if (vm.gridView) "Vue liste" else "Vue grille",
                                    )
                                }
                            }
                        }
                    },
                )
            },
            floatingActionButton = {
                if (vm.section == Section.NOTES) {
                    var menu by remember { mutableStateOf(false) }
                    Box {
                        FloatingActionButton(onClick = { menu = true }) { Icon(Icons.Default.Add, "Nouvelle note") }
                        DropdownMenu(expanded = menu, onDismissRequest = { menu = false }) {
                            DropdownMenuItem(text = { Text("Note") }, onClick = { menu = false; vm.newNote() })
                            DropdownMenuItem(text = { Text("Liste") }, onClick = { menu = false; vm.newNote(checklist = true) })
                        }
                    }
                }
            },
        ) { padding ->
            Column(Modifier.padding(padding).fillMaxSize()) {
                val update = vm.updateState
                if (update is Updater.State.Available) {
                    Surface(color = MaterialTheme.colorScheme.primaryContainer, modifier = Modifier.fillMaxWidth()) {
                        Row(Modifier.padding(start = 16.dp, end = 8.dp), verticalAlignment = Alignment.CenterVertically) {
                            Text("Mise à jour disponible (build ${update.info.build})", modifier = Modifier.weight(1f))
                            TextButton(onClick = { vm.downloadAndInstall() }) { Text("Installer") }
                        }
                    }
                }
                if (visible.isEmpty()) {
                    Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                        Text(
                            when {
                                vm.query.isNotBlank() -> "Aucun résultat"
                                vm.section == Section.ARCHIVE -> "Aucune note archivée"
                                vm.section == Section.TRASH -> "La corbeille est vide"
                                else -> "Les notes que vous ajoutez apparaissent ici"
                            },
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                } else {
                    val pinned = visible.filter { it.pinned }
                    val others = visible.filter { !it.pinned }
                    LazyVerticalStaggeredGrid(
                        columns = StaggeredGridCells.Fixed(if (vm.gridView) 2 else 1),
                        contentPadding = PaddingValues(8.dp),
                        verticalItemSpacing = 8.dp,
                        horizontalArrangement = Arrangement.spacedBy(8.dp),
                        modifier = Modifier.fillMaxSize(),
                    ) {
                        if (pinned.isNotEmpty()) {
                            item(span = StaggeredGridItemSpan.FullLine, key = "h-pinned") { SectionHeader("ÉPINGLÉES") }
                            items(pinned, key = { it.path }) { NoteCard(it) { vm.openNote(it) } }
                            if (others.isNotEmpty()) {
                                item(span = StaggeredGridItemSpan.FullLine, key = "h-others") { SectionHeader("AUTRES") }
                            }
                        }
                        items(others, key = { it.path }) { NoteCard(it) { vm.openNote(it) } }
                    }
                }
            }
        }
    }
}

@Composable
private fun SectionHeader(text: String) {
    Text(
        text, style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant,
        modifier = Modifier.padding(start = 8.dp, top = 8.dp),
    )
}

@Composable
private fun NoteCard(note: Note, onClick: () -> Unit) {
    val fg = noteForeground(note.color)
    Card(
        onClick = onClick,
        shape = RoundedCornerShape(12.dp),
        colors = CardDefaults.cardColors(containerColor = noteBackground(note.color), contentColor = fg),
        elevation = CardDefaults.cardElevation(defaultElevation = 1.dp),
        modifier = Modifier.fillMaxWidth(),
    ) {
        Column(Modifier.padding(12.dp)) {
            if (note.conflict) {
                Surface(
                    shape = RoundedCornerShape(50),
                    color = MaterialTheme.colorScheme.errorContainer,
                    modifier = Modifier.padding(bottom = 6.dp),
                ) {
                    Text(
                        "Conflit", fontSize = 11.sp, color = MaterialTheme.colorScheme.onErrorContainer,
                        modifier = Modifier.padding(horizontal = 8.dp, vertical = 2.dp),
                    )
                }
            }
            if (note.title.isNotBlank()) {
                Row(verticalAlignment = Alignment.Top) {
                    Text(
                        note.title, style = MaterialTheme.typography.titleMedium,
                        maxLines = 3, overflow = TextOverflow.Ellipsis, modifier = Modifier.weight(1f),
                    )
                    if (note.pinned) Icon(Icons.Default.PushPin, null, Modifier.padding(start = 4.dp))
                }
                Box(Modifier.padding(top = 6.dp))
            }
            val preview = previewText(note)
            if (preview.isNotBlank()) {
                Text(preview, style = MaterialTheme.typography.bodyMedium, maxLines = 10, overflow = TextOverflow.Ellipsis)
            }
            if (note.labels.isNotEmpty()) {
                Row(Modifier.padding(top = 8.dp), horizontalArrangement = Arrangement.spacedBy(4.dp)) {
                    note.labels.take(3).forEach { l ->
                        Surface(
                            shape = RoundedCornerShape(50),
                            color = fg.copy(alpha = 0.12f),
                        ) {
                            Text(l, fontSize = 11.sp, modifier = Modifier.padding(horizontal = 8.dp, vertical = 2.dp), maxLines = 1)
                        }
                    }
                }
            }
        }
    }
}
