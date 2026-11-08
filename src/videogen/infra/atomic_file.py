"""Escrita atômica: grava em arquivo temporário, fsync e `os.replace` (nunca deixa meio arquivo)."""

import os
import uuid
from pathlib import Path


def write_atomic(path: Path, data: bytes) -> None:
    """Leitores veem o conteúdo antigo ou o novo, nunca um parcial — mesmo após crash."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with tmp.open("wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)
    fsync_dir(path.parent)


def fsync_dir(directory: Path) -> None:
    """Persiste a entrada do diretório (o rename) — necessário no Linux para durabilidade."""
    descriptor = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
