"""
Servicio de traducción de letras.

Traduce letras de canciones bidireccionalmente entre inglés y español
usando Google Translate. Detecta automáticamente el idioma de las letras
y traduce en la dirección correcta (EN→ES o ES→EN).
Incluye caché local para evitar traducciones repetidas.
"""

import hashlib
import json
import logging
import re
import threading
from pathlib import Path
from typing import Callable, Optional

from deep_translator import GoogleTranslator

from .lrc_parser import LyricsData, LyricLine
from .storage import atomic_write_text, read_text_limited

logger = logging.getLogger(__name__)


class TranslationCache:
    """Caché local de traducciones en disco."""

    def __init__(self, cache_dir: Optional[Path] = None):
        """
        Inicializa el caché de traducciones.

        Args:
            cache_dir: Directorio para el caché. Default: ~/.lyrics-cache/translations/
        """
        if cache_dir is None:
            cache_dir = Path.home() / ".lyrics-cache" / "translations"

        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _get_cache_key(self, artist: str, title: str) -> str:
        """Genera una clave única para la combinación artista-título."""
        normalized = f"{artist.lower().strip()}|{title.lower().strip()}"
        return hashlib.md5(normalized.encode()).hexdigest()

    def _get_cache_path(self, artist: str, title: str, target_lang: str) -> Path:
        """Obtiene la ruta del archivo de caché."""
        if target_lang not in {"en", "es"}:
            raise ValueError("Idioma destino no permitido para caché")
        key = self._get_cache_key(artist, title)
        return self.cache_dir / f"{key}_{target_lang}.json"

    def get(
        self, artist: str, title: str, target_lang: str = "es"
    ) -> Optional[dict[int, str]]:
        """
        Busca traducciones en el caché.

        Returns:
            Dict {timestamp_ms: traducción} si existe, None si no.
        """
        cache_path = self._get_cache_path(artist, title, target_lang)

        if cache_path.exists():
            try:
                content = read_text_limited(cache_path, max_bytes=1048576)
                data = json.loads(content)
                if not isinstance(data, dict):
                    return None
                raw_translations = data.get("translations")
                if not isinstance(raw_translations, dict):
                    return None
                # Convertir keys de string a int
                translations: dict[int, str] = {}
                for key, value in raw_translations.items():
                    timestamp_ms = int(key)
                    if (
                        timestamp_ms < 0
                        or not isinstance(value, str)
                        or not value.strip()
                    ):
                        return None
                    translations[timestamp_ms] = value
                logger.debug(f"Translation cache hit: {artist} - {title}")
                return translations
            except Exception as e:
                logger.warning(f"Error leyendo caché de traducción: {e}")

        return None

    def save(
        self,
        artist: str,
        title: str,
        translations: dict[int, str],
        target_lang: str = "es",
    ) -> None:
        """
        Guarda traducciones en el caché.

        Args:
            artist: Nombre del artista
            title: Título de la canción
            translations: Dict {timestamp_ms: traducción}
            target_lang: Idioma destino
        """
        try:
            cache_path = self._get_cache_path(artist, title, target_lang)
            data = {
                "artist": artist,
                "title": title,
                "target_lang": target_lang,
                "translations": {str(k): v for k, v in translations.items()},
            }
            atomic_write_text(
                cache_path,
                json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            logger.debug(f"Traducción guardada en caché: {artist} - {title}")
        except Exception as e:
            logger.warning(f"Error guardando traducción en caché: {e}")

    def delete(self, artist: str, title: str) -> int:
        """Elimina todas las traducciones persistidas para una canción."""
        key = self._get_cache_key(artist, title)
        count = 0
        for cache_path in self.cache_dir.glob(f"{key}_*.json"):
            try:
                cache_path.unlink()
                count += 1
            except OSError as exc:
                logger.warning(
                    "Error eliminando traducción %s: %s",
                    cache_path.name,
                    exc,
                )
        return count


def _is_spanish_text(text: str) -> bool:
    """
    Detecta si el texto está en español usando heurísticas simples.

    Busca palabras comunes en español que son poco frecuentes en inglés.
    """
    spanish_indicators = [
        r"\bel\b",
        r"\bla\b",
        r"\blos\b",
        r"\blas\b",
        r"\bde\b",
        r"\bdel\b",
        r"\bque\b",
        r"\ben\b",
        r"\bcon\b",
        r"\bpor\b",
        r"\bpara\b",
        r"\buna\b",
        r"\buno\b",
        r"\bsu\b",
        r"\bsus\b",
        r"\bmi\b",
        r"\btu\b",
        r"\bes\b",
        r"\bson\b",
        r"\bestá\b",
        r"\bestoy\b",
        r"\btengo\b",
        r"\bquiero\b",
        r"\bcorazón\b",
        r"\bamor\b",
        r"\bvida\b",
        r"\bnoche\b",
        r"\bsiempre\b",
        r"\bnunca\b",
        r"\bdonde\b",
        r"\bcuando\b",
        r"\bcomo\b",
        r"\bpero\b",
        r"\bsin\b",
        r"\btodo\b",
        r"\bnada\b",
        r"\byo\b",
        r"\btú\b",
        r"\bél\b",
        r"\bella\b",
    ]

    text_lower = text.lower()
    matches = sum(1 for pattern in spanish_indicators if re.search(pattern, text_lower))

    # Si encontramos al menos 3 indicadores en el texto completo, probablemente es español
    return matches >= 3


def _is_english_text(text: str) -> bool:
    """
    Detecta si el texto está en inglés usando heurísticas simples.

    Busca palabras comunes en inglés que son poco frecuentes en español.
    """
    english_indicators = [
        r"\bthe\b",
        r"\bis\b",
        r"\bare\b",
        r"\byou\b",
        r"\bmy\b",
        r"\bwith\b",
        r"\bthis\b",
        r"\bthat\b",
        r"\bhave\b",
        r"\bwas\b",
        r"\bfor\b",
        r"\bnot\b",
        r"\bbut\b",
        r"\bwhat\b",
        r"\bwhen\b",
        r"\byour\b",
        r"\bfrom\b",
        r"\bthey\b",
        r"\bwill\b",
        r"\bcan\b",
        r"\bjust\b",
        r"\bdon't\b",
        r"\bknow\b",
        r"\blike\b",
        r"\btime\b",
        r"\bcome\b",
        r"\bmake\b",
        r"\bwant\b",
        r"\bhere\b",
        r"\bthere\b",
        r"\binto\b",
        r"\bonly\b",
        r"\bsome\b",
        r"\bcould\b",
        r"\bwould\b",
        r"\band\b",
        r"\ball\b",
        r"\been\b",
    ]

    text_lower = text.lower()
    matches = sum(1 for pattern in english_indicators if re.search(pattern, text_lower))

    # Si encontramos al menos 3 indicadores en el texto completo, probablemente es inglés
    return matches >= 3


def _is_italian_text(text: str) -> bool:
    """Detecta si el texto está en italiano usando palabras frecuentes."""
    italian_indicators = [
        r"\bil\b",
        r"\blo\b",
        r"\bgli\b",
        r"\bche\b",
        r"\bdi\b",
        r"\bsono\b",
        r"\bsei\b",
        r"\bnon\b",
        r"\bper\b",
        r"\bcon\b",
        r"\bquesta\b",
        r"\bquesto\b",
        r"\bamore\b",
        r"\bcuore\b",
        r"\bvita\b",
        r"\bnotte\b",
        r"\bsempre\b",
        r"\bmai\b",
        r"\bdove\b",
        r"\bquando\b",
        r"\bcome\b",
        r"\btutto\b",
        r"\bniente\b",
        r"\bmio\b",
        r"\bmia\b",
    ]

    text_lower = text.lower()
    matches = sum(1 for pattern in italian_indicators if re.search(pattern, text_lower))
    return matches >= 3


def _detect_language(text: str) -> tuple[str, str]:
    """
    Detecta el idioma del texto y retorna la dirección de traducción.

    Returns:
        Tupla (source_lang, target_lang) para usar con GoogleTranslator.
        Ejemplo: ("en", "es") para inglés→español, ("es", "en") para español→inglés.
    """
    is_spanish = _is_spanish_text(text)
    is_english = _is_english_text(text)
    is_italian = _is_italian_text(text)

    if is_italian and not is_english:
        # Texto en italiano → traducir a español. Se prioriza sobre español
        # porque ambos idiomas comparten varias palabras frecuentes.
        return ("it", "es")
    elif is_spanish and not is_english:
        # Texto en español → traducir a inglés
        return ("es", "en")
    elif is_english and not is_spanish:
        # Texto en inglés → traducir a español
        return ("en", "es")
    elif is_spanish and is_english:
        # Ambiguo (posiblemente bilingüe) → dejar que Google auto-detecte, target español
        return ("auto", "es")
    else:
        # No se detectó ninguno → auto-detectar con Google, target español
        return ("auto", "es")


def is_translation_enabled_by_default(lyrics: LyricsData) -> bool:
    """Indica si una letra debe traducirse automáticamente por defecto.

    Se activa para letras cuyo idioma de origen se identifica explícitamente
    como inglés o italiano. Los textos ambiguos o en otros idiomas quedan
    desactivados por defecto.
    """
    all_text = " ".join(line.text for line in lyrics.lines if line.text.strip())
    source_lang, _ = _detect_language(all_text)
    return source_lang in {"en", "it"}


# Compatibilidad con consumidores que usaban el nombre anterior.
is_english_lyrics = is_translation_enabled_by_default


def _is_instrumental_line(text: str) -> bool:
    """Detecta si una línea es instrumental o no tiene contenido traducible."""
    text_lower = text.lower().strip()

    # Patrones de líneas instrumentales o no traducibles
    instrumental_patterns = [
        r"^\[.*\]$",  # [Instrumental], [Solo], etc.
        r"^[\*♪♫🎵🎶\s\-\_\.]+$",  # Solo símbolos musicales
        r"^\(.*instrumental.*\)$",
        r"^\(.*solo.*\)$",
        r"^instrumental$",
        r"^intro$",
        r"^outro$",
        r"^verse\s*\d*$",
        r"^chorus$",
        r"^bridge$",
    ]

    for pattern in instrumental_patterns:
        if re.match(pattern, text_lower, re.IGNORECASE):
            return True

    # Líneas muy cortas sin letras reales
    if len(text_lower) < 2:
        return True

    return False


def _resolve_translation_direction(
    lyrics: LyricsData, target_lang: str
) -> tuple[str, str]:
    """Determina la dirección de traducción para una letra completa."""
    all_text = " ".join(line.text for line in lyrics.lines if line.text.strip())
    source_lang, detected_target = _detect_language(all_text)

    if target_lang != "auto":
        detected_target = target_lang
        if detected_target == "es":
            source_lang = "en"
        elif detected_target == "en":
            source_lang = "es"

    return source_lang, detected_target


def _get_translatable_lines(
    lyrics: LyricsData,
) -> list[tuple[int, LyricLine]]:
    """Devuelve las líneas con contenido apto para enviar al traductor."""
    return [
        (idx, line)
        for idx, line in enumerate(lyrics.lines)
        if line.text.strip() and not _is_instrumental_line(line.text)
    ]


class TranslationService:
    """
    Servicio de traducción bidireccional de letras usando Google Translate.

    Características:
    - Traducción bidireccional: inglés↔español (auto-detecta dirección)
    - Traducción batch para eficiencia
    - Caché local de traducciones
    - Detección automática de idioma
    - Manejo de líneas instrumentales
    """

    def __init__(self, cache_dir: Optional[Path] = None):
        """
        Inicializa el servicio de traducción.

        Args:
            cache_dir: Directorio para caché de traducciones
        """
        self.cache = TranslationCache(cache_dir)
        self._translator: Optional[GoogleTranslator] = None
        # Caché parcial en memoria: {(artist_lower, title_lower): {timestamp_ms: traducción}}
        self._partial_cache: dict[tuple[str, str], dict[int, str]] = {}

    def _get_translator(
        self, source: str = "en", target: str = "es"
    ) -> GoogleTranslator:
        """Obtiene o crea el traductor."""
        if (
            self._translator is None
            or self._translator.target != target
            or self._translator.source != source
        ):
            self._translator = GoogleTranslator(source=source, target=target)
        return self._translator

    def translate_lyrics(
        self, lyrics: LyricsData, target_lang: str = "auto", force: bool = False
    ) -> LyricsData:
        """
        Traduce todas las líneas de las letras.

        Detecta automáticamente el idioma de las letras y traduce en la
        dirección correcta:
        - Letras en inglés → traduce a español
        - Letras en español → traduce a inglés

        Args:
            lyrics: Datos de letras a traducir
            target_lang: Idioma destino. "auto" detecta automáticamente la
                        dirección. También acepta "es" o "en" para forzar.
            force: Si es True, traduce sin importar el idioma detectado

        Returns:
            LyricsData con traducciones añadidas a cada línea
        """
        if not lyrics.lines:
            return lyrics

        artist = lyrics.artist or "Unknown"
        title = lyrics.title or "Unknown"

        source_lang, detected_target = _resolve_translation_direction(
            lyrics, target_lang
        )

        logger.info(
            f"Dirección de traducción detectada: {source_lang}→{detected_target} "
            f"para: {artist} - {title}"
        )

        # Verificar si ya está en caché
        cached_translations = self.cache.get(artist, title, detected_target)
        if cached_translations:
            logger.info(f"Usando traducciones cacheadas para: {artist} - {title}")
            return self._apply_translations(lyrics, cached_translations)

        lines_to_translate = _get_translatable_lines(lyrics)

        if not lines_to_translate:
            logger.debug("No hay líneas para traducir")
            return lyrics

        # Traducir en batch
        try:
            translations = self._batch_translate(
                [line.text for _, line in lines_to_translate],
                source_lang=source_lang,
                target_lang=detected_target,
            )

            # Crear diccionario de traducciones {timestamp_ms: traducción}
            translation_dict: dict[int, str] = {}
            for i, (idx, line) in enumerate(lines_to_translate):
                if i < len(translations) and translations[i]:
                    translation_dict[line.timestamp_ms] = translations[i]

            # Guardar en caché
            self.cache.save(artist, title, translation_dict, detected_target)

            logger.info(
                f"Traducidas {len(translation_dict)} líneas para: {artist} - {title}"
            )

            return self._apply_translations(lyrics, translation_dict)

        except Exception as e:
            logger.error(f"Error traduciendo letras: {e}")
            return lyrics

    def _get_partial_cache_key(self, artist: str, title: str) -> tuple[str, str]:
        """Genera clave para el caché parcial en memoria."""
        return (artist.lower().strip(), title.lower().strip())

    def translate_lyrics_progressive(
        self,
        lyrics: LyricsData,
        callback: Callable[[int, int, str], None],
        cancel_event: threading.Event,
        target_lang: str = "auto",
        chunk_size: int = 5,
    ) -> dict[int, str]:
        """
        Traduce letras de forma progresiva, notificando vía callback conforme
        cada bloque se completa.

        Args:
            lyrics: Datos de letras a traducir.
            callback: Función (line_index, timestamp_ms, translation) invocada
                      por cada línea traducida.
            cancel_event: Si se activa, la traducción se aborta.
            target_lang: Idioma destino ("auto" para auto-detectar).
            chunk_size: Número de líneas por bloque de traducción.

        Returns:
            Dict {timestamp_ms: traducción} con todas las traducciones completadas.
        """
        if not lyrics.lines:
            return {}

        artist = lyrics.artist or "Unknown"
        title = lyrics.title or "Unknown"

        source_lang, detected_target = _resolve_translation_direction(
            lyrics, target_lang
        )

        logger.info(
            f"Traducción progresiva: {source_lang}→{detected_target} "
            f"para: {artist} - {title}"
        )

        # --- 1. Verificar caché de disco (resultado completo) ---
        cached_translations = self.cache.get(artist, title, detected_target)
        if cached_translations:
            logger.info(f"Cache hit completo (progresivo): {artist} - {title}")
            for idx, line in enumerate(lyrics.lines):
                tr = cached_translations.get(line.timestamp_ms)
                if tr:
                    if cancel_event.is_set():
                        return cached_translations
                    callback(idx, line.timestamp_ms, tr)
            return cached_translations

        # --- 2. Verificar caché parcial en memoria ---
        partial_key = self._get_partial_cache_key(artist, title)
        existing_partial = self._partial_cache.get(partial_key, {})

        lines_to_translate = _get_translatable_lines(lyrics)

        if not lines_to_translate:
            logger.debug("No hay líneas para traducir (progresivo)")
            return {}

        # Emitir traducciones parciales ya conocidas e identificar pendientes
        pending: list[tuple[int, LyricLine]] = []
        translation_dict: dict[int, str] = {}

        for idx, line in lines_to_translate:
            if cancel_event.is_set():
                return translation_dict
            cached_tr = existing_partial.get(line.timestamp_ms)
            if cached_tr:
                translation_dict[line.timestamp_ms] = cached_tr
                callback(idx, line.timestamp_ms, cached_tr)
            else:
                pending.append((idx, line))

        if not pending:
            logger.info(f"Caché parcial completo: {artist} - {title}")
            # Todas estaban en caché parcial → promover a caché de disco
            self.cache.save(artist, title, translation_dict, detected_target)
            return translation_dict

        # --- 3. Traducir pendientes en chunks ---
        # Primer chunk más pequeño para latencia mínima inicial
        first_chunk_size = min(3, chunk_size)
        chunks: list[list[tuple[int, LyricLine]]] = []
        if len(pending) > first_chunk_size:
            chunks.append(pending[:first_chunk_size])
            remaining = pending[first_chunk_size:]
            for i in range(0, len(remaining), chunk_size):
                chunks.append(remaining[i : i + chunk_size])
        else:
            chunks.append(pending)

        for chunk in chunks:
            if cancel_event.is_set():
                logger.info("Traducción progresiva cancelada")
                # Guardar parcial en memoria para reutilización
                self._partial_cache[partial_key] = translation_dict
                return translation_dict

            texts = [line.text for _, line in chunk]
            translations = self._batch_translate(
                texts,
                source_lang=source_lang,
                target_lang=detected_target,
            )

            # Emitir resultados del chunk
            for i, (idx, line) in enumerate(chunk):
                if cancel_event.is_set():
                    self._partial_cache[partial_key] = translation_dict
                    return translation_dict
                if i < len(translations) and translations[i]:
                    tr = translations[i]
                    translation_dict[line.timestamp_ms] = tr
                    callback(idx, line.timestamp_ms, tr)

        # --- 4. Solo persistir resultados completos; los parciales se reintentan. ---
        if len(translation_dict) == len(lines_to_translate):
            self.cache.save(artist, title, translation_dict, detected_target)
            self._partial_cache.pop(partial_key, None)
        else:
            self._partial_cache[partial_key] = translation_dict
            logger.warning(
                "Traducción progresiva incompleta: %s/%s líneas",
                len(translation_dict),
                len(lines_to_translate),
            )
        logger.info(
            f"Traducción progresiva completada: {len(translation_dict)} líneas "
            f"para: {artist} - {title}"
        )
        return translation_dict

    def _batch_translate(
        self,
        texts: list[str],
        source_lang: str = "en",
        target_lang: str = "es",
    ) -> list[Optional[str]]:
        """
        Traduce múltiples textos en batch.

        Args:
            texts: Lista de textos a traducir
            source_lang: Idioma origen ("en", "es" o "auto")
            target_lang: Idioma destino ("en" o "es")

        Returns:
            Lista de traducciones
        """
        if not texts:
            return []

        translator = self._get_translator(source=source_lang, target=target_lang)

        try:
            # deep-translator soporta traducción por lotes
            translations = translator.translate_batch(texts)
            return translations if translations else []
        except Exception as e:
            logger.warning(f"Error en batch translate, intentando uno por uno: {e}")

            # Fallback: traducir uno por uno
            results = []
            for text in texts:
                try:
                    result = translator.translate(text)
                    results.append(result or None)
                except Exception:
                    results.append(None)
            return results

    def _apply_translations(
        self, lyrics: LyricsData, translations: dict[int, str]
    ) -> LyricsData:
        """
        Aplica traducciones a las líneas de letras.

        Args:
            lyrics: Datos de letras original
            translations: Dict {timestamp_ms: traducción}

        Returns:
            LyricsData con traducciones aplicadas
        """
        # Crear nuevas líneas con traducciones
        new_lines = []
        for line in lyrics.lines:
            translation = translations.get(line.timestamp_ms)
            new_line = LyricLine(
                timestamp_ms=line.timestamp_ms, text=line.text, translation=translation
            )
            new_lines.append(new_line)

        # Crear nuevo LyricsData con las líneas actualizadas
        return LyricsData(
            lines=new_lines,
            title=lyrics.title,
            artist=lyrics.artist,
            album=lyrics.album,
            offset_ms=lyrics.offset_ms,
            is_synced=lyrics.is_synced,
        )

    def clear_cache(self) -> int:
        """
        Limpia el caché de traducciones.

        Returns:
            Número de archivos eliminados.
        """
        count = 0
        for file in self.cache.cache_dir.glob("*.json"):
            try:
                file.unlink()
                count += 1
            except Exception:
                pass
        logger.info(f"Caché de traducciones limpiado: {count} archivos eliminados")
        return count

    def invalidate_track(self, artist: str, title: str) -> int:
        """Invalida traducciones completas y parciales de una canción."""
        count = self.cache.delete(artist, title)
        self._partial_cache.pop(
            self._get_partial_cache_key(artist, title), None
        )
        return count


# --- Test ---
def main():
    """Test del TranslationService."""
    import asyncio

    logging.basicConfig(level=logging.DEBUG)

    service = TranslationService()

    # --- Test 1: Letras en inglés → traducción a español ---
    print("="*60)
    print("TEST 1: Inglés → Español")
    print("="*60)

    test_lyrics_en = LyricsData(
        lines=[
            LyricLine(timestamp_ms=0, text="Hello, how are you?"),
            LyricLine(timestamp_ms=5000, text="I'm doing fine"),
            LyricLine(timestamp_ms=10000, text="The sun is shining bright"),
            LyricLine(timestamp_ms=15000, text="Everything will be alright"),
            LyricLine(timestamp_ms=20000, text="[Instrumental]"),
            LyricLine(timestamp_ms=25000, text="Love is in the air tonight"),
        ],
        title="Test Song EN",
        artist="Test Artist",
        is_synced=True,
    )

    print("Letras originales (EN):")
    for line in test_lyrics_en.lines:
        print(f"  [{line.timestamp_ms}] {line.text}")

    print("\nTraduciendo EN→ES...")
    translated_en = service.translate_lyrics(test_lyrics_en)

    print("\nLetras traducidas:")
    for line in translated_en.lines:
        print(f"  [{line.timestamp_ms}] {line.text}")
        if line.translation:
            print(f"              → {line.translation}")

    # --- Test 2: Letras en español → traducción a inglés ---
    print("\n" + "="*60)
    print("TEST 2: Español → Inglés")
    print("="*60)

    test_lyrics_es = LyricsData(
        lines=[
            LyricLine(timestamp_ms=0, text="Hola, ¿cómo estás?"),
            LyricLine(timestamp_ms=5000, text="La vida es bella y el sol brilla"),
            LyricLine(timestamp_ms=10000, text="Mi corazón late por ti"),
            LyricLine(timestamp_ms=15000, text="Quiero estar contigo para siempre"),
            LyricLine(timestamp_ms=20000, text="[Instrumental]"),
            LyricLine(timestamp_ms=25000, text="Nunca te voy a olvidar, mi amor"),
        ],
        title="Test Song ES",
        artist="Test Artist",
        is_synced=True,
    )

    print("Letras originales (ES):")
    for line in test_lyrics_es.lines:
        print(f"  [{line.timestamp_ms}] {line.text}")

    print("\nTraduciendo ES→EN...")
    translated_es = service.translate_lyrics(test_lyrics_es)

    print("\nLetras traducidas:")
    for line in translated_es.lines:
        print(f"  [{line.timestamp_ms}] {line.text}")
        if line.translation:
            print(f"              → {line.translation}")


if __name__ == "__main__":
    main()
