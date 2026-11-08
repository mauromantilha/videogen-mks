"""Hierarquia de erros esperados, com `code` estável.

O mapeamento para HTTP mora em `api/error_handlers.py`; `http_status` aqui é só a sugestão.
Erros específicos de uma regra (ex.: `ScriptValidationError`) vivem no `domain` e herdam daqui.
"""

from typing import ClassVar


class DomainError(Exception):
    """Falha de negócio prevista. `code` vai para a API, para o estado do job e para os logs."""

    code: ClassVar[str] = "DOMAIN_ERROR"
    http_status: ClassVar[int] = 400
    default_retryable: ClassVar[bool] = False

    def __init__(self, message: str, *, retryable: bool | None = None, **context: object) -> None:
        super().__init__(message)
        self.message = message
        self.retryable = self.default_retryable if retryable is None else retryable
        self.context = context


class NotFound(DomainError):
    code = "NOT_FOUND"
    http_status = 404


class AlreadyExists(DomainError):
    code = "ALREADY_EXISTS"
    http_status = 409


class InvalidTransition(DomainError):
    code = "INVALID_STATE"
    http_status = 409


class VersionConflict(DomainError):
    code = "VERSION_CONFLICT"
    http_status = 409


class ValidationFailed(DomainError):
    code = "VALIDATION_FAILED"
    http_status = 422


class BudgetExceeded(DomainError):
    code = "BUDGET_EXCEEDED"
    http_status = 422


class ProviderError(DomainError):
    """Falha de um provedor remoto; `retryable` decide se o retry pode repetir a chamada."""

    code = "PROVIDER_ERROR"
    http_status = 502


class ProviderTimeout(ProviderError):
    code = "PROVIDER_TIMEOUT"
    http_status = 504
    default_retryable = True


class ContentRejected(ProviderError):
    """O provedor recusou o conteúdo (política de uso). Nunca é repetido automaticamente."""

    code = "CONTENT_REJECTED"
    http_status = 422


class MediaError(DomainError):
    """Mídia inválida ou falha do FFmpeg/ffprobe."""

    code = "MEDIA_ERROR"
    http_status = 500
