# Guía del repositorio

## Estructura del proyecto y organización de módulos

Este repositorio contiene una aplicación de escritorio en Python, exclusiva para Windows, que muestra letras sincronizadas de Qobuz. El código de la aplicación está en `src/`. Usa `src/main.py` como punto de entrada; las clases de datos compartidas están en `src/models.py`. La detección de música, obtención y traducción de letras, sincronización, atajos y configuración persistente se organizan en módulos como `detector.py`, `lyrics_service.py` y `sync_engine.py`. El código de presentación con PyQt6 pertenece en `src/ui/`.

Los scripts de PowerShell de la raíz gestionan el inicio local y el empaquetado. La configuración y las letras almacenadas en caché se guardan fuera del repositorio, en `~/.lyrics-cache/`. No confirmes en Git datos de caché ni los directorios `.venv/`, `build/` o `dist/`.

## Comandos de compilación, pruebas y desarrollo

- `.\run-letra-cancion.ps1` crea `.venv`, instala las dependencias cuando es necesario e inicia la aplicación.
- `python -m src.main` ejecuta la aplicación desde un entorno activado.
- `pip install -r requirements.txt` instala las dependencias de ejecución.
- `python -m compileall src launcher.py` realiza una comprobación rápida de sintaxis y compilación de importaciones.
- `.\build.ps1` empaqueta la aplicación con PyInstaller. Requiere `app.spec` y genera `dist\LetraCancion\`.

El desarrollo y la verificación de la interfaz requieren Windows 10/11; la detección integral también necesita la aplicación de escritorio de Qobuz.

## Estilo de código y convenciones de nombres

Sigue PEP 8 con sangría de cuatro espacios. Usa `snake_case` para módulos, funciones, variables y callbacks; `PascalCase` para clases y dataclasses; y guion bajo inicial para ayudantes internos. Conserva las anotaciones de tipo, especialmente para valores opcionales, callbacks y límites asíncronos. Mantén asíncronas las operaciones de red y de sesiones multimedia, y dirige los cambios de interfaz mediante el bucle de eventos de Qt. No hay un formateador o linter configurado; mantén los cambios coherentes con el código y los imports cercanos.

## Pautas para pruebas

Actualmente no existe una suite automatizada ni un umbral de cobertura. Para cambios de lógica, añade pruebas específicas con `pytest` en `tests/`, nombradas `test_<modulo>.py`, y simula las API externas y los servicios de Windows. Antes de enviar cambios, ejecuta la comprobación de compilación y prueba manualmente cualquier comportamiento afectado del overlay, bandeja, atajos, sincronización o traducción.

## Pautas para commits y pull requests

El historial reciente usa prefijos de Conventional Commits, como `feat:`, `fix:` y `refactor:`, seguidos de descripciones breves en español. Mantén cada commit enfocado. Los pull requests deben explicar el cambio de comportamiento, enumerar los pasos de verificación, enlazar los issues relacionados e incluir capturas o una grabación breve para cambios visibles de interfaz. Destaca los cambios que afecten a proveedores de letras, formatos de caché, atajos o permisos de Windows.
