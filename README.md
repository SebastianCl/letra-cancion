# Letra Canción 🎵

Sistema de letras sincronizadas para **Qobuz** en Windows.

Detecta automáticamente la canción que estás reproduciendo en Qobuz, busca la letra correspondiente y la muestra en una ventana inmersiva sincronizada con la música. Traduce automáticamente las letras entre inglés y español.

## ✨ Características

- **Detección automática** de la canción via Windows Media Session (SMTC), con fallback por título de ventana
- **Letras sincronizadas** desde LRCLIB y NetEase Music
- **Traducción bidireccional** inglés↔español automática (con caché local)
- **Ventana inmersiva responsive** con traducciones apiladas y progreso de reproducción
- **Modo “Siempre encima” opcional**, desactivado por defecto
- **Hotkeys globales** para controlar desde cualquier aplicación
- **Panel de configuración** para personalizar apariencia y comportamiento
- **Ayuda integrada** con referencia rápida de atajos
- **Fallback inteligente**: si no hay letra sincronizada, muestra scroll estimado
- **Caché local** para evitar búsquedas repetidas
- **Persistencia** de posición, tamaño, estado maximizado y preferencias de ventana

## 🚀 Instalación y ejecución

### Requisitos

- Windows 10/11
- Python 3.10+
- Qobuz Desktop App

La aplicación web de Qobuz no expone la información multimedia necesaria para la detección automática.

### Pasos

1. Clonar o descargar el proyecto

2. Ejecutar (crea venv automáticamente):
```powershell
.\run-letra-cancion.ps1
```

**O manualmente:**
```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m src.main
```

## 📦 Ejecutable distribuible

Para generar una versión empaquetada con PyInstaller, ejecuta:

```powershell
.\build.ps1
```

El ejecutable se crea en `dist\LetraCancion\LetraCancion.exe`.

## ⌨️ Atajos de teclado

| Combinación | Acción |
|-------------|--------|
| `Ctrl+Shift+L` | Mostrar/ocultar la ventana |
| `Ctrl+T` | Activar/desactivar traducción |
| `Ctrl+Alt+↑` | Retrasar letras (si van adelantadas) |
| `Ctrl+Alt+↓` | Adelantar letras (si van atrasadas) |
| `Ctrl+Alt+R` | Resetear sincronización |
| `Ctrl+Shift+Q` | Salir de la aplicación |

## 🖱️ Interacciones del mouse

| Acción | Comportamiento |
|--------|---------------|
| Arrastrar barra superior | Mover la ventana |
| Doble clic en barra superior | Maximizar/restaurar |
| Click izquierdo en línea | Sincronizar reproducción a esa línea |
| Click derecho | Ajustar tiempo de sincronización manualmente |
| Scroll (rueda) | Navegar por la letra manualmente |
| Bordes / esquinas | Redimensionar la ventana |
| Botón cerrar | Ocultar en la bandeja |

## 📁 Estructura del Proyecto

```
letra-cancion/
├── src/
│   ├── __init__.py
│   ├── main.py              # Aplicación principal
│   ├── detector.py          # Detección via SMTC
│   ├── window_detector.py   # Detección por título (fallback)
│   ├── lyrics_service.py    # Búsqueda de letras
│   ├── translation_service.py # Traducción EN↔ES
│   ├── sync_engine.py       # Motor de sincronización
│   ├── lrc_parser.py        # Parser formato LRC
│   ├── hotkeys.py           # Hotkeys globales
│   ├── settings.py          # Configuración persistente
│   └── ui/
│       ├── __init__.py
│       ├── overlay.py       # Ventana inmersiva de letras
│       ├── brand.py         # Identidad vectorial compartida
│       ├── tray.py          # Icono en bandeja
│       └── settings.py      # Diálogos de config y ayuda
├── assets/
├── requirements.txt
├── requirements-dev.txt
└── README.md
```

## 🔧 Configuración

Accede a la configuración desde el menú del tray: **⚙ Configuración**.

Opciones disponibles:
- **Opacidad** de la superficie
- **Tamaño de fuente** del texto, línea activa y traducción
- **Paso de offset** para ajustes de sincronización
- **Timeout de scroll manual** antes de volver a modo automático
- **Traducción automática** activar/desactivar
- **Siempre encima** activar/desactivar

La configuración se guarda automáticamente en `~/.lyrics-cache/settings.json`.

Las letras traducidas y las respuestas reutilizables también se almacenan localmente en `~/.lyrics-cache/`; no deben confirmarse en Git.

### Ajuste de sincronización

Si la letra aparece adelantada o atrasada:
- `Ctrl+Alt+↑` para retrasar la letra (van adelantadas)
- `Ctrl+Alt+↓` para adelantar la letra (van atrasadas)
- `Ctrl+Alt+R` para resetear

También puedes usar el menú del tray → Sincronización, o click derecho en la ventana para ingresar un tiempo exacto.

## 📝 Fuentes de Letras

El sistema usa fuentes abiertas y gratuitas:

1. **LRCLIB** (primario): Base de datos comunitaria de letras sincronizadas
2. **NetEase Music** (fallback): Servicio de música chino con buena cobertura

Si no se encuentra letra sincronizada, se muestra la letra plana con scroll automático estimado.

## ⚠️ Limitaciones

- **Solo Windows**: Usa APIs específicas de Windows para detectar música
- **Requiere Qobuz Desktop**: La app web no expone información al sistema
- **Cobertura de letras**: No todas las canciones tienen letras disponibles
- **Precisión**: La sincronización depende de la calidad de los datos de LRCLIB
- Las consultas de letras y traducción requieren conexión a Internet

## 🔒 Uso Personal

Este proyecto está diseñado para **uso personal**. Las letras se obtienen de fuentes públicas y se cachean localmente para evitar consultas repetidas.

## 🐛 Solución de Problemas

### "No se detecta la música"
- Verifica que Qobuz Desktop esté ejecutándose
- La canción debe estar reproduciéndose (no en pausa)
- Reinicia la aplicación

### "No se encuentran letras"
- Canciones muy nuevas pueden no tener letras aún
- Verifica que el nombre del artista/canción sea correcto en Qobuz
- Prueba con click derecho para sincronizar manualmente

### La ventana no aparece
- Presiona `Ctrl+Shift+L` para mostrarlo
- Verifica que no esté fuera de la pantalla (mueve arrastrando el header)

### Los atajos no funcionan
- La librería `keyboard` debe estar instalada (`pip install keyboard`)
- Algunos atajos pueden requerir ejecutar como administrador

## 📄 Licencia

Proyecto de uso personal. Las letras pertenecen a sus respectivos autores.


## 🧪 Desarrollo y verificación

Comprobación rápida de sintaxis e importaciones:

```powershell
python -m compileall src launcher.py
```

Actualmente no hay una suite automatizada configurada. Para cambios de lógica, añade pruebas específicas en `tests/` con `pytest`, simulando las APIs externas y los servicios de Windows.
