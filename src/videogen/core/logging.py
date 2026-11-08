"""Logs JSON com contexto (job_id, scene_index, step) e redação de segredos (RNF-07, RNF-08)."""

import json
import logging
import re
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime

_CONTEXT: dict[str, ContextVar[object | None]] = {
    name: ContextVar(name, default=None) for name in ("job_id", "scene_index", "step", "provider")
}
_STANDARD_ATTRS = set(vars(logging.makeLogRecord({}))) | {"message", "asctime"}
_SECRET_PATTERNS = (
    re.compile(r"(?i)(authorization[\"']?\s*[:=]\s*[\"']?)(bearer\s+|token\s+)?[^\s\"',}]+"),
    re.compile(
        r"(?i)\b([\w-]*(?:api[_-]?key|token|secret|password)[\w-]*[\"']?\s*[:=]\s*[\"']?)"
        r"[^\s\"',}]+"
    ),
    re.compile(r"\b(sk-|r8_|fal_)[A-Za-z0-9_\-]{8,}"),
)
REDACTED = "***"


def redact(text: str) -> str:
    """Substitui valores de credenciais conhecidas por `***`."""
    text = _SECRET_PATTERNS[0].sub(lambda m: f"{m.group(1)}{m.group(2) or ''}{REDACTED}", text)
    text = _SECRET_PATTERNS[1].sub(lambda m: f"{m.group(1)}{REDACTED}", text)
    return _SECRET_PATTERNS[2].sub(lambda m: f"{m.group(1)}{REDACTED}", text)


@contextmanager
def log_context(**values: object) -> Iterator[None]:
    """Anexa campos (job_id, scene_index, step, provider) a todos os logs do bloco."""
    tokens = [(_CONTEXT[name], _CONTEXT[name].set(value)) for name, value in values.items()]
    try:
        yield
    finally:
        for var, token in reversed(tokens):
            var.reset(token)


class JsonFormatter(logging.Formatter):
    """Uma linha JSON por registro; extras de `logger.info(..., extra={...})` são incluídos."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        payload |= {name: var.get() for name, var in _CONTEXT.items() if var.get() is not None}
        payload |= {k: v for k, v in vars(record).items() if k not in _STANDARD_ATTRS}
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return redact(json.dumps(payload, ensure_ascii=False, default=str))


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level.upper())
