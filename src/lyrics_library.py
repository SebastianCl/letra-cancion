"""Biblioteca persistente de letras agregadas o editadas por el usuario."""

from __future__ import annotations

import hashlib
import json
import logging
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Optional

from .lrc_parser import LyricLine, LyricsData
from .storage import atomic_write_text, read_text_limited

logger = logging.getLogger(__name__)

LIBRARY_SCHEMA_VERSION = 1
MAX_LIBRARY_FILE_BYTES = 1048576
MAX_LIBRARY_LINES = 5000
MAX_METADATA_CHARS = 512
MAX_LYRIC_LINE_CHARS = 4096


def normalize_track_text(value: Optional[str]) -> str:
    """Normaliza metadatos para claves, búsqueda y deduplicación."""
    if not value:
        return ""
    normalized = unicodedata.normalize("NFKD", value)
    normalized = "".join(
        character for character in normalized
        if not unicodedata.combining(character)
    )
    return " ".join(
        re.findall(r"\w+", normalized.casefold(), flags=re.UNICODE)
    )


def make_track_key(artist: str, title: str) -> str:
    """Genera una clave estable para una canción."""
    identity = f"{normalize_track_text(artist)}|{normalize_track_text(title)}"
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()


def metadata_text_matches(expected: str, candidate: str) -> bool:
    """Compara metadatos permitiendo acentos y sufijos como remaster."""
    expected_normalized = normalize_track_text(expected)
    candidate_normalized = normalize_track_text(candidate)
    if not expected_normalized or not candidate_normalized:
        return False
    if expected_normalized == candidate_normalized:
        return True
    shorter, longer = sorted(
        (expected_normalized, candidate_normalized), key=len
    )
    if len(shorter) >= 4 and f" {shorter} " in f" {longer} ":
        return True
    return SequenceMatcher(
        None, expected_normalized, candidate_normalized
    ).ratio() >= 0.82


def track_metadata_matches(
    expected_artist: str,
    expected_title: str,
    candidate_artist: str,
    candidate_title: str,
) -> bool:
    return metadata_text_matches(
        expected_artist, candidate_artist
    ) and metadata_text_matches(expected_title, candidate_title)


def clone_lyrics_data(lyrics: LyricsData) -> LyricsData:
    """Crea una copia independiente, incluidas traducciones existentes."""
    return LyricsData(
        lines=[
            LyricLine(
                timestamp_ms=line.timestamp_ms,
                text=line.text,
                translation=line.translation,
            )
            for line in lyrics.lines
        ],
        title=lyrics.title,
        artist=lyrics.artist,
        album=lyrics.album,
        offset_ms=lyrics.offset_ms,
        is_synced=lyrics.is_synced,
    )


@dataclass
class LyricsCandidate:
    """Coincidencia local o remota mostrada en el gestor de letras."""

    provider: str
    provider_id: str
    artist: str
    title: str
    album: str = ""
    duration_ms: int = 0
    is_synced: Optional[bool] = None
    is_local: bool = False
    lyrics_data: Optional[LyricsData] = field(
        default=None, repr=False, compare=False
    )

    @property
    def identity(self) -> tuple[str, str, str]:
        """Identidad normalizada usada para deduplicar resultados."""
        return (
            normalize_track_text(self.artist),
            normalize_track_text(self.title),
            normalize_track_text(self.album),
        )


@dataclass
class UserLyricsEntry:
    """Registro versionado almacenado en la biblioteca personal."""

    artist: str
    title: str
    lyrics_data: LyricsData
    album: str = ""
    duration_ms: int = 0
    source: str = "manual"
    updated_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    @property
    def key(self) -> str:
        return make_track_key(self.artist, self.title)

    def to_candidate(self) -> LyricsCandidate:
        return LyricsCandidate(
            provider="Biblioteca local",
            provider_id=self.key,
            artist=self.artist,
            title=self.title,
            album=self.album,
            duration_ms=self.duration_ms,
            is_synced=self.lyrics_data.is_synced,
            is_local=True,
            lyrics_data=clone_lyrics_data(self.lyrics_data),
        )


class UserLyricsLibrary:
    """Almacén JSON por canción, independiente del caché de proveedores."""

    def __init__(self, library_dir: Optional[Path] = None):
        if library_dir is None:
            library_dir = Path.home() / ".lyrics-cache" / "library"
        self.library_dir = library_dir
        self.library_dir.mkdir(parents=True, exist_ok=True)

    def _path_for(self, artist: str, title: str) -> Path:
        return self.library_dir / f"{make_track_key(artist, title)}.json"

    @staticmethod
    def _serialize(entry: UserLyricsEntry) -> dict:
        return {
            "schema_version": LIBRARY_SCHEMA_VERSION,
            "artist": entry.artist,
            "title": entry.title,
            "album": entry.album,
            "duration_ms": max(0, int(entry.duration_ms)),
            "source": entry.source,
            "updated_at": entry.updated_at,
            "lyrics": {
                "is_synced": entry.lyrics_data.is_synced,
                "offset_ms": entry.lyrics_data.offset_ms,
                "lines": [
                    {
                        "timestamp_ms": int(line.timestamp_ms),
                        "text": line.text,
                    }
                    for line in entry.lyrics_data.lines
                ],
            },
        }

    @staticmethod
    def _deserialize(payload: dict) -> UserLyricsEntry:
        if not isinstance(payload, dict):
            raise ValueError("La entrada local debe ser un objeto JSON")
        if payload.get("schema_version") != LIBRARY_SCHEMA_VERSION:
            raise ValueError("Versión de biblioteca no compatible")

        artist = payload.get("artist", "")
        title = payload.get("title", "")
        if not isinstance(artist, str) or not isinstance(title, str):
            raise ValueError("Los metadatos de la entrada no son texto")
        artist = artist.strip()
        title = title.strip()
        if not artist or not title:
            raise ValueError("La entrada no contiene artista y título")
        if len(artist) > MAX_METADATA_CHARS or len(title) > MAX_METADATA_CHARS:
            raise ValueError("Los metadatos de la entrada son demasiado largos")
        album = payload.get("album", "")
        source = payload.get("source", "manual")
        updated_at = payload.get("updated_at", "")
        if not all(isinstance(value, str) for value in (album, source, updated_at)):
            raise ValueError("Los metadatos de la entrada no son texto")
        album = album.strip()
        source = source.strip() or "manual"
        updated_at = updated_at.strip() or datetime.now(timezone.utc).isoformat()
        if (
            len(album) > MAX_METADATA_CHARS
            or len(source) > MAX_METADATA_CHARS
            or len(updated_at) > MAX_METADATA_CHARS
        ):
            raise ValueError("Los metadatos de la entrada son demasiado largos")

        lyrics_payload = payload.get("lyrics")
        if not isinstance(lyrics_payload, dict):
            raise ValueError("La entrada no contiene datos de letra")

        raw_lines = lyrics_payload.get("lines")
        if not isinstance(raw_lines, list):
            raise ValueError("La lista de líneas no es válida")
        if len(raw_lines) > MAX_LIBRARY_LINES:
            raise ValueError("La entrada contiene demasiadas líneas")

        lines: list[LyricLine] = []
        for raw_line in raw_lines:
            if not isinstance(raw_line, dict):
                raise ValueError("Una línea de letra no es válida")
            timestamp_ms = raw_line.get("timestamp_ms", 0)
            text = raw_line.get("text", "")
            if (
                not isinstance(timestamp_ms, int)
                or isinstance(timestamp_ms, bool)
                or not isinstance(text, str)
            ):
                raise ValueError("Una línea contiene tipos inválidos")
            text = text.strip()
            if timestamp_ms < 0 or not text:
                raise ValueError("Una línea contiene tiempo o texto inválido")
            if len(text) > MAX_LYRIC_LINE_CHARS:
                raise ValueError("Una línea de letra es demasiado larga")
            lines.append(LyricLine(timestamp_ms=timestamp_ms, text=text))

        offset_ms = lyrics_payload.get("offset_ms", 0)
        is_synced = lyrics_payload.get("is_synced", False)
        duration_ms = payload.get("duration_ms", 0)
        if (
            not isinstance(offset_ms, int)
            or isinstance(offset_ms, bool)
            or not isinstance(is_synced, bool)
            or not isinstance(duration_ms, int)
            or isinstance(duration_ms, bool)
        ):
            raise ValueError("La entrada contiene valores numéricos inválidos")

        lyrics_data = LyricsData(
            lines=lines,
            title=title,
            artist=artist,
            album=album or None,
            offset_ms=offset_ms,
            is_synced=is_synced,
        )
        return UserLyricsEntry(
            artist=artist,
            title=title,
            album=album,
            duration_ms=max(0, duration_ms),
            source=source,
            updated_at=updated_at,
            lyrics_data=lyrics_data,
        )

    def get(self, artist: str, title: str) -> Optional[UserLyricsEntry]:
        path = self._path_for(artist, title)
        if not path.exists():
            for entry in self.all_entries():
                if track_metadata_matches(
                    artist,
                    title,
                    entry.artist,
                    entry.title,
                ):
                    return entry
            return None
        try:
            payload = json.loads(
                read_text_limited(path, max_bytes=MAX_LIBRARY_FILE_BYTES)
            )
            entry = self._deserialize(payload)
            if entry.key != make_track_key(artist, title):
                logger.warning(
                    "Ignorando entrada local con metadatos distintos: %s - %s",
                    artist,
                    title,
                )
                return None
            return entry
        except Exception as exc:
            logger.warning("Error leyendo letra local %s: %s", path.name, exc)
            return None

    def save(self, entry: UserLyricsEntry) -> UserLyricsEntry:
        """Guarda una entrada mediante reemplazo atómico."""
        if not all(
            isinstance(value, str)
            for value in (entry.artist, entry.title, entry.album, entry.source)
        ):
            raise ValueError("Los metadatos de la letra deben ser texto")
        entry.artist = entry.artist.strip()
        entry.title = entry.title.strip()
        entry.album = entry.album.strip()
        entry.updated_at = datetime.now(timezone.utc).isoformat()
        entry.lyrics_data.artist = entry.artist
        entry.lyrics_data.title = entry.title
        entry.lyrics_data.album = entry.album or None

        if not entry.artist or not entry.title:
            raise ValueError("El artista y el título son obligatorios")
        if any(
            len(value) > MAX_METADATA_CHARS
            for value in (entry.artist, entry.title, entry.album, entry.source)
        ):
            raise ValueError("Los metadatos de la letra son demasiado largos")
        if not entry.lyrics_data.lines:
            raise ValueError("La letra debe contener al menos una línea")
        if len(entry.lyrics_data.lines) > MAX_LIBRARY_LINES:
            raise ValueError("La letra contiene demasiadas líneas")
        if any(
            not isinstance(line.text, str)
            or len(line.text.strip()) > MAX_LYRIC_LINE_CHARS
            for line in entry.lyrics_data.lines
        ):
            raise ValueError("La letra contiene una línea demasiado larga")

        path = self._path_for(entry.artist, entry.title)
        payload = self._serialize(entry)
        atomic_write_text(path, json.dumps(payload, ensure_ascii=False, indent=2))
        return entry

    def exists(self, artist: str, title: str) -> bool:
        return self._path_for(artist, title).exists()

    def delete(self, artist: str, title: str) -> bool:
        """Elimina únicamente la entrada identificada por sus metadatos exactos."""
        path = self._path_for(artist, title)
        if not path.exists():
            return False
        path.unlink()
        return True

    def all_entries(self) -> list[UserLyricsEntry]:
        entries: list[UserLyricsEntry] = []
        for path in self.library_dir.glob("*.json"):
            try:
                payload = json.loads(
                    read_text_limited(path, max_bytes=MAX_LIBRARY_FILE_BYTES)
                )
                entries.append(self._deserialize(payload))
            except Exception as exc:
                logger.warning(
                    "Ignorando entrada local corrupta %s: %s", path.name, exc
                )
        return entries

    def search(
        self, artist: str, title: str, limit: int = 20
    ) -> list[LyricsCandidate]:
        """Busca coincidencias locales con tolerancia a variantes."""
        expected_artist = normalize_track_text(artist)
        expected_title = normalize_track_text(title)
        if not expected_artist or not expected_title:
            return []

        ranked: list[tuple[float, str, UserLyricsEntry]] = []
        for entry in self.all_entries():
            candidate_artist = normalize_track_text(entry.artist)
            candidate_title = normalize_track_text(entry.title)
            artist_ratio = SequenceMatcher(
                None, expected_artist, candidate_artist
            ).ratio()
            title_ratio = SequenceMatcher(
                None, expected_title, candidate_title
            ).ratio()
            exact_bonus = 2.0 if (
                expected_artist == candidate_artist
                and expected_title == candidate_title
            ) else 0.0
            containment_bonus = 0.25 if (
                expected_artist in candidate_artist
                and expected_title in candidate_title
            ) else 0.0
            score = exact_bonus + containment_bonus + (
                artist_ratio * 0.4 + title_ratio * 0.6
            )
            if exact_bonus or (artist_ratio >= 0.45 and title_ratio >= 0.45):
                ranked.append((score, entry.updated_at, entry))

        ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)
        return [entry.to_candidate() for _, _, entry in ranked[:limit]]
