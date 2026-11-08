"""Usuários da organização (só admins): cadastrar, ativar e desativar.

Quem é cadastrado entra pela primeira vez com um código enviado ao e-mail (tela de login) e
pode definir a senha depois. Ninguém escolhe ou vê a senha de outra pessoa.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Form, Request, Response, status
from fastapi.responses import RedirectResponse

from videogen.api.deps import Services
from videogen.core.errors import DomainError
from videogen.domain.identity import CurrentUser, Role
from videogen.ui.auth import UiUser, require_ui_auth
from videogen.ui.responses import page

router = APIRouter(include_in_schema=False, dependencies=[Depends(require_ui_auth)])


@router.get("/members")
async def members_page(request: Request, services: Services, user: UiUser) -> Response:
    return await _render(request, services, user)


@router.post("/members")
async def add_member(
    request: Request, services: Services, user: UiUser,
    email: Annotated[str, Form(max_length=254)], name: Annotated[str, Form(max_length=120)],
    role: Annotated[Role, Form()] = Role.MEMBER,
) -> Response:  # fmt: skip
    try:
        await services.members.add(user, email, name, role)
    except DomainError as exc:
        return await _render(request, services, user, exc.http_status, error=exc.message,
                             form={"email": email, "name": name, "role": role.value})  # fmt: skip
    return RedirectResponse("/members", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/members/active")
async def set_active(
    request: Request, services: Services, user: UiUser,
    email: Annotated[str, Form(max_length=254)], active: Annotated[bool, Form()],
) -> Response:  # fmt: skip
    try:
        await services.members.set_active(user, email, active)
    except DomainError as exc:
        return await _render(request, services, user, exc.http_status, error=exc.message)
    return RedirectResponse("/members", status_code=status.HTTP_303_SEE_OTHER)


async def _render(
    request: Request, services: Services, user: CurrentUser, status_code: int = 200,
    **context: object,
) -> Response:  # fmt: skip
    try:
        members = await services.members.list_all(user)
    except DomainError as exc:  # não-admin
        return page(request, "members.html", exc.http_status, members=[], error=exc.message,
                    forbidden=True)  # fmt: skip
    return page(request, "members.html", status_code, members=members, roles=list(Role),
                **context)  # fmt: skip
