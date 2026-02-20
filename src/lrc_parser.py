"""
Parser para formato LRC (Lyrics)

Formato LRC estándar:
[mm:ss.xx] Línea de letra
[00:12.00] Primera línea
[00:17.20] Segunda línea

Tags de metadatos (opcionales):
[ti:Título]
[ar:Artista]
[al:Álbum]
[offset:+/-ms]
"""

import re
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class LyricLine:
    """Representa una línea de letra con su timestamp."""

    timestamp_ms: int  # Tiempo en milisegundos
    text: str
    translation: Optional[str] = field(default=None)  # Traducción opcional

    @property
    def timestamp_seconds(self) -> float:
        """Retorna el timestamp en segundos."""
        return self.timestamp_ms / 1000.0

    def __repr__(self) -> str:
        minutes = self.timestamp_ms // 60000
        seconds = (self.timestamp_ms % 60000) / 1000
        return f"[{minutes:02d}:{seconds:05.2f}] {self.text}"


@dataclass
class LyricsData:
    """Contiene las letras parseadas y metadatos."""

    lines: list[LyricLine]
    title: Optional[str] = None
    artist: Optional[str] = None
    album: Optional[str] = None
    offset_ms: int = 0  # Offset global en ms
    is_synced: bool = True  # True si tiene timestamps

    @property
    def duration_ms(self) -> int:
        """Duración estimada basada en el último timestamp."""
        if not self.lines:
            return 0
        return self.lines[-1].timestamp_ms

    def get_line_at(self, position_ms: int) -> tuple[int, Optional[LyricLine]]:
        """
        Encuentra la línea que corresponde a una posición temporal.

        Args:
            position_ms: Posición actual en milisegundos

        Returns:
            Tupla (índice, LyricLine) o (-1, None) si no hay línea
        """
        if not self.lines:
            return -1, None

        # Aplicar offset
        adjusted_pos = position_ms - self.offset_ms

        # Buscar la línea cuyo timestamp sea <= posición actual
        result_idx = -1
        for idx, line in enumerate(self.lines):
            if line.timestamp_ms <= adjusted_pos:
                result_idx = idx
            else:
                break

        if result_idx >= 0:
            return result_idx, self.lines[result_idx]
        return -1, None

    def get_context_lines(
        self, current_idx: int, before: int = 2, after: int = 2
    ) -> list[tuple[int, LyricLine]]:
        """
        Obtiene líneas de contexto alrededor de la línea actual.

        Args:
            current_idx: Índice de la línea actual
            before: Cantidad de líneas anteriores
            after: Cantidad de líneas siguientes

        Returns:
            Lista de tuplas (índice_relativo, LyricLine)
            donde índice_relativo es 0 para la actual, negativo para anteriores, positivo para siguientes
        """
        result = []

        start_idx = max(0, current_idx - before)
        end_idx = min(len(self.lines), current_idx + after + 1)

        for idx in range(start_idx, end_idx):
            relative_idx = idx - current_idx
            result.append((relative_idx, self.lines[idx]))

        return result


class LRCParser:
    """Parser para archivos/strings en formato LRC."""

    # Regex para líneas con timestamp: [mm:ss.xx] o [mm:ss:xx] o [mm:ss]
    TIMESTAMP_PATTERN = re.compile(r"\[(\d{1,2}):(\d{2})(?:[.:](\d{1,3}))?\]")

    # Regex para tags de metadatos: [tag:valor]
    TAG_PATTERN = re.compile(r"\[([a-zA-Z]+):([^\]]*)\]")

    @classmethod
    def parse(cls, lrc_content: str) -> LyricsData:
        """
        Parsea contenido LRC a estructura de datos.

        Args:
            lrc_content: String con contenido en formato LRC

        Returns:
            LyricsData con las líneas parseadas
        """
        lines: list[LyricLine] = []
        title = None
        artist = None
        album = None
        offset_ms = 0

        for line in lrc_content.strip().split("\n"):
            line = line.strip()
            if not line:
                continue

            # Intentar parsear como tag de metadatos
            tag_match = cls.TAG_PATTERN.match(line)
            if tag_match and not cls.TIMESTAMP_PATTERN.match(line):
                tag_name = tag_match.group(1).lower()
                tag_value = tag_match.group(2).strip()

                if tag_name == "ti":
                    title = tag_value
                elif tag_name == "ar":
                    artist = tag_value
                elif tag_name == "al":
                    album = tag_value
                elif tag_name == "offset":
                    try:
                        offset_ms = int(tag_value)
                    except ValueError:
                        pass
                continue

            # Buscar todos los timestamps en la línea
            # (algunas líneas pueden tener múltiples: [00:12.00][00:24.00] Texto)
            timestamps = []
            last_end = 0

            for match in cls.TIMESTAMP_PATTERN.finditer(line):
                minutes = int(match.group(1))
                seconds = int(match.group(2))

                # Milisegundos (puede ser .xx o .xxx)
                ms_str = match.group(3) or "0"
                if len(ms_str) == 2:
                    milliseconds = int(ms_str) * 10
                else:
                    milliseconds = int(ms_str)

                total_ms = (minutes * 60 + seconds) * 1000 + milliseconds
                timestamps.append(total_ms)
                last_end = match.end()

            # Extraer el texto después de los timestamps
            text = line[last_end:].strip()

            # Crear una línea por cada timestamp
            for ts in timestamps:
                if text:  # Solo agregar si hay texto
                    lines.append(LyricLine(timestamp_ms=ts, text=text))

        # Ordenar por timestamp
        lines.sort(key=lambda x: x.timestamp_ms)

        # Determinar si está sincronizado
        is_synced = len(lines) > 0 and any(line.timestamp_ms > 0 for line in lines)

        return LyricsData(
            lines=lines,
            title=title,
            artist=artist,
            album=album,
            offset_ms=offset_ms,
            is_synced=is_synced,
        )

    @classmethod
    def parse_plain_lyrics(cls, plain_text: str, duration_ms: int = 0) -> LyricsData:
        """
        Convierte letra plana (sin timestamps) a LyricsData con timestamps estimados.

        Args:
            plain_text: Letra sin formato LRC
            duration_ms: Duración total de la canción en ms (para estimar timestamps)

        Returns:
            LyricsData con timestamps distribuidos uniformemente
        """
        lines_text = [
            line.strip() for line in plain_text.strip().split("\n") if line.strip()
        ]

        if not lines_text:
            return LyricsData(lines=[], is_synced=False)

        lines: list[LyricLine] = []

        if duration_ms > 0 and len(lines_text) > 1:
            # Distribuir timestamps uniformemente
            # Dejar un margen al inicio y al final
            start_offset = 5000  # 5 segundos de margen inicial
            end_offset = 10000  # 10 segundos de margen final

            usable_duration = max(
                duration_ms - start_offset - end_offset, duration_ms // 2
            )
            interval = usable_duration // len(lines_text)

            for idx, text in enumerate(lines_text):
                timestamp = start_offset + (idx * interval)
                lines.append(LyricLine(timestamp_ms=timestamp, text=text))
        else:
            # Sin duración conocida, asignar timestamps cada 4 segundos
            for idx, text in enumerate(lines_text):
                timestamp = idx * 4000
                lines.append(LyricLine(timestamp_ms=timestamp, text=text))

        return LyricsData(lines=lines, is_synced=False)

    @classmethod
    def to_lrc(cls, lyrics_data: LyricsData) -> str:
        """
        Convierte LyricsData de vuelta a formato LRC string.

        Args:
            lyrics_data: Datos de letras a convertir

        Returns:
            String en formato LRC
        """
        result = []

        # Agregar metadatos
        if lyrics_data.title:
            result.append(f"[ti:{lyrics_data.title}]")
        if lyrics_data.artist:
            result.append(f"[ar:{lyrics_data.artist}]")
        if lyrics_data.album:
            result.append(f"[al:{lyrics_data.album}]")
        if lyrics_data.offset_ms != 0:
            result.append(f"[offset:{lyrics_data.offset_ms}]")

        if result:
            result.append("")  # Línea vacía después de metadatos

        # Agregar líneas
        for line in lyrics_data.lines:
            result.append(str(line))

        return "\n".join(result)


# Ejemplo de uso
if __name__ == "__main__":
    sample_lrc = """
[ti:Sample Song]
[ar:Sample Artist]
[al:Sample Album]
[offset:+500]

[00:12.00]This is the first line
[00:17.20]This is the second line
[00:22.50]And this is the third line
[00:28.00]The song continues here
[00:33.45]Almost at the end
[00:38.90]Final line of the song
    """

    parser = LRCParser()
    data = parser.parse(sample_lrc)

    print(f"Title: {data.title}")
    print(f"Artist: {data.artist}")
    print(f"Album: {data.album}")
    print(f"Offset: {data.offset_ms}ms")
    print(f"Is Synced: {data.is_synced}")
    print(f"\nLines ({len(data.lines)}):")
    for line in data.lines:
        print(f"  {line}")

    # Test get_line_at
    print("\n--- Test get_line_at ---")
    for test_pos in [0, 15000, 20000, 35000]:
        idx, line = data.get_line_at(test_pos)
        print(f"Position {test_pos}ms -> idx={idx}, line={line}")
