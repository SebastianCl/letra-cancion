"""
Detector de música alternativo usando título de ventana.

Para aplicaciones que no integran con Windows SMTC,
detecta la canción parseando el título de la ventana.

Formato típico de Qobuz: "Título - Artista"
"""

import ctypes
import json
import os
import logging
from ctypes import wintypes
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional
import asyncio

logger = logging.getLogger(__name__)


from .models import TrackInfo, PlaybackInfo, PlayerState


# Type aliases para callbacks
OnTrackChangedCallback = Callable[[Optional[TrackInfo]], None]
OnPlaybackChangedCallback = Callable[[PlaybackInfo], None]
OnSeekedCallback = Callable[[int], None]


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
        (r"^(.+?)\s*-\s*(.+)$", "title_artist"),
        # Algunos reproductores: "Artist - Title"
        (r"^(.+?)\s*-\s*(.+)$", "artist_title"),
    ]

    # Palabras clave para identificar ventanas de reproductores
    PLAYER_KEYWORDS = ["qobuz"]

    # Títulos a ignorar (ventanas sin música)
    IGNORE_TITLES = [
        "qobuz",
        "qobuz desktop",
        "home",
        "discover",
        "my music",
        "favorites",
        "playlists",
        "settings",
        "search",
    ]

    SEEK_DETECTION_THRESHOLD_MS = 1500

    def __init__(
        self,
        poll_interval: float = 1.0,
        qobuz_state_path: Optional[Path] = None,
    ):
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
        self._is_playing: bool = False  # Estado de reproducción

        # Callbacks
        self._on_track_changed: list[OnTrackChangedCallback] = []
        self._on_playback_changed: list[OnPlaybackChangedCallback] = []
        self._on_seeked: list[OnSeekedCallback] = []

        # Para estimar posición (sin SMTC no tenemos posición real)
        self._playback_start_time: Optional[datetime] = None
        self._paused_position_ms: int = 0  # Posición al pausar
        self._qobuz_state_path = qobuz_state_path or (
            Path(os.environ.get("APPDATA", "")) / "Qobuz" / "player-0.json"
        )
        self._last_qobuz_timestamp_ms: Optional[int] = None

        # Windows API
        self._user32 = ctypes.windll.user32
        self._kernel32 = ctypes.windll.kernel32
        self._kernel32.OpenProcess.argtypes = [
            wintypes.DWORD,
            wintypes.BOOL,
            wintypes.DWORD,
        ]
        self._kernel32.OpenProcess.restype = wintypes.HANDLE
        self._kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        self._kernel32.CloseHandle.restype = wintypes.BOOL
        self._kernel32.QueryFullProcessImageNameW.argtypes = [
            wintypes.HANDLE,
            wintypes.DWORD,
            wintypes.LPWSTR,
            ctypes.POINTER(wintypes.DWORD),
        ]
        self._kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL

    async def initialize(self) -> bool:
        """Inicializa el detector."""
        logger.info("WindowTitleDetector inicializado")
        return True

    def _enumerate_visible_windows(self) -> list[tuple[int, str]]:
        """Enumera handles y títulos de las ventanas visibles."""
        windows: list[tuple[int, str]] = []

        def enum_callback(hwnd, _):
            if self._user32.IsWindowVisible(hwnd):
                length = self._user32.GetWindowTextLengthW(hwnd)
                if length > 0:
                    buff = ctypes.create_unicode_buffer(length + 1)
                    self._user32.GetWindowTextW(hwnd, buff, length + 1)
                    windows.append((int(hwnd), buff.value))
            return True

        WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        self._user32.EnumWindows(WNDENUMPROC(enum_callback), 0)
        return windows

    def _get_window_process_name(self, hwnd: int) -> Optional[str]:
        """Obtiene el nombre del ejecutable propietario de una ventana."""
        process_id = wintypes.DWORD()
        self._user32.GetWindowThreadProcessId(hwnd, ctypes.byref(process_id))
        if not process_id.value:
            return None

        process_handle = self._kernel32.OpenProcess(
            0x1000, False, process_id.value  # PROCESS_QUERY_LIMITED_INFORMATION
        )
        if not process_handle:
            return None

        try:
            size = wintypes.DWORD(32768)
            path_buffer = ctypes.create_unicode_buffer(size.value)
            if not self._kernel32.QueryFullProcessImageNameW(
                process_handle, 0, path_buffer, ctypes.byref(size)
            ):
                return None
            return os.path.basename(path_buffer.value).lower()
        finally:
            self._kernel32.CloseHandle(process_handle)

    def _get_qobuz_window_title(self) -> Optional[str]:
        """Retorna el título musical de una ventana propiedad de Qobuz.exe."""
        for hwnd, title in self._enumerate_visible_windows():
            if self._get_window_process_name(hwnd) != "qobuz.exe":
                continue

            title_lower = title.strip().lower()
            if " - " in title and title_lower not in self.IGNORE_TITLES:
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
        parts = title.split(" - ")

        if len(parts) >= 2:
            # El último elemento es el artista
            artist = parts[-1].strip()
            # Todo lo demás es el título
            song_title = " - ".join(parts[:-1]).strip()

            # Limpiar el título (quitar info entre paréntesis para búsqueda)
            # pero mantener el original para mostrar

            if song_title and artist:
                return TrackInfo(title=song_title, artist=artist)

        return None

    def _check_for_changes(self) -> None:
        """Verifica si cambió la canción o el estado de reproducción."""
        window_title = self._get_qobuz_window_title()

        # Si no hay ventana con canción activa
        if window_title is None:
            self._update_position_from_qobuz_state()
            # Si estábamos reproduciendo, ahora estamos pausados
            if self._is_playing and self._current_track is not None:
                # Guardar posición ANTES de cambiar estado (para que el cálculo sea correcto)
                current_pos = self.get_interpolated_position_ms()
                self._is_playing = False
                self._paused_position_ms = current_pos

                self._current_playback = PlaybackInfo(
                    state=PlayerState.STOPPED,
                    position_ms=self._paused_position_ms,
                    duration_ms=0,
                    last_updated=datetime.now(),
                )

                logger.info(
                    f"Reproducción pausada en posición {self._paused_position_ms}ms"
                )
                self._notify_playback_changed(self._current_playback)
            return

        # Hay ventana con canción - parsear título
        new_track = self._parse_window_title(window_title)

        if new_track is None:
            return

        # Verificar si es la misma canción o una nueva
        is_same_track = self._current_track is not None and self._current_track.matches(
            new_track
        )

        if is_same_track:
            # Misma canción - verificar si estábamos pausados y ahora reproduciendo
            if not self._is_playing:
                self._is_playing = True
                # Reanudar: el tiempo de inicio es AHORA, la posición guardada se mantiene
                self._playback_start_time = datetime.now()

                self._current_playback = PlaybackInfo(
                    state=PlayerState.PLAYING,
                    position_ms=self._paused_position_ms,
                    duration_ms=0,
                    last_updated=datetime.now(),
                )

                logger.info(
                    f"Reproducción reanudada desde posición {self._paused_position_ms}ms"
                )
                self._notify_playback_changed(self._current_playback)
            self._update_position_from_qobuz_state()
        else:
            # Nueva canción - reiniciar todo
            self._current_track = new_track
            self._is_playing = True
            self._playback_start_time = datetime.now()
            self._paused_position_ms = 0  # Nueva canción empieza en 0
            self._last_window_title = window_title

            self._current_playback = PlaybackInfo(
                state=PlayerState.PLAYING,
                position_ms=0,
                duration_ms=0,
                last_updated=datetime.now(),
            )

            logger.info(f"Nueva canción detectada: {new_track}")
            self._notify_track_changed(new_track)
            self._notify_playback_changed(self._current_playback)
            self._update_position_from_qobuz_state(notify_seek=False)

    def _read_qobuz_position(self) -> Optional[tuple[int, int]]:
        """Lee el punto de posición persistido por Qobuz Desktop."""
        try:
            payload = json.loads(
                self._qobuz_state_path.read_text(encoding="utf-8")
            )
            position = payload["player"]["data"]["position"]
            value_ms = int(position["value"])
            timestamp_ms = int(position["timestamp"])
            if value_ms < 0 or timestamp_ms <= 0:
                return None
            try:
                datetime.fromtimestamp(timestamp_ms / 1000)
            except (OSError, OverflowError, ValueError):
                return None
            return value_ms, timestamp_ms
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
            # Qobuz puede estar escribiendo el JSON justo durante este poll.
            return None

    def _update_position_from_qobuz_state(
        self, notify_seek: bool = True
    ) -> None:
        """Actualiza la posición usando el estado interno de Qobuz Desktop."""
        anchor = self._read_qobuz_position()
        if anchor is None:
            return

        position_ms, timestamp_ms = anchor
        if timestamp_ms == self._last_qobuz_timestamp_ms:
            return

        expected_position_ms = self.get_interpolated_position_ms()
        self._last_qobuz_timestamp_ms = timestamp_ms
        self._paused_position_ms = position_ms
        self._playback_start_time = datetime.fromtimestamp(timestamp_ms / 1000)

        if self._current_playback is not None:
            self._current_playback.position_ms = position_ms
            self._current_playback.last_updated = self._playback_start_time

        if (
            notify_seek
            and self._current_track is not None
            and abs(position_ms - expected_position_ms)
            >= self.SEEK_DETECTION_THRESHOLD_MS
        ):
            current_position_ms = self.get_interpolated_position_ms()
            logger.info(
                f"Seek detectado desde estado de Qobuz: "
                f"{expected_position_ms}ms -> {current_position_ms}ms"
            )
            self._notify_seeked(current_position_ms)

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

    def _notify_seeked(self, position_ms: int) -> None:
        """Notifica que Qobuz movió la reproducción a otra posición."""
        for callback in self._on_seeked:
            try:
                callback(position_ms)
            except Exception as e:
                logger.error(f"Error en callback de seek: {e}")

    # --- API Pública ---

    def on_track_changed(self, callback: OnTrackChangedCallback) -> None:
        """Registra callback para cambio de canción."""
        self._on_track_changed.append(callback)

    def on_playback_changed(self, callback: OnPlaybackChangedCallback) -> None:
        """Registra callback para cambio de playback."""
        self._on_playback_changed.append(callback)

    def on_seeked(self, callback: OnSeekedCallback) -> None:
        """Registra callback para cambios reales de posición en Qobuz."""
        self._on_seeked.append(callback)

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
        return self._is_playing and self._current_track is not None

    def get_interpolated_position_ms(self) -> int:
        """
        Estima la posición actual basándose en tiempo transcurrido.

        Sin SMTC no tenemos posición real, así que estimamos.
        Tiene en cuenta la posición guardada al pausar.
        """
        if not self._is_playing:
            # Si está pausado, retornar la posición guardada
            return self._paused_position_ms

        if self._playback_start_time is None:
            return self._paused_position_ms

        # Posición = posición al pausar + tiempo transcurrido desde que se reanudó
        elapsed = datetime.now() - self._playback_start_time
        return self._paused_position_ms + int(elapsed.total_seconds() * 1000)

    def set_position_ms(self, position_ms: int) -> None:
        """
        Establece manualmente la posición de reproducción.

        Útil cuando el usuario hace seek en Qobuz y quiere re-sincronizar.

        Args:
            position_ms: Nueva posición en milisegundos.
        """
        self._paused_position_ms = position_ms
        self._playback_start_time = datetime.now()
        logger.info(f"Posición establecida manualmente: {position_ms}ms")

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
