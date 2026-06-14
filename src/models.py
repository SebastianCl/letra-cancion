"""
Modelos de datos compartidos entre detectores y componentes.

Unifica TrackInfo, PlaybackInfo y PlayerState que estaban
duplicados en detector.py y window_detector.py.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class PlayerState(Enum):
    """Estado del reproductor (unificado)."""

    CLOSED = 0
    OPENED = 1
    CHANGING = 2
    STOPPED = 3
    PLAYING = 4
    PAUSED = 5
    UNKNOWN = 6


@dataclass
class TrackInfo:
    """Información de la canción actual (unificada)."""

    title: str
    artist: str
    album: str = ""
    album_artist: str = ""
    track_number: int = 0
    genres: list[str] = field(default_factory=list)

    def __str__(self) -> str:
        return f"{self.artist} - {self.title}"

    def matches(self, other: "TrackInfo") -> bool:
        """Compara si dos TrackInfo son la misma canción (case-insensitive)."""
        if other is None:
            return False
        return (
            self.title.lower() == other.title.lower()
            and self.artist.lower() == other.artist.lower()
        )


@dataclass
class PlaybackInfo:
    """Información del estado de reproducción (unificada)."""

    state: PlayerState
    position_ms: int = 0
    duration_ms: int = 0
    last_updated: datetime = field(default_factory=datetime.now)

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
