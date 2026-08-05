"""Gestor no modal para buscar, agregar y editar letras."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QSplitter,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..lrc_parser import LRCParser, LyricLine, LyricsData
from ..lyrics_library import (
    LyricsCandidate,
    clone_lyrics_data,
    track_metadata_matches,
)
from ..storage import read_text_limited
from ..models import TrackInfo

_TIME_PATTERN = re.compile(r"^(\d+):([0-5]\d)(?:\.(\d{1,3}))?$")


def format_timestamp(milliseconds: int) -> str:
    milliseconds = max(0, int(milliseconds))
    minutes = milliseconds // 60000
    seconds = (milliseconds % 60000) // 1000
    centiseconds = (milliseconds % 1000) // 10
    return f"{minutes:02d}:{seconds:02d}.{centiseconds:02d}"


def parse_timestamp(value: str) -> Optional[int]:
    match = _TIME_PATTERN.fullmatch(value.strip())
    if not match:
        return None
    minutes = int(match.group(1))
    seconds = int(match.group(2))
    fraction = match.group(3) or "0"
    if len(fraction) == 1:
        milliseconds = int(fraction) * 100
    elif len(fraction) == 2:
        milliseconds = int(fraction) * 10
    else:
        milliseconds = int(fraction)
    return (minutes * 60 + seconds) * 1000 + milliseconds


def _metadata_matches_track(
    artist: str, title: str, track: Optional[TrackInfo]
) -> bool:
    if track is None:
        return False
    return track_metadata_matches(
        track.artist,
        track.title,
        artist,
        title,
    )


@dataclass
class LyricsSaveRequest:
    artist: str
    title: str
    album: str
    duration_ms: int
    lyrics_data: LyricsData
    source: str = "manual"


class LyricsManagerDialog(QDialog):
    """Ventana persistente que deja continuar la reproducción de Qobuz."""

    search_requested = pyqtSignal(str, str)
    local_requested = pyqtSignal()
    preview_requested = pyqtSignal(object)
    apply_requested = pyqtSignal(object)
    save_requested = pyqtSignal(object)
    delete_requested = pyqtSignal(object)
    capture_requested = pyqtSignal(int)

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setWindowTitle("Gestionar letras — Letra Canción")
        self.setModal(False)
        self.setMinimumSize(980, 720)
        self.resize(1120, 780)
        self._current_track: Optional[TrackInfo] = None
        self._preview_candidate: Optional[LyricsCandidate] = None
        self._preview_lyrics: Optional[LyricsData] = None
        self._editor_source = "manual"
        self._editor_dirty = False
        self._loading_editor = False

        self._build_ui()
        self._apply_style()
        self._capture_shortcut = QShortcut(QKeySequence("F8"), self)
        self._capture_shortcut.activated.connect(self._capture_selected_row)
        self._connect_editor_dirty_signals()

    def _apply_style(self) -> None:
        self.setStyleSheet(
            """
            QDialog, QWidget { background:#090e24; color:#e8e9f2; }
            QGroupBox {
                border:1px solid #29325d; border-radius:10px;
                margin-top:12px; padding-top:12px; font-weight:600;
            }
            QGroupBox::title { left:12px; padding:0 5px; color:#b8a7ff; }
            QLineEdit, QPlainTextEdit, QListWidget, QTableWidget, QSpinBox {
                background:#111735; color:#f4f5fb; border:1px solid #303a70;
                border-radius:7px; padding:6px; selection-background-color:#6d4bd6;
            }
            QLineEdit:focus, QPlainTextEdit:focus, QListWidget:focus,
            QTableWidget:focus, QSpinBox:focus {
                border:2px solid #c4b5fd;
            }
            QPushButton {
                background:#6d4bd6; color:white; border:none;
                border-radius:7px; padding:8px 13px; font-weight:600;
            }
            QPushButton:hover { background:#825df8; }
            QPushButton:focus { border:2px solid #f8fafc; }
            QPushButton:disabled { background:#303550; color:#777e9d; }
            QPushButton#dangerButton { background:#8f2942; }
            QPushButton#dangerButton:hover { background:#b33452; }
            QPushButton#dangerButton:disabled {
                background:#303550; color:#777e9d;
            }
            QTabBar::tab {
                background:#111735; color:#aeb3cc; padding:10px 22px;
                border-top-left-radius:7px; border-top-right-radius:7px;
            }
            QTabBar::tab:selected { background:#25204d; color:white; }
            QTabBar::tab:focus { border:2px solid #c4b5fd; }
            QCheckBox:focus {
                border:2px solid #c4b5fd; border-radius:5px;
            }
            QHeaderView::section {
                background:#171e43; color:#d6d8e8; border:none; padding:7px;
            }
            """
        )

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(10)

        self.current_track_label = QLabel("Qobuz: sin canción activa")
        self.current_track_label.setAccessibleName(
            "Canción activa en Qobuz"
        )
        self.current_track_label.setStyleSheet("color:#aeb3cc;")
        root.addWidget(self.current_track_label)

        self.tabs = QTabWidget()
        self.tabs.setAccessibleName("Secciones del gestor de letras")
        root.addWidget(self.tabs, 1)
        self._build_search_tab()
        self._build_editor_tab()

        self.close_button = QPushButton("Cerrar")
        self.close_button.setAccessibleDescription(
            "Oculta el gestor y conserva el borrador actual."
        )
        self.close_button.clicked.connect(self.hide)
        footer = QHBoxLayout()
        footer.addStretch()
        footer.addWidget(self.close_button)
        root.addLayout(footer)

    def _build_search_tab(self) -> None:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(10, 14, 10, 10)

        form_host = QGroupBox("Buscar cualquier canción")
        form = QGridLayout(form_host)
        self.search_artist_edit = QLineEdit()
        self.search_artist_edit.setPlaceholderText("Artista")
        self.search_artist_edit.setAccessibleName("Artista para buscar")
        self.search_title_edit = QLineEdit()
        self.search_title_edit.setPlaceholderText("Título")
        self.search_title_edit.setAccessibleName("Título para buscar")
        self.search_button = QPushButton("Buscar")
        self.search_button.setAccessibleDescription(
            "Busca coincidencias en la biblioteca y los proveedores."
        )
        self.new_button = QPushButton("Nueva letra")
        self.new_button.setAccessibleDescription(
            "Abre un borrador vacío en el editor."
        )
        artist_label = QLabel("&Artista")
        artist_label.setBuddy(self.search_artist_edit)
        title_label = QLabel("&Título")
        title_label.setBuddy(self.search_title_edit)
        form.addWidget(artist_label, 0, 0)
        form.addWidget(self.search_artist_edit, 0, 1)
        form.addWidget(title_label, 0, 2)
        form.addWidget(self.search_title_edit, 0, 3)
        form.addWidget(self.search_button, 0, 4)
        form.addWidget(self.new_button, 0, 5)
        layout.addWidget(form_host)

        self.local_button = QPushButton("Ver letras guardadas")
        self.local_button.setAccessibleDescription(
            "Muestra todas las letras guardadas en la biblioteca local."
        )
        layout.addWidget(self.local_button)

        self.search_status_label = QLabel(
            "Escribe artista y título para buscar en tu biblioteca y proveedores."
        )
        self.search_status_label.setAccessibleName("Estado de búsqueda")
        self.search_status_label.setStyleSheet("color:#9ca3c5; padding:4px;")
        layout.addWidget(self.search_status_label)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.results_list = QListWidget()
        self.results_list.setAccessibleName("Resultados de búsqueda")
        self.results_list.setAccessibleDescription(
            "Selecciona una coincidencia para cargar su previsualización."
        )
        self.results_list.setMinimumWidth(360)
        splitter.addWidget(self.results_list)

        preview_host = QWidget()
        preview_layout = QVBoxLayout(preview_host)
        preview_layout.setContentsMargins(8, 0, 0, 0)
        self.preview_metadata_label = QLabel("Selecciona una coincidencia")
        self.preview_metadata_label.setAccessibleName(
            "Metadatos de la previsualización"
        )
        self.preview_metadata_label.setWordWrap(True)
        self.preview_metadata_label.setStyleSheet(
            "font-size:15px; font-weight:600; color:#dcd8ff;"
        )
        self.preview_text = QPlainTextEdit()
        self.preview_text.setReadOnly(True)
        self.preview_text.setAccessibleName("Previsualización de la letra")
        self.preview_text.setPlaceholderText(
            "La previsualización aparecerá aquí."
        )
        preview_layout.addWidget(self.preview_metadata_label)
        preview_layout.addWidget(self.preview_text, 1)

        actions = QHBoxLayout()
        self.apply_button = QPushButton("Aplicar a Qobuz")
        self.apply_button.setAccessibleDescription(
            "Usa esta letra para la canción que se reproduce actualmente."
        )
        self.save_copy_button = QPushButton("Guardar copia")
        self.save_copy_button.setAccessibleDescription(
            "Guarda una copia en la biblioteca personal."
        )
        self.edit_button = QPushButton("Editar")
        self.edit_button.setAccessibleDescription(
            "Abre esta letra en el editor."
        )
        self.delete_button = QPushButton("Eliminar local")
        self.delete_button.setAccessibleDescription(
            "Elimina la copia seleccionada de la biblioteca personal."
        )
        self.delete_button.setObjectName("dangerButton")
        for button in (
            self.apply_button,
            self.save_copy_button,
            self.edit_button,
            self.delete_button,
        ):
            button.setEnabled(False)
            actions.addWidget(button)
        preview_layout.addLayout(actions)
        splitter.addWidget(preview_host)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)
        layout.addWidget(splitter, 1)
        self.tabs.addTab(tab, "Buscar")

        self.search_button.clicked.connect(self._request_search)
        self.local_button.clicked.connect(self._request_local)
        self.search_artist_edit.returnPressed.connect(self._request_search)
        self.search_title_edit.returnPressed.connect(self._request_search)
        self.new_button.clicked.connect(self.start_new_entry)
        self.results_list.currentItemChanged.connect(
            self._on_result_selected
        )
        self.apply_button.clicked.connect(self._apply_preview)
        self.save_copy_button.clicked.connect(self._save_preview_copy)
        self.edit_button.clicked.connect(self._edit_preview)
        self.delete_button.clicked.connect(self._delete_preview)

    def _build_editor_tab(self) -> None:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(10, 14, 10, 10)

        metadata_group = QGroupBox("Canción")
        self.editor_metadata_group = metadata_group
        metadata_form = QFormLayout(metadata_group)
        self.editor_artist_edit = QLineEdit()
        self.editor_artist_edit.setAccessibleName("Artista de la letra")
        self.editor_title_edit = QLineEdit()
        self.editor_title_edit.setAccessibleName("Título de la letra")
        self.editor_album_edit = QLineEdit()
        self.editor_album_edit.setAccessibleName("Álbum de la letra")
        self.editor_duration_spin = QSpinBox()
        self.editor_duration_spin.setAccessibleName(
            "Duración de la canción"
        )
        self.editor_duration_spin.setRange(0, 60 * 60)
        self.editor_duration_spin.setSuffix(" s")
        metadata_form.addRow("Artista:", self.editor_artist_edit)
        metadata_form.addRow("Título:", self.editor_title_edit)
        metadata_form.addRow("Álbum:", self.editor_album_edit)
        metadata_form.addRow("Duración:", self.editor_duration_spin)
        import_group = QGroupBox("Pegar o importar")
        self.editor_import_group = import_group
        import_layout = QVBoxLayout(import_group)
        self.raw_lyrics_edit = QPlainTextEdit()
        self.raw_lyrics_edit.setAccessibleName(
            "Texto de letra para procesar"
        )
        self.raw_lyrics_edit.setPlaceholderText(
            "Pega texto plano o contenido LRC. Después pulsa “Procesar texto”."
        )
        import_layout.addWidget(self.raw_lyrics_edit)
        import_actions = QHBoxLayout()
        self.process_text_button = QPushButton("Procesar texto")
        self.import_button = QPushButton("Importar .lrc")
        self.distribute_button = QPushButton("Distribuir tiempos")
        import_actions.addWidget(self.process_text_button)
        import_actions.addWidget(self.import_button)
        import_actions.addWidget(self.distribute_button)
        import_actions.addStretch()
        import_layout.addLayout(import_actions)

        self.lines_table = QTableWidget(0, 2)
        self.lines_table.setAccessibleName("Líneas de la letra")
        self.lines_table.setAccessibleDescription(
            "Tabla editable con el tiempo y el texto de cada línea."
        )
        self.lines_table.setHorizontalHeaderLabels(("Tiempo", "Texto"))
        self.lines_table.verticalHeader().setVisible(False)
        self.lines_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.ResizeToContents
        )
        self.lines_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch
        )
        self.lines_table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows
        )
        row_actions = QHBoxLayout()
        self.add_row_button = QPushButton("Añadir línea")
        self.remove_row_button = QPushButton("Eliminar línea")
        self.move_up_button = QPushButton("Subir")
        self.move_down_button = QPushButton("Bajar")
        self.capture_button = QPushButton("Usar tiempo actual (F8)")
        for button in (
            self.add_row_button,
            self.remove_row_button,
            self.move_up_button,
            self.move_down_button,
            self.capture_button,
        ):
            row_actions.addWidget(button)
        row_actions.addStretch()

        footer = QHBoxLayout()
        self.synced_check = QCheckBox("Letra sincronizada")
        self.synced_check.setAccessibleDescription(
            "Indica que cada línea tiene un tiempo válido y creciente."
        )
        self.editor_status_label = QLabel("")
        self.editor_status_label.setAccessibleName("Estado del editor")
        self.editor_status_label.setStyleSheet("color:#9ca3c5;")
        self.save_editor_button = QPushButton("Guardar en biblioteca")
        footer.addWidget(self.synced_check)
        footer.addWidget(self.editor_status_label, 1)
        footer.addWidget(self.save_editor_button)

        time_section = QWidget()
        self.editor_time_section = time_section
        time_layout = QVBoxLayout(time_section)
        time_layout.setContentsMargins(0, 0, 0, 0)
        time_layout.addWidget(self.lines_table, 1)
        time_layout.addLayout(row_actions)
        time_layout.addLayout(footer)

        self.editor_sections_splitter = QSplitter(Qt.Orientation.Vertical)
        self.editor_sections_splitter.setAccessibleName(
            "Secciones redimensionables del editor"
        )
        self.editor_sections_splitter.setChildrenCollapsible(True)
        self.editor_sections_splitter.addWidget(metadata_group)
        self.editor_sections_splitter.addWidget(import_group)
        self.editor_sections_splitter.addWidget(time_section)
        self.editor_sections_splitter.setStretchFactor(0, 1)
        self.editor_sections_splitter.setStretchFactor(1, 1)
        self.editor_sections_splitter.setStretchFactor(2, 2)
        self.editor_sections_splitter.setSizes([150, 180, 400])
        layout.addWidget(self.editor_sections_splitter, 1)
        self.tabs.addTab(tab, "Agregar / editar")

        self.process_text_button.clicked.connect(self._process_raw_text)
        self.import_button.clicked.connect(self._import_lrc)
        self.distribute_button.clicked.connect(self._distribute_times)
        self.add_row_button.clicked.connect(self._add_row)
        self.remove_row_button.clicked.connect(self._remove_selected_row)
        self.move_up_button.clicked.connect(lambda: self._move_selected_row(-1))
        self.move_down_button.clicked.connect(
            lambda: self._move_selected_row(1)
        )
        self.capture_button.clicked.connect(self._capture_selected_row)
        self.save_editor_button.clicked.connect(self._save_editor)
        self.editor_artist_edit.textChanged.connect(
            self._update_capture_availability
        )
        self.editor_title_edit.textChanged.connect(
            self._update_capture_availability
        )

    def _connect_editor_dirty_signals(self) -> None:
        for editor in (
            self.editor_artist_edit,
            self.editor_title_edit,
            self.editor_album_edit,
        ):
            editor.textEdited.connect(self._mark_editor_dirty)
        self.editor_duration_spin.valueChanged.connect(
            self._mark_editor_dirty
        )
        self.raw_lyrics_edit.textChanged.connect(self._mark_editor_dirty)
        self.lines_table.itemChanged.connect(self._mark_editor_dirty)
        self.synced_check.toggled.connect(self._mark_editor_dirty)

    def _mark_editor_dirty(self, *args) -> None:
        if not self._loading_editor:
            self._editor_dirty = True

    def _confirm_discard_editor(self) -> bool:
        if not self._editor_dirty:
            return True
        answer = QMessageBox.question(
            self,
            "Descartar cambios sin guardar",
            (
                "El editor contiene cambios sin guardar.\n\n"
                "¿Quieres descartarlos y abrir otra letra?"
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return answer == QMessageBox.StandardButton.Yes

    def confirm_application_exit(self) -> bool:
        """Confirma el cierre global cuando existe un borrador sin guardar."""
        if not self._editor_dirty:
            return True
        answer = QMessageBox.question(
            self,
            "Salir con cambios sin guardar",
            (
                "El editor contiene cambios sin guardar.\n\n"
                "¿Quieres descartarlos y salir de Letra Canción?"
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return answer == QMessageBox.StandardButton.Yes

    def set_current_track(self, track: Optional[TrackInfo]) -> None:
        """Actualiza acciones contextuales sin modificar el borrador."""
        self._current_track = track
        if track is None:
            self.current_track_label.setText("Qobuz: sin canción activa")
        else:
            self.current_track_label.setText(
                f"Qobuz: {track.artist} — {track.title}"
            )
        self._update_preview_actions()
        self._update_capture_availability()

    def show_for_track(self, track: Optional[TrackInfo]) -> None:
        self.set_current_track(track)
        if track is not None:
            self.search_artist_edit.setText(track.artist)
            self.search_title_edit.setText(track.title)
        self.show()
        self.raise_()
        self.activateWindow()

    def _request_search(self) -> None:
        artist = self.search_artist_edit.text().strip()
        title = self.search_title_edit.text().strip()
        if not artist or not title:
            self.search_status_label.setText(
                "El artista y el título son obligatorios."
            )
            missing = (
                self.search_artist_edit
                if not artist
                else self.search_title_edit
            )
            missing.setFocus()
            return
        self.set_searching()
        self.search_requested.emit(artist, title)

    def _request_local(self) -> None:
        self.set_searching()
        self.search_status_label.setText("Cargando letras guardadas…")
        self.local_requested.emit()

    def set_searching(self) -> None:
        self.search_button.setEnabled(False)
        self.results_list.clear()
        self._clear_preview()
        self.search_status_label.setText("Buscando coincidencias…")

    def set_search_results(self, candidates: list[LyricsCandidate]) -> None:
        self.search_button.setEnabled(True)
        self.results_list.clear()
        self._clear_preview()
        if not candidates:
            self.search_status_label.setText(
                "No se encontraron coincidencias. Puedes agregar la letra manualmente."
            )
            self.new_button.setFocus()
            return
        for candidate in candidates:
            sync_label = (
                "sincronizada"
                if candidate.is_synced is True
                else "sin sincronizar"
                if candidate.is_synced is False
                else "sin verificar"
            )
            item = QListWidgetItem(
                f"{candidate.title}\n"
                f"{candidate.artist} · {candidate.provider} · {sync_label}"
            )
            item.setData(Qt.ItemDataRole.UserRole, candidate)
            self.results_list.addItem(item)
        self.search_status_label.setText(
            f"{len(candidates)} coincidencia(s). Selecciona una para previsualizar."
        )
        self.results_list.setCurrentRow(0)
        self.results_list.setFocus()

    def set_search_error(self, message: str) -> None:
        self.search_button.setEnabled(True)
        self.search_status_label.setText(f"No se pudo completar la búsqueda: {message}")
        self.search_button.setFocus()

    def _on_result_selected(
        self,
        current: Optional[QListWidgetItem],
        _previous: Optional[QListWidgetItem],
    ) -> None:
        self._clear_preview()
        if current is None:
            return
        candidate = current.data(Qt.ItemDataRole.UserRole)
        if not isinstance(candidate, LyricsCandidate):
            return
        self._preview_candidate = candidate
        self.preview_metadata_label.setText(
            f"{candidate.artist} — {candidate.title}\n"
            f"{candidate.album or 'Álbum desconocido'} · {candidate.provider}"
        )
        self.preview_text.setPlainText("Cargando letra…")
        self.preview_requested.emit(candidate)

    def set_preview(
        self,
        candidate: LyricsCandidate,
        lyrics: Optional[LyricsData],
        error: str = "",
    ) -> None:
        if candidate is not self._preview_candidate:
            return
        if lyrics is None or not lyrics.lines:
            self._preview_lyrics = None
            self.preview_text.setPlainText(
                error or "Esta coincidencia no contiene una letra utilizable."
            )
        else:
            self._preview_lyrics = clone_lyrics_data(lyrics)
            candidate.lyrics_data = clone_lyrics_data(lyrics)
            candidate.is_synced = lyrics.is_synced
            self.preview_text.setPlainText(LRCParser.to_lrc(lyrics))
        self._update_preview_actions()

    def _clear_preview(self) -> None:
        self._preview_candidate = None
        self._preview_lyrics = None
        self.preview_metadata_label.setText("Selecciona una coincidencia")
        self.preview_text.clear()
        self._update_preview_actions()

    def _update_preview_actions(self) -> None:
        loaded = (
            self._preview_candidate is not None
            and self._preview_lyrics is not None
            and bool(self._preview_lyrics.lines)
        )
        self.save_copy_button.setEnabled(loaded)
        self.edit_button.setEnabled(loaded)
        self.delete_button.setEnabled(
            loaded and bool(self._preview_candidate.is_local)
        )
        self.apply_button.setEnabled(
            loaded
            and _metadata_matches_track(
                self._preview_candidate.artist,
                self._preview_candidate.title,
                self._current_track,
            )
        )

    def _apply_preview(self) -> None:
        if self._preview_candidate and self._preview_lyrics:
            self._preview_candidate.lyrics_data = clone_lyrics_data(
                self._preview_lyrics
            )
            self.apply_requested.emit(self._preview_candidate)

    def _save_preview_copy(self) -> None:
        if not self._preview_candidate or not self._preview_lyrics:
            return
        self.save_requested.emit(
            LyricsSaveRequest(
                artist=self._preview_candidate.artist,
                title=self._preview_candidate.title,
                album=self._preview_candidate.album,
                duration_ms=self._preview_candidate.duration_ms,
                lyrics_data=clone_lyrics_data(self._preview_lyrics),
                source=self._preview_candidate.provider,
            )
        )

    def _edit_preview(self) -> None:
        if not self._preview_candidate or not self._preview_lyrics:
            return
        self.load_editor(
            self._preview_lyrics,
            duration_ms=self._preview_candidate.duration_ms,
            source=self._preview_candidate.provider,
        )

    def _delete_preview(self) -> None:
        candidate = self._preview_candidate
        if candidate is None or not candidate.is_local:
            return
        response = QMessageBox.question(
            self,
            "Eliminar letra local",
            (
                f"¿Eliminar la letra local de "
                f"{candidate.artist} — {candidate.title}?\n\n"
                "Esta acción no se puede deshacer. La aplicación volverá "
                "a buscar la letra en el caché y los proveedores."
            ),
            QMessageBox.StandardButton.Yes
            | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if response == QMessageBox.StandardButton.Yes:
            self.delete_requested.emit(candidate)

    def remove_candidate(self, candidate: LyricsCandidate) -> None:
        """Retira de la lista un resultado local eliminado."""
        for row in range(self.results_list.count()):
            item = self.results_list.item(row)
            stored = item.data(Qt.ItemDataRole.UserRole)
            if (
                stored is candidate
                or (
                    isinstance(stored, LyricsCandidate)
                    and stored.provider == candidate.provider
                    and stored.provider_id == candidate.provider_id
                )
            ):
                self.results_list.takeItem(row)
                break
        self._clear_preview()
        self.search_status_label.setText(
            f"Se eliminó la letra local de "
            f"{candidate.artist} — {candidate.title}."
        )

    def start_new_entry(self) -> bool:
        lyrics = LyricsData(lines=[], is_synced=False)
        if self._current_track is not None:
            lyrics.artist = self._current_track.artist
            lyrics.title = self._current_track.title
            lyrics.album = self._current_track.album
        return self.load_editor(lyrics, source="manual")

    def load_editor(
        self,
        lyrics: LyricsData,
        duration_ms: int = 0,
        source: str = "manual",
    ) -> bool:
        if not self._confirm_discard_editor():
            return False
        self._loading_editor = True
        try:
            self._editor_source = source or "manual"
            self.editor_artist_edit.setText(lyrics.artist or "")
            self.editor_title_edit.setText(lyrics.title or "")
            self.editor_album_edit.setText(lyrics.album or "")
            self.editor_duration_spin.setValue(
                max(0, duration_ms // 1000)
            )
            self.synced_check.setChecked(lyrics.is_synced)
            self._set_table_lines(lyrics.lines)
            self.raw_lyrics_edit.clear()
            self.editor_status_label.setText("")
        finally:
            self._loading_editor = False
        self._editor_dirty = False
        self.tabs.setCurrentIndex(1)
        self._update_capture_availability()
        self.editor_artist_edit.setFocus()
        return True

    def _set_table_lines(self, lines: list[LyricLine]) -> None:
        self.lines_table.setRowCount(0)
        for line in lines:
            self._append_row(line.timestamp_ms, line.text)
        if self.lines_table.rowCount():
            self.lines_table.selectRow(0)

    def _append_row(self, timestamp_ms: int, text: str) -> None:
        row = self.lines_table.rowCount()
        self.lines_table.insertRow(row)
        self.lines_table.setItem(
            row, 0, QTableWidgetItem(format_timestamp(timestamp_ms))
        )
        self.lines_table.setItem(row, 1, QTableWidgetItem(text))

    def _add_row(self) -> None:
        row_count = self.lines_table.rowCount()
        previous_ms = 0
        if row_count:
            previous_item = self.lines_table.item(row_count - 1, 0)
            previous_ms = (
                parse_timestamp(previous_item.text())
                if previous_item is not None
                else 0
            ) or 0
        self._append_row(previous_ms + (4000 if row_count else 0), "")
        self.lines_table.selectRow(self.lines_table.rowCount() - 1)
        self.lines_table.editItem(
            self.lines_table.item(self.lines_table.rowCount() - 1, 1)
        )
        self._mark_editor_dirty()

    def _remove_selected_row(self) -> None:
        row = self.lines_table.currentRow()
        if row >= 0:
            self.lines_table.removeRow(row)
            self._mark_editor_dirty()
            if self.lines_table.rowCount():
                self.lines_table.selectRow(
                    min(row, self.lines_table.rowCount() - 1)
                )

    def _move_selected_row(self, delta: int) -> None:
        row = self.lines_table.currentRow()
        target = row + delta
        if row < 0 or not 0 <= target < self.lines_table.rowCount():
            return
        values = [
            self.lines_table.item(row, column).text()
            if self.lines_table.item(row, column)
            else ""
            for column in range(2)
        ]
        target_values = [
            self.lines_table.item(target, column).text()
            if self.lines_table.item(target, column)
            else ""
            for column in range(2)
        ]
        for column in range(2):
            self.lines_table.setItem(
                row, column, QTableWidgetItem(target_values[column])
            )
            self.lines_table.setItem(
                target, column, QTableWidgetItem(values[column])
            )
        self.lines_table.selectRow(target)
        self._mark_editor_dirty()

    def _process_raw_text(self) -> None:
        content = self.raw_lyrics_edit.toPlainText().strip()
        if not content:
            QMessageBox.warning(self, "Letra vacía", "Pega una letra primero.")
            return
        try:
            if LRCParser.TIMESTAMP_PATTERN.search(content):
                lyrics = LRCParser.parse(content)
            else:
                lyrics = LRCParser.parse_plain_lyrics(
                    content, self.editor_duration_spin.value() * 1000
                )
        except ValueError as exc:
            QMessageBox.warning(self, "Formato no válido", str(exc))
            return
        if not lyrics.lines:
            QMessageBox.warning(
                self, "Formato no válido", "No se encontraron líneas de letra."
            )
            return
        if lyrics.artist and not self.editor_artist_edit.text().strip():
            self.editor_artist_edit.setText(lyrics.artist)
        if lyrics.title and not self.editor_title_edit.text().strip():
            self.editor_title_edit.setText(lyrics.title)
        if lyrics.album and not self.editor_album_edit.text().strip():
            self.editor_album_edit.setText(lyrics.album)
        self._set_table_lines(lyrics.lines)
        self.synced_check.setChecked(lyrics.is_synced)
        self._mark_editor_dirty()
        self.editor_status_label.setText(
            f"{len(lyrics.lines)} líneas procesadas."
        )

    def _import_lrc(self) -> None:
        filename, _ = QFileDialog.getOpenFileName(
            self,
            "Importar letra LRC",
            "",
            "Letras LRC (*.lrc);;Archivos de texto (*.txt);;Todos (*.*)",
        )
        if not filename:
            return
        try:
            content = read_text_limited(
                Path(filename),
                max_bytes=LRCParser.MAX_CONTENT_CHARS,
                encoding="utf-8-sig",
            )
        except Exception as exc:
            logger.warning("No se pudo importar un archivo LRC: %s", exc)
            QMessageBox.critical(
                self,
                "No se pudo importar",
                "El archivo debe ser texto UTF-8 y no superar 512 KiB.",
            )
            return
        self.raw_lyrics_edit.setPlainText(content)
        self._process_raw_text()

    def _current_table_texts(self) -> list[str]:
        texts: list[str] = []
        for row in range(self.lines_table.rowCount()):
            item = self.lines_table.item(row, 1)
            text = item.text().strip() if item else ""
            if text:
                texts.append(text)
        return texts

    def _distribute_times(self) -> None:
        texts = self._current_table_texts()
        if not texts:
            QMessageBox.warning(
                self, "Sin líneas", "Agrega o procesa líneas antes de distribuir."
            )
            return
        lyrics = LRCParser.parse_plain_lyrics(
            "\n".join(texts), self.editor_duration_spin.value() * 1000
        )
        self._set_table_lines(lyrics.lines)
        self.synced_check.setChecked(False)
        self._mark_editor_dirty()
        self.editor_status_label.setText("Tiempos estimados automáticamente.")

    def _update_capture_availability(self) -> None:
        enabled = _metadata_matches_track(
            self.editor_artist_edit.text(),
            self.editor_title_edit.text(),
            self._current_track,
        )
        self.capture_button.setEnabled(enabled)
        self._capture_shortcut.setEnabled(enabled)
        guidance = (
            "Asigna la posición actual de Qobuz a la fila seleccionada"
            if enabled
            else "Disponible cuando el editor coincide con la canción de Qobuz"
        )
        self.capture_button.setToolTip(guidance)
        self.capture_button.setAccessibleDescription(guidance)

    def _capture_selected_row(self) -> None:
        if not self.capture_button.isEnabled():
            return
        row = self.lines_table.currentRow()
        if row < 0:
            QMessageBox.warning(
                self, "Selecciona una línea", "Selecciona la fila que deseas marcar."
            )
            return
        self.capture_requested.emit(row)

    def set_captured_timestamp(self, row: int, timestamp_ms: int) -> None:
        if not 0 <= row < self.lines_table.rowCount():
            return
        self.lines_table.setItem(
            row, 0, QTableWidgetItem(format_timestamp(timestamp_ms))
        )
        self.synced_check.setChecked(True)
        self._mark_editor_dirty()
        next_row = min(row + 1, self.lines_table.rowCount() - 1)
        self.lines_table.selectRow(next_row)
        self.editor_status_label.setText(
            f"Fila {row + 1} marcada en {format_timestamp(timestamp_ms)}."
        )

    def _build_save_request(self) -> LyricsSaveRequest:
        artist = self.editor_artist_edit.text().strip()
        title = self.editor_title_edit.text().strip()
        album = self.editor_album_edit.text().strip()
        if not artist or not title:
            raise ValueError("El artista y el título son obligatorios.")

        lines: list[LyricLine] = []
        for row in range(self.lines_table.rowCount()):
            time_item = self.lines_table.item(row, 0)
            text_item = self.lines_table.item(row, 1)
            timestamp_ms = (
                parse_timestamp(time_item.text()) if time_item else None
            )
            text = text_item.text().strip() if text_item else ""
            if timestamp_ms is None:
                raise ValueError(
                    f"El tiempo de la fila {row + 1} debe usar mm:ss.xx."
                )
            if not text:
                raise ValueError(f"La fila {row + 1} no contiene texto.")
            lines.append(LyricLine(timestamp_ms=timestamp_ms, text=text))

        if not lines:
            raise ValueError("La letra debe contener al menos una línea.")
        if self.synced_check.isChecked():
            for previous, current in zip(lines, lines[1:]):
                if current.timestamp_ms <= previous.timestamp_ms:
                    raise ValueError(
                        "Las letras sincronizadas requieren tiempos "
                        "estrictamente crecientes."
                    )

        lyrics = LyricsData(
            lines=lines,
            artist=artist,
            title=title,
            album=album or None,
            is_synced=self.synced_check.isChecked(),
        )
        return LyricsSaveRequest(
            artist=artist,
            title=title,
            album=album,
            duration_ms=self.editor_duration_spin.value() * 1000,
            lyrics_data=lyrics,
            source=self._editor_source,
        )

    def _save_editor(self) -> None:
        try:
            request = self._build_save_request()
        except ValueError as exc:
            QMessageBox.warning(self, "Revisa la letra", str(exc))
            return
        self.save_requested.emit(request)

    def confirm_overwrite(self, artist: str, title: str) -> bool:
        answer = QMessageBox.question(
            self,
            "Reemplazar letra local",
            f"Ya existe una versión local para {artist} — {title}.\n"
            "¿Quieres reemplazarla?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return answer == QMessageBox.StandardButton.Yes

    def show_save_success(self, artist: str, title: str) -> None:
        self._editor_dirty = False
        self.editor_status_label.setText(
            f"Guardada: {artist} — {title}"
        )
        self.search_status_label.setText(
            f"La versión local de {artist} — {title} está lista."
        )
