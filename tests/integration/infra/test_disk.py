"""T-020…T-022 com disco real: workspace seguro, escrita atômica e detalhes do cache."""

import json
import os
from pathlib import Path

import pytest

from tests.fakes.builders import JOB_ID, VOICE_ID, make_job
from tests.fakes.fake_clock import FakeClock
from videogen.core.errors import NotFound
from videogen.domain.media import ArtifactKind
from videogen.infra.artifact_cache import FileArtifactCache
from videogen.infra.atomic_file import write_atomic
from videogen.infra.job_repository import JsonJobRepository
from videogen.infra.workspace import Workspace

KEY = "ab" + "c" * 62


@pytest.fixture
def workspace(tmp_path: Path) -> Workspace:
    ws = Workspace(tmp_path / "ws")
    ws.ensure_layout()
    return ws


def test_layout_e_caminhos(workspace: Workspace) -> None:
    assert workspace.job_state_path(JOB_ID) == workspace.jobs_dir / JOB_ID / "job_state.json"
    assert workspace.script_snapshot_path(JOB_ID, 3).name == "v0003.json"
    assert workspace.scene_dir(JOB_ID, 4).name == "scene_04"
    assert workspace.voice_dir(VOICE_ID).parent == workspace.voices_dir
    workspace.ensure_layout()  # idempotente


@pytest.mark.parametrize("bad", ["../../etc", "job_0123456789ab/../x", "JOB_0123456789AB"])
def test_ids_maliciosos_sao_recusados(workspace: Workspace, bad: str) -> None:
    with pytest.raises(NotFound):
        workspace.job_dir(bad)


def test_symlink_para_fora_do_workspace_e_recusado(workspace: Workspace, tmp_path: Path) -> None:
    outside = tmp_path / "fora"
    outside.mkdir()
    (workspace.jobs_dir / JOB_ID).symlink_to(outside)
    with pytest.raises(NotFound):
        workspace.job_dir(JOB_ID)


@pytest.mark.parametrize("index", [-1, 100])
def test_indice_de_cena_fora_da_faixa(workspace: Workspace, index: int) -> None:
    with pytest.raises(ValueError, match="scene_index"):
        workspace.scene_dir(JOB_ID, index)


def test_falha_entre_tmp_e_replace_preserva_o_arquivo_anterior(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "estado.json"
    write_atomic(target, b"antigo")

    def crash(*_: object) -> None:
        raise OSError("energia caiu")

    monkeypatch.setattr(os, "replace", crash)
    with pytest.raises(OSError, match="energia"):
        write_atomic(target, b"novo")
    assert target.read_bytes() == b"antigo"
    assert [p.name for p in tmp_path.iterdir()] == ["estado.json"]  # sem lixo .tmp


async def test_manifesto_legivel_e_lista_ignora_corrompido(workspace: Workspace) -> None:
    repo = JsonJobRepository(workspace, FakeClock())
    await repo.create(make_job())
    raw = json.loads(workspace.job_state_path(JOB_ID).read_text())
    assert raw["job_id"] == JOB_ID and raw["status"] == "awaiting_approval"
    broken = workspace.jobs_dir / "job_ffffffffffff"
    broken.mkdir()
    (broken / "job_state.json").write_text("{ isto não é json")
    assert [job.job_id for job in await repo.list_all()] == [JOB_ID]


def _commit(cache: FileArtifactCache, kind: ArtifactKind = ArtifactKind.CLIP) -> Path:
    tmp = cache.tmp_path(kind, KEY)
    tmp.write_bytes(b"mp4")
    return cache.commit(kind, KEY, tmp, {"remote_id": "pred-1"})


def test_layout_do_cache_e_meta(tmp_path: Path) -> None:
    cache = FileArtifactCache(tmp_path)
    final = _commit(cache)
    assert final == tmp_path / "clip" / "ab" / f"{KEY}.mp4"
    assert cache.meta(ArtifactKind.CLIP, KEY) == {
        "remote_id": "pred-1",
        "kind": "clip",
        "key": KEY,
        "size": 3,
    }
    assert cache.tmp_path(ArtifactKind.AUDIO_RAW, KEY).suffix == ".wav"  # FFmpeg infere o formato


def test_arquivo_sem_meta_ou_vazio_nao_e_hit(tmp_path: Path) -> None:
    cache = FileArtifactCache(tmp_path)
    final = _commit(cache)
    final.with_name(f"{KEY}.meta.json").unlink()  # crash entre dado e meta
    assert cache.get(ArtifactKind.CLIP, KEY) is None
    empty = cache.tmp_path(ArtifactKind.CLIP, KEY)
    empty.touch()
    with pytest.raises(ValueError, match="vazio"):
        cache.commit(ArtifactKind.CLIP, KEY, empty, {})


@pytest.mark.parametrize("bad", ["../../etc/passwd", "abc", "A" * 64])
def test_chave_de_cache_deve_ser_sha256(tmp_path: Path, bad: str) -> None:
    with pytest.raises(ValueError, match="SHA-256"):
        FileArtifactCache(tmp_path).get(ArtifactKind.CLIP, bad)


def test_view_de_cena_e_limpeza_de_parciais(tmp_path: Path) -> None:
    cache = FileArtifactCache(tmp_path / "cache")
    final = _commit(cache)
    view = cache.link_into(tmp_path / "scene_00" / "clip.mp4", ArtifactKind.CLIP, KEY)
    assert view.read_bytes() == final.read_bytes()
    cache.link_into(view, ArtifactKind.CLIP, KEY)  # recriar não falha
    cache.tmp_path(ArtifactKind.CLIP, KEY).write_bytes(b"lixo")
    assert cache.remove_partials() == 1
    assert [key for _, key, _ in cache.entries()] == [KEY]
    with pytest.raises(FileNotFoundError):
        cache.link_into(tmp_path / "x.mp4", ArtifactKind.FINAL, KEY)
