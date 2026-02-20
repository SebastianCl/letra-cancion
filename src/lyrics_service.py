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
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from urllib.parse import quote

import aiohttp

from .lrc_parser import LRCParser, LyricsData

logger = logging.getLogger(__name__)


@dataclass
class LyricsSearchResult:
    """Resultado de búsqueda de letras."""

    lyrics_data: LyricsData
    provider: str
    cached: bool = False


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

    def __init__(self, session: aiohttp.ClientSession):
        self.session = session

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
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    return self._parse_response(data)
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
            ) as response:
                if response.status == 200:
                    results = await response.json()
                    if results and len(results) > 0:
                        # Tomar el primer resultado
                        return self._parse_response(results[0])
        except Exception as e:
            logger.warning(f"LRCLIB /search exception: {e}")

        return None

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
        song_id = await self._search_song(artist, title)
        if not song_id:
            return None

        # Paso 2: Obtener letras
        return await self._get_lyrics(song_id, duration_seconds)

    async def _search_song(self, artist: str, title: str) -> Optional[int]:
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

                result = await response.json()
                songs = result.get("result", {}).get("songs", [])

                if not songs:
                    return None

                # Buscar la mejor coincidencia
                title_lower = title.lower()
                artist_lower = artist.lower()

                for song in songs:
                    song_title = song.get("name", "").lower()
                    song_artists = [
                        a.get("name", "").lower() for a in song.get("artists", [])
                    ]

                    # Coincidencia exacta de título
                    if title_lower in song_title or song_title in title_lower:
                        # Verificar artista
                        if any(
                            artist_lower in a or a in artist_lower for a in song_artists
                        ):
                            return song.get("id")

                # Si no hay coincidencia exacta, usar el primer resultado
                return songs[0].get("id")

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

                result = await response.json()

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
        self.cache = LyricsCache(cache_dir)
        self._session: Optional[aiohttp.ClientSession] = None
        self._providers: list = []

    async def initialize(self) -> None:
        """Inicializa la sesión HTTP y los proveedores."""
        self._session = aiohttp.ClientSession()

        # Configurar proveedores en orden de prioridad
        self._providers = [
            ("LRCLIB", LRCLIBProvider(self._session)),
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
            prefer_synced: Si True, solo acepta letras sincronizadas en primera pasada

        Returns:
            LyricsSearchResult si se encontró, None si no.
        """
        if not artist or not title:
            logger.warning("Se requiere artista y título para buscar letras")
            return None

        # 1. Buscar en caché
        cached = self.cache.get(artist, title)
        if cached:
            # Si preferimos sincronizadas y el caché tiene sincronizadas, usar
            if not prefer_synced or cached.is_synced:
                return LyricsSearchResult(
                    lyrics_data=cached, provider="cache", cached=True
                )

        # 2. Buscar en proveedores
        duration_seconds = duration_ms // 1000 if duration_ms else None

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
                    # Verificar si cumple preferencia de sincronización
                    if prefer_synced and not result.is_synced:
                        logger.debug(
                            f"{provider_name}: encontró solo letra plana, continuando..."
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
                continue

        # 3. Segunda pasada: aceptar letras planas si prefer_synced estaba activo
        if prefer_synced:
            logger.debug("No se encontraron letras sincronizadas, buscando planas...")
            return await self.search(
                artist=artist,
                title=title,
                album=album,
                duration_ms=duration_ms,
                prefer_synced=False,
            )

        logger.info(f"No se encontraron letras para: {artist} - {title}")
        return None

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
