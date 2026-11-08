"""Converte respostas e falhas de transporte em `ProviderError` com `retryable` correto.

Regra anti-cobrança-dupla: numa chamada NÃO idempotente (criar predição), só é seguro repetir
quando a falha comprovadamente ocorreu antes do provedor aceitar o pedido.
"""

import json
import re
from collections.abc import Mapping
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime

import httpx

from videogen.core.errors import ContentRejected, ProviderError, ProviderTimeout

UNPROCESSABLE = 422
RETRYABLE_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504})
_CONTENT_REJECTION = re.compile(
    r"nsfw|safety (checker|filter)|content (policy|filter|moderation)|flagged|inappropriate",
    re.IGNORECASE,
)
_PRE_SEND_ERRORS = (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout)
_MAX_DETAIL = 300


def looks_like_content_rejection(text: str) -> bool:
    return bool(_CONTENT_REJECTION.search(text))


def parse_retry_after(value: str | None, now: datetime | None = None) -> float | None:
    if not value:
        return None
    if value.strip().isdigit():
        return float(value.strip())
    try:
        moment = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    return max(0.0, (moment - (now or datetime.now(UTC))).total_seconds())


def extract_detail(body: str) -> str:
    """Mensagem legível do corpo de erro (`detail`, `error`, `message`), truncada."""
    try:
        data = json.loads(body)
    except ValueError:
        return body.strip()[:_MAX_DETAIL]
    if isinstance(data, dict):
        for key in ("detail", "error", "message"):
            value = data.get(key)
            if isinstance(value, dict):
                value = value.get("message", value)
            if value:
                return str(value)[:_MAX_DETAIL]
    return str(data)[:_MAX_DETAIL]


def classify_response(
    status: int, body: str, headers: Mapping[str, str], *, provider: str
) -> ProviderError:
    detail = extract_detail(body)
    message = f"{provider} respondeu HTTP {status}: {detail}"
    if status == UNPROCESSABLE and looks_like_content_rejection(detail):
        return ContentRejected(message, provider=provider, status=status)
    if status in RETRYABLE_STATUS:
        retry_after = parse_retry_after(headers.get("retry-after"))
        context: dict[str, object] = {"provider": provider, "status": status}
        if retry_after is not None:
            context["retry_after_s"] = retry_after
        return ProviderError(message, retryable=True, **context)
    return ProviderError(message, retryable=False, provider=provider, status=status)


def transport_error(exc: httpx.TransportError, *, provider: str, idempotent: bool) -> ProviderError:
    name = type(exc).__name__
    if isinstance(exc, _PRE_SEND_ERRORS):
        return ProviderError(f"{provider}: falha de conexão ({name})", retryable=True)
    if isinstance(exc, httpx.TimeoutException):
        return ProviderTimeout(f"{provider}: tempo esgotado ({name})", retryable=idempotent)
    # O pedido pode ter sido aceito: repetir um submit poderia cobrar duas vezes.
    return ProviderError(f"{provider}: falha de rede ({name})", retryable=idempotent)
