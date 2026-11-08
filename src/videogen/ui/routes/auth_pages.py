"""Entrar e sair: senha, código por e-mail (sem senha) e definir/recuperar a senha.

O servidor fala com o provedor; o navegador só recebe o cookie `vg_session` (HttpOnly,
SameSite=Lax, Secure em produção). No modo local não há login: tudo redireciona para o app.
"""

from typing import Annotated

from fastapi import APIRouter, Form, Request, Response, status
from fastapi.responses import RedirectResponse

from videogen.api.auth import SESSION_COOKIE
from videogen.api.deps import Services
from videogen.core.errors import DomainError
from videogen.domain.identity import AuthSession
from videogen.ui.auth import safe_next
from videogen.ui.responses import page

router = APIRouter(include_in_schema=False)
Email = Annotated[str, Form(max_length=254)]
Next = Annotated[str, Form()]
HTTP_ERRORS = range(400, 600)
CODE_SENT = "Se o e-mail estiver cadastrado, enviamos um código. Ele vale por poucos minutos."


@router.get("/login")
async def login_form(request: Request, services: Services, next: str | None = None) -> Response:
    if services.auth is None:
        return _go(safe_next(next))
    return page(request, "login.html", next=safe_next(next))


@router.post("/login")
async def login_password(
    request: Request, services: Services, email: Email,
    password: Annotated[str, Form(max_length=256)], next: Next = "/",
) -> Response:  # fmt: skip
    if services.auth is None:
        return _go(safe_next(next))
    try:
        session = await services.auth.login_password(email, password)
    except DomainError as exc:
        return _login_error(request, exc, next, email=email)
    return _signed_in(services, session, next)


@router.post("/login/code/send")
async def send_login_code(request: Request, services: Services, email: Email,
                          next: Next = "/") -> Response:  # fmt: skip
    if services.auth is None:
        return _go(safe_next(next))
    try:
        await services.auth.request_code(email, "sign-in")
    except DomainError as exc:
        return _login_error(request, exc, next, email=email)
    return page(request, "login_code.html", email=email.strip(), next=safe_next(next),
                notice=CODE_SENT)  # fmt: skip


@router.post("/login/code")
async def login_code(
    request: Request, services: Services, email: Email,
    code: Annotated[str, Form(max_length=16)], next: Next = "/",
) -> Response:  # fmt: skip
    if services.auth is None:
        return _go(safe_next(next))
    try:
        session = await services.auth.login_code(email, code)
    except DomainError as exc:
        return page(request, "login_code.html", _status(exc), email=email.strip(),
                    next=safe_next(next), error=exc.message)  # fmt: skip
    return _signed_in(services, session, next)


@router.get("/password")
async def password_form(request: Request, email: str = "") -> Response:
    return page(request, "password.html", email=email[:254], step="email")


@router.post("/password/send")
async def send_password_code(request: Request, services: Services, email: Email) -> Response:
    if services.auth is None:
        return _go("/")
    try:
        await services.auth.request_code(email, "forget-password")
    except DomainError as exc:
        return page(request, "password.html", _status(exc), email=email, step="email",
                    error=exc.message)  # fmt: skip
    return page(request, "password.html", email=email.strip(), step="code", notice=CODE_SENT)


@router.post("/password")
async def set_password(
    request: Request, services: Services, email: Email,
    code: Annotated[str, Form(max_length=16)],
    password: Annotated[str, Form(max_length=256)],
    confirm: Annotated[str, Form(max_length=256)],
) -> Response:  # fmt: skip
    if services.auth is None:
        return _go("/")
    if password != confirm:
        return page(request, "password.html", status.HTTP_422_UNPROCESSABLE_CONTENT,
                    email=email, step="code", error="as senhas não conferem")  # fmt: skip
    try:
        session = await services.auth.set_password(email, code, password)
    except DomainError as exc:
        return page(request, "password.html", _status(exc), email=email, step="code",
                    error=exc.message)  # fmt: skip
    return _signed_in(services, session, "/")


@router.post("/logout")
async def logout(request: Request, services: Services) -> Response:
    token = request.cookies.get(SESSION_COOKIE)
    if services.auth is not None and token:
        await services.auth.logout(token)
    response = _go("/login")
    response.delete_cookie(SESSION_COOKIE, secure=services.secure_cookies, httponly=True,
                           samesite="lax")  # fmt: skip
    return response


def _signed_in(services: Services, session: AuthSession, next: str) -> Response:
    response = _go(safe_next(next))
    max_age = services.session_max_age_s
    response.set_cookie(SESSION_COOKIE, session.token, max_age=max_age, httponly=True,
                        samesite="lax", secure=services.secure_cookies)  # fmt: skip
    return response


def _login_error(request: Request, exc: DomainError, next: str, *, email: str) -> Response:
    return page(request, "login.html", _status(exc), next=safe_next(next), email=email,
                error=exc.message)  # fmt: skip


def _status(exc: DomainError) -> int:
    return exc.http_status if exc.http_status in HTTP_ERRORS else status.HTTP_400_BAD_REQUEST


def _go(url: str) -> RedirectResponse:
    return RedirectResponse(url, status_code=status.HTTP_303_SEE_OTHER)
