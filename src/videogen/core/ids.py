"""Identificadores públicos. O formato fixo também protege contra path traversal."""

import re
import secrets

from videogen.core.errors import NotFound

JOB_ID_RE = re.compile(r"^job_[0-9a-f]{12}$")
VOICE_ID_RE = re.compile(r"^voz_[0-9a-f]{12}$")


def new_job_id() -> str:
    return f"job_{secrets.token_hex(6)}"


def new_voice_id() -> str:
    return f"voz_{secrets.token_hex(6)}"


def ensure_job_id(value: str) -> str:
    """Devolve o id se o formato for válido; um id malformado é tratado como inexistente."""
    if not JOB_ID_RE.fullmatch(value):
        raise NotFound("job não encontrado", job_id=value[:40])
    return value


def ensure_voice_id(value: str) -> str:
    if not VOICE_ID_RE.fullmatch(value):
        raise NotFound("voz não encontrada", voice_id=value[:40])
    return value
