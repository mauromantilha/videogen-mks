"""T-061/T-065/T-066/T-067: auth, SSE, artefatos com Range, vozes, catálogo e prontidão."""

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from tests.fakes.api_app import ApiHarness, running_api
from tests.fakes.builders import JOB_ID, make_job
from tests.fakes.media_factory import make_audio
from videogen.api.dto.jobs import JobView
from videogen.api.routers.events import event_stream
from videogen.domain.events import JobStatusChanged, ScriptUpdated
from videogen.domain.media import ArtifactKind
from videogen.domain.status import JobStatus

pytestmark = pytest.mark.ffmpeg
FINAL_KEY = "f" * 64


@pytest.fixture
async def api(tmp_path: Path) -> AsyncIterator[ApiHarness]:
    async with running_api(tmp_path) as harness:
        yield harness


async def test_modo_local_so_aceita_loopback(api: ApiHarness, tmp_path: Path) -> None:
    assert (await api.client.get("/api/v1/jobs")).status_code == 200  # ASGI: 127.0.0.1
    async with running_api(tmp_path / "remoto", client_host="203.0.113.7") as remote:
        denied = await remote.client.get("/api/v1/jobs")
        assert (denied.status_code, denied.json()["code"]) == (401, "UNAUTHORIZED")
        assert (await remote.client.get("/healthz")).status_code == 200  # sondas são abertas


async def test_api_com_login_usa_o_cookie_de_sessao(tmp_path: Path) -> None:
    async with running_api(tmp_path, auth=True) as api:
        assert (await api.client.get("/api/v1/jobs")).status_code == 401
        api.client.cookies.set("vg_session", "token-inventado")
        assert (await api.client.get("/api/v1/jobs")).status_code == 401
        session = await api.identity.sign_in_password("admin@mksseguros.com", "senha-do-admin")
        api.client.cookies.set("vg_session", session.token)
        assert (await api.client.get("/api/v1/jobs")).status_code == 200


async def test_sse_snapshot_eventos_e_fim(api: ApiHarness) -> None:
    await api.container.infra.repo.create(make_job(JobStatus.AWAITING_APPROVAL))
    bus = api.container.infra.bus
    bus.publish(JOB_ID, ScriptUpdated(script_version=2))  # já no buffer: replay
    snapshot = JobView.of(await api.container.infra.repo.get(JOB_ID))
    chunks: list[str] = []

    async def consume() -> None:
        async for chunk in event_stream(bus, snapshot, last_event_id=0, heartbeat_s=0.05):
            chunks.append(chunk)

    reader = asyncio.create_task(consume())
    await asyncio.sleep(0.12)  # pelo menos um heartbeat
    bus.publish(JOB_ID, JobStatusChanged(status=JobStatus.CANCELED))
    await asyncio.wait_for(reader, 2)
    assert chunks[0].startswith("event: snapshot\ndata: {")
    assert chunks[1].startswith("id: 1\nevent: script.updated")
    assert ": ping\n\n" in chunks
    assert chunks[-1].startswith("id: 2\nevent: job.status") and bus.subscriber_count(JOB_ID) == 0


async def test_sse_de_job_finalizado_envia_so_o_snapshot(api: ApiHarness) -> None:
    await api.container.infra.repo.create(make_job(JobStatus.COMPLETED))
    response = await api.client.get(f"/api/v1/jobs/{JOB_ID}/events")
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.text.count("event: ") == 1 and "event: snapshot" in response.text


async def test_artefatos_com_range(api: ApiHarness) -> None:
    job = make_job(JobStatus.COMPLETED)
    job.final_hash = FINAL_KEY
    job.scenes[0].clip.finish("c" * 64)
    await api.container.infra.repo.create(job)
    base = f"/api/v1/jobs/{JOB_ID}"
    assert (await api.client.get(f"{base}/artifacts/final")).status_code == 404
    cache = api.container.infra.cache
    for kind, key in ((ArtifactKind.FINAL, FINAL_KEY), (ArtifactKind.CLIP, "c" * 64)):
        tmp = cache.tmp_path(kind, key)
        tmp.write_bytes(bytes(range(256)) * 4)
        cache.commit(kind, key, tmp, {})
    full = await api.client.get(f"{base}/artifacts/final")
    assert (full.status_code, len(full.content), full.headers["content-type"]) == (
        200,
        1024,
        "video/mp4",
    )
    part = await api.client.get(f"{base}/artifacts/final", headers={"Range": "bytes=0-99"})
    assert (part.status_code, part.content) == (206, bytes(range(100)))
    assert (await api.client.get(f"{base}/scenes/0/clip")).status_code == 200
    assert (await api.client.get(f"{base}/scenes/1/clip")).status_code == 404
    assert (await api.client.get(f"{base}/scenes/9/clip")).status_code == 404
    assert (await api.client.get(f"{base}/scenes/0/segredo")).status_code == 422


async def test_vozes(api: ApiHarness, tmp_path: Path) -> None:
    audio = (await make_audio(tmp_path / "voz.wav", 5.0)).read_bytes()
    created = await api.client.post(
        "/api/v1/voices", files={"audio": ("voz.wav", audio, "audio/wav")},
        data={"name": "Mauro", "ref_text": "Olá, esta é a minha voz de referência."},
    )  # fmt: skip
    assert created.status_code == 201, created.text
    voice_id = created.json()["voice_id"]
    assert "path" not in created.json()
    assert voice_id in {v["voice_id"] for v in (await api.client.get("/api/v1/voices")).json()}
    assert (await api.client.delete(f"/api/v1/voices/{voice_id}")).status_code == 204
    assert (await api.client.delete(f"/api/v1/voices/{voice_id}")).status_code == 404
    bad = await api.client.post(
        "/api/v1/voices",
        files={"audio": ("x.exe", b"MZ", "x")},
        data={"name": "x", "ref_text": "y"},
    )
    assert (bad.status_code, bad.json()["code"]) == (422, "INVALID_VOICE")


async def test_catalogo_e_prontidao(api: ApiHarness) -> None:
    models = (await api.client.get("/api/v1/catalog/models", params={"kind": "t2v"})).json()
    assert {m["key"] for m in models} == {"wan-2.1-t2v-480p", "wan-2.1-t2v-720p", "cogvideox-5b"}
    cog = next(m for m in models if m["key"] == "cogvideox-5b")
    assert (cog["aspect_ratios"], cog["estimated_usd"]) == (["16:9"], 0.5)
    assert len((await api.client.get("/api/v1/catalog/models")).json()) == 6
    assert (await api.client.get("/readyz")).json() == {"status": "ready"}


async def test_erro_inesperado_nao_vaza_detalhes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async with running_api(tmp_path, raise_errors=False) as api:

        async def boom() -> None:
            raise RuntimeError("senha=hunter2 no stack")

        monkeypatch.setattr(api.container.infra.repo, "list_all", boom)
        response = await api.client.get("/api/v1/jobs")
    assert (response.status_code, response.json()["code"]) == (500, "INTERNAL_ERROR")
    assert "hunter2" not in response.text


def test_app_do_modulo_principal_sobe_sem_env() -> None:
    from videogen.main import app

    paths = set(app.openapi()["paths"])
    assert {"/api/v1/jobs", "/api/v1/jobs/{job_id}/events", "/readyz"} <= paths


async def test_prontidao_aponta_workspace_removido(api: ApiHarness) -> None:
    import shutil

    shutil.rmtree(api.container.infra.workspace.jobs_dir)
    response = await api.client.get("/readyz")
    assert response.status_code == 503
    assert any("inexistente" in p for p in response.json()["problems"])
