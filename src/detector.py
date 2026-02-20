"""
Detector de música usando Windows Media Session (SMTC)

Utiliza la API GlobalSystemMediaTransportControlsSessionManager
para detectar qué canción se está reproduciendo en aplicaciones
como Qobuz, Spotify, etc.
"""

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import Callable, Optional
import logging

# Windows SDK imports
try:
    from winsdk.windows.media.control import (
        GlobalSystemMediaTransportControlsSessionManager as MediaManager,
        GlobalSystemMediaTransportControlsSession as MediaSession,
        GlobalSystemMediaTransportControlsSessionPlaybackStatus as PlaybackStatus,
        GlobalSystemMediaTransportControlsSessionMediaProperties as MediaProperties,
        GlobalSystemMediaTransportControlsSessionTimelineProperties as TimelineProperties,
    )
    from winsdk.windows.storage.streams import DataReader, Buffer, InputStreamOptions

    WINSDK_AVAILABLE = True
except ImportError:
    WINSDK_AVAILABLE = False
    print("WARNING: winsdk not available. Media detection will not work.")


logger = logging.getLogger(__name__)


class PlayerState(Enum):
    """Estado del reproductor."""

    CLOSED = 0
    OPENED = 1
    CHANGING = 2
    STOPPED = 3
    PLAYING = 4
    PAUSED = 5


@dataclass
class TrackInfo:
    """Información de la canción actual."""

    title: str
    artist: str
    album: str
    album_artist: str
    track_number: int
    genres: list[str]

    def __str__(self) -> str:
        return f"{self.artist} - {self.title}"

    def matches(self, other: "TrackInfo") -> bool:
        """Compara si dos TrackInfo son la misma canción."""
        return (
            self.title == other.title
            and self.artist == other.artist
            and self.album == other.album
        )


@dataclass
class PlaybackInfo:
    """Información del estado de reproducción."""

    state: PlayerState
    position_ms: int
    duration_ms: int
    last_updated: datetime

    @property
    def position_seconds(self) -> float:
        return self.position_ms / 1000.0

    @property
    def duration_seconds(self) -> float:
        return self.duration_ms / 1000.0

    @property
    def progress_percent(self) -> float:
        if self.duration_ms == 0:
            return 0.0
        return (self.position_ms / self.duration_ms) * 100


# Type aliases para callbacks
OnTrackChangedCallback = Callable[[Optional[TrackInfo]], None]
OnPlaybackChangedCallback = Callable[[PlaybackInfo], None]
OnPositionChangedCallback = Callable[[int], None]  # position_ms


class MediaDetector:
    """
    Detector de música usando Windows Media Session API.

    Detecta la canción actual, estado de reproducción y posición
    en reproductores como Qobuz, Spotify, etc.
    """

    def __init__(self, target_app: Optional[str] = None):
        """
        Inicializa el detector.

        Args:
            target_app: Nombre de la app objetivo (ej: "Qobuz").
                       Si es None, usa cualquier sesión activa.
        """
        if not WINSDK_AVAILABLE:
            raise RuntimeError(
                "winsdk no está disponible. Instala con: pip install winsdk"
            )

        self.target_app = target_app
        self._manager: Optional[MediaManager] = None
        self._current_session: Optional[MediaSession] = None

        # Estado actual
        self._current_track: Optional[TrackInfo] = None
        self._current_playback: Optional[PlaybackInfo] = None

        # Callbacks
        self._on_track_changed: list[OnTrackChangedCallback] = []
        self._on_playback_changed: list[OnPlaybackChangedCallback] = []
        self._on_position_changed: list[OnPositionChangedCallback] = []

        # Control de polling
        self._polling = False
        self._poll_interval = 0.1  # 100ms

    async def initialize(self) -> bool:
        """
        Inicializa la conexión con Windows Media Session.

        Returns:
            True si se inicializó correctamente.
        """
        try:
            self._manager = await MediaManager.request_async()

            if self._manager is None:
                logger.error("No se pudo obtener el MediaManager")
                return False

            # Obtener sesión actual
            await self._update_current_session()

            # Registrar callback para cambios de sesión
            self._manager.add_current_session_changed(
                lambda sender, args: asyncio.create_task(self._on_session_changed())
            )

            logger.info("MediaDetector inicializado correctamente")
            return True

        except Exception as e:
            logger.error(f"Error inicializando MediaDetector: {e}")
            return False

    async def _update_current_session(self) -> None:
        """Actualiza la sesión de medios actual."""
        if self._manager is None:
            return

        # Obtener sesión actual
        session = self._manager.get_current_session()

        if session is None:
            # Intentar obtener de las sesiones disponibles
            sessions = self._manager.get_sessions()
            if sessions and sessions.size > 0:
                # Buscar sesión que coincida con target_app
                for i in range(sessions.size):
                    s = sessions.get_at(i)
                    source_id = s.source_app_user_model_id
                    if (
                        self.target_app is None
                        or self.target_app.lower() in source_id.lower()
                    ):
                        session = s
                        break

                # Si no encontramos target, usar la primera
                if session is None and sessions.size > 0:
                    session = sessions.get_at(0)

        if session != self._current_session:
            self._current_session = session
            if session:
                logger.info(f"Sesión activa: {session.source_app_user_model_id}")

                # Registrar callbacks de la sesión
                session.add_media_properties_changed(
                    lambda s, a: asyncio.create_task(
                        self._on_media_properties_changed()
                    )
                )
                session.add_playback_info_changed(
                    lambda s, a: asyncio.create_task(self._on_playback_info_changed())
                )
                session.add_timeline_properties_changed(
                    lambda s, a: asyncio.create_task(
                        self._on_timeline_properties_changed()
                    )
                )

                # Obtener info inicial
                await self._update_track_info()
                await self._update_playback_info()

    async def _on_session_changed(self) -> None:
        """Callback cuando cambia la sesión activa."""
        logger.debug("Sesión de medios cambiada")
        await self._update_current_session()

    async def _on_media_properties_changed(self) -> None:
        """Callback cuando cambian las propiedades del media."""
        logger.debug("Propiedades de media cambiadas")
        await self._update_track_info()

    async def _on_playback_info_changed(self) -> None:
        """Callback cuando cambia la info de reproducción."""
        logger.debug("Info de playback cambiada")
        await self._update_playback_info()

    async def _on_timeline_properties_changed(self) -> None:
        """Callback cuando cambia la timeline (posición, seek)."""
        logger.debug("Timeline cambiada")
        await self._update_playback_info()

    async def _update_track_info(self) -> None:
        """Actualiza la información del track actual."""
        if self._current_session is None:
            if self._current_track is not None:
                self._current_track = None
                self._notify_track_changed(None)
            return

        try:
            props = await self._current_session.try_get_media_properties_async()

            if props is None:
                return

            new_track = TrackInfo(
                title=props.title or "",
                artist=props.artist or "",
                album=props.album_title or "",
                album_artist=props.album_artist or "",
                track_number=props.track_number,
                genres=list(props.genres) if props.genres else [],
            )

            # Verificar si cambió el track
            if self._current_track is None or not self._current_track.matches(
                new_track
            ):
                self._current_track = new_track
                self._notify_track_changed(new_track)
                logger.info(f"Nueva canción: {new_track}")

        except Exception as e:
            logger.error(f"Error obteniendo propiedades del media: {e}")

    async def _update_playback_info(self) -> None:
        """Actualiza la información de reproducción."""
        if self._current_session is None:
            return

        try:
            # Obtener estado de playback
            playback_info = self._current_session.get_playback_info()
            timeline = self._current_session.get_timeline_properties()

            if playback_info is None or timeline is None:
                return

            # Mapear estado
            status_map = {
                PlaybackStatus.CLOSED: PlayerState.CLOSED,
                PlaybackStatus.OPENED: PlayerState.OPENED,
                PlaybackStatus.CHANGING: PlayerState.CHANGING,
                PlaybackStatus.STOPPED: PlayerState.STOPPED,
                PlaybackStatus.PLAYING: PlayerState.PLAYING,
                PlaybackStatus.PAUSED: PlayerState.PAUSED,
            }

            state = status_map.get(playback_info.playback_status, PlayerState.STOPPED)

            # Convertir TimeSpan a milisegundos
            # WinRT TimeSpan está en unidades de 100 nanosegundos
            position_ms = int(timeline.position.duration / 10000)
            duration_ms = int(timeline.end_time.duration / 10000)

            # Timestamp de última actualización
            last_updated = datetime.now()

            new_playback = PlaybackInfo(
                state=state,
                position_ms=position_ms,
                duration_ms=duration_ms,
                last_updated=last_updated,
            )

            # Verificar cambios significativos
            state_changed = (
                self._current_playback is None
                or self._current_playback.state != new_playback.state
            )

            self._current_playback = new_playback

            if state_changed:
                self._notify_playback_changed(new_playback)
                logger.debug(
                    f"Estado: {state.name}, Pos: {position_ms}ms, Dur: {duration_ms}ms"
                )

            # Siempre notificar cambio de posición
            self._notify_position_changed(position_ms)

        except Exception as e:
            logger.error(f"Error obteniendo info de playback: {e}")

    def _notify_track_changed(self, track: Optional[TrackInfo]) -> None:
        """Notifica a los listeners que cambió el track."""
        for callback in self._on_track_changed:
            try:
                callback(track)
            except Exception as e:
                logger.error(f"Error en callback on_track_changed: {e}")

    def _notify_playback_changed(self, playback: PlaybackInfo) -> None:
        """Notifica a los listeners que cambió el playback."""
        for callback in self._on_playback_changed:
            try:
                callback(playback)
            except Exception as e:
                logger.error(f"Error en callback on_playback_changed: {e}")

    def _notify_position_changed(self, position_ms: int) -> None:
        """Notifica a los listeners que cambió la posición."""
        for callback in self._on_position_changed:
            try:
                callback(position_ms)
            except Exception as e:
                logger.error(f"Error en callback on_position_changed: {e}")

    # --- API Pública ---

    def on_track_changed(self, callback: OnTrackChangedCallback) -> None:
        """Registra callback para cuando cambia la canción."""
        self._on_track_changed.append(callback)

    def on_playback_changed(self, callback: OnPlaybackChangedCallback) -> None:
        """Registra callback para cuando cambia el estado de reproducción."""
        self._on_playback_changed.append(callback)

    def on_position_changed(self, callback: OnPositionChangedCallback) -> None:
        """Registra callback para cuando cambia la posición."""
        self._on_position_changed.append(callback)

    @property
    def current_track(self) -> Optional[TrackInfo]:
        """Retorna el track actual."""
        return self._current_track

    @property
    def current_playback(self) -> Optional[PlaybackInfo]:
        """Retorna el estado de reproducción actual."""
        return self._current_playback

    @property
    def is_playing(self) -> bool:
        """Retorna True si está reproduciendo."""
        return (
            self._current_playback is not None
            and self._current_playback.state == PlayerState.PLAYING
        )

    def get_interpolated_position_ms(self) -> int:
        """
        Obtiene la posición interpolada basada en el último update.

        Útil porque Windows no actualiza la posición en tiempo real,
        sino periódicamente. Esta función estima la posición actual
        basándose en el tiempo transcurrido.
        """
        if self._current_playback is None:
            return 0

        if self._current_playback.state != PlayerState.PLAYING:
            return self._current_playback.position_ms

        # Calcular tiempo transcurrido desde último update
        elapsed = datetime.now() - self._current_playback.last_updated
        elapsed_ms = int(elapsed.total_seconds() * 1000)

        # Interpolar posición
        interpolated = self._current_playback.position_ms + elapsed_ms

        # No exceder duración
        if self._current_playback.duration_ms > 0:
            interpolated = min(interpolated, self._current_playback.duration_ms)

        return interpolated

    async def start_polling(self, interval: float = 0.1) -> None:
        """
        Inicia el polling de posición.

        Args:
            interval: Intervalo en segundos (default 100ms)
        """
        self._poll_interval = interval
        self._polling = True

        while self._polling:
            await self._update_playback_info()
            await asyncio.sleep(self._poll_interval)

    def stop_polling(self) -> None:
        """Detiene el polling de posición."""
        self._polling = False

    async def get_available_sessions(self) -> list[str]:
        """
        Obtiene lista de sesiones de media disponibles.

        Returns:
            Lista de IDs de aplicaciones con sesiones activas.
        """
        if self._manager is None:
            return []

        sessions = self._manager.get_sessions()
        if sessions is None:
            return []

        result = []
        for i in range(sessions.size):
            session = sessions.get_at(i)
            result.append(session.source_app_user_model_id)

        return result

    async def close(self) -> None:
        """Cierra el detector y libera recursos."""
        self.stop_polling()
        self._current_session = None
        self._manager = None
        logger.info("MediaDetector cerrado")


# --- Ejemplo de uso ---
async def main():
    """Ejemplo de uso del MediaDetector."""
    logging.basicConfig(level=logging.DEBUG)

    detector = MediaDetector(target_app="Qobuz")

    # Registrar callbacks
    def on_track(track: Optional[TrackInfo]):
        if track:
            print(f"\n🎵 Ahora suena: {track}")
        else:
            print("\n⏹️ No hay canción reproduciéndose")

    def on_playback(playback: PlaybackInfo):
        print(f"   Estado: {playback.state.name}")

    detector.on_track_changed(on_track)
    detector.on_playback_changed(on_playback)

    # Inicializar
    if not await detector.initialize():
        print("Error: No se pudo inicializar el detector")
        return

    # Mostrar sesiones disponibles
    sessions = await detector.get_available_sessions()
    print(f"Sesiones disponibles: {sessions}")

    # Mostrar track actual
    if detector.current_track:
        print(f"Track actual: {detector.current_track}")

    # Polling de posición por 30 segundos
    print("\nMonitoreando posición por 30 segundos...")

    try:
        end_time = datetime.now() + timedelta(seconds=30)
        while datetime.now() < end_time:
            await detector._update_playback_info()

            if detector.current_playback and detector.is_playing:
                pos = detector.get_interpolated_position_ms()
                dur = detector.current_playback.duration_ms
                print(
                    f"\r   Posición: {pos//1000}s / {dur//1000}s   ", end="", flush=True
                )

            await asyncio.sleep(0.5)
    except KeyboardInterrupt:
        pass

    await detector.close()
    print("\n\nDetector cerrado.")


if __name__ == "__main__":
    asyncio.run(main())
