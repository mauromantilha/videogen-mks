"""Erros em `application/problem+json` (design/06 §5).

O status vem da própria classe de erro (`http_status`), um só lugar para o mapa. Contexto só é
exposto por lista branca; erro inesperado vira 500 sem detalhes internos.
"""

import logging
from typing import cast

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from videogen.core.config import ConfigError
from videogen.core.errors import DomainError
from videogen.domain.script_rules import ScriptValidationError

logger = logging.getLogger(__name__)
PROBLEM = "application/problem+json"
PUBLIC_CONTEXT = frozenset({"current_version", "requested_version", "estimated_usd",
                            "budget_usd", "job_id", "status"})  # fmt: skip


def problem(status: int, code: str, detail: str, **extra: object) -> JSONResponse:
    body = {"type": "about:blank", "title": code.replace("_", " ").lower(), "status": status,
            "code": code, "detail": detail, **extra}  # fmt: skip
    return JSONResponse(body, status_code=status, media_type=PROBLEM)


# O FastAPI só chama cada handler com o tipo registrado: o `cast` é seguro.
async def domain_error(_: Request, error: Exception) -> JSONResponse:
    exc = cast(DomainError, error)
    extra = {k: v for k, v in exc.context.items() if k in PUBLIC_CONTEXT}
    if isinstance(exc, ScriptValidationError):
        extra["violations"] = [
            {"scene_index": v.scene_index, "code": v.code, "message": v.message}
            for v in exc.violations
        ]
    return problem(exc.http_status, exc.code, exc.message, **extra)


async def validation_error(_: Request, error: Exception) -> JSONResponse:
    exc = cast(RequestValidationError, error)
    errors = [{"loc": [str(p) for p in e["loc"]], "message": e["msg"]} for e in exc.errors()]
    return problem(422, "VALIDATION_ERROR", "requisição inválida", errors=errors)


async def http_error(_: Request, error: Exception) -> JSONResponse:
    exc = cast(HTTPException, error)
    code = {401: "UNAUTHORIZED", 404: "NOT_FOUND", 405: "METHOD_NOT_ALLOWED"}.get(
        exc.status_code, "HTTP_ERROR"
    )
    return problem(exc.status_code, code, str(exc.detail))


async def config_error(_: Request, exc: Exception) -> JSONResponse:
    return problem(503, "NOT_CONFIGURED", str(exc))


async def unexpected_error(_: Request, exc: Exception) -> JSONResponse:
    logger.exception("erro inesperado na API", exc_info=exc)
    return problem(500, "INTERNAL_ERROR", "erro interno; consulte os logs")


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(DomainError, domain_error)
    app.add_exception_handler(RequestValidationError, validation_error)
    app.add_exception_handler(HTTPException, http_error)
    app.add_exception_handler(ConfigError, config_error)
    app.add_exception_handler(Exception, unexpected_error)
