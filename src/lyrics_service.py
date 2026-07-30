"""
Servicio de obtención de letras desde múltiples fuentes.

Proveedores soportados (fuentes abiertas):
- LRCLIB (primario): https://lrclib.net/api
- NetEase Music (fallback): https://music.163.com/api

Incluye caché local para evitar consultas repetidas.
"""

import asyncio
import hashlib
import logging
import ssl
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Optional

import aiohttp
import certifi

from .lrc_parser import LRCParser, LyricsData
from .lyrics_library import (
    LyricsCandidate,
    UserLyricsEntry,
    UserLyricsLibrary,
    clone_lyrics_data,
    metadata_text_matches,
    normalize_track_text,
    track_metadata_matches,
)

logger = logging.getLogger(__name__)


def _normalize_metadata(value: Optional[str]) -> str:
    """Normaliza metadatos musicales para compararlos de forma tolerante."""
    return normalize_track_text(value)


def _metadata_matches(expected: str, candidate: Optional[str]) -> bool:
    """Evita falsos positivos sin penalizar pequeñas variantes de escritura."""
    return metadata_text_matches(expected, candidate or "")


def _track_matches(
    artist: str,
    title: str,
    candidate_artist: Optional[str],
    candidate_title: Optional[str],
) -> bool:
    """Comprueba que un resultado corresponde realmente a la pista solicitada."""
    return track_metadata_matches(
        artist,
        title,
        candidate_artist or "",
        candidate_title or "",
    )


@dataclass
class LyricsSearchResult:
    """Resultado de búsqueda de letras."""

    lyrics_data: LyricsData
    provider: str
    cached: bool = False
    local: bool = False


class LyricsCache:
    """Caché local de letras en disco."""

    def __init__(self, cache_dir: Optional[Path] = None):
        """
        Inicializa el caché.

        Args:
            cache_dir: Directorio para el caché. Default: ~/.lyrics-cache/
        """
        if cache_dir is None:
            cache_dir = Path.home() / ".lyrics-cache"

        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        # Sub-directorio para letras sincronizadas
        self.synced_dir = self.cache_dir / "synced"
        self.synced_dir.mkdir(exist_ok=True)

        # Sub-directorio para letras planas
        self.plain_dir = self.cache_dir / "plain"
        self.plain_dir.mkdir(exist_ok=True)

    def _get_cache_key(self, artist: str, title: str) -> str:
        """Genera una clave única para la combinación artista-título."""
        normalized = f"{artist.lower().strip()}|{title.lower().strip()}"
        return hashlib.md5(normalized.encode()).hexdigest()

    def _get_cache_path(self, artist: str, title: str, synced: bool) -> Path:
        """Obtiene la ruta del archivo de caché."""
        key = self._get_cache_key(artist, title)
        directory = self.synced_dir if synced else self.plain_dir
        return directory / f"{key}.lrc"

    def get(self, artist: str, title: str) -> Optional[LyricsData]:
        """
        Busca letras en el caché.

        Prioriza letras sincronizadas sobre planas.

        Returns:
            LyricsData si existe en caché, None si no.
        """
        # Primero buscar sincronizadas
        synced_path = self._get_cache_path(artist, title, synced=True)
        if synced_path.exists():
            try:
                content = synced_path.read_text(encoding="utf-8")
                data = LRCParser.parse(content)
                logger.debug(f"Cache hit (synced): {artist} - {title}")
                return data
            except Exception as e:
                logger.warning(f"Error leyendo caché synced: {e}")

        # Luego buscar planas
        plain_path = self._get_cache_path(artist, title, synced=False)
        if plain_path.exists():
            try:
                content = plain_path.read_text(encoding="utf-8")
                data = LRCParser.parse(content)
                logger.debug(f"Cache hit (plain): {artist} - {title}")
                return data
            except Exception as e:
                logger.warning(f"Error leyendo caché plain: {e}")

        return None

    def save(self, artist: str, title: str, lyrics_data: LyricsData) -> None:
        """
        Guarda letras en el caché.

        Args:
            artist: Nombre del artista
            title: Título de la canción
            lyrics_data: Datos de letras a guardar
        """
        try:
            cache_path = self._get_cache_path(
                artist, title, synced=lyrics_data.is_synced
            )
            lrc_content = LRCParser.to_lrc(lyrics_data)
            cache_path.write_text(lrc_content, encoding="utf-8")
            logger.debug(f"Guardado en caché: {artist} - {title}")
        except Exception as e:
            logger.warning(f"Error guardando en caché: {e}")

    def delete(self, artist: str, title: str) -> int:
        """Elimina las variantes descargadas de una canción."""
        count = 0
        for synced in (True, False):
            path = self._get_cache_path(artist, title, synced)
            if path.exists():
                try:
                    path.unlink()
                    count += 1
                except OSError as exc:
                    logger.warning(
                        "Error eliminando caché %s: %s", path.name, exc
                    )
        return count

    def clear(self) -> int:
        """
        Limpia todo el caché.

        Returns:
            Número de archivos eliminados.
        """
        count = 0
        for directory in [self.synced_dir, self.plain_dir]:
            for file in directory.glob("*.lrc"):
                try:
                    file.unlink()
                    count += 1
                except Exception:
                    pass
        logger.info(f"Caché limpiado: {count} archivos eliminados")
        return count


class LRCLIBProvider:
    """
    Proveedor de letras desde LRCLIB.

    API: https://lrclib.net/api
    - Sin autenticación requerida
    - Sin rate limiting conocido
    - Soporta letras sincronizadas y planas
    """

    BASE_URL = "https://lrclib.net/api"

    def __init__(
        self,
        session: aiohttp.ClientSession,
        ssl_context: Optional[ssl.SSLContext] = None,
    ):
        self.session = session
        self.ssl_context = ssl_context

    async def search(
        self,
        artist: str,
        title: str,
        album: Optional[str] = None,
        duration_seconds: Optional[int] = None,
    ) -> Optional[LyricsData]:
        """
        Busca letras en LRCLIB.

        Args:
            artist: Nombre del artista
            title: Título de la canción
            album: Nombre del álbum (opcional, mejora precisión)
            duration_seconds: Duración en segundos (opcional, mejora precisión)

        Returns:
            LyricsData si se encontró, None si no.
        """
        # Método 1: Búsqueda exacta con parámetros
        params = {
            "artist_name": artist,
            "track_name": title,
        }
        if album:
            params["album_name"] = album
        if duration_seconds:
            params["duration"] = str(duration_seconds)

        try:
            async with self.session.get(
                f"{self.BASE_URL}/get",
                params=params,
                timeout=aiohttp.ClientTimeout(total=10),
                ssl=self.ssl_context,
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    if _track_matches(
                        artist,
                        title,
                        data.get("artistName"),
                        data.get("trackName"),
                    ):
                        return self._parse_response(data)
                    logger.warning(
                        "LRCLIB /get devolvió una pista con metadatos distintos"
                    )
                elif response.status != 404:
                    logger.warning(f"LRCLIB /get error: {response.status}")
        except Exception as e:
            logger.warning(f"LRCLIB /get exception: {e}")

        # Método 2: Búsqueda textual
        try:
            search_query = f"{artist} {title}"
            async with self.session.get(
                f"{self.BASE_URL}/search",
                params={"q": search_query},
                timeout=aiohttp.ClientTimeout(total=10),
                ssl=self.ssl_context,
            ) as response:
                if response.status == 200:
                    results = await response.json()
                    for result in results or []:
                        if _track_matches(
                            artist,
                            title,
                            result.get("artistName"),
                            result.get("trackName"),
                        ):
                            return self._parse_response(result)
        except Exception as e:
            logger.warning(f"LRCLIB /search exception: {e}")

        return None

    async def search_candidates(
        self, artist: str, title: str, limit: int = 10
    ) -> list[LyricsCandidate]:
        """Devuelve coincidencias de LRCLIB sin forzar una selección exacta."""
        try:
            async with self.session.get(
                f"{self.BASE_URL}/search",
                params={"q": f"{artist} {title}"},
                timeout=aiohttp.ClientTimeout(total=10),
                ssl=self.ssl_context,
            ) as response:
                if response.status != 200:
                    return []
                results = await response.json()
        except Exception as exc:
            logger.warning("LRCLIB candidate search exception: %s", exc)
            return []

        candidates: list[LyricsCandidate] = []
        for result in (results or [])[:limit]:
            lyrics_data = self._parse_response(result)
            if lyrics_data is None:
                continue
            duration_ms = int(float(result.get("duration") or 0) * 1000)
            candidates.append(
                LyricsCandidate(
                    provider="LRCLIB",
                    provider_id=str(
                        result.get("id")
                        or f"{result.get('artistName', '')}|"
                        f"{result.get('trackName', '')}"
                    ),
                    artist=str(result.get("artistName") or ""),
                    title=str(result.get("trackName") or ""),
                    album=str(result.get("albumName") or ""),
                    duration_ms=duration_ms,
                    is_synced=lyrics_data.is_synced,
                    lyrics_data=lyrics_data,
                )
            )
        return candidates

    async def load_candidate(
        self, candidate: LyricsCandidate
    ) -> Optional[LyricsData]:
        if candidate.lyrics_data is None:
            return None
        return clone_lyrics_data(candidate.lyrics_data)

    def _parse_response(self, data: dict) -> Optional[LyricsData]:
        """Parsea la respuesta de LRCLIB a LyricsData."""
        synced_lyrics = data.get("syncedLyrics")
        plain_lyrics = data.get("plainLyrics")

        if synced_lyrics:
            # Preferir letras sincronizadas
            lyrics_data = LRCParser.parse(synced_lyrics)
            lyrics_data.title = data.get("trackName")
            lyrics_data.artist = data.get("artistName")
            lyrics_data.album = data.get("albumName")
            return lyrics_data
        elif plain_lyrics:
            # Fallback a letras planas
            duration_ms = int(data.get("duration", 0) * 1000)
            lyrics_data = LRCParser.parse_plain_lyrics(plain_lyrics, duration_ms)
            lyrics_data.title = data.get("trackName")
            lyrics_data.artist = data.get("artistName")
            lyrics_data.album = data.get("albumName")
            return lyrics_data

        return None


class NetEaseProvider:
    """
    Proveedor de letras desde NetEase Music (163.com).

    API no oficial pero funcional.
    Buena cobertura de música asiática y occidental.
    """

    SEARCH_URL = "https://music.163.com/api/search/get"
    LYRICS_URL = "https://music.163.com/api/song/lyric"

    def __init__(self, session: aiohttp.ClientSession):
        self.session = session
        self.headers = {
            "Referer": "https://music.163.com/",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        }

    async def search(
        self,
        artist: str,
        title: str,
        album: Optional[str] = None,
        duration_seconds: Optional[int] = None,
    ) -> Optional[LyricsData]:
        """
        Busca letras en NetEase.

        Args:
            artist: Nombre del artista
            title: Título de la canción

        Returns:
            LyricsData si se encontró, None si no.
        """
        # Paso 1: Buscar la canción
        song = await self._search_song(artist, title)
        if not song:
            return None

        # Paso 2: Obtener letras
        lyrics = await self._get_lyrics(song["id"], duration_seconds)
        if lyrics:
            lyrics.title = song.get("title")
            lyrics.artist = song.get("artist")
            lyrics.album = song.get("album")
        return lyrics

    async def search_candidates(
        self, artist: str, title: str, limit: int = 10
    ) -> list[LyricsCandidate]:
        """Lista canciones de NetEase; la letra se carga al previsualizar."""
        try:
            data = {
                "s": f"{artist} {title}",
                "type": 1,
                "limit": max(1, min(limit, 20)),
                "offset": 0,
            }
            async with self.session.post(
                self.SEARCH_URL,
                data=data,
                headers=self.headers,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as response:
                if response.status != 200:
                    return []
                result = await response.json(content_type=None)
        except Exception as exc:
            logger.warning("NetEase candidate search error: %s", exc)
            return []

        candidates: list[LyricsCandidate] = []
        for song in result.get("result", {}).get("songs", [])[:limit]:
            artists = [
                str(item.get("name") or "")
                for item in song.get("artists", [])
                if item.get("name")
            ]
            album = song.get("album") or {}
            candidates.append(
                LyricsCandidate(
                    provider="NetEase",
                    provider_id=str(song.get("id") or ""),
                    artist=", ".join(artists),
                    title=str(song.get("name") or ""),
                    album=str(album.get("name") or ""),
                    duration_ms=max(0, int(song.get("duration") or 0)),
                    is_synced=None,
                )
            )
        return [
            candidate
            for candidate in candidates
            if candidate.provider_id and candidate.artist and candidate.title
        ]

    async def load_candidate(
        self, candidate: LyricsCandidate
    ) -> Optional[LyricsData]:
        try:
            song_id = int(candidate.provider_id)
        except (TypeError, ValueError):
            return None
        lyrics = await self._get_lyrics(song_id, candidate.duration_ms or None)
        if lyrics:
            lyrics.artist = candidate.artist
            lyrics.title = candidate.title
            lyrics.album = candidate.album or None
        return lyrics

    async def _search_song(self, artist: str, title: str) -> Optional[dict]:
        """Busca el ID de la canción en NetEase."""
        try:
            search_query = f"{artist} {title}"
            data = {"s": search_query, "type": 1, "limit": 10, "offset": 0}  # 1 = songs

            async with self.session.post(
                self.SEARCH_URL,
                data=data,
                headers=self.headers,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as response:
                if response.status != 200:
                    return None

                result = await response.json(content_type=None)
                songs = result.get("result", {}).get("songs", [])

                if not songs:
                    return None

                for song in songs:
                    song_title = song.get("name")
                    song_artists = [
                        a.get("name") for a in song.get("artists", [])
                    ]
                    matching_artist = next(
                        (
                            song_artist
                            for song_artist in song_artists
                            if _metadata_matches(artist, song_artist)
                        ),
                        None,
                    )
                    if matching_artist and _metadata_matches(title, song_title):
                        album_data = song.get("album") or {}
                        return {
                            "id": song.get("id"),
                            "title": song_title,
                            "artist": matching_artist,
                            "album": album_data.get("name"),
                        }

                return None

        except Exception as e:
            logger.warning(f"NetEase search error: {e}")
            return None

    async def _get_lyrics(
        self, song_id: int, duration_ms: Optional[int] = None
    ) -> Optional[LyricsData]:
        """Obtiene las letras de una canción por su ID."""
        try:
            params = {
                "id": song_id,
                "lv": 1,  # Letras con timestamp
                "kv": 1,  # Karaoke (word-by-word)
                "tv": -1,
            }

            async with self.session.get(
                self.LYRICS_URL,
                params=params,
                headers=self.headers,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as response:
                if response.status != 200:
                    return None

                result = await response.json(content_type=None)

                # Intentar obtener letras sincronizadas
                lrc_data = result.get("lrc", {})
                lrc_content = lrc_data.get("lyric", "")

                if lrc_content and "[" in lrc_content:
                    return LRCParser.parse(lrc_content)

                # Fallback: letras sin sincronizar (si las hay)
                # NetEase generalmente tiene sincronizadas

                return None

        except Exception as e:
            logger.warning(f"NetEase lyrics error: {e}")
            return None


class LyricsService:
    """
    Servicio principal de obtención de letras.

    Gestiona múltiples proveedores con fallback y caché local.
    """

    def __init__(self, cache_dir: Optional[Path] = None):
        """
        Inicializa el servicio de letras.

        Args:
            cache_dir: Directorio para el caché local.
        """
        base_dir = cache_dir or Path.home() / ".lyrics-cache"
        self.cache = LyricsCache(base_dir)
        self.library = UserLyricsLibrary(base_dir / "library")
        self._session: Optional[aiohttp.ClientSession] = None
        self._providers: list = []

    async def initialize(self) -> None:
        """Inicializa la sesión HTTP y los proveedores."""
        self._session = aiohttp.ClientSession(
            headers={
                "User-Agent": "LetraCancion/1.0 (personal desktop lyrics client)"
            }
        )

        # Usar un bundle CA actualizado sin desactivar la validación TLS.
        lrclib_ssl_context = ssl.create_default_context(cafile=certifi.where())

        # Configurar proveedores en orden de prioridad
        self._providers = [
            ("LRCLIB", LRCLIBProvider(self._session, lrclib_ssl_context)),
            ("NetEase", NetEaseProvider(self._session)),
        ]

        logger.info(
            "LyricsService inicializado con proveedores: "
            + ", ".join(p[0] for p in self._providers)
        )

    async def close(self) -> None:
        """Cierra la sesión HTTP."""
        if self._session:
            await self._session.close()
            self._session = None

    async def search(
        self,
        artist: str,
        title: str,
        album: Optional[str] = None,
        duration_ms: Optional[int] = None,
        prefer_synced: bool = True,
    ) -> Optional[LyricsSearchResult]:
        """
        Busca letras para una canción.

        Args:
            artist: Nombre del artista
            title: Título de la canción
            album: Nombre del álbum (opcional)
            duration_ms: Duración en milisegundos (opcional)
            prefer_synced: Si True, prioriza letras sincronizadas

        Returns:
            LyricsSearchResult si se encontró, None si no.
        """
        if not artist or not title:
            logger.warning("Se requiere artista y título para buscar letras")
            return None

        # 1. Buscar una personalización local
        local_entry = self.library.get(artist, title)
        if local_entry and local_entry.lyrics_data.lines:
            return LyricsSearchResult(
                lyrics_data=clone_lyrics_data(local_entry.lyrics_data),
                provider="Biblioteca local",
                cached=False,
                local=True,
            )

        # 2. Buscar en caché
        cached = self.cache.get(artist, title)
        if cached:
            if not _track_matches(
                artist, title, cached.artist, cached.title
            ):
                logger.warning(
                    f"Ignorando letra en caché con metadatos incorrectos: "
                    f"{artist} - {title}"
                )
            elif not prefer_synced or cached.is_synced:
                return LyricsSearchResult(
                    lyrics_data=cached, provider="cache", cached=True
                )

        # 3. Buscar en proveedores
        duration_seconds = duration_ms // 1000 if duration_ms else None
        plain_fallback: Optional[tuple[str, LyricsData]] = None

        for provider_name, provider in self._providers:
            try:
                logger.debug(f"Buscando en {provider_name}: {artist} - {title}")

                result = await provider.search(
                    artist=artist,
                    title=title,
                    album=album,
                    duration_seconds=duration_seconds,
                )

                if result:
                    # Si preferimos sincronizadas y el resultado es plano,
                    # guardarlo como fallback y continuar buscando sincronizadas
                    if prefer_synced and not result.is_synced:
                        if plain_fallback is None:
                            plain_fallback = (provider_name, result)
                            logger.debug(
                                f"{provider_name}: guardando letra plana como fallback"
                            )
                        continue

                    # Guardar en caché
                    self.cache.save(artist, title, result)

                    logger.info(
                        f"Letras encontradas en {provider_name} para: {artist} - {title}"
                    )
                    return LyricsSearchResult(
                        lyrics_data=result, provider=provider_name, cached=False
                    )

            except Exception as e:
                logger.warning(f"Error en proveedor {provider_name}: {e}")

        # 4. Usar fallback plano si prefer_synced estaba activo
        if prefer_synced and plain_fallback:
            provider_name, result = plain_fallback
            self.cache.save(artist, title, result)
            logger.info(
                f"Usando letra plana de {provider_name} para: {artist} - {title}"
            )
            return LyricsSearchResult(
                lyrics_data=result, provider=provider_name, cached=False
            )

        # 5. Segunda pasada aceptando cualquier tipo (solo si no hubo ningún resultado)
        if prefer_synced and plain_fallback is None:
            logger.debug("No se encontraron resultados, reintentando sin preferencia...")
            for provider_name, provider in self._providers:
                try:
                    result = await provider.search(
                        artist=artist,
                        title=title,
                        album=album,
                        duration_seconds=duration_seconds,
                    )
                    if result:
                        self.cache.save(artist, title, result)
                        logger.info(
                            f"Letras encontradas en {provider_name} para: {artist} - {title}"
                        )
                        return LyricsSearchResult(
                            lyrics_data=result, provider=provider_name, cached=False
                        )
                except Exception as e:
                    logger.warning(f"Error en proveedor {provider_name}: {e}")

        logger.info(f"No se encontraron letras para: {artist} - {title}")
        return None

    async def search_candidates(
        self,
        artist: str,
        title: str,
        limit: int = 20,
    ) -> list[LyricsCandidate]:
        """Busca resultados locales y remotos para el gestor de letras."""
        if not artist.strip() or not title.strip():
            return []

        local_candidates = self.library.search(artist, title, limit=limit)
        tasks = [
            provider.search_candidates(artist, title, limit=min(limit, 10))
            for _, provider in self._providers
            if hasattr(provider, "search_candidates")
        ]
        remote_groups: list = []
        if tasks:
            remote_groups = list(
                await asyncio.gather(*tasks, return_exceptions=True)
            )

        combined = list(local_candidates)
        for group in remote_groups:
            if isinstance(group, Exception):
                logger.warning("Un proveedor falló buscando candidatos: %s", group)
                continue
            combined.extend(group)

        provider_priority = {
            "Biblioteca local": 3,
            "LRCLIB": 2,
            "NetEase": 1,
        }
        expected_artist = normalize_track_text(artist)
        expected_title = normalize_track_text(title)

        def rank(candidate: LyricsCandidate) -> tuple:
            candidate_artist = normalize_track_text(candidate.artist)
            candidate_title = normalize_track_text(candidate.title)
            exact = int(
                candidate_artist == expected_artist
                and candidate_title == expected_title
            )
            title_ratio = SequenceMatcher(
                None, expected_title, candidate_title
            ).ratio()
            artist_ratio = SequenceMatcher(
                None, expected_artist, candidate_artist
            ).ratio()
            return (
                exact,
                provider_priority.get(candidate.provider, 0),
                int(candidate.is_synced is True),
                title_ratio * 0.6 + artist_ratio * 0.4,
            )

        combined.sort(key=rank, reverse=True)
        deduplicated: list[LyricsCandidate] = []
        seen: set[tuple[str, str]] = set()
        for candidate in combined:
            identity = candidate.identity[:2]
            if identity in seen:
                continue
            seen.add(identity)
            deduplicated.append(candidate)
            if len(deduplicated) >= limit:
                break
        return deduplicated

    async def load_candidate(
        self, candidate: LyricsCandidate
    ) -> Optional[LyricsData]:
        """Carga la letra completa de una coincidencia seleccionada."""
        if candidate.lyrics_data is not None:
            return clone_lyrics_data(candidate.lyrics_data)
        if candidate.is_local:
            entry = self.library.get(candidate.artist, candidate.title)
            return (
                clone_lyrics_data(entry.lyrics_data)
                if entry is not None
                else None
            )

        for provider_name, provider in self._providers:
            if provider_name != candidate.provider:
                continue
            if not hasattr(provider, "load_candidate"):
                return None
            lyrics = await provider.load_candidate(candidate)
            if lyrics:
                candidate.lyrics_data = clone_lyrics_data(lyrics)
                candidate.is_synced = lyrics.is_synced
            return lyrics
        return None

    def has_user_lyrics(self, artist: str, title: str) -> bool:
        return self.library.exists(artist, title)

    def save_user_lyrics(
        self,
        artist: str,
        title: str,
        lyrics_data: LyricsData,
        album: str = "",
        duration_ms: int = 0,
        source: str = "manual",
    ) -> UserLyricsEntry:
        """Guarda una versión local prioritaria e invalida descargas previas."""
        entry = UserLyricsEntry(
            artist=artist,
            title=title,
            album=album,
            duration_ms=duration_ms,
            source=source,
            lyrics_data=clone_lyrics_data(lyrics_data),
        )
        saved = self.library.save(entry)
        self.cache.delete(artist, title)
        return saved

    def delete_user_lyrics(self, artist: str, title: str) -> bool:
        """Elimina una versión local sin afectar el caché de proveedores."""
        return self.library.delete(artist, title)

    async def search_with_fallback(
        self,
        artist: str,
        title: str,
        album: Optional[str] = None,
        duration_ms: Optional[int] = None,
    ) -> LyricsData:
        """
        Busca letras con fallback garantizado.

        Siempre retorna un LyricsData, aunque sea vacío.

        Args:
            artist: Nombre del artista
            title: Título de la canción
            album: Nombre del álbum
            duration_ms: Duración en milisegundos

        Returns:
            LyricsData (puede estar vacío si no se encontró nada)
        """
        result = await self.search(artist, title, album, duration_ms)

        if result:
            return result.lyrics_data

        # Retornar LyricsData vacío con metadatos
        return LyricsData(
            lines=[], title=title, artist=artist, album=album, is_synced=False
        )


# --- Ejemplo de uso ---
async def main():
    """Ejemplo de uso del LyricsService."""
    logging.basicConfig(level=logging.DEBUG)

    service = LyricsService()
    await service.initialize()

    # Ejemplos de búsqueda
    test_songs = [
        ("Coldplay", "Yellow"),
        ("Queen", "Bohemian Rhapsody"),
        ("The Beatles", "Hey Jude"),
        ("Daft Punk", "Get Lucky"),
    ]

    for artist, title in test_songs:
        print(f"\n{'='*60}")
        print(f"Buscando: {artist} - {title}")
        print("=" * 60)

        result = await service.search(artist, title)

        if result:
            print(f"✓ Proveedor: {result.provider}")
            print(f"  Sincronizada: {result.lyrics_data.is_synced}")
            print(f"  Líneas: {len(result.lyrics_data.lines)}")
            print(f"  Cached: {result.cached}")

            # Mostrar primeras líneas
            print("\n  Primeras líneas:")
            for line in result.lyrics_data.lines[:5]:
                print(f"    {line}")
        else:
            print("✗ No se encontraron letras")

    await service.close()


if __name__ == "__main__":
    asyncio.run(main())
