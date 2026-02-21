"""
Motor de sincronización de letras.

Gestiona la sincronización entre la posición de reproducción
y las líneas de letra, con soporte para:
- Letras sincronizadas (timestamps precisos)
- Letras planas (scroll estimado por duración)
- Ajuste de offset manual
- Detección de pausas/seeks
"""

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Callable, Optional

from PyQt6.QtCore import QTimer

from .lrc_parser import LyricsData, LyricLine
from .window_detector import WindowTitleDetector, PlayerState, PlaybackInfo, TrackInfo

logger = logging.getLogger(__name__)


class SyncMode(Enum):
    """Modo de sincronización."""

    SYNCED = "synced"  # Letras con timestamps
    ESTIMATED = "estimated"  # Scroll estimado por duración
    MANUAL = "manual"  # Sin auto-scroll


@dataclass
class SyncState:
    """Estado actual de la sincronización."""

    mode: SyncMode
    current_line_index: int
    current_line: Optional[LyricLine]
    position_ms: int
    is_playing: bool
    offset_ms: int


# Type alias para callbacks
OnSyncUpdateCallback = Callable[[SyncState], None]
OnLyricsLoadedCallback = Callable[[LyricsData], None]


class SyncEngine:
    """
    Motor de sincronización de letras con la reproducción.

    Coordina el detector con las letras cargadas para
    determinar qué línea mostrar en cada momento.
    """

    # Límites de offset ajustable
    MIN_OFFSET_MS = -10000  # -10 segundos
    MAX_OFFSET_MS = 10000  # +10 segundos
    OFFSET_STEP_MS = 500  # Paso de ajuste: 500ms

    def __init__(self, detector: WindowTitleDetector):
        """
        Inicializa el motor de sincronización.

        Args:
            detector: Instancia de detector inicializada.
        """
        self.detector = detector

        # Estado de letras
        self._lyrics: Optional[LyricsData] = None
        self._mode: SyncMode = SyncMode.SYNCED

        # Estado de sincronización
        self._current_line_index: int = -1
        self._offset_ms: int = 0
        self._previous_offset_ms: int = 0  # H3: para "deshacer offset"

        # Control de loop - usar QTimer para no bloquear con asyncio
        self._running: bool = False
        self._paused: bool = False  # Estado de pausa de reproducción
        self._update_interval_ms: int = 50  # 50ms para suavidad
        self._sync_timer: Optional[QTimer] = None

        # Callbacks
        self._on_sync_update: list[OnSyncUpdateCallback] = []
        self._on_lyrics_loaded: list[OnLyricsLoadedCallback] = []

        # Para modo estimado
        self._estimated_line_duration_ms: int = 0

        # Lock temporal para ajustes manuales
        # Cuando el usuario ajusta la sincronización (clic, offset, seek),
        # se activa un lock que impide que el auto-sync sobreescriba
        # el ajuste durante un periodo configurable.
        self._manual_lock_active: bool = False
        self._manual_lock_timer: Optional[QTimer] = None
        self._manual_lock_duration_ms: int = 3000  # 3 segundos por defecto

    def set_lyrics(self, lyrics: Optional[LyricsData], duration_ms: int = 0) -> None:
        """
        Establece las letras actuales.

        Args:
            lyrics: Datos de letras, o None para limpiar.
            duration_ms: Duración de la canción (para modo estimado).
        """
        self._lyrics = lyrics
        self._current_line_index = -1

        if lyrics is None:
            self._mode = SyncMode.MANUAL
            return

        # Determinar modo basado en si tiene sincronización
        if lyrics.is_synced:
            self._mode = SyncMode.SYNCED
            logger.info("Modo de sincronización: SYNCED (timestamps)")
        else:
            self._mode = SyncMode.ESTIMATED
            # Calcular duración por línea para scroll estimado
            if lyrics.lines and duration_ms > 0:
                # Dejar margen al inicio y final
                usable_duration = int(duration_ms * 0.9)  # 90% de la duración
                self._estimated_line_duration_ms = usable_duration // len(lyrics.lines)
            else:
                self._estimated_line_duration_ms = 4000  # 4 segundos por defecto
            logger.info(
                f"Modo de sincronización: ESTIMATED ({self._estimated_line_duration_ms}ms/línea)"
            )

        # Aplicar offset almacenado en las letras
        if lyrics.offset_ms != 0:
            self._offset_ms = lyrics.offset_ms

        # Notificar que se cargaron letras
        for callback in self._on_lyrics_loaded:
            try:
                callback(lyrics)
            except Exception as e:
                logger.error(f"Error en callback on_lyrics_loaded: {e}")

    def clear_lyrics(self) -> None:
        """Limpia las letras actuales."""
        self.set_lyrics(None)

    @property
    def has_lyrics(self) -> bool:
        """Retorna True si hay letras cargadas."""
        return self._lyrics is not None and len(self._lyrics.lines) > 0

    @property
    def lyrics(self) -> Optional[LyricsData]:
        """Retorna las letras actuales."""
        return self._lyrics

    @property
    def sync_mode(self) -> SyncMode:
        """Retorna el modo de sincronización actual."""
        return self._mode

    @property
    def offset_ms(self) -> int:
        """Retorna el offset actual en ms."""
        return self._offset_ms

    def adjust_offset(self, delta_ms: int) -> int:
        """
        Ajusta el offset de sincronización.

        Args:
            delta_ms: Cambio en milisegundos (positivo = retrasar letras)

        Returns:
            Nuevo valor de offset.
        """
        self._previous_offset_ms = self._offset_ms  # H3: guardar para undo
        new_offset = self._offset_ms + delta_ms
        new_offset = max(self.MIN_OFFSET_MS, min(self.MAX_OFFSET_MS, new_offset))
        self._offset_ms = new_offset
        logger.info(f"Offset ajustado: {self._offset_ms}ms")

        # Activar lock temporal para que el auto-sync no sobreescriba inmediatamente
        self._activate_manual_lock()

        # Forzar recálculo inmediato con el nuevo offset
        self._force_sync_update()

        return self._offset_ms

    def reset_offset(self) -> None:
        """Reinicia el offset a 0."""
        self._previous_offset_ms = self._offset_ms  # H3: guardar para undo
        self._offset_ms = 0
        logger.info("Offset reiniciado a 0")

    def undo_offset(self) -> int:
        """
        Restaura el offset anterior (H3: deshacer).

        Returns:
            Valor de offset restaurado.
        """
        self._offset_ms, self._previous_offset_ms = (
            self._previous_offset_ms,
            self._offset_ms,
        )
        logger.info(f"Offset restaurado: {self._offset_ms}ms")
        return self._offset_ms

    def _get_line_at_position(
        self, position_ms: int
    ) -> tuple[int, Optional[LyricLine]]:
        """
        Determina qué línea corresponde a una posición temporal.

        Args:
            position_ms: Posición en milisegundos.

        Returns:
            Tupla (índice, línea) o (-1, None) si no hay línea.
        """
        if self._lyrics is None or not self._lyrics.lines:
            return -1, None

        # Aplicar offset
        adjusted_pos = position_ms + self._offset_ms

        if self._mode == SyncMode.SYNCED:
            # Usar timestamps de las letras (offset ya incluido en adjusted_pos)
            return self._lyrics.get_line_at(adjusted_pos)

        elif self._mode == SyncMode.ESTIMATED:
            # Calcular línea basada en tiempo estimado
            if self._estimated_line_duration_ms <= 0:
                return -1, None

            # Margen inicial fijo de 5 segundos
            effective_pos = max(0, adjusted_pos - 5000)

            line_idx = effective_pos // self._estimated_line_duration_ms
            line_idx = min(line_idx, len(self._lyrics.lines) - 1)
            line_idx = max(0, line_idx)

            return int(line_idx), self._lyrics.lines[int(line_idx)]

        return -1, None

    def _update_sync(self) -> None:
        """Actualiza el estado de sincronización."""
        if not self.has_lyrics:
            return

        # Si el lock manual está activo, no recalcular desde el detector
        # para respetar el ajuste del usuario.
        if self._manual_lock_active:
            return

        # Obtener posición interpolada del detector
        position_ms = self.detector.get_interpolated_position_ms()
        is_playing = self.detector.is_playing

        # Determinar línea actual
        line_idx, current_line = self._get_line_at_position(position_ms)

        # Solo notificar si cambió la línea
        if line_idx != self._current_line_index:
            # Protección anti-regresión: evitar que la línea retroceda brevemente
            # cuando SMTC reporta una posición ligeramente menor que la interpolada.
            # Solo bloquear retrocesos de 1 línea — retrocesos mayores (seek) sí se aplican.
            if (
                line_idx >= 0
                and self._current_line_index >= 0
                and line_idx == self._current_line_index - 1
                and is_playing
            ):
                # Retroceso de 1 línea durante reproducción = probable micro-corrección SMTC
                # Ignorar para evitar flicker
                return

            self._current_line_index = line_idx

            # Crear estado de sincronización
            state = SyncState(
                mode=self._mode,
                current_line_index=line_idx,
                current_line=current_line,
                position_ms=position_ms,
                is_playing=is_playing,
                offset_ms=self._offset_ms,
            )

            # Notificar a los listeners
            self._notify_sync_update(state)

    def _force_sync_update(self) -> None:
        """
        Fuerza una actualización de sincronización inmediata.

        Se usa después de un ajuste manual para reflejar el cambio
        sin esperar al próximo tick del timer.
        """
        if not self.has_lyrics:
            return

        position_ms = self.detector.get_interpolated_position_ms()
        is_playing = self.detector.is_playing
        line_idx, current_line = self._get_line_at_position(position_ms)

        self._current_line_index = line_idx

        state = SyncState(
            mode=self._mode,
            current_line_index=line_idx,
            current_line=current_line,
            position_ms=position_ms,
            is_playing=is_playing,
            offset_ms=self._offset_ms,
        )

        self._notify_sync_update(state)

    def _notify_sync_update(self, state: SyncState) -> None:
        """Notifica a los listeners de cambio en sincronización."""
        for callback in self._on_sync_update:
            try:
                callback(state)
            except Exception as e:
                logger.error(f"Error en callback on_sync_update: {e}")

    # --- Callbacks públicos ---

    def on_sync_update(self, callback: OnSyncUpdateCallback) -> None:
        """Registra callback para actualizaciones de sincronización."""
        self._on_sync_update.append(callback)

    def on_lyrics_loaded(self, callback: OnLyricsLoadedCallback) -> None:
        """Registra callback para cuando se cargan letras."""
        self._on_lyrics_loaded.append(callback)

    # --- Control del loop ---

    def start(self) -> None:
        """Inicia el loop de sincronización usando QTimer (no bloquea durante arrastre de UI)."""
        if self._running:
            return

        self._running = True

        # Crear QTimer para actualizaciones - esto funciona dentro del event loop de Qt
        # y no se bloquea cuando se arrastra la ventana
        self._sync_timer = QTimer()
        self._sync_timer.timeout.connect(self._on_timer_tick)
        self._sync_timer.start(self._update_interval_ms)

        logger.info("SyncEngine iniciado")

    def _on_timer_tick(self) -> None:
        """Callback del timer - actualiza la sincronización."""
        if not self._running or self._paused:
            return
        try:
            self._update_sync()
        except Exception as e:
            logger.error(f"Error en loop de sincronización: {e}")

    def pause(self) -> None:
        """Pausa la sincronización (cuando la música está pausada)."""
        if not self._paused:
            self._paused = True
            logger.debug("Sincronización pausada")

    def resume(self) -> None:
        """Reanuda la sincronización (cuando la música continúa)."""
        if self._paused:
            self._paused = False
            logger.debug("Sincronización reanudada")

    @property
    def is_paused(self) -> bool:
        """Retorna True si la sincronización está pausada."""
        return self._paused

    def stop(self) -> None:
        """Detiene el loop de sincronización."""
        self._running = False
        if self._sync_timer:
            self._sync_timer.stop()
            self._sync_timer = None
        if self._manual_lock_timer:
            self._manual_lock_timer.stop()
            self._manual_lock_timer = None
        self._manual_lock_active = False
        logger.info("SyncEngine detenido")

    @property
    def is_running(self) -> bool:
        """Retorna True si el loop está corriendo."""
        return self._running

    # --- Lock temporal para ajustes manuales ---

    def _activate_manual_lock(self) -> None:
        """
        Activa el lock temporal que impide que el auto-sync
        sobreescriba el ajuste manual del usuario.

        Cada invocación reinicia el timer. Al expirar el timer,
        la sincronización automática retoma el control.
        """
        self._manual_lock_active = True

        if self._manual_lock_timer is None:
            self._manual_lock_timer = QTimer()
            self._manual_lock_timer.setSingleShot(True)
            self._manual_lock_timer.timeout.connect(self._deactivate_manual_lock)

        # Reiniciar timer (permite que interacciones sucesivas extiendan el lock)
        self._manual_lock_timer.start(self._manual_lock_duration_ms)
        logger.debug(f"Lock manual activado ({self._manual_lock_duration_ms}ms)")

    def _deactivate_manual_lock(self) -> None:
        """
        Desactiva el lock temporal y permite que la sincronización
        automática retome el control.
        """
        self._manual_lock_active = False
        logger.debug("Lock manual desactivado — sincronización automática retomada")

        # Forzar una actualización inmediata para que la transición sea suave
        if self._running and not self._paused:
            self._force_sync_update()

    @property
    def is_manual_lock_active(self) -> bool:
        """Retorna True si el lock manual está activo."""
        return self._manual_lock_active

    def apply_manual_sync(self, target_time_ms: int) -> None:
        """
        Aplica una sincronización manual: ajusta el offset para que
        la posición actual del detector apunte a target_time_ms en la letra.

        Usado cuando el usuario hace clic en una línea o usa el diálogo
        de sincronización manual.

        Args:
            target_time_ms: Timestamp de la letra al que el usuario quiere sincronizar.
        """
        if not self.has_lyrics:
            return

        current_pos = self.detector.get_interpolated_position_ms()
        # Calcular el offset necesario: queremos que adjusted_pos = current_pos + offset
        # corresponda a target_time_ms en la letra
        needed_offset = target_time_ms - current_pos

        # Aplicar con clampeo
        self._previous_offset_ms = self._offset_ms
        self._offset_ms = max(
            self.MIN_OFFSET_MS, min(self.MAX_OFFSET_MS, needed_offset)
        )
        logger.info(
            f"Sincronización manual: offset={self._offset_ms}ms "
            f"(target={target_time_ms}ms, pos={current_pos}ms)"
        )

        # Activar lock y forzar actualización
        self._activate_manual_lock()
        self._force_sync_update()

    # --- Métodos de utilidad ---

    def get_context_lines(
        self, before: int = 2, after: int = 2
    ) -> list[tuple[int, LyricLine]]:
        """
        Obtiene líneas de contexto alrededor de la línea actual.

        Args:
            before: Cantidad de líneas anteriores
            after: Cantidad de líneas siguientes

        Returns:
            Lista de tuplas (índice_relativo, LyricLine)
        """
        if self._lyrics is None or self._current_line_index < 0:
            return []

        return self._lyrics.get_context_lines(self._current_line_index, before, after)

    def seek_to_line(self, line_index: int) -> None:
        """
        Salta a una línea específica (para UI interactiva).

        Activa el lock temporal para que el auto-sync no sobreescriba
        inmediatamente la línea seleccionada por el usuario.

        Args:
            line_index: Índice de la línea objetivo.
        """
        if self._lyrics is None or not self._lyrics.lines:
            return

        if 0 <= line_index < len(self._lyrics.lines):
            self._current_line_index = line_index
            line = self._lyrics.lines[line_index]

            state = SyncState(
                mode=self._mode,
                current_line_index=line_index,
                current_line=line,
                position_ms=line.timestamp_ms,
                is_playing=self.detector.is_playing,
                offset_ms=self._offset_ms,
            )

            self._notify_sync_update(state)

            # Activar lock para que el ajuste persista
            self._activate_manual_lock()

    def get_progress(self) -> tuple[int, int]:
        """
        Obtiene el progreso actual (línea actual / total).

        Returns:
            Tupla (línea_actual, total_líneas)
        """
        if self._lyrics is None:
            return 0, 0

        return max(0, self._current_line_index + 1), len(self._lyrics.lines)


# --- Ejemplo de uso ---
async def main():
    """Ejemplo de uso del SyncEngine."""
    from .window_detector import WindowTitleDetector
    from .lrc_parser import LRCParser

    logging.basicConfig(level=logging.DEBUG)

    # Inicializar detector
    detector = WindowTitleDetector()
    if not await detector.initialize():
        print("Error inicializando detector")
        return

    # Crear motor de sincronización
    engine = SyncEngine(detector)

    # Registrar callback de sincronización
    def on_sync(state: SyncState):
        if state.current_line:
            print(
                f"\r[{state.mode.value}] Línea {state.current_line_index}: {state.current_line.text[:50]:<50}",
                end="",
            )

    engine.on_sync_update(on_sync)

    # Cargar letras de ejemplo
    sample_lrc = """
[00:12.00]This is the first line
[00:17.20]This is the second line
[00:22.50]And this is the third line
[00:28.00]The song continues here
[00:33.45]Almost at the end
[00:38.90]Final line of the song
    """

    lyrics = LRCParser.parse(sample_lrc)
    engine.set_lyrics(lyrics, duration_ms=60000)

    # Iniciar loop
    print("Iniciando sincronización (Ctrl+C para salir)...")
    try:
        await engine.start()
    except KeyboardInterrupt:
        pass
    finally:
        engine.stop()
        await detector.close()

    print("\nSync engine detenido.")


if __name__ == "__main__":
    asyncio.run(main())
