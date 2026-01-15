"""
Gestor de hotkeys globales usando la librería 'keyboard'.

Más simple y confiable en Windows que pynput.

Hotkeys configurados:
- Ctrl+Shift+L: Toggle visibilidad del overlay
- Ctrl+Alt+Up: Aumentar offset (+500ms)
- Ctrl+Alt+Down: Disminuir offset (-500ms)
- Ctrl+Alt+R: Resetear offset a 0
- Ctrl+Shift+M: Modo mover overlay (drag)
"""

import logging
from enum import Enum
from typing import Callable, Optional
from dataclasses import dataclass

try:
    import keyboard
    KEYBOARD_AVAILABLE = True
except ImportError:
    KEYBOARD_AVAILABLE = False
    print("WARNING: 'keyboard' library not available. Install with: pip install keyboard")

logger = logging.getLogger(__name__)


class HotkeyAction(Enum):
    """Acciones disponibles via hotkeys."""
    TOGGLE_OVERLAY = "toggle_overlay"
    OFFSET_INCREASE = "offset_increase"
    OFFSET_DECREASE = "offset_decrease"
    OFFSET_RESET = "offset_reset"


@dataclass
class HotkeyConfig:
    """Configuración de un hotkey."""
    action: HotkeyAction
    keys: str  # Formato: "ctrl+shift+l"
    description: str


# Tipo para callbacks de acciones
HotkeyCallback = Callable[[HotkeyAction], None]


class HotkeyManager:
    """
    Gestor de hotkeys globales usando la librería keyboard.
    
    Más simple y confiable que pynput en Windows.
    Requiere ejecutar como administrador para algunos hotkeys.
    """
    
    # Hotkeys por defecto
    DEFAULT_HOTKEYS = [
        HotkeyConfig(HotkeyAction.TOGGLE_OVERLAY, "ctrl+shift+l", "Mostrar/ocultar overlay"),
        HotkeyConfig(HotkeyAction.OFFSET_INCREASE, "ctrl+alt+up", "Aumentar offset (+500ms)"),
        HotkeyConfig(HotkeyAction.OFFSET_DECREASE, "ctrl+alt+down", "Disminuir offset (-500ms)"),
        HotkeyConfig(HotkeyAction.OFFSET_RESET, "ctrl+alt+r", "Resetear offset"),
    ]
    
    def __init__(self):
        """Inicializa el gestor de hotkeys."""
        self._callbacks: list[HotkeyCallback] = []
        self._hotkeys: list[HotkeyConfig] = self.DEFAULT_HOTKEYS.copy()
        self._enabled: bool = True
        self._registered_hooks: list = []
    
    def _create_handler(self, action: HotkeyAction):
        """Crea un handler para una acción específica."""
        def handler():
            if self._enabled:
                logger.info(f"Hotkey activado: {action.value}")
                self._trigger_action(action)
        return handler
    
    def _trigger_action(self, action: HotkeyAction) -> None:
        """Dispara los callbacks para una acción."""
        for callback in self._callbacks:
            try:
                callback(action)
            except Exception as e:
                logger.error(f"Error en callback de hotkey: {e}")
    
    # --- API Pública ---
    
    def on_hotkey(self, callback: HotkeyCallback) -> None:
        """
        Registra un callback para cuando se activa un hotkey.
        
        Args:
            callback: Función que recibe HotkeyAction
        """
        self._callbacks.append(callback)
    
    def start(self) -> None:
        """Inicia el listener de hotkeys."""
        if not KEYBOARD_AVAILABLE:
            logger.error("Librería 'keyboard' no disponible")
            return
        
        # Registrar cada hotkey
        for hk in self._hotkeys:
            try:
                hook = keyboard.add_hotkey(
                    hk.keys,
                    self._create_handler(hk.action),
                    suppress=False,  # No bloquear la tecla para otras apps
                    trigger_on_release=False
                )
                self._registered_hooks.append(hook)
                logger.debug(f"Registrado: {hk.keys} -> {hk.action.value}")
            except Exception as e:
                logger.error(f"Error registrando hotkey {hk.keys}: {e}")
        
        logger.info("HotkeyManager iniciado")
        
        # Mostrar hotkeys disponibles
        print("\n📌 Hotkeys disponibles:")
        for hk in self._hotkeys:
            keys_display = hk.keys.replace('+', '+').upper()
            print(f"   {keys_display}: {hk.description}")
        print()
    
    def stop(self) -> None:
        """Detiene el listener y limpia los hotkeys."""
        if not KEYBOARD_AVAILABLE:
            return
        
        try:
            keyboard.unhook_all_hotkeys()
        except Exception as e:
            logger.warning(f"Error limpiando hotkeys: {e}")
        
        self._registered_hooks.clear()
        logger.info("HotkeyManager detenido")
    
    @property
    def enabled(self) -> bool:
        """Retorna si los hotkeys están habilitados."""
        return self._enabled
    
    @enabled.setter
    def enabled(self, value: bool) -> None:
        """Habilita o deshabilita los hotkeys."""
        self._enabled = value
        logger.info(f"Hotkeys {'habilitados' if value else 'deshabilitados'}")
    
    def get_hotkey_string(self, action: HotkeyAction) -> str:
        """
        Obtiene la representación en string de un hotkey.
        
        Args:
            action: Acción del hotkey
            
        Returns:
            String como "CTRL+SHIFT+L"
        """
        for hk in self._hotkeys:
            if hk.action == action:
                return hk.keys.upper()
        return ""


# --- Test ---
def main():
    """Test del HotkeyManager."""
    import time
    
    logging.basicConfig(level=logging.DEBUG)
    
    if not KEYBOARD_AVAILABLE:
        print("ERROR: Librería keyboard no disponible")
        print("Instalar con: pip install keyboard")
        return
    
    manager = HotkeyManager()
    
    running = True
    
    def on_action(action: HotkeyAction):
        nonlocal running
        print(f"\n🎯 Acción detectada: {action.value}")
        
        if action == HotkeyAction.QUIT_APP:
            print("Saliendo...")
            running = False
    
    manager.on_hotkey(on_action)
    manager.start()
    
    print("\nPresiona los hotkeys configurados (Ctrl+Shift+Q para salir)...")
    print("Esperando 60 segundos o hasta Ctrl+Shift+Q...")
    
    try:
        start_time = time.time()
        while running and (time.time() - start_time) < 60:
            time.sleep(0.1)
    except KeyboardInterrupt:
        print("\nInterrumpido")
    finally:
        manager.stop()
    
    print("HotkeyManager detenido.")


if __name__ == "__main__":
    main()
