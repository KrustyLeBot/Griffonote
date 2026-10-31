"""The "Activités" folder: figures and the list, then one activity with its map, figures and charts."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QPointF, Qt, Signal
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QFrame, QGridLayout, QHBoxLayout,
                               QLabel, QLineEdit, QMessageBox, QPlainTextEdit, QPushButton, QScrollArea, QStackedWidget,
                               QToolButton, QVBoxLayout, QWidget)

from ..core import activity as act
from ..core.analysis import Analysis, analyze
from ..core.note import Note
from ..core.store import Store
from ..core.track import Sport
from . import icons, theme
from .trackmap import TrackMap

EMOJI = {Sport.WALK: "🚶", Sport.BIKE: "🚴", Sport.SKI: "⛷️", Sport.GPS: "📍", Sport.PLAIN: "⏱️"}
SLOW, FAST = QColor("#2E7DF6"), QColor("#E5484D")
DAYS = ["lun.", "mar.", "mer.", "jeu.", "ven.", "sam.", "dim."]
MONTHS = ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc."]


def short_label(sport: Sport) -> str:
    return sport.label.split(" (")[0]


def fmt_date(ms: int) -> str:
    d = datetime.fromtimestamp(ms / 1000)
    return f"{DAYS[d.weekday()]} {d.day} {MONTHS[d.month - 1]} {d.year}, {d:%H:%M}"


def fmt_hour(ms: int) -> str:
    return f"{datetime.fromtimestamp(ms / 1000):%H:%M}"


def summary_line(i: act.ActivityInfo) -> str:
    parts = []
    if i.distance > 0:
        parts.append(act.fmt_distance(i.distance))
    parts.append(act.fmt_duration(i.moving if i.moving > 0 else i.elapsed))
    if i.sport.has_gps and i.moving > 0 and i.distance > 0:
        parts.append(act.fmt_speed_for(i.sport, i.distance / i.moving))
    if i.ascent > 0:
        parts.append(f"↑ {i.ascent} m")
    if i.sport == Sport.SKI and i.runs > 0:
        parts.append(f"{i.runs} descentes")
    return " · ".join(parts)


def map_lines(a: Analysis, ski: bool, show_all: bool):
    """Chunks of the track coloured from blue (slow) to red (fast); skiing: descents only unless show_all."""
    s = a.samples
    if len(s) < 2:
        return []
    speeds = sorted(x.speed for x in s)
    top = max(speeds[min(int(len(speeds) * 0.9), len(speeds) - 1)], 0.5)
    max_gap = max(a.quality.median_interval_sec * 6, 30.0) * 1000
    out, i = [], 0
    while i < len(s) - 1:
        if ski and not show_all and not s[i].down:
            i += 1
            continue
        first, j, total = i, i, 0.0
        while (j + 1 < len(s) and j - first < 8 and s[j + 1].time - s[j].time <= max_gap
               and (not ski or show_all or s[j + 1].down)):
            j += 1
            total += s[j].speed
        if j == first:
            i += 1
            continue
        if ski and show_all and not s[first].down:
            color = QColor("#9AA0A6")
        else:
            f = max(0.0, min(1.0, total / (j - first) / top))
            color = QColor(int(SLOW.red() + (FAST.red() - SLOW.red()) * f), int(SLOW.green() + (FAST.green() - SLOW.green()) * f),
                           int(SLOW.blue() + (FAST.blue() - SLOW.blue()) * f))
        out.append(([(p.lat, p.lon) for p in s[first:j + 1]], color))
        i = j
    return out


class Chart(QWidget):
    """A filled line chart with its extremes written above."""

    def __init__(self, title: str, xs: list[float], ys: list[float], low: str, high: str, color: str):
        super().__init__()
        self.xs, self.ys, self.color = xs, ys, QColor(color)
        s = theme.scheme()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        head = QHBoxLayout()
        name = QLabel(title)
        name.setStyleSheet(f"color: {s.primary}; font-weight: 600;")
        extremes = QLabel(f"min {low}   max {high}")
        extremes.setStyleSheet(f"color: {s.on_surface_variant}; font-size: 8.5pt;")
        head.addWidget(name)
        head.addStretch()
        head.addWidget(extremes)
        layout.addLayout(head)
        self.canvas = _ChartCanvas(self)
        layout.addWidget(self.canvas)


class _ChartCanvas(QWidget):
    def __init__(self, chart: Chart):
        super().__init__()
        self.chart = chart
        self.setFixedHeight(110)

    def paintEvent(self, event) -> None:
        xs, ys = self.chart.xs, self.chart.ys
        if len(xs) < 2:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        lo, hi = min(ys), max(ys)
        span_y, min_x = max(hi - lo, 1e-6), xs[0]
        span_x = max(xs[-1] - min_x, 1e-6)
        w, h = self.width(), self.height()
        path = QPainterPath()
        for i, (x, y) in enumerate(zip(xs, ys)):
            pt = QPointF((x - min_x) / span_x * w, h - (y - lo) / span_y * h * 0.9 - h * 0.05)
            path.moveTo(pt) if i == 0 else path.lineTo(pt)
        fill = QPainterPath(path)
        fill.lineTo(w, h)
        fill.lineTo(0, h)
        fill.closeSubpath()
        gradient = QLinearGradient(0, 0, 0, h)
        top = QColor(self.chart.color)
        top.setAlphaF(0.35)
        bottom = QColor(self.chart.color)
        bottom.setAlphaF(0.02)
        gradient.setColorAt(0, top)
        gradient.setColorAt(1, bottom)
        p.fillPath(fill, gradient)
        p.setPen(QPen(self.chart.color, 2))
        p.drawPath(path)


def thin(n: int, limit: int = 300) -> list[int]:
    return list(range(n)) if n <= limit else [i * (n - 1) // (limit - 1) for i in range(limit)]


def card(title: str | None = None) -> tuple[QFrame, QVBoxLayout]:
    s = theme.scheme()
    frame = QFrame()
    frame.setObjectName("sec")
    frame.setStyleSheet(f"#sec {{ background: {s.surface_container}; border-radius: 16px; }}")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(16, 12, 16, 14)
    layout.setSpacing(8)
    if title:
        label = QLabel(title)
        label.setStyleSheet(f"color: {s.primary}; font-weight: 600;")
        layout.addWidget(label)
    return frame, layout


def stat_grid(items: list[tuple[str, str]], columns: int = 3) -> QWidget:
    s = theme.scheme()
    host = QWidget()
    grid = QGridLayout(host)
    grid.setContentsMargins(0, 0, 0, 0)
    grid.setHorizontalSpacing(24)
    grid.setVerticalSpacing(10)
    for i, (label, value) in enumerate(items):
        cell = QVBoxLayout()
        cell.setSpacing(0)
        l = QLabel(label)
        l.setStyleSheet(f"color: {s.on_surface_variant}; font-size: 8.5pt;")
        v = QLabel(value)
        v.setStyleSheet("font-size: 13pt; font-weight: 600;")
        cell.addWidget(l)
        cell.addWidget(v)
        grid.addLayout(cell, i // columns, i % columns)
    return host


class ImportDialog(QDialog):
    def __init__(self, parent, name: str, title: str, sport: Sport):
        super().__init__(parent)
        self.setWindowTitle("Importer l'activité")
        form = QFormLayout(self)
        form.addRow(QLabel(name))
        self.title = QLineEdit(title)
        self.sport = QComboBox()
        for s in (Sport.WALK, Sport.BIKE, Sport.SKI, Sport.GPS):
            self.sport.addItem(f"{EMOJI[s]} {short_label(s)}", s)
        self.sport.setCurrentIndex(max(0, self.sport.findData(sport)))
        form.addRow("Nom", self.title)
        form.addRow("Sport", self.sport)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)


class EditDialog(QDialog):
    def __init__(self, parent, note: Note, has_file: bool):
        super().__init__(parent)
        self.setWindowTitle("Modifier l'activité")
        self.resize(420, 300)
        form = QFormLayout(self)
        self.title = QLineEdit(note.title)
        self.description = QPlainTextEdit(note.body)
        self.sport = QComboBox()
        options = (Sport.WALK, Sport.BIKE, Sport.SKI, Sport.GPS) if has_file else (Sport.PLAIN,)
        for s in options:
            self.sport.addItem(f"{EMOJI[s]} {s.label}", s)
        if note.activity:
            self.sport.setCurrentIndex(max(0, self.sport.findData(note.activity.sport)))
        form.addRow("Nom", self.title)
        form.addRow("Description", self.description)
        form.addRow("Sport", self.sport)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)


class ActivityRow(QFrame):
    clicked = Signal(object)

    def __init__(self, note: Note):
        super().__init__()
        self.note = note
        s = theme.scheme()
        self.setObjectName("row")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet(f"#row {{ background: {s.surface_container}; border-radius: 14px; }} "
                           f"#row:hover {{ background: {s.surface_high}; }} #row QLabel {{ background: transparent; }}")
        row = QHBoxLayout(self)
        row.setContentsMargins(14, 10, 14, 10)
        emoji = QLabel(EMOJI.get(note.activity.sport, "📍"))
        emoji.setStyleSheet("font-size: 20pt;")
        row.addWidget(emoji)
        col = QVBoxLayout()
        col.setSpacing(0)
        title = QLabel(note.title)
        title.setStyleSheet("font-weight: 600; font-size: 11pt;")
        when = QLabel(fmt_date(note.activity.start))
        when.setStyleSheet(f"color: {s.on_surface_variant}; font-size: 9pt;")
        col.addWidget(title)
        col.addWidget(when)
        col.addWidget(QLabel(summary_line(note.activity)))
        row.addLayout(col, 1)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(event.position().toPoint()):
            self.clicked.emit(self.note)
        super().mouseReleaseEvent(event)


class ActivitiesScreen(QWidget):
    back_requested = Signal()
    message = Signal(str)
    changed = Signal()  # something was written: the window rescans
    open_file = Signal(str)
    reveal_file = Signal(str)

    def __init__(self):
        super().__init__()
        self.store: Store | None = None
        self.activities: list[Note] = []
        self.sport_filter: Sport | None = None
        self.current: Note | None = None
        self.stack = QStackedWidget()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self.stack)
        self.list_page = QWidget()
        self.detail_page = QWidget()
        self.stack.addWidget(self.list_page)
        self.stack.addWidget(self.detail_page)
        self._build_list()
        self.detail_layout = QVBoxLayout(self.detail_page)
        self.detail_layout.setContentsMargins(0, 0, 0, 0)

    def set_store(self, store: Store) -> None:
        self.store = store

    # ---- list ----

    def _build_list(self) -> None:
        layout = QVBoxLayout(self.list_page)
        layout.setContentsMargins(14, 12, 14, 0)
        head = QHBoxLayout()
        self.back = QToolButton()
        self.back.clicked.connect(self.back_requested)
        title = QLabel("Activités")
        title.setStyleSheet("font-size: 16pt; font-weight: 700;")
        self.import_button = QPushButton("Importer FIT / GPX…")
        self.import_button.clicked.connect(self.import_files)
        head.addWidget(self.back)
        head.addWidget(title)
        head.addStretch()
        head.addWidget(self.import_button)
        layout.addLayout(head)
        self.totals = QHBoxLayout()
        layout.addLayout(self.totals)
        self.filter = QComboBox()
        self.filter.addItem("Tous les sports", None)
        for s in Sport:
            self.filter.addItem(f"{EMOJI[s]} {short_label(s)}", s)
        self.filter.currentIndexChanged.connect(self._filter_changed)
        layout.addWidget(self.filter)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.rows_host = QWidget()
        self.rows = QVBoxLayout(self.rows_host)
        self.rows.setSpacing(8)
        self.rows.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.scroll.setWidget(self.rows_host)
        layout.addWidget(self.scroll, 1)
        self.restyle()

    def restyle(self) -> None:
        self.back.setIcon(icons.icon("back", theme.scheme().on_surface, 22))
        self.rebuild()

    def set_activities(self, notes: list[Note]) -> None:
        self.activities = sorted((n for n in notes if n.activity), key=lambda n: -n.activity.start)
        self.rebuild()

    def _filter_changed(self) -> None:
        self.sport_filter = self.filter.currentData()
        self.rebuild()

    def rebuild(self) -> None:
        s = theme.scheme()
        while self.totals.count():
            item = self.totals.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        now = datetime.now()
        week_start = datetime(now.year, now.month, now.day).timestamp() * 1000 - now.weekday() * 86_400_000
        month_start = datetime(now.year, now.month, 1).timestamp() * 1000
        for name, since in (("Semaine", week_start), ("Mois", month_start), ("Total", 0)):
            items = [n.activity for n in self.activities if n.activity.start >= since]
            frame, lay = card(name)
            lay.addWidget(QLabel(f"{len(items)} activité{'s' if len(items) > 1 else ''}"))
            big = QLabel(act.fmt_distance(sum(i.distance for i in items)))
            big.setStyleSheet("font-size: 13pt; font-weight: 600;")
            lay.addWidget(big)
            detail = act.fmt_duration(sum(i.moving for i in items))
            ascent = sum(i.ascent for i in items)
            lay.addWidget(QLabel(detail + (f" · ↑ {ascent} m" if ascent else "")))
            self.totals.addWidget(frame)
        while self.rows.count():
            item = self.rows.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        shown = [n for n in self.activities if self.sport_filter is None or n.activity.sport == self.sport_filter]
        if not shown:
            hint = QLabel("Aucune activité. Importe un fichier FIT ou GPX (montre, Strava).")
            hint.setStyleSheet(f"color: {s.on_surface_variant};")
            self.rows.addWidget(hint)
        for n in shown:
            row = ActivityRow(n)
            row.clicked.connect(self.open_activity)
            self.rows.addWidget(row)

    # ---- import ----

    def import_files(self) -> None:
        if self.store is None:
            return
        paths, _ = QFileDialog.getOpenFileNames(self, "Importer des activités", str(Path.home()),
                                                "Activités (*.fit *.gpx);;Tous les fichiers (*)")
        last = None
        for path in paths:
            try:
                from ..core import fit, gpx
                from ..core.store import default_title
                data = Path(path).read_bytes()
                track = fit.read(data) if fit.looks_like_fit(data) else gpx.read(data.decode("utf-8", "replace"))
                sport = Sport.from_fit(track.fit_sport) if fit.looks_like_fit(data) else Sport.WALK
                dialog = ImportDialog(self, Path(path).name, default_title(sport, track.start_time or 0, track.name), sport)
                if dialog.exec() != QDialog.DialogCode.Accepted:
                    continue
                last = self.store.import_activity(Path(path), dialog.title.text(), dialog.sport.currentData())
            except Exception as error:  # noqa: BLE001 — the message goes to the user
                QMessageBox.warning(self, "Import impossible", f"{Path(path).name} : {error}")
        if last is not None:
            self.changed.emit()
            self.open_activity(last)

    # ---- detail ----

    def show_list(self) -> None:
        self.current = None
        self.stack.setCurrentWidget(self.list_page)

    def open_activity(self, note: Note) -> None:
        if self.store is None or note.activity is None:
            return
        self.current = note
        while self.detail_layout.count():
            item = self.detail_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.detail_layout.addWidget(self._detail(note))
        self.stack.setCurrentWidget(self.detail_page)

    def _detail(self, note: Note) -> QWidget:
        s = theme.scheme()
        info = note.activity
        host = QWidget()
        outer = QVBoxLayout(host)
        outer.setContentsMargins(14, 12, 14, 0)
        head = QHBoxLayout()
        back = QToolButton()
        back.setIcon(icons.icon("back", s.on_surface, 22))
        back.clicked.connect(self.show_list)
        title = QLabel(note.title)
        title.setStyleSheet("font-size: 15pt; font-weight: 700;")
        edit = QPushButton("Modifier")
        edit.clicked.connect(lambda: self._edit(note))
        delete = QToolButton()
        delete.setIcon(icons.icon("delete", s.on_surface, 22))
        delete.setToolTip("Supprimer")
        delete.clicked.connect(lambda: self._delete(note))
        for w in (back, title):
            head.addWidget(w)
        head.addStretch()
        head.addWidget(edit)
        head.addWidget(delete)
        outer.addLayout(head)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        body = QWidget()
        col = QVBoxLayout(body)
        col.setSpacing(10)
        col.setAlignment(Qt.AlignmentFlag.AlignTop)
        sub = QLabel(f"{EMOJI[info.sport]} {info.sport.label} · {fmt_date(info.start)}")
        sub.setStyleSheet(f"color: {s.on_surface_variant};")
        col.addWidget(sub)
        if note.body.strip():
            description = QLabel(note.body)
            description.setWordWrap(True)
            col.addWidget(description)

        analysis = None
        try:
            if info.file:
                analysis = analyze(self.store.read_track(info), info.sport)
        except Exception as error:  # noqa: BLE001
            frame, lay = card("Fichier")
            lay.addWidget(QLabel(f"{error}"))
            col.addWidget(frame)

        ski = info.sport == Sport.SKI
        if analysis is not None:
            lines = map_lines(analysis, ski, False)
            if lines:
                tmap = TrackMap()
                samples = analysis.samples
                tmap.set_data(lines, [(samples[0].lat, samples[0].lon, QColor("#2E9E5B")), (samples[-1].lat, samples[-1].lon, QColor("#E5484D"))])
                col.addWidget(tmap)
                if ski:
                    toggle = QPushButton("Afficher tout le tracé")
                    toggle.setCheckable(True)

                    def switch(checked: bool, m=tmap, a=analysis, sm=samples) -> None:
                        m.set_data(map_lines(a, True, checked), [(sm[0].lat, sm[0].lon, QColor("#2E9E5B")), (sm[-1].lat, sm[-1].lon, QColor("#E5484D"))])
                    toggle.toggled.connect(switch)
                    col.addWidget(toggle)

        frame, lay = card("Résumé")
        items = []
        if info.distance > 0 or info.sport.has_gps:
            items.append(("Distance", act.fmt_distance(info.distance)))
        items.append(("Durée", act.fmt_duration(info.elapsed)))
        if info.sport.has_gps:
            items.append(("En mouvement", act.fmt_duration(info.moving)))
            if info.moving > 0 and info.distance > 0:
                items.append(("Allure moyenne" if info.sport == Sport.WALK else "Vitesse moyenne",
                              act.fmt_speed_for(info.sport, info.distance / info.moving)))
            if info.vmax and not ski:
                items.append(("Allure max" if info.sport == Sport.WALK else "Vitesse max", act.fmt_speed_for(info.sport, info.vmax)))
            if analysis is None or analysis.quality.has_altitude:
                items.append(("Dénivelé +", f"{info.ascent} m"))
                items.append(("Dénivelé −", f"{info.descent} m"))
        elif info.distance > 0 and info.elapsed > 0:
            items.append(("Vitesse moyenne", act.fmt_speed(info.distance / info.elapsed)))
        if info.hr is not None:
            items.append(("FC moyenne", f"{info.hr} bpm"))
        if analysis is not None and analysis.stats.hr_max is not None:
            items.append(("FC max", f"{analysis.stats.hr_max} bpm"))
        lay.addWidget(stat_grid(items))
        col.addWidget(frame)

        if analysis is not None and ski:
            st = analysis.stats
            frame, lay = card("Ski · descentes seulement")
            if st.runs == 0:
                lay.addWidget(QLabel("Aucune descente détectée."))
            else:
                lay.addWidget(stat_grid([
                    ("Descentes", str(st.runs)),
                    ("Dénivelé descendu", f"{round(st.run_drop)} m" if analysis.quality.has_altitude else "–"),
                    ("Vitesse max", act.fmt_speed(st.run_max_speed)),
                    ("Vitesse moyenne", act.fmt_speed(st.run_avg_speed)),
                    ("Plus longue", act.fmt_distance(st.run_longest)),
                ]))
            col.addWidget(frame)

        if analysis is not None:
            stops = sorted(analysis.pauses + analysis.stops, key=lambda x: x.start)
            if stops:
                frame, lay = card("Pauses et arrêts")
                for stop in stops:
                    row = QHBoxLayout()
                    row.addWidget(QLabel("Pause" if stop.manual else "Arrêt détecté"))
                    row.addStretch()
                    right = QLabel(f"{act.fmt_duration(stop.duration_ms // 1000)} · {fmt_hour(stop.start)}")
                    right.setStyleSheet(f"color: {s.on_surface_variant};")
                    row.addWidget(right)
                    lay.addLayout(row)
                col.addWidget(frame)
            idx = thin(len(analysis.samples))
            samples = analysis.samples
            if analysis.quality.has_altitude and len(idx) >= 2 and all(samples[i].alt is not None for i in idx):
                frame, lay = card()
                lay.addWidget(Chart("Altitude", [samples[i].dist for i in idx], [samples[i].alt for i in idx],
                                    f"{round(analysis.stats.min_alt or 0)} m", f"{round(analysis.stats.max_alt or 0)} m", s.primary))
                col.addWidget(frame)
            if len(idx) >= 2 and analysis.stats.max_speed > 0:
                frame, lay = card()
                lay.addWidget(Chart("Allure" if info.sport == Sport.WALK else "Vitesse", [samples[i].dist for i in idx],
                                    [samples[i].speed * 3.6 for i in idx], "0 km/h", act.fmt_speed(analysis.stats.max_speed), "#2E7DF6"))
                col.addWidget(frame)
            hr_idx = [i for i in idx if samples[i].hr is not None]
            if analysis.quality.has_hr and len(hr_idx) >= 2:
                frame, lay = card()
                lay.addWidget(Chart("Fréquence cardiaque", [samples[i].dist for i in hr_idx], [float(samples[i].hr) for i in hr_idx],
                                    f"{min(x.hr for x in samples if x.hr is not None)} bpm", f"{analysis.stats.hr_max or 0} bpm", "#E5484D"))
                col.addWidget(frame)

        frame, lay = card("Photos")
        photos = [a for a in note.attachments if a.lower().rsplit(".", 1)[-1] in {"jpg", "jpeg", "png", "gif", "webp", "bmp"}]
        if photos:
            from .attachments import AttachmentStrip
            strip = AttachmentStrip()
            strip.set_files(self.store.root, photos, s.on_surface)
            strip.open_requested.connect(self.open_file)
            strip.reveal_requested.connect(self.reveal_file)
            strip.remove_requested.connect(lambda p, n=note: self._remove_photo(n, p))
            lay.addWidget(strip)
        add = QPushButton("Ajouter une photo…")
        add.clicked.connect(lambda: self._add_photo(note))
        lay.addWidget(add)
        col.addWidget(frame)

        if info.file is None:
            distance = QPushButton("Modifier la distance…" if info.distance > 0 else "Ajouter une distance…")
            distance.clicked.connect(lambda: self._set_distance(note))
            col.addWidget(distance)

        if analysis is not None:
            q = analysis.quality
            frame, lay = card("Qualité des données")
            text = QLabel(f"{q.points} points" + (f" ({q.dropped} écartés)" if q.dropped else "")
                          + f" · un point toutes les {round(q.median_interval_sec)} s\n"
                          + f"Altitude : {'oui' if q.has_altitude else 'absente du fichier'}"
                          + f" · Fréquence cardiaque : {'oui' if q.has_hr else 'non'}")
            text.setStyleSheet(f"color: {s.on_surface_variant}; font-size: 9pt;")
            lay.addWidget(text)
            col.addWidget(frame)

        scroll.setWidget(body)
        outer.addWidget(scroll, 1)
        return host

    # ---- edits ----

    def _reopen(self, note: Note) -> None:
        self.changed.emit()
        fresh = next((n for n in self.store.scan_activities() if n.path == note.path), note)
        self.open_activity(fresh)

    def _edit(self, note: Note) -> None:
        dialog = EditDialog(self, note, note.activity.file is not None)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            try:
                saved = self.store.update_activity(note, dialog.title.text(), dialog.description.toPlainText(), dialog.sport.currentData())
                self._reopen(saved)
            except Exception as error:  # noqa: BLE001
                QMessageBox.warning(self, "Modification impossible", str(error))

    def _delete(self, note: Note) -> None:
        answer = QMessageBox.question(self, "Supprimer cette activité ?",
                                      "Le fichier du tracé et les photos sont supprimés aussi.")
        if answer == QMessageBox.StandardButton.Yes:
            self.store.delete(note)
            self.changed.emit()
            self.show_list()

    def _add_photo(self, note: Note) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Ajouter une photo", str(Path.home()), "Images (*.jpg *.jpeg *.png *.gif *.webp *.bmp)")
        if path:
            try:
                relative = self.store.add_attachment(Path(path))
                self._reopen(self.store.save(note.copy(attachments=note.attachments + [relative], updated=_now())))
            except OSError as error:
                QMessageBox.warning(self, "Photo impossible", str(error))

    def _remove_photo(self, note: Note, path: str) -> None:
        try:
            self.store.file_path(path).unlink()
        except OSError:
            pass
        self._reopen(self.store.save(note.copy(attachments=[a for a in note.attachments if a != path], updated=_now())))

    def _set_distance(self, note: Note) -> None:
        from PySide6.QtWidgets import QInputDialog
        km, ok = QInputDialog.getDouble(self, "Distance", "Distance (km)", note.activity.distance / 1000, 0, 100000, 2)
        if ok:
            info = act.ActivityInfo(**{**note.activity.__dict__, "distance": km * 1000})
            self._reopen(self.store.save(note.copy(activity=info, updated=_now())))


def _now() -> int:
    from ..core.store import now_ms
    return now_ms()
