"""T-063/T-064: a Etapa 1 inteira via HTTP, contra o container real em modo fake."""

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest

from tests.fakes.api_app import ApiHarness, running_api

pytestmark = pytest.mark.ffmpeg  # o startup roda o healthcheck do toolchain
LONG = " ".join(["palavra"] * 13)


@pytest.fixture
async def api(tmp_path: Path) -> AsyncIterator[ApiHarness]:
    async with running_api(tmp_path) as harness:
        yield harness


async def _job(api: ApiHarness, **overrides: Any) -> str:
    response = await api.client.post("/api/v1/jobs", json=api.job_body(**overrides))
    assert response.status_code == 202, response.text
    assert response.headers["location"] == f"/api/v1/jobs/{response.json()['job_id']}"
    job_id: str = response.json()["job_id"]
    assert (await api.settle(job_id))["status"] == "awaiting_approval"
    return job_id


async def _patch(api: ApiHarness, job_id: str, version: int, **fields: object) -> Any:
    return await api.client.patch(
        f"/api/v1/jobs/{job_id}/script/scenes/0", json={"expected_version": version, **fields}
    )


async def test_fluxo_completo_da_etapa_1(api: ApiHarness) -> None:
    job_id = await _job(api)
    script = (await api.client.get(f"/api/v1/jobs/{job_id}/script")).json()
    assert (script["script_version"], script["violations"], len(script["script"]["cenas"])) == (
        1,
        [],
        3,
    )

    stale = await _patch(api, job_id, 0, texto_narrado="Atrasado.")
    assert (stale.status_code, stale.json()["code"], stale.json()["current_version"]) == (
        409,
        "VERSION_CONFLICT",
        1,
    )
    long = await _patch(api, job_id, 1, texto_narrado=LONG)
    assert long.status_code == 200
    assert [v["code"] for v in long.json()["violations"]] == ["TOO_MANY_WORDS"]

    blocked = await api.client.post(f"/api/v1/jobs/{job_id}/approve", json={"script_version": 2})
    assert (blocked.status_code, blocked.json()["code"]) == (422, "SCRIPT_INVALID")
    assert blocked.json()["violations"][0]["scene_index"] == 0

    assert (await _patch(api, job_id, 2, texto_narrado="Agora sim, curto.")).status_code == 200
    estimate = (await api.client.get(f"/api/v1/jobs/{job_id}/estimate")).json()
    assert estimate["total_usd"] == pytest.approx(0.3)
    approved = await api.client.post(f"/api/v1/jobs/{job_id}/approve", json={"script_version": 3})
    assert approved.status_code == 202 and approved.json()["status"] == "approved"
    assert approved.json()["approved_version"] == 3 and len(approved.json()["scenes"]) == 3
    again = await api.client.post(f"/api/v1/jobs/{job_id}/approve", json={"script_version": 3})
    assert (again.status_code, again.json()["code"]) == (409, "INVALID_STATE")


async def test_orcamento_insuficiente(api: ApiHarness) -> None:
    job_id = await _job(api)
    response = await api.client.post(
        f"/api/v1/jobs/{job_id}/approve", json={"script_version": 1, "max_budget_usd": 0.1}
    )
    assert (response.status_code, response.json()["code"]) == (422, "BUDGET_EXCEEDED")
    assert response.json()["estimated_usd"] == pytest.approx(0.3)


async def test_operacoes_de_cena(api: ApiHarness) -> None:
    job_id, base = await _job(api), "/api/v1/jobs"
    prompt = "A calm beach at sunrise, gentle waves, wide drone shot, golden light"
    added = await api.client.post(
        f"{base}/{job_id}/script/scenes",
        json={
            "expected_version": 1,
            "after_index": 2,
            "texto_narrado": "Extra.",
            "prompt_video": prompt,
        },
    )
    assert (added.status_code, added.json()["script_version"]) == (201, 2)
    moved = await api.client.post(
        f"{base}/{job_id}/script/scenes/3/move", json={"expected_version": 2, "target": 0}
    )
    reseeded = await api.client.post(
        f"{base}/{job_id}/script/scenes/0/reseed", json={"expected_version": 3}
    )
    removed = await api.client.delete(
        f"{base}/{job_id}/script/scenes/0", params={"expected_version": 4}
    )
    assert [r.status_code for r in (moved, reseeded, removed)] == [200, 200, 200]
    assert removed.json()["script_version"] == 5
    regen = await api.client.post(
        f"{base}/{job_id}/script/regenerate", json={"scene_index": 1, "feedback": "mais leve"}
    )
    assert regen.status_code == 202 and regen.json()["status"] == "scripting"
    assert (await api.settle(job_id))["script_version"] == 6


async def test_controle_do_job(api: ApiHarness) -> None:
    job_id = await _job(api)
    clone = await api.client.post(f"/api/v1/jobs/{job_id}/clone")
    assert clone.status_code == 201 and clone.json()["script_version"] == 1
    canceled = await api.client.post(f"/api/v1/jobs/{job_id}/cancel")
    assert canceled.json()["status"] == "canceled"
    retry = await api.client.post(f"/api/v1/jobs/{job_id}/retry")
    assert (retry.status_code, retry.json()["code"]) == (409, "INVALID_STATE")
    listed = (await api.client.get("/api/v1/jobs")).json()
    assert {item["job_id"] for item in listed} == {job_id, clone.json()["job_id"]}


@pytest.mark.parametrize(
    ("body", "status", "code"),
    [
        ({"n_cenas": 99}, 422, "VALIDATION_ERROR"),
        ({"models": {"llm": "x", "tts": "f5-tts", "video": "wan-2.1-t2v-480p"}}, 404, "NOT_FOUND"),
        (
            {"models": {"llm": "deepseek-flash", "tts": "f5-tts", "video": "cogvideox-5b"}},
            422,
            "VALIDATION_FAILED",
        ),
    ],
)
async def test_pedidos_invalidos(
    api: ApiHarness, body: dict[str, Any], status: int, code: str
) -> None:
    response = await api.client.post("/api/v1/jobs", json=api.job_body(**body))
    assert (response.status_code, response.json()["code"]) == (status, code)
    assert response.headers["content-type"] == "application/problem+json"


async def test_visao_do_job_nao_vaza_detalhes_internos(api: ApiHarness) -> None:
    job_id = await _job(api)
    await api.client.post(f"/api/v1/jobs/{job_id}/approve", json={"script_version": 1})
    text = (await api.client.get(f"/api/v1/jobs/{job_id}")).text
    assert "remote_id" not in text and "artifact_hash" not in text and "_cache" not in text
    assert (await api.client.get("/api/v1/jobs/job_ffffffffffff")).status_code == 404
    assert (await api.client.get("/api/v1/jobs/..%2F..%2Fetc")).status_code in (404, 422)
