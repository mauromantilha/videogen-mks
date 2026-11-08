"""T-080…T-084: UI server-rendered contra o app real (modo fake), como um navegador faria."""

from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from tests.fakes.api_app import ADMIN_EMAIL, ApiHarness, running_api
from tests.fakes.builders import JOB_ID, make_job
from tests.fakes.media_factory import make_audio
from videogen.domain.status import JobStatus

pytestmark = pytest.mark.ffmpeg
HTMX = {"HX-Request": "true"}


@pytest.fixture
async def ui(tmp_path: Path) -> AsyncIterator[ApiHarness]:
    async with running_api(tmp_path, auth=True) as harness:
        yield harness


async def _login(ui: ApiHarness) -> None:
    credentials = {"email": ADMIN_EMAIL, "password": "senha-do-admin"}
    response = await ui.client.post("/login", data=credentials | {"next": "/voices"})
    assert (response.status_code, response.headers["location"]) == (303, "/voices")
    cookie = response.headers["set-cookie"]
    assert "httponly" in cookie.lower() and "samesite=lax" in cookie.lower()


async def _job(ui: ApiHarness) -> str:
    form = {"tema": "Seguro de vida", "aspect_ratio": "9:16", "n_cenas": "3",
            "voice_id": ui.voice_id, "llm": "deepseek-flash", "tts": "f5-tts",
            "video": "wan-2.1-t2v-480p", "resolution": "480p", "max_budget_usd": "1",
            "legendas": "on"}  # fmt: skip
    response = await ui.client.post("/jobs", data=form)
    assert response.status_code == 303
    job_id = response.headers["location"].removeprefix("/jobs/")
    await ui.settle(job_id)
    return job_id


async def test_login_protege_paginas_e_fragmentos(ui: ApiHarness) -> None:
    response = await ui.client.get("/")
    assert (response.status_code, response.headers["location"]) == (303, "/login?next=/")
    fragment = await ui.client.get("/ui/jobs/job_0123456789ab/progress", headers=HTMX)
    assert fragment.headers["hx-redirect"].startswith("/login")
    wrong = {"email": ADMIN_EMAIL, "password": "errada", "next": "//evil.com"}
    bad = await ui.client.post("/login", data=wrong)
    assert bad.status_code == 401 and "senha inválidos" in bad.text
    await _login(ui)
    assert (await ui.client.get("/")).status_code == 200
    good = {"email": ADMIN_EMAIL, "password": "senha-do-admin", "next": "//evil.com"}
    evil = await ui.client.post("/login", data=good)
    assert evil.headers["location"] == "/"  # sem open redirect


async def test_pagina_inicial_tem_cabecalhos_de_seguranca(ui: ApiHarness) -> None:
    await _login(ui)
    response = await ui.client.get("/")
    assert "script-src 'self'" in response.headers["content-security-policy"]
    assert response.headers["x-frame-options"] == "DENY"
    assert "Novo vídeo" in response.text and "wan-2.1-t2v-480p" in response.text
    assert (await ui.client.get("/static/vendor/htmx.min.js")).status_code == 200


async def test_fluxo_de_revisao_e_aprovacao(ui: ApiHarness) -> None:
    await _login(ui)
    job_id = await _job(ui)
    page = (await ui.client.get(f"/jobs/{job_id}")).text
    assert "Aguardando aprovação" in page and page.count('id="script-version"') == 1
    assert "sse-connect" not in page  # revisão não precisa de tempo real

    saved = await ui.client.patch(
        f"/ui/jobs/{job_id}/scenes/0",
        headers=HTMX,
        data={"expected_version": "1", "texto_narrado": " ".join(["x"] * 13)},
    )
    assert "13/12 palavras" in saved.text and 'value="2"' in saved.text  # versão via OOB
    assert saved.headers["hx-trigger"] == "script-changed"
    stale = await ui.client.patch(
        f"/ui/jobs/{job_id}/scenes/0",
        headers=HTMX,
        data={"expected_version": "1", "texto_narrado": "Curto."},
    )
    assert stale.headers["hx-retarget"] == "#flash" and "mudou" in stale.text

    blocked = await ui.client.post(
        f"/ui/jobs/{job_id}/approve",
        headers=HTMX,
        data={"expected_version": "2", "max_budget_usd": "1"},
    )
    assert "cena 1: 13 palavras" in blocked.text  # numeração da tela (a partir de 1)
    assert blocked.headers["hx-retarget"] == "#flash"
    await ui.client.patch(
        f"/ui/jobs/{job_id}/scenes/0",
        headers=HTMX,
        data={"expected_version": "2", "texto_narrado": "Agora sim."},
    )
    estimate = await ui.client.get(f"/ui/jobs/{job_id}/estimate", headers=HTMX)
    assert "US$ 0,30" in estimate.text
    approved = await ui.client.post(
        f"/ui/jobs/{job_id}/approve",
        headers=HTMX,
        data={"expected_version": "3", "max_budget_usd": "1"},
    )
    assert approved.headers["hx-refresh"] == "true"

    await ui.settle(job_id)
    done = (await ui.client.get(f"/jobs/{job_id}")).text
    assert "Vídeo pronto" in done and f"/api/v1/jobs/{job_id}/artifacts/final" in done
    assert (await ui.client.get(f"/api/v1/jobs/{job_id}/artifacts/final")).status_code == 200


async def test_operacoes_de_cena_e_regeneracao(ui: ApiHarness) -> None:
    await _login(ui)
    job_id = await _job(ui)
    base = f"/ui/jobs/{job_id}"
    for path, data in (
        (f"{base}/scenes/0/reseed", {"expected_version": "1"}),
        (f"{base}/scenes/0/move", {"expected_version": "2", "target": "1"}),
        (f"{base}/scenes/2/add-after", {"expected_version": "3"}),
        (f"{base}/scenes/3/delete", {"expected_version": "4"}),
    ):
        response = await ui.client.post(path, headers=HTMX, data=data)
        assert response.headers.get("hx-refresh") == "true", (path, response.text)
    regen = await ui.client.post(
        f"{base}/regenerate", headers=HTMX, data={"feedback": "mais leve", "scene_index": "1"}
    )
    assert regen.headers["hx-refresh"] == "true"
    await ui.settle(job_id)
    assert (await ui.client.get(f"/api/v1/jobs/{job_id}")).json()["script_version"] == 6


async def test_texto_do_llm_e_escapado(ui: ApiHarness) -> None:
    await _login(ui)
    job_id = await _job(ui)
    await ui.client.patch(
        f"/ui/jobs/{job_id}/scenes/0",
        headers=HTMX,
        data={"expected_version": "1", "texto_narrado": "<script>alert(1)</script>"},
    )
    page = (await ui.client.get(f"/jobs/{job_id}")).text
    assert "<script>alert(1)</script>" not in page and "&lt;script&gt;" in page


async def test_vozes(ui: ApiHarness, tmp_path: Path) -> None:
    await _login(ui)
    audio = (await make_audio(tmp_path / "v.wav", 5)).read_bytes()
    created = await ui.client.post(
        "/voices",
        files={"audio": ("v.wav", audio, "audio/wav")},
        data={"name": "Locutora", "ref_text": "Olá, tudo bem?"},
    )
    assert created.status_code == 303
    assert "Locutora" in (await ui.client.get("/voices")).text
    bad = await ui.client.post(
        "/voices",
        files={"audio": ("v.txt", b"x", "text/plain")},
        data={"name": "X", "ref_text": "Y"},
    )
    assert bad.status_code == 422 and "formato" in bad.text


async def test_job_em_andamento_usa_tempo_real(ui: ApiHarness) -> None:
    await _login(ui)
    await ui.container.infra.repo.create(make_job(JobStatus.SCRIPTING))
    page = (await ui.client.get(f"/jobs/{JOB_ID}")).text
    assert f'sse-connect="/api/v1/jobs/{JOB_ID}/events"' in page and "Gerando o roteiro" in page
    assert 'hx-trigger="sse:job.status"' in page
