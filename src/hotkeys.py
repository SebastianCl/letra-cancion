"""
Gestor de hotkeys globales.

Captura combinaciones de teclas a nivel de sistema
para controlar la aplicación desde cualquier lugar.

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

from pynput import keyboard
from pynput.keyboard import Key, KeyCode

logger = logging.getLogger(__name__)


class HotkeyAction(Enum):
    """Acciones disponibles via hotkeys."""
    TOGGLE_OVERLAY = "toggle_overlay"
    OFFSET_INCREASE = "offset_increase"
    OFFSET_DECREASE = "offset_decrease"
    OFFSET_RESET = "offset_reset"
    MOVE_OVERLAY = "move_overlay"
    QUIT_APP = "quit_app"


@dataclass
class Hotkey:
    """Representa una combinación de teclas."""
    action: HotkeyAction
    modifiers: frozenset  # Set de modificadores (ctrl, shift, alt)
    key: Optional[KeyCode]  # Tecla principal
    description: str
    
    def matches(self, current_modifiers: set, key: keyboard.Key | keyboard.KeyCode) -> bool:
        """Verifica si la combinación actual coincide con este hotkey."""
        # Verificar modificadores
        if self.modifiers != current_modifiers:
            return False
        
        # Verificar tecla principal
        if self.key is None:
            return True
        
        # Comparar tecla
        if isinstance(key, KeyCode) and isinstance(self.key, KeyCode):
            return key.char == self.key.char if hasattr(key, 'char') and hasattr(self.key, 'char') else key == self.key
        
        return key == self.key


# Tipo para callbacks de acciones
HotkeyCallback = Callable[[HotkeyAction], None]


class HotkeyManager:
    """
    Gestor de hotkeys globales usando pynput.
    
    Captura combinaciones de teclas a nivel de sistema operativo.
    """
    
    # Modificadores reconocidos
    MODIFIER_KEYS = {
        Key.ctrl_l, Key.ctrl_r,
        Key.shift_l, Key.shift_r,
        Key.alt_l, Key.alt_r,
        Key.alt_gr,
        Key.cmd_l, Key.cmd_r,  # Windows key
    }
    
    def __init__(self):
        """Inicializa el gestor de hotkeys."""
        self._listener: Optional[keyboard.Listener] = None
        self._current_modifiers: set = set()
        self._callbacks: list[HotkeyCallback] = []
        self._hotkeys: list[Hotkey] = []
        self._enabled: bool = True
        
        # Configurar hotkeys por defecto
        self._setup_default_hotkeys()
    
    def _setup_default_hotkeys(self) -> None:
        """Configura los hotkeys por defecto."""
        self._hotkeys = [
            # Ctrl+Shift+L: Toggle overlay
            Hotkey(
                action=HotkeyAction.TOGGLE_OVERLAY,
                modifiers=frozenset({'ctrl', 'shift'}),
                key=KeyCode.from_char('l'),
                description="Toggle visibilidad del overlay"
            ),
            # Ctrl+Alt+Up: Aumentar offset
            Hotkey(
                action=HotkeyAction.OFFSET_INCREASE,
                modifiers=frozenset({'ctrl', 'alt'}),
                key=Key.up,
                description="Aumentar offset de sincronización"
            ),
            # Ctrl+Alt+Down: Disminuir offset
            Hotkey(
                action=HotkeyAction.OFFSET_DECREASE,
                modifiers=frozenset({'ctrl', 'alt'}),
                key=Key.down,
                description="Disminuir offset de sincronización"
            ),
            # Ctrl+Alt+R: Resetear offset
            Hotkey(
                action=HotkeyAction.OFFSET_RESET,
                modifiers=frozenset({'ctrl', 'alt'}),
                key=KeyCode.from_char('r'),
                description="Resetear offset a 0"
            ),
            # Ctrl+Shift+M: Modo mover
            Hotkey(
                action=HotkeyAction.MOVE_OVERLAY,
                modifiers=frozenset({'ctrl', 'shift'}),
                key=KeyCode.from_char('m'),
                description="Activar modo mover overlay"
            ),
            # Ctrl+Shift+Q: Salir
            Hotkey(
                action=HotkeyAction.QUIT_APP,
                modifiers=frozenset({'ctrl', 'shift'}),
                key=KeyCode.from_char('q'),
                description="Cerrar aplicación"
            ),
        ]
    
    def _normalize_modifier(self, key: Key) -> Optional[str]:
        """Normaliza una tecla modificadora a string."""
        if key in (Key.ctrl_l, Key.ctrl_r):
            return 'ctrl'
        elif key in (Key.shift_l, Key.shift_r):
            return 'shift'
        elif key in (Key.alt_l, Key.alt_r, Key.alt_gr):
            return 'alt'
        elif key in (Key.cmd_l, Key.cmd_r):
            return 'win'
        return None
    
    def _on_press(self, key: keyboard.Key | keyboard.KeyCode) -> None:
        """Callback cuando se presiona una tecla."""
        if not self._enabled:
            return
        
        # Actualizar modificadores activos
        if key in self.MODIFIER_KEYS:
            modifier = self._normalize_modifier(key)
            if modifier:
                self._current_modifiers.add(modifier)
            return
        
        # Buscar hotkey que coincida
        current_mods = frozenset(self._current_modifiers)
        
        for hotkey in self._hotkeys:
            if hotkey.modifiers == current_mods:
                # Verificar tecla principal
                key_matches = False
                
                if hotkey.key is None:
                    key_matches = True
                elif isinstance(hotkey.key, Key):
                    key_matches = (key == hotkey.key)
                elif isinstance(hotkey.key, KeyCode):
                    if isinstance(key, KeyCode):
                        # Comparar caracteres
                        hotkey_char = hotkey.key.char.lower() if hotkey.key.char else None
                        key_char = key.char.lower() if hasattr(key, 'char') and key.char else None
                        key_matches = (hotkey_char == key_char)
                
                if key_matches:
                    logger.debug(f"Hotkey detectado: {hotkey.action.value}")
                    self._trigger_action(hotkey.action)
                    return
    
    def _on_release(self, key: keyboard.Key | keyboard.KeyCode) -> None:
        """Callback cuando se suelta una tecla."""
        # Actualizar modificadores activos
        if key in self.MODIFIER_KEYS:
            modifier = self._normalize_modifier(key)
            if modifier:
                self._current_modifiers.discard(modifier)
    
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
        if self._listener is not None:
            return
        
        self._listener = keyboard.Listener(
            on_press=self._on_press,
            on_release=self._on_release
        )
        self._listener.start()
        logger.info("HotkeyManager iniciado")
        
        # Log de hotkeys disponibles
        print("\n📌 Hotkeys disponibles:")
        for hotkey in self._hotkeys:
            mods = '+'.join(sorted(hotkey.modifiers)).upper()
            key_str = hotkey.key.char.upper() if isinstance(hotkey.key, KeyCode) and hotkey.key.char else str(hotkey.key).replace('Key.', '').upper()
            print(f"   {mods}+{key_str}: {hotkey.description}")
        print()
    
    def stop(self) -> None:
        """Detiene el listener de hotkeys."""
        if self._listener is not None:
            self._listener.stop()
            self._listener = None
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
    
    def get_hotkey_for_action(self, action: HotkeyAction) -> Optional[Hotkey]:
        """Obtiene el hotkey configurado para una acción."""
        for hotkey in self._hotkeys:
            if hotkey.action == action:
                return hotkey
        return None
    
    def get_hotkey_string(self, action: HotkeyAction) -> str:
        """
        Obtiene la representación en string de un hotkey.
        
        Args:
            action: Acción del hotkey
            
        Returns:
            String como "Ctrl+Shift+L"
        """
        hotkey = self.get_hotkey_for_action(action)
        if hotkey is None:
            return ""
        
        parts = [m.capitalize() for m in sorted(hotkey.modifiers)]
        
        if hotkey.key:
            if isinstance(hotkey.key, KeyCode) and hotkey.key.char:
                parts.append(hotkey.key.char.upper())
            else:
                parts.append(str(hotkey.key).replace('Key.', '').capitalize())
        
        return '+'.join(parts)


# --- Ejemplo de uso ---
def main():
    """Ejemplo de uso del HotkeyManager."""
    import time
    
    logging.basicConfig(level=logging.DEBUG)
    
    manager = HotkeyManager()
    
    def on_action(action: HotkeyAction):
        print(f"\n🎯 Acción detectada: {action.value}")
        
        if action == HotkeyAction.QUIT_APP:
            print("Saliendo...")
            manager.stop()
    
    manager.on_hotkey(on_action)
    manager.start()
    
    print("\nPresiona los hotkeys configurados (Ctrl+Shift+Q para salir)...")
    
    try:
        while manager._listener and manager._listener.is_alive():
            time.sleep(0.1)
    except KeyboardInterrupt:
        pass
    finally:
        manager.stop()
    
    print("HotkeyManager detenido.")


if __name__ == "__main__":
    main()
