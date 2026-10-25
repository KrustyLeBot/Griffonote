package app.griffonote.ui

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilterChip
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import app.griffonote.BuildConfig
import app.griffonote.MainViewModel
import app.griffonote.StorageConfig
import app.griffonote.ThemeMode
import app.griffonote.Updater
import app.griffonote.scan.ScanFormat

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun SettingsScreen(vm: MainViewModel, onPickFolder: () -> Unit) {
    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("Paramètres") },
                navigationIcon = {
                    IconButton(onClick = { vm.back() }) { Icon(Icons.AutoMirrored.Filled.ArrowBack, "Retour") }
                },
            )
        },
    ) { padding ->
        Column(Modifier.padding(padding).verticalScroll(rememberScrollState())) {
            Section("Synchronisation Proton Drive")
            Column(Modifier.padding(horizontal = 16.dp)) {
                Text(
                    "Les notes sont synchronisées par l'application Synchrotron : à l'ouverture, à chaque modification et régulièrement en arrière-plan.",
                    style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                TextButton(onClick = { vm.setUpSync() }) { Text("Configurer / ouvrir Synchrotron") }
            }
            HorizontalDivider()
            Section("Stockage")
            Column(Modifier.padding(horizontal = 16.dp)) {
                Text("Dossier des notes", style = MaterialTheme.typography.bodyLarge)
                Text(
                    vm.storageLabel.ifEmpty { "—" },
                    style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    TextButton(onClick = onPickFolder) { Text("Choisir un dossier") }
                    if (vm.settings.storage !is StorageConfig.Default) {
                        TextButton(onClick = { vm.requestStorageChange(StorageConfig.Default) }) {
                            Text("Dossier par défaut")
                        }
                    }
                }
            }
            HorizontalDivider(Modifier.padding(vertical = 8.dp))

            Section("Affichage")
            Row(Modifier.padding(horizontal = 16.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                FilterChip(selected = vm.gridView, onClick = { vm.changeGridView(true) }, label = { Text("Grille") })
                FilterChip(selected = !vm.gridView, onClick = { vm.changeGridView(false) }, label = { Text("Liste") })
            }
            Text("Thème", Modifier.padding(start = 16.dp, top = 12.dp, bottom = 4.dp))
            Row(Modifier.padding(horizontal = 16.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                FilterChip(vm.theme == ThemeMode.SYSTEM, { vm.changeTheme(ThemeMode.SYSTEM) }, { Text("Système") })
                FilterChip(vm.theme == ThemeMode.LIGHT, { vm.changeTheme(ThemeMode.LIGHT) }, { Text("Clair") })
                FilterChip(vm.theme == ThemeMode.DARK, { vm.changeTheme(ThemeMode.DARK) }, { Text("Sombre") })
            }
            HorizontalDivider(Modifier.padding(vertical = 12.dp))

            Section("Scans")
            Text("Format des pages", Modifier.padding(start = 16.dp, bottom = 4.dp))
            Row(Modifier.padding(horizontal = 16.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                ScanFormat.entries.forEach { f ->
                    FilterChip(vm.scanFormat == f, { vm.changeScanFormat(f) }, { Text(f.label) })
                }
            }
            Text(
                "Automatique : A4 ou US Letter selon la forme de la page.",
                style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.padding(start = 16.dp, top = 4.dp),
            )
            HorizontalDivider(Modifier.padding(vertical = 12.dp))

            Section("À propos")
            Text(
                "Griffonote ${BuildConfig.VERSION_NAME} (build ${BuildConfig.VERSION_CODE})",
                Modifier.padding(horizontal = 16.dp, vertical = 4.dp),
            )
            UpdateRow(vm)
        }
    }

    vm.pendingStorage?.let { target ->
        AlertDialog(
            onDismissRequest = { vm.pendingStorage = null },
            title = { Text("Changer de dossier") },
            text = {
                Text(
                    "Voulez-vous déplacer les notes existantes vers " +
                        (if (target is StorageConfig.Default) "le dossier par défaut" else "le nouveau dossier") +
                        " ou repartir de zéro ? Dans ce cas, les anciens fichiers restent où ils sont.",
                )
            },
            confirmButton = { TextButton(onClick = { vm.confirmStorageChange(move = true) }) { Text("Déplacer") } },
            dismissButton = {
                Row {
                    TextButton(onClick = { vm.pendingStorage = null }) { Text("Annuler") }
                    TextButton(onClick = { vm.confirmStorageChange(move = false) }) { Text("Repartir de zéro") }
                }
            },
        )
    }
}

@Composable
private fun Section(title: String) {
    Text(
        title, style = MaterialTheme.typography.titleSmall, color = MaterialTheme.colorScheme.primary,
        modifier = Modifier.padding(start = 16.dp, top = 12.dp, bottom = 4.dp),
    )
}

@Composable
private fun UpdateRow(vm: MainViewModel) {
    val state = vm.updateState
    Column(Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 8.dp)) {
        Text("Mise à jour")
        when (state) {
            is Updater.State.Idle -> Muted("Appuyez pour vérifier")
            is Updater.State.Checking -> Muted("Vérification…")
            is Updater.State.UpToDate -> Muted("Vous avez la dernière version")
            is Updater.State.Available -> Muted("Build ${state.info.build} disponible")
            is Updater.State.Downloading -> {
                Muted("Téléchargement… ${state.percent} %")
                LinearProgressIndicator(progress = { state.percent / 100f }, modifier = Modifier.fillMaxWidth().padding(top = 4.dp))
            }
            is Updater.State.Error -> Muted(state.message)
        }
        Row {
            TextButton(onClick = { vm.checkUpdate() }) { Text("Vérifier") }
            if (state is Updater.State.Available) {
                TextButton(onClick = { vm.downloadAndInstall() }) { Text("Installer") }
            }
        }
    }
}

@Composable
private fun Muted(text: String) {
    Text(text, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
}
