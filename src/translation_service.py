"""
Servicio de traducción de letras.

Traduce letras de canciones de inglés a español usando Google Translate.
Incluye caché local para evitar traducciones repetidas.
"""

import hashlib
import json
import logging
import re
from pathlib import Path
from typing import Optional

from deep_translator import GoogleTranslator

from .lrc_parser import LyricsData, LyricLine

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
        key = self._get_cache_key(artist, title)
        return self.cache_dir / f"{key}_{target_lang}.json"
    
    def get(self, artist: str, title: str, target_lang: str = "es") -> Optional[dict[int, str]]:
        """
        Busca traducciones en el caché.
        
        Returns:
            Dict {timestamp_ms: traducción} si existe, None si no.
        """
        cache_path = self._get_cache_path(artist, title, target_lang)
        
        if cache_path.exists():
            try:
                content = cache_path.read_text(encoding='utf-8')
                data = json.loads(content)
                # Convertir keys de string a int
                translations = {int(k): v for k, v in data.get("translations", {}).items()}
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
        target_lang: str = "es"
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
                "translations": {str(k): v for k, v in translations.items()}
            }
            cache_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
            logger.debug(f"Traducción guardada en caché: {artist} - {title}")
        except Exception as e:
            logger.warning(f"Error guardando traducción en caché: {e}")


def _is_spanish_text(text: str) -> bool:
    """
    Detecta si el texto está en español usando heurísticas simples.
    
    Busca palabras comunes en español que son poco frecuentes en inglés.
    """
    spanish_indicators = [
        r'\bel\b', r'\bla\b', r'\blos\b', r'\blas\b',
        r'\bde\b', r'\bdel\b', r'\bque\b', r'\ben\b',
        r'\bcon\b', r'\bpor\b', r'\bpara\b', r'\buna\b',
        r'\buno\b', r'\bsu\b', r'\bsus\b', r'\bmi\b',
        r'\btu\b', r'\bes\b', r'\bson\b', r'\bestá\b',
        r'\bestoy\b', r'\btengo\b', r'\bquiero\b', r'\bcorazón\b',
        r'\bamor\b', r'\bvida\b', r'\bnoche\b', r'\bsiempre\b',
        r'\bnunca\b', r'\bdonde\b', r'\bcuando\b', r'\bcomo\b',
        r'\bpero\b', r'\bsin\b', r'\btodo\b', r'\bnada\b',
        r'\byo\b', r'\btú\b', r'\bél\b', r'\bella\b',
    ]
    
    text_lower = text.lower()
    matches = sum(1 for pattern in spanish_indicators if re.search(pattern, text_lower))
    
    # Si encontramos al menos 3 indicadores en el texto completo, probablemente es español
    return matches >= 3


def _is_instrumental_line(text: str) -> bool:
    """Detecta si una línea es instrumental o no tiene contenido traducible."""
    text_lower = text.lower().strip()
    
    # Patrones de líneas instrumentales o no traducibles
    instrumental_patterns = [
        r'^\[.*\]$',  # [Instrumental], [Solo], etc.
        r'^[\*♪♫🎵🎶\s\-\_\.]+$',  # Solo símbolos musicales
        r'^\(.*instrumental.*\)$',
        r'^\(.*solo.*\)$',
        r'^instrumental$',
        r'^intro$',
        r'^outro$',
        r'^verse\s*\d*$',
        r'^chorus$',
        r'^bridge$',
    ]
    
    for pattern in instrumental_patterns:
        if re.match(pattern, text_lower, re.IGNORECASE):
            return True
    
    # Líneas muy cortas sin letras reales
    if len(text_lower) < 2:
        return True
    
    return False


class TranslationService:
    """
    Servicio de traducción de letras usando Google Translate.
    
    Características:
    - Traducción batch para eficiencia
    - Caché local de traducciones
    - Detección de idioma para evitar traducir español
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
    
    def _get_translator(self, source: str = "en", target: str = "es") -> GoogleTranslator:
        """Obtiene o crea el traductor."""
        if self._translator is None or self._translator.target != target:
            self._translator = GoogleTranslator(source=source, target=target)
        return self._translator
    
    def translate_lyrics(
        self, 
        lyrics: LyricsData, 
        target_lang: str = "es",
        force: bool = False
    ) -> LyricsData:
        """
        Traduce todas las líneas de las letras.
        
        Args:
            lyrics: Datos de letras a traducir
            target_lang: Idioma destino (default: español)
            force: Si es True, traduce aunque parezca estar en español
            
        Returns:
            LyricsData con traducciones añadidas a cada línea
        """
        if not lyrics.lines:
            return lyrics
        
        artist = lyrics.artist or "Unknown"
        title = lyrics.title or "Unknown"
        
        # Verificar si ya está en caché
        cached_translations = self.cache.get(artist, title, target_lang)
        if cached_translations:
            logger.info(f"Usando traducciones cacheadas para: {artist} - {title}")
            return self._apply_translations(lyrics, cached_translations)
        
        # Recolectar texto para análisis de idioma
        all_text = " ".join(line.text for line in lyrics.lines if line.text.strip())
        
        # Detectar si ya está en español
        if not force and _is_spanish_text(all_text):
            logger.info(f"Letras ya están en español, omitiendo traducción: {artist} - {title}")
            return lyrics
        
        # Preparar líneas para traducción (filtrar instrumentales)
        lines_to_translate: list[tuple[int, LyricLine]] = []
        for idx, line in enumerate(lyrics.lines):
            if line.text.strip() and not _is_instrumental_line(line.text):
                lines_to_translate.append((idx, line))
        
        if not lines_to_translate:
            logger.debug("No hay líneas para traducir")
            return lyrics
        
        # Traducir en batch
        try:
            translations = self._batch_translate(
                [line.text for _, line in lines_to_translate],
                target_lang
            )
            
            # Crear diccionario de traducciones {timestamp_ms: traducción}
            translation_dict: dict[int, str] = {}
            for i, (idx, line) in enumerate(lines_to_translate):
                if i < len(translations) and translations[i]:
                    translation_dict[line.timestamp_ms] = translations[i]
            
            # Guardar en caché
            self.cache.save(artist, title, translation_dict, target_lang)
            
            logger.info(f"Traducidas {len(translation_dict)} líneas para: {artist} - {title}")
            
            return self._apply_translations(lyrics, translation_dict)
            
        except Exception as e:
            logger.error(f"Error traduciendo letras: {e}")
            return lyrics
    
    def _batch_translate(self, texts: list[str], target_lang: str = "es") -> list[str]:
        """
        Traduce múltiples textos en batch.
        
        Args:
            texts: Lista de textos a traducir
            target_lang: Idioma destino
            
        Returns:
            Lista de traducciones
        """
        if not texts:
            return []
        
        translator = self._get_translator(source="en", target=target_lang)
        
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
                    results.append(result if result else text)
                except Exception:
                    results.append(text)  # Mantener original si falla
            return results
    
    def _apply_translations(
        self, 
        lyrics: LyricsData, 
        translations: dict[int, str]
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
                timestamp_ms=line.timestamp_ms,
                text=line.text,
                translation=translation
            )
            new_lines.append(new_line)
        
        # Crear nuevo LyricsData con las líneas actualizadas
        return LyricsData(
            lines=new_lines,
            title=lyrics.title,
            artist=lyrics.artist,
            album=lyrics.album,
            offset_ms=lyrics.offset_ms,
            is_synced=lyrics.is_synced
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


# --- Test ---
def main():
    """Test del TranslationService."""
    import asyncio
    
    logging.basicConfig(level=logging.DEBUG)
    
    # Crear letras de prueba
    test_lyrics = LyricsData(
        lines=[
            LyricLine(timestamp_ms=0, text="Hello, how are you?"),
            LyricLine(timestamp_ms=5000, text="I'm doing fine"),
            LyricLine(timestamp_ms=10000, text="The sun is shining bright"),
            LyricLine(timestamp_ms=15000, text="Everything will be alright"),
            LyricLine(timestamp_ms=20000, text="[Instrumental]"),
            LyricLine(timestamp_ms=25000, text="Love is in the air tonight"),
        ],
        title="Test Song",
        artist="Test Artist",
        is_synced=True
    )
    
    service = TranslationService()
    
    print("Letras originales:")
    for line in test_lyrics.lines:
        print(f"  [{line.timestamp_ms}] {line.text}")
    
    print("\nTraduciendo...")
    translated = service.translate_lyrics(test_lyrics)
    
    print("\nLetras traducidas:")
    for line in translated.lines:
        print(f"  [{line.timestamp_ms}] {line.text}")
        if line.translation:
            print(f"              → {line.translation}")


if __name__ == "__main__":
    main()
