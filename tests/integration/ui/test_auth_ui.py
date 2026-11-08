"""Login por usuário no app real (modo fake): código por e-mail, primeiro acesso, usuários da
organização e isolamento — job/voz de outra pessoa é 404 na UI e na API.
"""

from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest

from tests.fakes.api_app import ADMIN_EMAIL, ApiHarness, running_api
from videogen.domain.status import JobStatus

pytestmark = pytest.mark.ffmpeg
ANA = "ana@mksseguros.com"


@pytest.fixture
async def ui(tmp_path: Path) -> AsyncIterator[ApiHarness]:
    async with running_api(tmp_path, auth=True) as harness:
        yield harness


async def _login_admin(client: httpx.AsyncClient) -> None:
    data = {"email": ADMIN_EMAIL, "password": "senha-do-admin", "next": "/"}
    assert (await client.post("/login", data=data)).status_code == 303


async def _login_by_code(ui: ApiHarness, client: httpx.AsyncClient, email: str) -> None:
    sent = await client.post("/login/code/send", data={"email": email, "next": "/"})
    assert sent.status_code == 200 and "Se o e-mail estiver cadastrado" in sent.text
    form = {"email": email, "code": ui.identity.last_code(email), "next": "/"}
    response = await client.post("/login/code", data=form)
    assert (response.status_code, response.headers["location"]) == (303, "/")


async def test_admin_cadastra_e_a_pessoa_entra_com_codigo(ui: ApiHarness) -> None:
    await _login_admin(ui.client)
    page = await ui.client.get("/members")
    assert page.status_code == 200 and ADMIN_EMAIL in page.text
    outside = await ui.client.post("/members", data={"email": "x@gmail.com", "name": "X"})
    assert outside.status_code == 422 and "@mksseguros.com" in outside.text
    added = await ui.client.post("/members", data={"email": ANA, "name": "Ana", "role": "member"})
    assert added.status_code == 303
    transport = ui.client._transport  # mesmo app, outro navegador (outros cookies)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ana:
        await _login_by_code(ui, ana, ANA)
        home = await ana.get("/")
        assert home.status_code == 200 and ANA in home.text and 'href="/members"' not in home.text
        assert (await ana.get("/members")).status_code == 403


async def test_nao_membro_nao_recebe_codigo_nem_entra(ui: ApiHarness) -> None:
    sent = await ui.client.post("/login/code/send", data={"email": "intruso@mksseguros.com"})
    assert sent.status_code == 200 and ui.identity.sent == []  # mesma resposta, sem e-mail
    bad = await ui.client.post("/login/code", data={"email": "intruso@mksseguros.com",
                                                     "code": "123456"})  # fmt: skip
    assert bad.status_code == 401 and "código inválido" in bad.text
    assert (await ui.client.get("/")).status_code == 303


async def test_primeiro_acesso_define_a_senha(ui: ApiHarness) -> None:
    ui.identity.passwords.pop(ADMIN_EMAIL)  # como o comercial@: criado sem senha
    assert (await ui.client.get("/password")).status_code == 200
    sent = await ui.client.post("/password/send", data={"email": ADMIN_EMAIL})
    assert sent.status_code == 200 and 'name="code"' in sent.text
    code = ui.identity.last_code(ADMIN_EMAIL, "forget-password")
    form = {"email": ADMIN_EMAIL, "code": code, "password": "minha-senha-nova", "confirm": "outra"}
    assert (await ui.client.post("/password", data=form)).status_code == 422
    done = await ui.client.post("/password", data=form | {"confirm": "minha-senha-nova"})
    assert (done.status_code, done.headers["location"]) == (303, "/")
    assert "vg_session=" in done.headers["set-cookie"]
    assert (await ui.client.get("/")).status_code == 200
    out = await ui.client.post("/logout")
    assert out.headers["location"] == "/login" and not ui.identity.sessions
    assert (await ui.client.get("/")).status_code == 303


async def test_cada_usuario_so_ve_os_proprios_videos_e_vozes(ui: ApiHarness) -> None:
    await _login_admin(ui.client)
    created = await ui.client.post("/api/v1/jobs", json=ui.job_body())
    assert created.status_code == 202
    job_id = created.json()["job_id"]
    assert (await ui.settle(job_id))["status"] == JobStatus.AWAITING_APPROVAL
    await ui.client.post("/members", data={"email": ANA, "name": "Ana"})
    async with httpx.AsyncClient(transport=ui.client._transport, base_url="http://test") as ana:
        await _login_by_code(ui, ana, ANA)
        assert (await ana.get("/api/v1/jobs")).json() == []
        assert (await ana.get("/api/v1/voices")).json() == []
        for url in (f"/api/v1/jobs/{job_id}", f"/jobs/{job_id}",
                    f"/api/v1/jobs/{job_id}/script", f"/ui/jobs/{job_id}/progress"):  # fmt: skip
            assert (await ana.get(url)).status_code == 404, url
        assert (await ana.post(f"/api/v1/jobs/{job_id}/cancel")).status_code == 404
        assert (await ana.post(f"/api/v1/jobs/{job_id}/clone")).status_code == 404
        stolen = await ana.post("/api/v1/jobs", json=ui.job_body())  # voz do admin
        assert (stolen.status_code, stolen.json()["code"]) == (404, "NOT_FOUND")
        gone = await ana.delete(f"/api/v1/voices/{ui.voice_id}")
        assert gone.status_code == 404
    mine = await ui.client.get("/api/v1/jobs")
    assert [job["job_id"] for job in mine.json()] == [job_id]
