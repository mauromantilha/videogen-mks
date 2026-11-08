"""Autenticação da UI: mesma sessão da API, mas sem login redireciona para a tela de entrada."""

from typing import Annotated
from urllib.parse import quote

from fastapi import Depends, HTTPException, Request, status

from videogen.api.auth import current_user
from videogen.domain.identity import CurrentUser


async def require_ui_auth(request: Request) -> CurrentUser:
    user = await current_user(request)
    if user is not None:
        return user
    target = f"/login?next={quote(request.url.path)}"
    if request.headers.get("HX-Request"):  # fragmento HTMX: recarrega a página inteira
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "sessão expirada",
                            headers={"HX-Redirect": target})  # fmt: skip
    raise HTTPException(status.HTTP_303_SEE_OTHER, "login necessário", headers={"Location": target})


UiUser = Annotated[CurrentUser, Depends(require_ui_auth)]


def safe_next(value: str | None) -> str:
    """Só redireciona para caminhos locais (evita open redirect)."""
    if value and value.startswith("/") and not value.startswith("//") and "\\" not in value:
        return value
    return "/"
