"""Respostas da UI: página, fragmento, recarregar, mensagem de erro (flash)."""

from typing import Any

from fastapi import Request, Response
from starlette.responses import HTMLResponse

from videogen.core.errors import DomainError
from videogen.ui.templating import templates


def page(request: Request, name: str, status_code: int = 200, **context: Any) -> HTMLResponse:
    """`user` (quem está logado, se já resolvido) vai para todo template — o menu usa."""
    context.setdefault("user", getattr(request.state, "current_user", None))
    return templates.TemplateResponse(request, name, context, status_code=status_code)


def refresh() -> Response:
    """HTMX: recarrega a página atual (estado mudou de forma estrutural)."""
    return Response(status_code=204, headers={"HX-Refresh": "true"})


def flash(request: Request, message: str, *, level: str = "error") -> HTMLResponse:
    """Mostra a mensagem na faixa `#flash`, sem trocar o alvo original do HTMX."""
    response = page(request, "_flash.html", message=message, level=level)
    response.headers.update({"HX-Retarget": "#flash", "HX-Reswap": "innerHTML"})
    return response


def flash_error(request: Request, exc: DomainError) -> HTMLResponse:
    violations = getattr(exc, "violations", ())
    details = "; ".join(f"cena {v.scene_index + 1}: {v.message}" if v.scene_index is not None
                        else v.message for v in violations)  # fmt: skip
    return flash(request, f"{exc.message}{' — ' + details if details else ''}")
