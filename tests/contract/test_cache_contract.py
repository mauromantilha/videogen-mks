"""Contrato do ArtifactCache: dublê e adapter de disco se comportam igual (T-022)."""

from pathlib import Path

import pytest

from tests.fakes.memory_cache import InMemoryArtifactCache
from videogen.domain.media import ArtifactKind
from videogen.infra.artifact_cache import FileArtifactCache
from videogen.ports.cache import ArtifactCache

KEY = "a" * 64
KIND = ArtifactKind.VIDEO_RAW


@pytest.fixture(params=["memory", "file"])
def cache(request: pytest.FixtureRequest, tmp_path: Path) -> ArtifactCache:
    if request.param == "memory":
        return InMemoryArtifactCache(tmp_path)
    return FileArtifactCache(tmp_path)


def test_implementa_o_port(cache: ArtifactCache) -> None:
    assert isinstance(cache, ArtifactCache)


def test_miss_antes_do_commit_e_hit_depois(cache: ArtifactCache) -> None:
    tmp = cache.tmp_path(KIND, KEY)
    tmp.write_bytes(b"conteudo")
    assert cache.get(KIND, KEY) is None
    final = cache.commit(KIND, KEY, tmp, {"remote_id": "p1"})
    assert cache.get(KIND, KEY) == final
    assert final.read_bytes() == b"conteudo"
    assert not tmp.exists()


def test_tipo_diferente_nao_colide(cache: ArtifactCache) -> None:
    tmp = cache.tmp_path(KIND, KEY)
    tmp.write_bytes(b"video")
    cache.commit(KIND, KEY, tmp, {})
    assert cache.get(ArtifactKind.AUDIO_RAW, KEY) is None


def test_temporarios_sao_exclusivos(cache: ArtifactCache) -> None:
    assert cache.tmp_path(KIND, KEY) != cache.tmp_path(KIND, KEY)


def test_commit_repetido_do_mesmo_hash_e_seguro(cache: ArtifactCache) -> None:
    for content in (b"primeiro", b"segundo"):
        tmp = cache.tmp_path(KIND, KEY)
        tmp.write_bytes(content)
        cache.commit(KIND, KEY, tmp, {})
    hit = cache.get(KIND, KEY)
    assert hit is not None and hit.read_bytes() == b"segundo"
