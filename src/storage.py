"""Utilidades defensivas para archivos persistentes de la aplicación."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path


_FILE_ATTRIBUTE_REPARSE_POINT = 0x0400


def _is_reparse_point(path: Path) -> bool:
    """Indica si una ruta existente es un enlace o punto de reanálisis."""
    try:
        metadata = path.lstat()
    except OSError:
        return False
    return path.is_symlink() or bool(
        getattr(metadata, "st_file_attributes", 0)
        & _FILE_ATTRIBUTE_REPARSE_POINT
    )


def _validate_file_path(path: Path) -> None:
    if _is_reparse_point(path):
        raise ValueError("No se permiten enlaces en archivos persistentes")
    if path.exists() and not path.is_file():
        raise ValueError("La ruta persistente no es un archivo regular")


def read_text_limited(
    path: Path, max_bytes: int, encoding: str = "utf-8"
) -> str:
    """Lee un archivo regular, no enlazado y con tamaño limitado."""
    _validate_file_path(path)
    if path.stat().st_size > max_bytes:
        raise ValueError("El archivo es demasiado grande")
    return path.read_text(encoding=encoding)


def atomic_write_text(
    path: Path, content: str, encoding: str = "utf-8"
) -> None:
    """Escribe texto mediante un temporal exclusivo y reemplazo atómico."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if _is_reparse_point(path.parent):
        raise ValueError("No se permiten enlaces en directorios persistentes")
    _validate_file_path(path)

    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding=encoding,
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)
            temporary_file.write(content)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
        os.replace(temporary_path, path)
    except Exception:
        if temporary_path is not None:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                pass
        raise
