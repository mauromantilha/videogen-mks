"""T-024: downloader seguro (allowlist, redirects, limite de tamanho, retry)."""

from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest
import respx

from videogen.core.errors import ProviderError
from videogen.core.retry import RetryPolicy
from videogen.infra.downloader import HttpDownloader, ensure_allowed

HOSTS = ["replicate.delivery", "*.fal.media"]
URL = "https://replicate.delivery/pbxt/abc/out.mp4"


@pytest.fixture
async def downloader() -> AsyncIterator[HttpDownloader]:
    async with httpx.AsyncClient() as client:
        yield HttpDownloader(client, RetryPolicy(max_attempts=3, base_delay_s=0))


async def _fetch(
    downloader: HttpDownloader, dest: Path, url: str = URL, max_bytes: int = 100
) -> None:
    await downloader.fetch(url, dest, allowed_hosts=HOSTS, max_bytes=max_bytes)


@pytest.mark.parametrize(
    "url",
    [
        "https://v3.fal.media/files/x.mp4",
        "https://replicate.delivery/x.wav",
        "HTTPS://Replicate.Delivery/x.wav",
    ],
)
def test_hosts_permitidos(url: str) -> None:
    ensure_allowed(url, HOSTS)


@pytest.mark.parametrize(
    "url",
    [
        "http://replicate.delivery/x.mp4",  # sem TLS
        "https://evil.com/x.mp4",
        "https://replicate.delivery.evil.com/x.mp4",
        "https://fal.media/x.mp4",  # "*.fal.media" não inclui o domínio raiz
        "https://evilfal.media/x.mp4",
        "https://user:pass@replicate.delivery/x.mp4",
        "https://169.254.169.254/latest/meta-data",
        "file:///etc/passwd",
    ],
)
def test_hosts_recusados(url: str) -> None:
    with pytest.raises(ProviderError):
        ensure_allowed(url, HOSTS)


@respx.mock
async def test_download_ok(downloader: HttpDownloader, tmp_path: Path) -> None:
    respx.get(URL).respond(200, content=b"video-bytes")
    dest = tmp_path / "out.mp4"
    await _fetch(downloader, dest)
    assert dest.read_bytes() == b"video-bytes"
    assert list(tmp_path.iterdir()) == [dest]


@respx.mock
async def test_retry_em_503_e_depois_sucesso(downloader: HttpDownloader, tmp_path: Path) -> None:
    route = respx.get(URL)
    route.side_effect = [httpx.Response(503), httpx.Response(200, content=b"ok")]
    await _fetch(downloader, tmp_path / "out.mp4")
    assert route.call_count == 2


@respx.mock
async def test_erro_de_rede_e_retryable(downloader: HttpDownloader, tmp_path: Path) -> None:
    route = respx.get(URL)
    route.side_effect = [httpx.ConnectError("caiu"), httpx.Response(200, content=b"ok")]
    await _fetch(downloader, tmp_path / "out.mp4")
    assert route.call_count == 2


@respx.mock
async def test_404_nao_e_repetido(downloader: HttpDownloader, tmp_path: Path) -> None:
    route = respx.get(URL).respond(404)
    with pytest.raises(ProviderError, match="404"):
        await _fetch(downloader, tmp_path / "out.mp4")
    assert route.call_count == 1


@respx.mock
async def test_redirect_para_host_proibido(downloader: HttpDownloader, tmp_path: Path) -> None:
    respx.get(URL).respond(302, headers={"location": "https://evil.com/x.mp4"})
    evil = respx.get("https://evil.com/x.mp4").respond(200, content=b"x")
    with pytest.raises(ProviderError, match="allowlist"):
        await _fetch(downloader, tmp_path / "out.mp4")
    assert evil.call_count == 0


@respx.mock
async def test_redirect_permitido_e_seguido(downloader: HttpDownloader, tmp_path: Path) -> None:
    target = "https://v3.fal.media/final.mp4"
    respx.get(URL).respond(302, headers={"location": target})
    respx.get(target).respond(200, content=b"ok")
    await _fetch(downloader, tmp_path / "out.mp4")


@respx.mock
@pytest.mark.parametrize("declared", [True, False])
async def test_corpo_acima_do_limite_aborta_e_remove_parcial(
    downloader: HttpDownloader, tmp_path: Path, declared: bool
) -> None:
    body = b"x" * 150
    headers = {} if declared else {"content-length": ""}
    respx.get(URL).respond(200, content=body, headers=headers)
    with pytest.raises(ProviderError, match="limite"):
        await _fetch(downloader, tmp_path / "out.mp4", max_bytes=100)
    assert list(tmp_path.iterdir()) == []
