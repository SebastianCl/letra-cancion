"""
Letra Canción - Aplicación principal

Sistema de letras sincronizadas para Qobuz.
Detecta la música reproduciéndose, obtiene letras y las muestra
en un overlay sincronizado.
"""

import asyncio
import logging
import sys
from typing import Optional

from PyQt6.QtWidgets import QApplication, QMessageBox
from PyQt6.QtCore import QTimer
import qasync

from .window_detector import WindowTitleDetector, TrackInfo, PlaybackInfo, PlayerState
from .lyrics_service import LyricsService, LyricsSearchResult
from .translation_service import TranslationService
from .sync_engine import SyncEngine, SyncState, SyncMode
from .hotkeys import HotkeyManager, HotkeyAction, KEYBOARD_AVAILABLE
from .settings import SettingsManager
from .ui.overlay import LyricsOverlay, OverlayConfig
from .ui.tray import TrayIcon

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


class LetraCancionApp:
    """
    Aplicación principal que orquesta todos los componentes.
    """

    def __init__(self):
        # Componentes
        self.detector: Optional[WindowTitleDetector] = None
        self.lyrics_service: Optional[LyricsService] = None
        self.translation_service: Optional[TranslationService] = None
        self.sync_engine: Optional[SyncEngine] = None
        self.hotkey_manager: Optional[HotkeyManager] = None
        self.overlay: Optional[LyricsOverlay] = None
        self.tray: Optional[TrayIcon] = None

        # Configuración persistente (H7)
        self.settings_manager = SettingsManager()

        # Estado
        self._current_track: Optional[TrackInfo] = None
        self._running: bool = False
        self._translation_enabled: bool = self.settings_manager.settings.translation_enabled

        # Qt App
        self.app: Optional[QApplication] = None
        self.loop: Optional[asyncio.AbstractEventLoop] = None

    def _build_overlay_config(self) -> OverlayConfig:
        """Construye OverlayConfig desde la configuración persistente."""
        s = self.settings_manager.settings
        return OverlayConfig(
            width=s.overlay_width,
            height=s.overlay_height,
            opacity=s.opacity,
            font_size=s.font_size,
            font_family=s.font_family,
            bg_color=s.bg_color,
            text_color=s.text_color,
            highlight_color=s.highlight_color,
            dim_color=s.dim_color,
            translation_enabled=s.translation_enabled,
            translation_font_size=s.translation_font_size,
            translation_color=s.translation_color,
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
            if SMTC_AVAILABLE:
                try:
                    self.detector = MediaDetector(target_app="Qobuz")
                    smtc_ok = await self.detector.initialize()
                    if smtc_ok:
                        logger.info("Usando detector SMTC (posición real)")
                except Exception as e:
                    logger.warning(f"SMTC no disponible, usando fallback: {e}")
                    smtc_ok = False

            if not smtc_ok:
                logger.info("Usando detector por título de ventana (posición estimada)")
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
            self.tray = TrayIcon(settings=self.settings_manager.settings)

            # Restaurar posición del overlay si fue guardada (H7)
            s = self.settings_manager.settings
            if s.overlay_x >= 0 and s.overlay_y >= 0:
                self.overlay.move(s.overlay_x, s.overlay_y)

            # Conectar signals del tray
            self.tray.toggle_overlay.connect(self._toggle_overlay)
            self.tray.toggle_translation.connect(self._toggle_translation)
            self.tray.offset_reset.connect(self._reset_offset)
            self.tray.offset_increase.connect(
                lambda: self._adjust_offset(self.settings_manager.settings.offset_step_ms)
            )
            self.tray.offset_decrease.connect(
                lambda: self._adjust_offset(-self.settings_manager.settings.offset_step_ms)
            )
            self.tray.open_settings.connect(self._apply_settings)
            self.tray.quit_app.connect(self._quit)

            # Conectar signals del overlay
            self.overlay.sync_time_changed.connect(self._on_sync_time_changed)
            self.overlay.quit_requested.connect(self._quit)

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

        if track is None:
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

        # Buscar letras en un task separado
        asyncio.create_task(self._fetch_lyrics(track))

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

                lyrics_data = result.lyrics_data

                # Mostrar letra original inmediatamente
                self.sync_engine.set_lyrics(lyrics_data, duration_ms or 0)
                self.overlay.set_lyrics(lyrics_data)
                if not result.cached:
                    self.tray.show_lyrics_found(result.provider)

                # Lanzar traducción en segundo plano si está habilitada
                if self._translation_enabled and self.translation_service:

                    async def translate_and_update():
                        try:
                            logger.info("Traduciendo letras en segundo plano...")
                            # H1: Indicador visual de traducción en progreso
                            self.overlay.set_translating()
                            translated_lyrics = await asyncio.to_thread(
                                self.translation_service.translate_lyrics, lyrics_data
                            )
                            translated_count = sum(
                                1
                                for line in translated_lyrics.lines
                                if getattr(line, "translation", None)
                            )
                            logger.info(
                                f"Traducción completada: {translated_count} líneas traducidas"
                            )

                            # Verificar que siga siendo el mismo track
                            if (
                                self._current_track is None
                                or not self._current_track.matches(track)
                            ):
                                logger.debug(
                                    "Track cambió durante traducción, descartando resultado"
                                )
                                return

                            # Actualizar solo las traducciones en el overlay y sync_engine
                            self.sync_engine.set_lyrics(
                                translated_lyrics, duration_ms or 0
                            )
                            self.overlay.set_lyrics(translated_lyrics)
                            self.overlay.set_translation_done()
                        except Exception as e:
                            logger.warning(f"Error en traducción: {e}")
                            # H1/H9: Notificar al usuario que la traducción falló
                            self.tray.show_notification(
                                "Traducción no disponible",
                                f"No se pudo traducir la letra: {e}",
                                duration_ms=3000,
                            )
                            self.overlay.set_translation_done()

                    asyncio.create_task(translate_and_update())
            else:
                logger.info("No se encontraron letras")
                self.sync_engine.clear_lyrics()
                # H9: mensaje con artista/título para contexto
                self.overlay.set_no_lyrics_available(track.artist, track.title)
                self.tray.show_lyrics_not_found()

        except Exception as e:
            logger.error(f"Error buscando letras: {e}")
            self.overlay.set_no_lyrics_available()

    def _on_playback_changed(self, playback: PlaybackInfo) -> None:
        """Callback cuando cambia el estado de reproducción."""
        logger.debug(f"Playback: {playback.state.name}")

        # Pausar/reanudar el sync engine según el estado de reproducción
        # Comparamos por nombre para compatibilidad entre los enums de detector.py y window_detector.py
        if self.sync_engine:
            if playback.state.name == "PLAYING":
                self.sync_engine.resume()
            else:
                self.sync_engine.pause()

    def _on_sync_update(self, state: SyncState) -> None:
        """Callback cuando se actualiza la sincronización."""
        # Actualizar overlay
        if self.overlay:
            self.overlay.update_sync(state)

    def _on_hotkey(self, action: HotkeyAction) -> None:
        """Callback cuando se activa un hotkey."""
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
            logger.info(f"Traducción {'habilitada' if enabled else 'deshabilitada'}")

    def _apply_settings(self) -> None:
        """Aplica la configuración cambiada desde el diálogo de settings (H7)."""
        self.settings_manager.save()
        s = self.settings_manager.settings
        self._translation_enabled = s.translation_enabled

        # Reconstruir config del overlay
        if self.overlay:
            self.overlay.config.opacity = s.opacity
            self.overlay.config.font_size = s.font_size
            self.overlay.config.translation_font_size = s.translation_font_size
            self.overlay.config.translation_enabled = s.translation_enabled
            # Refrescar estilos del container
            self.overlay.container.setStyleSheet(
                f"""
                QFrame#container {{
                    background-color: rgba(26, 26, 46, {int(s.opacity * 255)});
                    border-radius: 15px;
                    border: 1px solid rgba(255, 255, 255, 0.1);
                }}
            """
            )
            # Actualizar labels de traducción
            for label in self.overlay.line_labels:
                label.set_translation_visible(s.translation_enabled)
            self.overlay._recalculate_visible_lines()

        if self.tray:
            self.tray.set_translation_enabled(s.translation_enabled)

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
        if self.detector and hasattr(self.detector, 'set_position_ms'):
            self.detector.set_position_ms(time_ms)
            logger.info(f"Sincronización manual establecida: {time_ms}ms")
        else:
            # MediaDetector no soporta set_position_ms — calcular offset necesario
            logger.info(f"Sincronización manual: ajustando offset para posición {time_ms}ms")
            if self.sync_engine and self.detector:
                current_pos = self.detector.get_interpolated_position_ms()
                offset_delta = time_ms - current_pos
                new_offset = self.sync_engine.adjust_offset(offset_delta)
                if self.overlay:
                    self.overlay.show_offset_indicator(new_offset)

    def _quit(self) -> None:
        """Cierra la aplicación de forma segura."""
        logger.info("Cerrando aplicación...")
        self._running = False

        # H7: Guardar posición y tamaño del overlay antes de cerrar
        if self.overlay:
            pos = self.overlay.pos()
            size = self.overlay.size()
            s = self.settings_manager.settings
            s.overlay_x = pos.x()
            s.overlay_y = pos.y()
            s.overlay_width = size.width()
            s.overlay_height = size.height()
            self.settings_manager.save()

        # Detener componentes primero
        try:
            if self.sync_engine:
                self.sync_engine.stop()
            if self.hotkey_manager:
                self.hotkey_manager.stop()
            if self.overlay:
                self.overlay.hide()
                self.overlay.close()
            if self.tray:
                self.tray.hide()
        except Exception as e:
            logger.error(f"Error al limpiar recursos: {e}")

        # Salir del loop de Qt
        if self.app:
            QTimer.singleShot(100, self.app.quit)

    async def run(self) -> None:
        """
        Ejecuta la aplicación principal.
        """
        self._running = True

        # Mostrar UI
        self.overlay.show()
        self.tray.show()

        # Iniciar hotkeys
        self.hotkey_manager.start()

        # H5: Avisar si la librería keyboard no está disponible
        if not KEYBOARD_AVAILABLE:
            self.tray.show_notification(
                "⚠ Atajos no disponibles",
                "La librería 'keyboard' no está instalada.\n"
                "Los atajos de teclado no funcionarán.\n"
                "Instale con: pip install keyboard",
                duration_ms=8000,
            )

        # H10: Onboarding para primera ejecución
        s = self.settings_manager.settings
        if s.first_run:
            self.tray.show_notification(
                "Letras Sincronizadas",
                "¡Bienvenido! La aplicación está lista.\n\n"
                "• Ctrl+Shift+L: mostrar/ocultar overlay\n"
                "• Ctrl+T: activar/desactivar traducción\n"
                "• Arrastra el header para mover la ventana\n"
                "• Click derecho: ajustar sincronización\n"
                "• Menú del tray: Configuración y Ayuda",
                duration_ms=10000,
            )
            s.first_run = False
            s.onboarding_shown = True
            self.settings_manager.save()
        else:
            # Notificación de inicio estándar
            self.tray.show_notification(
                "Letras Sincronizadas",
                "Aplicación iniciada.\n"
                "Ctrl+Shift+L para mostrar/ocultar.\n"
                "Clic derecho en el icono para más opciones.",
                duration_ms=5000,
            )

        # Verificar si ya hay música reproduciéndose
        if hasattr(self.detector, '_check_for_changes'):
            self.detector._check_for_changes()  # Verificación inicial (WindowTitleDetector)
        if self.detector.current_track:
            self._on_track_changed(self.detector.current_track)

        # Iniciar polling del detector de ventanas
        detector_task = asyncio.create_task(self.detector.start_polling())

        # Iniciar motor de sincronización (usa QTimer internamente, no async)
        self.sync_engine.start()

        try:
            # El loop de Qt maneja los eventos
            while self._running:
                await asyncio.sleep(0.1)
        finally:
            # Limpiar
            self.sync_engine.stop()
            self.hotkey_manager.stop()

            if self.lyrics_service:
                await self.lyrics_service.close()

            if self.detector:
                await self.detector.close()

            logger.info("Aplicación cerrada")

    async def cleanup(self) -> None:
        """Limpia recursos."""
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
    logger.info("🎵 Letras Sincronizadas para Qobuz — Iniciando...")

    # Crear aplicación Qt
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)  # Mantener corriendo con solo el tray
    app.setApplicationName("Letras Sincronizadas")

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
