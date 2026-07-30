"""
Letra Canción - Aplicación principal

Sistema de letras sincronizadas para Qobuz.
Detecta la música reproduciéndose, obtiene letras y las muestra
en una ventana inmersiva sincronizada.
"""

import asyncio
import logging
import sys
import threading
from collections.abc import Coroutine
from typing import Any, Optional

from PyQt6.QtWidgets import QApplication, QMessageBox
from PyQt6.QtCore import QObject, QTimer, pyqtSignal
import qasync

from .window_detector import WindowTitleDetector
from .models import TrackInfo, PlaybackInfo, PlayerState
from .lyrics_service import LyricsService, LyricsSearchResult
from .lyrics_library import (
    LyricsCandidate,
    clone_lyrics_data,
    track_metadata_matches,
)
from .lrc_parser import LyricsData
from .translation_service import (
    TranslationService,
    is_translation_enabled_by_default,
)
from .sync_engine import SyncEngine, SyncState, SyncMode
from .hotkeys import HotkeyManager, HotkeyAction, KEYBOARD_AVAILABLE
from .settings import SettingsManager
from .ui.overlay import LyricsOverlay, OverlayConfig
from .ui.lyrics_manager import LyricsManagerDialog, LyricsSaveRequest
from .ui.tray import TrayIcon
from .ui.brand import create_brand_icon

# Intentar importar el detector SMTC como primario (H7)
try:
    from .detector import MediaDetector

    SMTC_AVAILABLE = True
except Exception:
    SMTC_AVAILABLE = False

# Configurar logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)

logger = logging.getLogger(__name__)


class _AppUiBridge(QObject):
    """Puente para reenviar acciones externas al hilo principal de Qt."""

    hotkey_triggered = pyqtSignal(object)


class LetraCancionApp:
    """
    Aplicación principal que orquesta todos los componentes.
    """

    def __init__(self):
        # Componentes
        self.detector: Any = None
        self.lyrics_service: Optional[LyricsService] = None
        self.translation_service: Optional[TranslationService] = None
        self.sync_engine: Optional[SyncEngine] = None
        self.hotkey_manager: Optional[HotkeyManager] = None
        self.overlay: Optional[LyricsOverlay] = None
        self.lyrics_manager: Optional[LyricsManagerDialog] = None
        self.tray: Optional[TrayIcon] = None

        # Configuración persistente (H7)
        self.settings_manager = SettingsManager()

        # Estado
        self._current_track: Optional[TrackInfo] = None
        self._running: bool = False
        self._translation_enabled: bool = (
            self.settings_manager.settings.translation_enabled
        )
        self._translation_cancel_event: Optional[threading.Event] = None
        self._lyrics_fetch_task: Optional[asyncio.Task[None]] = None
        self._translation_task: Optional[asyncio.Task[None]] = None
        self._manager_search_task: Optional[asyncio.Task[None]] = None
        self._manager_preview_task: Optional[asyncio.Task[None]] = None
        self._detector_task: Optional[asyncio.Task[None]] = None

        # Qt App
        self.app: Optional[QApplication] = None
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self._ui_bridge = _AppUiBridge()
        self._ui_bridge.hotkey_triggered.connect(self._handle_hotkey_on_ui_thread)

    def _build_overlay_config(self) -> OverlayConfig:
        """Construye OverlayConfig desde la configuración persistente."""
        s = self.settings_manager.settings
        return OverlayConfig(
            width=s.overlay_width,
            height=s.overlay_height,
            opacity=s.opacity,
            font_size=s.font_size,
            highlight_font_size=s.highlight_font_size,
            font_family=s.font_family,
            bg_color=s.bg_color,
            text_color=s.text_color,
            highlight_color=s.highlight_color,
            dim_color=s.dim_color,
            translation_enabled=s.translation_enabled,
            translation_font_size=s.translation_font_size,
            translation_color=s.translation_color,
            manual_scroll_timeout_s=s.manual_scroll_timeout_s,
            always_on_top=s.always_on_top,
            window_maximized=s.window_maximized,
        )

    async def initialize(self) -> bool:
        """
        Inicializa todos los componentes.

        Returns:
            True si la inicialización fue exitosa.
        """
        logger.info("Inicializando Letra Canción...")

        try:
            # 1. Inicializar detector de música — SMTC primario, WindowTitle fallback (H7)
            logger.info("Inicializando detector de música...")
            smtc_ok = False
            smtc_detector = None
            if SMTC_AVAILABLE:
                try:
                    smtc_detector = MediaDetector(target_app="Qobuz")
                    smtc_ok = await smtc_detector.initialize()
                    if smtc_ok:
                        self.detector = smtc_detector
                        logger.info("Usando detector SMTC (posición real)")
                except Exception as e:
                    logger.warning(f"SMTC no disponible, usando fallback: {e}")
                    smtc_ok = False

            if not smtc_ok:
                if smtc_detector is not None:
                    try:
                        await smtc_detector.close()
                    except Exception as e:
                        logger.debug(f"Error cerrando el detector SMTC: {e}")

                logger.info(
                    "Qobuz no publica una sesión SMTC; "
                    "usando su título de ventana (posición estimada)"
                )
                self.detector = WindowTitleDetector(poll_interval=1.0)
                if not await self.detector.initialize():
                    logger.error("No se pudo inicializar el detector de música")
                    return False

            # Registrar callbacks del detector
            self.detector.on_track_changed(self._on_track_changed)
            self.detector.on_playback_changed(self._on_playback_changed)

            # 2. Inicializar servicio de letras
            logger.info("Inicializando servicio de letras...")
            self.lyrics_service = LyricsService()
            await self.lyrics_service.initialize()

            # 2.1 Inicializar servicio de traducción
            logger.info("Inicializando servicio de traducción...")
            self.translation_service = TranslationService()

            # 3. Crear motor de sincronización
            logger.info("Inicializando motor de sincronización...")
            self.sync_engine = SyncEngine(self.detector)
            self.sync_engine.on_sync_update(self._on_sync_update)

            # 4. Crear UI — usar configuración persistente (H7)
            logger.info("Inicializando interfaz de usuario...")
            self.overlay = LyricsOverlay(self._build_overlay_config())
            self.lyrics_manager = LyricsManagerDialog()
            self.lyrics_manager.setWindowIcon(create_brand_icon())
            self.tray = TrayIcon(settings=self.settings_manager.settings)

            # Restaurar geometría únicamente si todavía intersecta una pantalla.
            s = self.settings_manager.settings
            self.overlay.restore_window_state(
                s.overlay_x,
                s.overlay_y,
                s.overlay_width,
                s.overlay_height,
                s.window_maximized,
            )

            # Conectar signals del tray
            self.tray.toggle_overlay.connect(self._toggle_overlay)
            self.tray.toggle_translation.connect(self._toggle_translation)
            self.tray.toggle_always_on_top.connect(self._toggle_always_on_top)
            self.tray.offset_reset.connect(self._reset_offset)
            self.tray.offset_increase.connect(
                lambda: self._adjust_offset(
                    self.settings_manager.settings.offset_step_ms
                )
            )
            self.tray.offset_decrease.connect(
                lambda: self._adjust_offset(
                    -self.settings_manager.settings.offset_step_ms
                )
            )
            self.tray.manage_lyrics.connect(self._open_lyrics_manager)
            self.tray.open_settings.connect(self._apply_settings)
            self.tray.quit_app.connect(self._quit)

            # Conectar signals del overlay
            self.overlay.sync_time_changed.connect(self._on_sync_time_changed)
            self.overlay.manage_lyrics_requested.connect(
                self._open_lyrics_manager
            )
            self.overlay.translation_toggle_requested.connect(
                self._toggle_translation
            )
            self.overlay.quit_requested.connect(self._quit)
            self.overlay.closed.connect(self._on_overlay_closed)
            self.tray.set_always_on_top(s.always_on_top)

            # El gestor no accede directamente a red, disco ni detectores.
            self.lyrics_manager.search_requested.connect(
                self._on_manager_search_requested
            )
            self.lyrics_manager.local_requested.connect(
                self._on_manager_local_requested
            )
            self.lyrics_manager.preview_requested.connect(
                self._on_manager_preview_requested
            )
            self.lyrics_manager.apply_requested.connect(
                self._on_manager_apply_requested
            )
            self.lyrics_manager.save_requested.connect(
                self._on_manager_save_requested
            )
            self.lyrics_manager.delete_requested.connect(
                self._on_manager_delete_requested
            )
            self.lyrics_manager.capture_requested.connect(
                self._on_manager_capture_requested
            )

            # 5. Inicializar hotkeys
            logger.info("Inicializando hotkeys...")
            self.hotkey_manager = HotkeyManager()
            self.hotkey_manager.on_hotkey(self._on_hotkey)

            logger.info("✓ Inicialización completa")
            return True

        except Exception as e:
            logger.error(f"Error durante la inicialización: {e}")
            # H9: Mostrar diálogo de error antes de salir
            QMessageBox.critical(
                None,
                "Error de inicialización",
                f"No se pudo iniciar la aplicación.\n\nError: {e}\n\n"
                "Verifique que Qobuz esté abierto y que las dependencias\n"
                "estén instaladas correctamente.",
            )
            return False

    def _on_track_changed(self, track: Optional[TrackInfo]) -> None:
        """Callback cuando cambia la canción."""
        self._current_track = track
        if self.lyrics_manager:
            self.lyrics_manager.set_current_track(track)

        # Cancelar traducción en vuelo de la canción anterior
        if self._translation_cancel_event is not None:
            self._translation_cancel_event.set()
            self._translation_cancel_event = None
        translation_task = getattr(self, "_translation_task", None)
        if translation_task and not translation_task.done():
            translation_task.cancel()

        if track is None:
            fetch_task = getattr(self, "_lyrics_fetch_task", None)
            if fetch_task and not fetch_task.done():
                fetch_task.cancel()
            logger.info("No hay canción reproduciéndose")
            self.sync_engine.clear_lyrics()
            self.overlay.set_lyrics(None)
            self.tray.clear_track_info()
            return

        logger.info(f"Nueva canción: {track}")

        # IMPORTANTE: Limpiar letras anteriores inmediatamente para evitar
        # mostrar letras de la canción anterior mientras se buscan las nuevas
        self.sync_engine.clear_lyrics()
        self.overlay.set_lyrics(None)

        # Actualizar UI inmediatamente
        self.tray.update_track_info(track.artist, track.title)
        self.overlay.set_track_info(track.artist, track.title)
        self.overlay.set_searching_lyrics()

        self._schedule_lyrics_fetch(track)

    def _schedule_lyrics_fetch(self, track: TrackInfo) -> None:
        """Inicia una búsqueda y cancela la que pertenecía a la pista anterior."""
        self._replace_task("_lyrics_fetch_task", self._fetch_lyrics(track))

    def _replace_task(
        self,
        attribute: str,
        coroutine: Coroutine[Any, Any, None],
    ) -> None:
        """Cancela la tarea previa de un flujo propio y programa su reemplazo."""
        task = getattr(self, attribute, None)
        if task and not task.done():
            task.cancel()
        setattr(self, attribute, asyncio.create_task(coroutine))

    async def _fetch_lyrics(self, track: TrackInfo) -> None:
        """Busca letras para un track y muestra la letra original inmediatamente, traduciendo en segundo plano."""
        try:
            # Obtener duración si está disponible
            duration_ms = None
            if self.detector.current_playback:
                duration_ms = self.detector.current_playback.duration_ms

            # Buscar letras
            result = await self.lyrics_service.search(
                artist=track.artist,
                title=track.title,
                album=track.album,
                duration_ms=duration_ms,
            )

            # Verificar que siga siendo el mismo track (usar matches() para comparar por contenido)
            if self._current_track is None or not self._current_track.matches(track):
                logger.debug("Track cambió durante búsqueda, descartando resultado")
                return

            if result and result.lyrics_data.lines:
                logger.info(
                    f"Letras encontradas ({result.provider}): {len(result.lyrics_data.lines)} líneas"
                )
                self._activate_lyrics(
                    track,
                    result.lyrics_data,
                    duration_ms or 0,
                    provider=result.provider,
                    notify=not result.cached and not result.local,
                )
            else:
                logger.info("No se encontraron letras")
                self.sync_engine.clear_lyrics()
                # H9: mensaje con artista/título para contexto
                self.overlay.set_no_lyrics_available(track.artist, track.title)
                self.tray.show_lyrics_not_found()

        except Exception as e:
            logger.error(f"Error buscando letras: {e}")
            self.overlay.set_no_lyrics_available()

    def _activate_lyrics(
        self,
        track: TrackInfo,
        lyrics_data: LyricsData,
        duration_ms: int = 0,
        provider: str = "",
        notify: bool = False,
    ) -> None:
        """Reemplaza la letra activa y lanza su traducción si corresponde."""
        if self._translation_cancel_event is not None:
            self._translation_cancel_event.set()
            self._translation_cancel_event = None
        translation_task = getattr(self, "_translation_task", None)
        if translation_task and not translation_task.done():
            translation_task.cancel()

        lyrics_data.artist = track.artist
        lyrics_data.title = track.title
        if track.album:
            lyrics_data.album = track.album

        # La traducción se activa automáticamente solo para letras en inglés.
        # La preferencia persistente sigue permitiendo desactivarla por completo.
        settings_manager = getattr(self, "settings_manager", None)
        settings = getattr(settings_manager, "settings", None)
        translation_preference = getattr(
            settings,
            "translation_enabled",
            getattr(self, "_translation_enabled", True),
        )
        self._translation_enabled = (
            translation_preference
            and is_translation_enabled_by_default(lyrics_data)
        )
        if self.overlay and hasattr(self.overlay, "set_translation_enabled"):
            self.overlay.set_translation_enabled(self._translation_enabled)
        if self.tray and hasattr(self.tray, "set_translation_enabled"):
            self.tray.set_translation_enabled(self._translation_enabled)

        self.sync_engine.set_lyrics(lyrics_data, duration_ms)
        self.overlay.set_lyrics(lyrics_data, duration_ms)
        if notify and provider:
            self.tray.show_lyrics_found(provider)

        if self._translation_enabled and self.translation_service:
            self._replace_task(
                "_translation_task",
                self._translate_active_lyrics(track, lyrics_data, duration_ms),
            )

    async def _translate_active_lyrics(
        self, track: TrackInfo, lyrics_data: LyricsData, duration_ms: int
    ) -> None:
        """Traduce progresivamente la letra activa sin bloquear la interfaz."""
        cancel_event = threading.Event()
        self._translation_cancel_event = cancel_event
        try:
            logger.info("Traducción progresiva en segundo plano...")
            self.overlay.set_translating()
            loop = asyncio.get_running_loop()

            def on_line_translated(
                line_index: int, timestamp_ms: int, translation: str
            ) -> None:
                def apply_translation() -> None:
                    if (
                        cancel_event.is_set()
                        or self._current_track is None
                        or not self._current_track.matches(track)
                        or self.overlay is None
                    ):
                        return
                    self.overlay.update_line_translation(
                        line_index, translation
                    )

                loop.call_soon_threadsafe(apply_translation)

            await asyncio.to_thread(
                self.translation_service.translate_lyrics_progressive,
                lyrics_data,
                on_line_translated,
                cancel_event,
            )
            if cancel_event.is_set():
                logger.debug("Traducción cancelada, descartando resultado final")
                return
            if (
                self._current_track is None
                or not self._current_track.matches(track)
            ):
                logger.debug(
                    "Track cambió durante traducción, descartando resultado"
                )
                return

            translated_count = sum(
                1
                for line in lyrics_data.lines
                if getattr(line, "translation", None)
            )
            logger.info(
                "Traducción progresiva completada: %s líneas",
                translated_count,
            )
            self.sync_engine.set_lyrics(lyrics_data, duration_ms)
            self.overlay.set_translation_done()
        except Exception as exc:
            if cancel_event.is_set():
                return
            logger.warning("Error en traducción: %s", exc)
            self.tray.show_notification(
                "Traducción no disponible",
                f"No se pudo traducir la letra: {exc}",
                duration_ms=3000,
            )
            self.overlay.set_translation_done()
        finally:
            if self._translation_cancel_event is cancel_event:
                self._translation_cancel_event = None

    @staticmethod
    def _track_matches_metadata(
        track: Optional[TrackInfo], artist: str, title: str
    ) -> bool:
        if track is None:
            return False
        return track_metadata_matches(
            track.artist,
            track.title,
            artist,
            title,
        )

    def _open_lyrics_manager(self) -> None:
        if self.lyrics_manager:
            self.lyrics_manager.show_for_track(self._current_track)

    def _on_manager_search_requested(
        self, artist: str, title: str
    ) -> None:
        self._replace_task(
            "_manager_search_task",
            self._search_manager_candidates(artist, title),
        )

    async def _search_manager_candidates(
        self, artist: str, title: str
    ) -> None:
        try:
            candidates = await self.lyrics_service.search_candidates(
                artist, title
            )
            if self.lyrics_manager:
                self.lyrics_manager.set_search_results(candidates)
        except asyncio.CancelledError:
            return
        except Exception as exc:
            logger.error("Error en búsqueda manual de letras: %s", exc)
            if self.lyrics_manager:
                self.lyrics_manager.set_search_error(str(exc))

    def _on_manager_local_requested(self) -> None:
        self._replace_task(
            "_manager_search_task",
            self._load_manager_local_candidates(),
        )

    async def _load_manager_local_candidates(self) -> None:
        try:
            candidates = await asyncio.to_thread(
                self.lyrics_service.list_local_candidates
            )
            if self.lyrics_manager:
                self.lyrics_manager.set_search_results(candidates)
        except asyncio.CancelledError:
            return
        except Exception as exc:
            logger.error("Error cargando letras locales: %s", exc)
            if self.lyrics_manager:
                self.lyrics_manager.set_search_error(str(exc))

    def _on_manager_preview_requested(
        self, candidate: LyricsCandidate
    ) -> None:
        self._replace_task(
            "_manager_preview_task",
            self._load_manager_preview(candidate),
        )

    async def _load_manager_preview(
        self, candidate: LyricsCandidate
    ) -> None:
        try:
            lyrics = await self.lyrics_service.load_candidate(candidate)
            if self.lyrics_manager:
                self.lyrics_manager.set_preview(candidate, lyrics)
        except asyncio.CancelledError:
            return
        except Exception as exc:
            logger.error("Error cargando previsualización: %s", exc)
            if self.lyrics_manager:
                self.lyrics_manager.set_preview(
                    candidate, None, error=str(exc)
                )

    def _current_duration_ms(self) -> int:
        playback = getattr(self.detector, "current_playback", None)
        return max(0, playback.duration_ms) if playback else 0

    def _on_manager_apply_requested(
        self, candidate: LyricsCandidate
    ) -> None:
        if (
            self._current_track is None
            or candidate.lyrics_data is None
            or not self._track_matches_metadata(
                self._current_track, candidate.artist, candidate.title
            )
        ):
            if self.tray:
                self.tray.show_error(
                    "La coincidencia no corresponde a la canción actual de Qobuz."
                )
            return

        lyrics = clone_lyrics_data(candidate.lyrics_data)
        duration_ms = candidate.duration_ms or self._current_duration_ms()
        if not candidate.is_local:
            lyrics.artist = self._current_track.artist
            lyrics.title = self._current_track.title
            lyrics.album = self._current_track.album or candidate.album or None
            self.lyrics_service.save_user_lyrics(
                artist=self._current_track.artist,
                title=self._current_track.title,
                album=lyrics.album or "",
                duration_ms=duration_ms,
                lyrics_data=lyrics,
                source=candidate.provider,
            )
        self._activate_lyrics(
            self._current_track,
            lyrics,
            duration_ms,
            provider=candidate.provider,
        )
        self.overlay.show_offset_indicator(0)

    def _on_manager_save_requested(
        self, request: LyricsSaveRequest
    ) -> None:
        if self.lyrics_service.has_user_lyrics(
            request.artist, request.title
        ):
            if not self.lyrics_manager.confirm_overwrite(
                request.artist, request.title
            ):
                return
        try:
            saved = self.lyrics_service.save_user_lyrics(
                artist=request.artist,
                title=request.title,
                album=request.album,
                duration_ms=request.duration_ms,
                lyrics_data=request.lyrics_data,
                source=request.source,
            )
            if self.translation_service:
                self.translation_service.invalidate_track(
                    request.artist, request.title
                )
        except Exception as exc:
            logger.error("Error guardando letra local: %s", exc)
            QMessageBox.critical(
                self.lyrics_manager,
                "No se pudo guardar",
                f"No se pudo guardar la letra local.\n\n{exc}",
            )
            return

        self.lyrics_manager.show_save_success(
            saved.artist, saved.title
        )
        if self.tray:
            self.tray.show_notification(
                "Letra guardada",
                f"{saved.artist} — {saved.title}",
                duration_ms=2500,
            )

        if self._track_matches_metadata(
            self._current_track, saved.artist, saved.title
        ):
            duration_ms = saved.duration_ms or self._current_duration_ms()
            self._activate_lyrics(
                self._current_track,
                clone_lyrics_data(saved.lyrics_data),
                duration_ms,
                provider="Biblioteca local",
            )

    def _on_manager_capture_requested(self, row: int) -> None:
        if not self.lyrics_manager or self._current_track is None:
            return
        position_ms = 0
        position_getter = getattr(
            self.detector, "get_interpolated_position_ms", None
        )
        if callable(position_getter):
            try:
                position_ms = max(0, int(position_getter()))
            except Exception as exc:
                logger.debug("No se pudo interpolar la posición: %s", exc)
        if position_ms == 0:
            playback = getattr(self.detector, "current_playback", None)
            if playback is not None:
                position_ms = max(0, int(playback.position_ms))
        self.lyrics_manager.set_captured_timestamp(row, position_ms)

    def _on_manager_delete_requested(
        self, candidate: LyricsCandidate
    ) -> None:
        if not candidate.is_local:
            return
        try:
            deleted = self.lyrics_service.delete_user_lyrics(
                candidate.artist, candidate.title
            )
            if not deleted:
                raise FileNotFoundError(
                    "La letra local ya no existe en la biblioteca."
                )
            if self.translation_service:
                self.translation_service.invalidate_track(
                    candidate.artist, candidate.title
                )
        except Exception as exc:
            logger.error("Error eliminando letra local: %s", exc)
            QMessageBox.critical(
                self.lyrics_manager,
                "No se pudo eliminar",
                f"No se pudo eliminar la letra local.\n\n{exc}",
            )
            return

        self.lyrics_manager.remove_candidate(candidate)
        if self.tray:
            self.tray.show_notification(
                "Letra local eliminada",
                f"{candidate.artist} — {candidate.title}",
                duration_ms=2500,
            )

        if self._track_matches_metadata(
            self._current_track, candidate.artist, candidate.title
        ):
            if self._translation_cancel_event:
                self._translation_cancel_event.set()
            self.sync_engine.clear_lyrics()
            self.overlay.set_searching_lyrics("proveedores")
            self._schedule_lyrics_fetch(self._current_track)

    def _on_playback_changed(self, playback: PlaybackInfo) -> None:
        """Callback cuando cambia el estado de reproducción."""
        logger.debug(f"Playback: {playback.state.name}")

        if self.overlay:
            self.overlay.update_playback(playback)

        # Pausar/reanudar el sync engine según el estado de reproducción
        if self.sync_engine:
            if playback.state == PlayerState.PLAYING:
                self.sync_engine.resume()
            else:
                self.sync_engine.pause()

    def _on_sync_update(self, state: SyncState) -> None:
        """Callback cuando se actualiza la sincronización."""
        # Actualizar overlay
        if self.overlay:
            self.overlay.update_sync(state)

    def _on_hotkey(self, action: HotkeyAction) -> None:
        """Callback cuando se activa un hotkey desde un hilo externo."""
        self._ui_bridge.hotkey_triggered.emit(action)

    def _handle_hotkey_on_ui_thread(self, action: HotkeyAction) -> None:
        """Procesa acciones de hotkeys de forma segura en el hilo de Qt."""
        logger.debug(f"Hotkey: {action.value}")

        if action == HotkeyAction.TOGGLE_OVERLAY:
            self._toggle_overlay()

        elif action == HotkeyAction.TOGGLE_TRANSLATION:
            self._toggle_translation()

        elif action == HotkeyAction.OFFSET_INCREASE:
            step = self.settings_manager.settings.offset_step_ms
            self._adjust_offset(step)

        elif action == HotkeyAction.OFFSET_DECREASE:
            step = self.settings_manager.settings.offset_step_ms
            self._adjust_offset(-step)

        elif action == HotkeyAction.OFFSET_RESET:
            self._reset_offset()

        elif action == HotkeyAction.QUIT_APP:
            self._quit()

    def _toggle_overlay(self) -> None:
        """Alterna la visibilidad del overlay."""
        if self.overlay:
            visible = self.overlay.toggle_visibility()
            self.tray.set_overlay_visible(visible)
            logger.info(f"Overlay {'visible' if visible else 'oculto'}")

    def _on_overlay_closed(self) -> None:
        """Sincroniza la bandeja cuando el botón cerrar oculta la ventana."""
        if self.tray:
            self.tray.set_overlay_visible(False)

    def _toggle_always_on_top(self) -> None:
        """Alterna y persiste el modo flotante de la ventana."""
        if not self.overlay:
            return
        enabled = not self.settings_manager.settings.always_on_top
        self.settings_manager.settings.always_on_top = enabled
        self.overlay.set_always_on_top(enabled)
        self.overlay.show_always_on_top_indicator(enabled)
        if self.tray:
            self.tray.set_always_on_top(enabled)
        self.settings_manager.save()

    def _toggle_translation(self) -> None:
        """Alterna la visibilidad de las traducciones."""
        if self.overlay:
            enabled = self.overlay.toggle_translation()
            self._translation_enabled = enabled
            # H6: Sincronizar estado con el menú del tray
            if self.tray:
                self.tray.set_translation_enabled(enabled)
            # Persistir preferencia
            self.settings_manager.settings.translation_enabled = enabled
            self.settings_manager.save()

            # Si se activa manualmente después de haber cargado una letra,
            # iniciar también la traducción que no se solicitó al principio.
            lyrics = getattr(self.sync_engine, "lyrics", None)
            translation_task = getattr(self, "_translation_task", None)
            if (
                enabled
                and self._current_track
                and lyrics
                and self.translation_service
                and not (translation_task and not translation_task.done())
            ):
                duration_ms = getattr(self.overlay, "_duration_ms", 0)
                self._replace_task(
                    "_translation_task",
                    self._translate_active_lyrics(
                        self._current_track, lyrics, duration_ms
                    ),
                )

            logger.info(f"Traducción {'habilitada' if enabled else 'deshabilitada'}")

    def _apply_settings(self) -> None:
        """Aplica la configuración cambiada desde el diálogo de settings (H7)."""
        self.settings_manager.save()
        s = self.settings_manager.settings
        self._translation_enabled = s.translation_enabled

        # Aplicar configuración visual y de ventana.
        if self.overlay:
            self.overlay.apply_config(self._build_overlay_config())

        if self.tray:
            self.tray.set_translation_enabled(s.translation_enabled)
            self.tray.set_always_on_top(s.always_on_top)

        logger.info("Configuración aplicada")

    def _reset_offset(self) -> None:
        """Resetea el offset de sincronización."""
        if self.sync_engine:
            self.sync_engine.reset_offset()
            if self.overlay:
                self.overlay.show_offset_indicator(0)

    def _adjust_offset(self, delta_ms: int) -> None:
        """Ajusta el offset de sincronización."""
        if self.sync_engine:
            new_offset = self.sync_engine.adjust_offset(delta_ms)
            if self.overlay:
                self.overlay.show_offset_indicator(new_offset)

    def _on_sync_time_changed(self, time_ms: int) -> None:
        """Callback cuando el usuario establece manualmente el tiempo de sincronización."""
        if self.detector and hasattr(self.detector, "set_position_ms"):
            # WindowTitleDetector: ajustar la posición interna del detector
            self.detector.set_position_ms(time_ms)
            logger.info(f"Sincronización manual establecida: {time_ms}ms")
            # Activar lock temporal para que el auto-sync no sobreescriba
            if self.sync_engine:
                self.sync_engine._activate_manual_lock()
                self.sync_engine._force_sync_update()
        else:
            # MediaDetector: usar apply_manual_sync que calcula offset + activa lock
            logger.info(
                f"Sincronización manual: ajustando offset para posición {time_ms}ms"
            )
            if self.sync_engine:
                self.sync_engine.apply_manual_sync(time_ms)
                if self.overlay:
                    self.overlay.show_offset_indicator(self.sync_engine.offset_ms)

    def _quit(self) -> None:
        """Cierra la aplicación de forma segura."""
        if (
            self.lyrics_manager
            and not self.lyrics_manager.confirm_application_exit()
        ):
            return
        logger.info("Cerrando aplicación...")
        self._running = False

        # Guardar geometría y estado de ventana antes de cerrar.
        if self.overlay:
            geometry = self.overlay.persisted_geometry()
            s = self.settings_manager.settings
            s.overlay_x = geometry.x()
            s.overlay_y = geometry.y()
            s.overlay_width = geometry.width()
            s.overlay_height = geometry.height()
            s.window_maximized = self.overlay.isMaximized()
            self.settings_manager.save()

        # Detener componentes primero
        try:
            self._cancel_pending_tasks()
            if self.sync_engine:
                self.sync_engine.stop()
            if self.hotkey_manager:
                self.hotkey_manager.stop()
            if self.overlay:
                self.overlay.hide()
                self.overlay.force_close()
            if self.lyrics_manager:
                self.lyrics_manager.close()
            if self.tray:
                self.tray.hide()
        except Exception as e:
            logger.error(f"Error al limpiar recursos: {e}")

        # Salir del loop de Qt
        if self.app:
            QTimer.singleShot(100, self.app.quit)

    def _cancel_pending_tasks(self) -> list[asyncio.Task]:
        """Solicita cancelación de todas las tareas propias aún activas."""
        if self._translation_cancel_event is not None:
            self._translation_cancel_event.set()
        cancelled: list[asyncio.Task] = []
        for attribute in (
            "_lyrics_fetch_task",
            "_translation_task",
            "_manager_search_task",
            "_manager_preview_task",
            "_detector_task",
        ):
            task = getattr(self, attribute, None)
            if task and not task.done():
                task.cancel()
                cancelled.append(task)
        return cancelled

    async def run(self) -> None:
        """
        Ejecuta la aplicación principal.
        """
        self._running = True

        # Mostrar UI
        self.overlay.show()
        self.tray.show()

        # Iniciar hotkeys
        failed_hotkeys = self.hotkey_manager.start()

        # H5: Avisar si la librería keyboard no está disponible
        if not KEYBOARD_AVAILABLE:
            self.tray.show_notification(
                "⚠ Atajos no disponibles",
                "La librería 'keyboard' no está instalada.\n"
                "Los atajos de teclado no funcionarán.\n"
                "Instale con: pip install keyboard",
                duration_ms=8000,
            )
        elif failed_hotkeys:
            failed_text = "\n".join(
                f"• {hotkey.keys.upper()}: {hotkey.description}"
                for hotkey in failed_hotkeys
            )
            self.tray.show_notification(
                "Algunos atajos no están disponibles",
                "No se pudieron registrar estas combinaciones:\n"
                f"{failed_text}\n"
                "Puedes seguir usando las acciones desde la bandeja.",
                duration_ms=8000,
            )

        # H10: Onboarding para primera ejecución
        s = self.settings_manager.settings
        if s.first_run:
            self.tray.show_notification(
                "Letra Canción",
                "¡Bienvenido! La aplicación está lista.\n\n"
                "• Ctrl+Shift+L: mostrar/ocultar ventana\n"
                "• Ctrl+T: activar/desactivar traducción\n"
                "• Arrastra la barra superior para mover la ventana\n"
                "• Click derecho: ajustar sincronización\n"
                "• Cerrar termina la aplicación\n"
                "• Menú del tray: Configuración y Ayuda",
                duration_ms=10000,
            )
            s.first_run = False
            s.onboarding_shown = True
            self.settings_manager.save()
        else:
            # Notificación de inicio estándar
            self.tray.show_notification(
                "Letra Canción",
                "Aplicación iniciada.\n"
                "Ctrl+Shift+L para mostrar/ocultar.\n"
                "Clic derecho en el icono para más opciones.",
                duration_ms=5000,
            )

        # Verificar si ya hay música reproduciéndose
        if hasattr(self.detector, "_check_for_changes"):
            self.detector._check_for_changes()  # Verificación inicial (WindowTitleDetector)
        if self.detector.current_track:
            self._on_track_changed(self.detector.current_track)

        # Iniciar polling del detector de ventanas
        self._detector_task = asyncio.create_task(
            self.detector.start_polling()
        )

        # Iniciar motor de sincronización (usa QTimer internamente, no async)
        self.sync_engine.start()

        try:
            # El loop de Qt maneja los eventos
            while self._running:
                await asyncio.sleep(0.1)
        finally:
            # Limpiar
            pending_tasks = self._cancel_pending_tasks()
            if pending_tasks:
                await asyncio.gather(*pending_tasks, return_exceptions=True)
            self.sync_engine.stop()
            self.hotkey_manager.stop()

            if self.lyrics_service:
                await self.lyrics_service.close()

            if self.detector:
                await self.detector.close()

            logger.info("Aplicación cerrada")

    async def cleanup(self) -> None:
        """Limpia recursos."""
        pending_tasks = self._cancel_pending_tasks()
        if pending_tasks:
            await asyncio.gather(*pending_tasks, return_exceptions=True)
        if self.sync_engine:
            self.sync_engine.stop()

        if self.hotkey_manager:
            self.hotkey_manager.stop()

        if self.lyrics_service:
            await self.lyrics_service.close()

        if self.detector:
            await self.detector.close()


def main():
    """Punto de entrada principal."""
    logger.info("Letra Canción para Qobuz — Iniciando...")

    # Crear aplicación Qt
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)  # Mantener corriendo con solo el tray
    app.setApplicationName("Letra Canción")
    app.setWindowIcon(create_brand_icon())

    # Crear event loop con qasync
    loop = qasync.QEventLoop(app)
    asyncio.set_event_loop(loop)

    # Crear aplicación
    letra_app = LetraCancionApp()
    letra_app.app = app
    letra_app.loop = loop

    async def run_app():
        """Ejecuta la aplicación."""
        if not await letra_app.initialize():
            logger.error("Error inicializando la aplicación")
            app.quit()
            return

        await letra_app.run()

    # Ejecutar
    with loop:
        try:
            loop.run_until_complete(run_app())
        except KeyboardInterrupt:
            logger.info("Interrupción de teclado")
        finally:
            loop.run_until_complete(letra_app.cleanup())


if __name__ == "__main__":
    main()
