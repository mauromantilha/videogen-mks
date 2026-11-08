"""Autenticação da UI: mesmo critério da API, mas sem chave redireciona para o login."""

from urllib.parse import quote

from fastapi import HTTPException, Request, status

from videogen.api.auth import is_authorized


def require_ui_auth(request: Request) -> None:
    if is_authorized(request):
        return
    target = f"/login?next={quote(request.url.path)}"
    if request.headers.get("HX-Request"):  # fragmento HTMX: recarrega a página inteira
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "sessão expirada",
                            headers={"HX-Redirect": target})  # fmt: skip
    raise HTTPException(status.HTTP_303_SEE_OTHER, "login necessário", headers={"Location": target})


def safe_next(value: str | None) -> str:
    """Só redireciona para caminhos locais (evita open redirect)."""
    if value and value.startswith("/") and not value.startswith("//"):
        return value
    return "/"
