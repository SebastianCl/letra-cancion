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

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QTimer
import qasync

from .window_detector import WindowTitleDetector, TrackInfo, PlaybackInfo, PlayerState
from .lyrics_service import LyricsService, LyricsSearchResult
from .sync_engine import SyncEngine, SyncState, SyncMode
from .hotkeys import HotkeyManager, HotkeyAction
from .ui.overlay import LyricsOverlay, OverlayConfig
from .ui.tray import TrayIcon

# Configurar logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)

logger = logging.getLogger(__name__)


class LetraCacionApp:
    """
    Aplicación principal que orquesta todos los componentes.
    """
    
    def __init__(self):
        # Componentes
        self.detector: Optional[WindowTitleDetector] = None
        self.lyrics_service: Optional[LyricsService] = None
        self.sync_engine: Optional[SyncEngine] = None
        self.hotkey_manager: Optional[HotkeyManager] = None
        self.overlay: Optional[LyricsOverlay] = None
        self.tray: Optional[TrayIcon] = None
        
        # Estado
        self._current_track: Optional[TrackInfo] = None
        self._running: bool = False
        
        # Qt App
        self.app: Optional[QApplication] = None
        self.loop: Optional[asyncio.AbstractEventLoop] = None
    
    async def initialize(self) -> bool:
        """
        Inicializa todos los componentes.
        
        Returns:
            True si la inicialización fue exitosa.
        """
        logger.info("Inicializando Letra Canción...")
        
        try:
            # 1. Inicializar detector de música (via título de ventana)
            logger.info("Inicializando detector de música...")
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
            
            # 3. Crear motor de sincronización
            logger.info("Inicializando motor de sincronización...")
            self.sync_engine = SyncEngine(self.detector)
            self.sync_engine.on_sync_update(self._on_sync_update)
            
            # 4. Crear UI
            logger.info("Inicializando interfaz de usuario...")
            self.overlay = LyricsOverlay(OverlayConfig())
            self.tray = TrayIcon()
            
            # Conectar signals del tray
            self.tray.toggle_overlay.connect(self._toggle_overlay)
            self.tray.offset_reset.connect(self._reset_offset)
            self.tray.offset_increase.connect(lambda: self._adjust_offset(500))
            self.tray.offset_decrease.connect(lambda: self._adjust_offset(-500))
            self.tray.quit_app.connect(self._quit)
            
            # Conectar signal de sincronización manual del overlay
            self.overlay.sync_time_changed.connect(self._on_sync_time_changed)
            
            # 5. Inicializar hotkeys
            logger.info("Inicializando hotkeys...")
            self.hotkey_manager = HotkeyManager()
            self.hotkey_manager.on_hotkey(self._on_hotkey)
            
            logger.info("✓ Inicialización completa")
            return True
            
        except Exception as e:
            logger.error(f"Error durante la inicialización: {e}")
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
        
        # Actualizar UI inmediatamente
        self.tray.update_track_info(track.artist, track.title)
        self.overlay.set_track_info(track.artist, track.title)
        self.overlay.set_searching_lyrics()
        
        # Buscar letras en un task separado
        asyncio.create_task(self._fetch_lyrics(track))
    
    async def _fetch_lyrics(self, track: TrackInfo) -> None:
        """Busca letras para un track."""
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
                duration_ms=duration_ms
            )
            
            # Verificar que siga siendo el mismo track
            if self._current_track != track:
                logger.debug("Track cambió durante búsqueda, descartando resultado")
                return
            
            if result and result.lyrics_data.lines:
                logger.info(f"Letras encontradas ({result.provider}): {len(result.lyrics_data.lines)} líneas")
                
                # Cargar en el motor de sincronización
                self.sync_engine.set_lyrics(result.lyrics_data, duration_ms or 0)
                
                # Actualizar overlay
                self.overlay.set_lyrics(result.lyrics_data)
                
                # Notificar
                if not result.cached:
                    self.tray.show_lyrics_found(result.provider)
            else:
                logger.info("No se encontraron letras")
                self.sync_engine.clear_lyrics()
                self.overlay.set_no_lyrics_available()
                self.tray.show_lyrics_not_found()
                
        except Exception as e:
            logger.error(f"Error buscando letras: {e}")
            self.overlay.set_no_lyrics_available()
    
    def _on_playback_changed(self, playback: PlaybackInfo) -> None:
        """Callback cuando cambia el estado de reproducción."""
        logger.debug(f"Playback: {playback.state.name}")
        
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
        """Callback cuando se activa un hotkey."""
        logger.debug(f"Hotkey: {action.value}")
        
        if action == HotkeyAction.TOGGLE_OVERLAY:
            self._toggle_overlay()
            
        elif action == HotkeyAction.OFFSET_INCREASE:
            if self.sync_engine:
                new_offset = self.sync_engine.adjust_offset(500)
                self.overlay.show_offset_indicator(new_offset)
                
        elif action == HotkeyAction.OFFSET_DECREASE:
            if self.sync_engine:
                new_offset = self.sync_engine.adjust_offset(-500)
                self.overlay.show_offset_indicator(new_offset)
                
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
        if self.detector:
            self.detector.set_position_ms(time_ms)
            logger.info(f"Sincronización manual establecida: {time_ms}ms")
    
    def _quit(self) -> None:
        """Cierra la aplicación."""
        logger.info("Cerrando aplicación...")
        self._running = False
        
        if self.app:
            self.app.quit()
    
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
        
        # Mostrar notificación de inicio
        self.tray.show_notification(
            "Letras Sincronizadas",
            "Aplicación iniciada.\n"
            "Ctrl+Shift+L para mostrar/ocultar.\n"
            "Clic derecho en el icono para más opciones.",
            duration_ms=5000
        )
        
        # Verificar si ya hay música reproduciéndose
        self.detector._check_for_changes()  # Verificación inicial
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
    print("""
    ╔═══════════════════════════════════════════════════════════╗
    ║                                                           ║
    ║   🎵  LETRAS SINCRONIZADAS PARA QOBUZ  🎵                ║
    ║                                                           ║
    ║   Detecta música • Busca letras • Sincroniza en vivo     ║
    ║                                                           ║
    ╚═══════════════════════════════════════════════════════════╝
    """)
    
    # Crear aplicación Qt
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)  # Mantener corriendo con solo el tray
    app.setApplicationName("Letras Sincronizadas")
    
    # Crear event loop con qasync
    loop = qasync.QEventLoop(app)
    asyncio.set_event_loop(loop)
    
    # Crear aplicación
    letra_app = LetraCacionApp()
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
