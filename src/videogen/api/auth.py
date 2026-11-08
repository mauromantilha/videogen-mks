"""Autenticação por chave (RNF-07): cabeçalho `X-API-Key` ou cookie `vg_key` (UI).

Sem `APP_API_KEY` configurada, só aceita conexões locais (modo dev) — gerar vídeo custa dinheiro.
"""

import secrets

from fastapi import HTTPException, Request, status

from videogen.api.deps import get_services

COOKIE_NAME = "vg_key"
HEADER_NAME = "X-API-Key"
LOOPBACK = frozenset({"127.0.0.1", "::1", "localhost"})


def require_auth(request: Request) -> None:
    expected = get_services(request).api_key
    if expected is None:
        host = request.client.host if request.client else ""
        if host not in LOOPBACK:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "configure APP_API_KEY")
        return
    provided = request.headers.get(HEADER_NAME) or request.cookies.get(COOKIE_NAME) or ""
    if not secrets.compare_digest(provided.encode(), expected.encode()):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "chave de API inválida")
