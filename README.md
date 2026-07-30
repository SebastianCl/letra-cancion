# Letra Canción 🎵

Sistema de letras sincronizadas para **Qobuz** en Windows.

Detecta automáticamente la canción que estás reproduciendo en Qobuz, busca la letra correspondiente y la muestra en una ventana inmersiva sincronizada con la música. Traduce automáticamente letras en inglés o italiano al español; al activarla manualmente, también traduce letras en español al inglés.

## ✨ Características

- **Detección automática** de la canción via Windows Media Session (SMTC), con fallback por título de ventana
- **Letras sincronizadas** desde LRCLIB y NetEase Music
- **Traducción automática** inglés→español e italiano→español, con español→inglés al activarla manualmente (con caché local)
- **Ventana inmersiva responsive** con traducciones apiladas y progreso de reproducción
- **Modo “Siempre encima” opcional**, desactivado por defecto
- **Hotkeys globales** para controlar desde cualquier aplicación
- **Panel de configuración** para personalizar apariencia y comportamiento
- **Ayuda integrada** con referencia rápida de atajos
- **Fallback inteligente**: si no hay letra sincronizada, muestra scroll estimado
- **Biblioteca local y funcionamiento offline**: cada letra encontrada se
  guarda en `~/.lyrics-cache/library/` y se reutiliza aunque no haya conexión
  a Internet
- **Gestor de letras** para buscar cualquier canción, previsualizar resultados y guardar versiones personales
- **Editor LRC** con pegado, importación, tiempos manuales y captura en vivo desde Qobuz
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

Para instalar las dependencias de desarrollo y ejecutar las pruebas:

```powershell
pip install -r requirements-dev.txt
python -m pytest
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
| `F8` | Capturar el tiempo actual en el editor de letras |

## 📝 Gestionar letras

Abre **Gestionar letras** desde el botón `♫` de la ventana principal o desde
el menú del icono de la bandeja.

- Busca por artista y título en la biblioteca local, LRCLIB y NetEase.
- Previsualiza una coincidencia antes de aplicarla, guardarla o editarla.
- Elimina una versión local desde su previsualización, con confirmación.
- Agrega una letra pegando texto plano, contenido LRC o importando un archivo
  `.lrc`.
- Edita el texto y los tiempos en formato `mm:ss.xx`.
- Mientras el editor coincida con la canción actual, usa **F8** o
  **Usar tiempo actual** para marcar la fila seleccionada y avanzar a la
  siguiente.

Las versiones personales tienen prioridad sobre las fuentes en línea y se
guardan en `~/.lyrics-cache/library/`. No se eliminan al limpiar el caché de
letras descargadas.

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
│   ├── lyrics_library.py    # Biblioteca local de letras personales
│   ├── translation_service.py # Detección y traducción de letras
│   ├── sync_engine.py       # Motor de sincronización
│   ├── lrc_parser.py        # Parser formato LRC
│   ├── hotkeys.py           # Hotkeys globales
│   ├── settings.py          # Configuración persistente
│   └── ui/
│       ├── __init__.py
│       ├── overlay.py       # Ventana inmersiva de letras
│       ├── lyrics_manager.py # Búsqueda, previsualización y editor
│       ├── brand.py         # Identidad vectorial compartida
│       ├── tray.py          # Icono en bandeja
│       └── settings.py      # Diálogos de config y ayuda
├── assets/
├── app.spec                    # Configuración de PyInstaller
├── launcher.py                 # Entrada del ejecutable empaquetado
├── requirements.txt
├── requirements-dev.txt
├── build.ps1
├── run-letra-cancion.ps1
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

Las letras traducidas, las respuestas reutilizables y la biblioteca local se
almacenan en `~/.lyrics-cache/`; no deben confirmarse en Git. Las letras se
guardan exclusivamente en `~/.lyrics-cache/library/`.

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

Instala primero las dependencias de desarrollo y ejecuta la suite automatizada con:

```powershell
python -m pytest
```

Las pruebas simulan las APIs externas y los servicios de Windows.
