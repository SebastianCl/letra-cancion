"""
Detector de música alternativo usando título de ventana.

Para aplicaciones que no integran con Windows SMTC,
detecta la canción parseando el título de la ventana.

Formato típico de Qobuz: "Título - Artista"
"""

import ctypes
import logging
import re
import time
from ctypes import wintypes
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Callable, Optional
import asyncio

logger = logging.getLogger(__name__)


class PlayerState(Enum):
    """Estado del reproductor."""
    STOPPED = 0
    PLAYING = 1
    UNKNOWN = 2


@dataclass
class TrackInfo:
    """Información de la canción actual."""
    title: str
    artist: str
    album: str = ""
    
    def __str__(self) -> str:
        return f"{self.artist} - {self.title}"
    
    def matches(self, other: 'TrackInfo') -> bool:
        """Compara si dos TrackInfo son la misma canción."""
        if other is None:
            return False
        return (
            self.title.lower() == other.title.lower() and
            self.artist.lower() == other.artist.lower()
        )


@dataclass
class PlaybackInfo:
    """Información del estado de reproducción."""
    state: PlayerState
    position_ms: int = 0
    duration_ms: int = 0
    last_updated: datetime = None
    
    def __post_init__(self):
        if self.last_updated is None:
            self.last_updated = datetime.now()


# Type aliases para callbacks
OnTrackChangedCallback = Callable[[Optional[TrackInfo]], None]
OnPlaybackChangedCallback = Callable[[PlaybackInfo], None]


class WindowTitleDetector:
    """
    Detector de música basado en título de ventana.
    
    Busca ventanas de reproductores conocidos y parsea
    el título para extraer artista y canción.
    """
    
    # Patrones de título para diferentes reproductores
    # Qobuz: "Título - Artista" o "Título (info) - Artista"
    WINDOW_PATTERNS = [
        # Qobuz: "Song Title - Artist Name"
        (r'^(.+?)\s*-\s*(.+)$', 'title_artist'),
        # Algunos reproductores: "Artist - Title"
        (r'^(.+?)\s*-\s*(.+)$', 'artist_title'),
    ]
    
    # Palabras clave para identificar ventanas de reproductores
    PLAYER_KEYWORDS = ['qobuz']
    
    # Títulos a ignorar (ventanas sin música)
    IGNORE_TITLES = ['qobuz', 'qobuz desktop', 'home', 'discover', 'my music', 
                     'favorites', 'playlists', 'settings', 'search']
    
    def __init__(self, poll_interval: float = 1.0):
        """
        Inicializa el detector.
        
        Args:
            poll_interval: Intervalo de polling en segundos
        """
        self.poll_interval = poll_interval
        self._running = False
        
        # Estado actual
        self._current_track: Optional[TrackInfo] = None
        self._current_playback: Optional[PlaybackInfo] = None
        self._last_window_title: str = ""
        
        # Callbacks
        self._on_track_changed: list[OnTrackChangedCallback] = []
        self._on_playback_changed: list[OnPlaybackChangedCallback] = []
        
        # Para estimar posición (sin SMTC no tenemos posición real)
        self._playback_start_time: Optional[datetime] = None
        
        # Windows API
        self._user32 = ctypes.windll.user32
    
    async def initialize(self) -> bool:
        """Inicializa el detector."""
        logger.info("WindowTitleDetector inicializado")
        return True
    
    def _get_qobuz_window_title(self) -> Optional[str]:
        """
        Busca la ventana de Qobuz y retorna su título.
        
        Returns:
            Título de la ventana o None si no se encuentra.
        """
        result = []
        
        def enum_callback(hwnd, _):
            if self._user32.IsWindowVisible(hwnd):
                length = self._user32.GetWindowTextLengthW(hwnd)
                if length > 0:
                    buff = ctypes.create_unicode_buffer(length + 1)
                    self._user32.GetWindowTextW(hwnd, buff, length + 1)
                    title = buff.value
                    
                    # Buscar ventana con patrón "Título - Artista"
                    # que NO sea solo "Qobuz" o similar
                    if title and ' - ' in title:
                        title_lower = title.lower()
                        # Verificar que no sea un título a ignorar
                        if not any(ign == title_lower for ign in self.IGNORE_TITLES):
                            # Verificar que parece ser música (tiene artista - título)
                            result.append(title)
            return True
        
        WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        self._user32.EnumWindows(WNDENUMPROC(enum_callback), 0)
        
        # Retornar el primer resultado que parezca música
        for title in result:
            # Filtrar títulos que claramente no son música
            if not any(skip in title.lower() for skip in ['visual studio', 'chrome', 'firefox', 'edge', 'explorer']):
                return title
        
        return None
    
    def _parse_window_title(self, title: str) -> Optional[TrackInfo]:
        """
        Parsea el título de ventana para extraer info de la canción.
        
        Args:
            title: Título de la ventana
            
        Returns:
            TrackInfo o None si no se pudo parsear
        """
        if not title:
            return None
        
        # Formato Qobuz: "Título (info extra) - Artista"
        # Ejemplo: "Interstate Love Song (LP Version) - Stone Temple Pilots"
        
        # Dividir por " - " (con espacios)
        parts = title.split(' - ')
        
        if len(parts) >= 2:
            # El último elemento es el artista
            artist = parts[-1].strip()
            # Todo lo demás es el título
            song_title = ' - '.join(parts[:-1]).strip()
            
            # Limpiar el título (quitar info entre paréntesis para búsqueda)
            # pero mantener el original para mostrar
            
            if song_title and artist:
                return TrackInfo(
                    title=song_title,
                    artist=artist
                )
        
        return None
    
    def _check_for_changes(self) -> None:
        """Verifica si cambió la canción."""
        window_title = self._get_qobuz_window_title()
        
        # Si no hay ventana con música
        if window_title is None:
            if self._current_track is not None:
                self._current_track = None
                self._playback_start_time = None
                self._notify_track_changed(None)
            return
        
        # Si el título cambió
        if window_title != self._last_window_title:
            self._last_window_title = window_title
            
            # Parsear nuevo título
            new_track = self._parse_window_title(window_title)
            
            if new_track is not None:
                # Verificar si es diferente al track actual
                if self._current_track is None or not self._current_track.matches(new_track):
                    self._current_track = new_track
                    self._playback_start_time = datetime.now()
                    
                    # Crear playback info
                    self._current_playback = PlaybackInfo(
                        state=PlayerState.PLAYING,
                        position_ms=0,
                        duration_ms=0,  # No tenemos duración sin SMTC
                        last_updated=datetime.now()
                    )
                    
                    logger.info(f"Nueva canción detectada: {new_track}")
                    self._notify_track_changed(new_track)
                    self._notify_playback_changed(self._current_playback)
    
    def _notify_track_changed(self, track: Optional[TrackInfo]) -> None:
        """Notifica cambio de track."""
        for callback in self._on_track_changed:
            try:
                callback(track)
            except Exception as e:
                logger.error(f"Error en callback: {e}")
    
    def _notify_playback_changed(self, playback: PlaybackInfo) -> None:
        """Notifica cambio de playback."""
        for callback in self._on_playback_changed:
            try:
                callback(playback)
            except Exception as e:
                logger.error(f"Error en callback: {e}")
    
    # --- API Pública ---
    
    def on_track_changed(self, callback: OnTrackChangedCallback) -> None:
        """Registra callback para cambio de canción."""
        self._on_track_changed.append(callback)
    
    def on_playback_changed(self, callback: OnPlaybackChangedCallback) -> None:
        """Registra callback para cambio de playback."""
        self._on_playback_changed.append(callback)
    
    @property
    def current_track(self) -> Optional[TrackInfo]:
        """Retorna el track actual."""
        return self._current_track
    
    @property
    def current_playback(self) -> Optional[PlaybackInfo]:
        """Retorna info de playback actual."""
        return self._current_playback
    
    @property
    def is_playing(self) -> bool:
        """Retorna True si está reproduciendo."""
        return self._current_track is not None
    
    def get_interpolated_position_ms(self) -> int:
        """
        Estima la posición actual basándose en tiempo transcurrido.
        
        Sin SMTC no tenemos posición real, así que estimamos.
        """
        if self._playback_start_time is None:
            return 0
        
        elapsed = datetime.now() - self._playback_start_time
        return int(elapsed.total_seconds() * 1000)
    
    async def start_polling(self) -> None:
        """Inicia el loop de polling."""
        self._running = True
        logger.info(f"Iniciando polling cada {self.poll_interval}s")
        
        while self._running:
            try:
                self._check_for_changes()
            except Exception as e:
                logger.error(f"Error en polling: {e}")
            
            await asyncio.sleep(self.poll_interval)
    
    def stop_polling(self) -> None:
        """Detiene el polling."""
        self._running = False
    
    async def close(self) -> None:
        """Cierra el detector."""
        self.stop_polling()
        logger.info("WindowTitleDetector cerrado")


# --- Test ---
async def main():
    """Test del detector."""
    logging.basicConfig(level=logging.DEBUG)
    
    detector = WindowTitleDetector(poll_interval=1.0)
    await detector.initialize()
    
    def on_track(track):
        if track:
            print(f"\n🎵 Detectado: {track}")
        else:
            print("\n⏹️ Sin música")
    
    detector.on_track_changed(on_track)
    
    # Verificación inmediata
    detector._check_for_changes()
    print(f"Track actual: {detector.current_track}")
    
    print("\nMonitoreando cambios por 30 segundos...")
    
    try:
        import asyncio
        await asyncio.wait_for(detector.start_polling(), timeout=30)
    except asyncio.TimeoutError:
        pass
    
    await detector.close()


if __name__ == "__main__":
    asyncio.run(main())
