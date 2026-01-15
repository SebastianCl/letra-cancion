# Letra Canción 🎵

Sistema de letras sincronizadas para **Qobuz** en Windows.

Detecta automáticamente la canción que estás reproduciendo en Qobuz, busca la letra correspondiente y la muestra en un overlay transparente sincronizado con la música.

## ✨ Características

- **Detección automática** de la canción via Windows Media Session (SMTC)
- **Letras sincronizadas** desde LRCLIB y NetEase Music
- **Overlay transparente** siempre visible con la letra actual resaltada
- **Hotkeys globales** para controlar desde cualquier aplicación
- **Fallback inteligente**: si no hay letra sincronizada, muestra scroll estimado
- **Caché local** para evitar búsquedas repetidas

## 🚀 Instalación

### Requisitos

- Windows 10/11
- Python 3.10+
- Qobuz Desktop App

### Pasos

1. Clonar o descargar el proyecto

2. Crear entorno virtual:
```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
```

3. Instalar dependencias:
```powershell
pip install -r requirements.txt
```

4. Ejecutar:
```powershell
python -m src.main
```

## ⌨️ Hotkeys

| Combinación | Acción |
|-------------|--------|
| `Ctrl+Shift+L` | Mostrar/ocultar overlay |
| `Ctrl+Alt+↑` | Aumentar offset (+500ms) |
| `Ctrl+Alt+↓` | Disminuir offset (-500ms) |
| `Ctrl+Alt+R` | Resetear offset |

## 📁 Estructura del Proyecto

```
letra-cancion/
├── src/
│   ├── __init__.py
│   ├── main.py              # Aplicación principal
│   ├── detector.py          # Detección via SMTC
│   ├── lyrics_service.py    # Búsqueda de letras
│   ├── sync_engine.py       # Motor de sincronización
│   ├── lrc_parser.py        # Parser formato LRC
│   ├── hotkeys.py           # Hotkeys globales
│   └── ui/
│       ├── __init__.py
│       ├── overlay.py       # Overlay transparente
│       └── tray.py          # Icono en bandeja
├── assets/
├── requirements.txt
└── README.md
```

## 🔧 Configuración

El overlay aparece centrado en la parte inferior de la pantalla. Puedes moverlo con `Ctrl+Shift+M`.

### Ajuste de sincronización

Si la letra aparece adelantada o atrasada:
- `Ctrl+Alt+↑` para retrasar la letra
- `Ctrl+Alt+↓` para adelantar la letra

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

### El overlay no aparece
- Presiona `Ctrl+Shift+L` para mostrarlo
- Verifica que no esté fuera de la pantalla (usa `Ctrl+Shift+M` para moverlo)

## 📄 Licencia

Proyecto de uso personal. Las letras pertenecen a sus respectivos autores.
