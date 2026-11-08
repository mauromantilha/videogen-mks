"""T-030/T-031: classificação de erros, cliente resiliente e polling."""

from datetime import UTC, datetime

import httpx
import pytest
import respx

from tests.fakes.net import FAST_POLICY, Sleeper
from videogen.core.errors import ContentRejected, ProviderError, ProviderTimeout
from videogen.providers.http.client import HttpCall, ResilientHttpClient
from videogen.providers.http.errors import (
    classify_response,
    extract_detail,
    parse_retry_after,
    transport_error,
)
from videogen.providers.http.polling import poll_until

URL = "https://api.example.com/v1/x"


@pytest.mark.parametrize(
    ("status", "retryable"),
    [
        (400, False),
        (401, False),
        (402, False),
        (404, False),
        (422, False),
        (408, True),
        (429, True),
        (500, True),
        (502, True),
        (503, True),
        (504, True),
    ],
)
def test_classificacao_por_status(status: int, retryable: bool) -> None:
    error = classify_response(status, '{"detail": "x"}', {}, provider="p")
    assert error.retryable is retryable
    assert error.context["status"] == status


def test_retry_after_e_conteudo_recusado() -> None:
    error = classify_response(429, "{}", {"retry-after": "12"}, provider="p")
    assert error.context["retry_after_s"] == 12.0
    rejected = classify_response(422, '{"detail": "NSFW content detected"}', {}, provider="p")
    assert isinstance(rejected, ContentRejected) and not rejected.retryable


def test_parse_retry_after() -> None:
    now = datetime(2026, 11, 8, 12, 0, tzinfo=UTC)
    assert parse_retry_after("Sun, 08 Nov 2026 12:00:30 GMT", now) == 30.0
    assert parse_retry_after("lixo") is None
    assert parse_retry_after(None) is None


@pytest.mark.parametrize(
    ("body", "detail"),
    [
        ('{"detail": "throttled"}', "throttled"),
        ('{"error": {"message": "sem saldo"}}', "sem saldo"),
        ("texto puro", "texto puro"),
    ],
)
def test_extrai_detalhe(body: str, detail: str) -> None:
    assert extract_detail(body) == detail


@pytest.mark.parametrize(
    ("exc", "idempotent", "retryable"),
    [
        (httpx.ConnectError("x"), False, True),  # antes de enviar: seguro repetir
        (httpx.ReadTimeout("x"), False, False),  # pedido talvez aceito: não repetir submit
        (httpx.ReadTimeout("x"), True, True),
        (httpx.RemoteProtocolError("x"), False, False),
    ],
)
def test_erro_de_transporte(exc: httpx.TransportError, idempotent: bool, retryable: bool) -> None:
    assert transport_error(exc, provider="p", idempotent=idempotent).retryable is retryable
    if isinstance(exc, httpx.TimeoutException):
        assert isinstance(
            transport_error(exc, provider="p", idempotent=idempotent), ProviderTimeout
        )


@pytest.fixture
async def http() -> ResilientHttpClient:
    return ResilientHttpClient(httpx.AsyncClient(), FAST_POLICY, provider="p", sleep=Sleeper())


@respx.mock
async def test_cliente_repete_429_e_ignora_linhas_de_keep_alive(http: ResilientHttpClient) -> None:
    route = respx.post(URL)
    route.side_effect = [httpx.Response(429), httpx.Response(200, text='\n\n  {"ok": true}')]
    assert await http.request_json(HttpCall("POST", URL, idempotent=False)) == {"ok": True}
    assert route.call_count == 2


@respx.mock
async def test_submit_nao_e_repetido_apos_timeout_de_leitura(http: ResilientHttpClient) -> None:
    route = respx.post(URL)
    route.side_effect = httpx.ReadTimeout("x")
    with pytest.raises(ProviderTimeout):
        await http.request_json(HttpCall("POST", URL, idempotent=False))
    assert route.call_count == 1


@respx.mock
@pytest.mark.parametrize(("body", "retryable"), [("", True), ("<html>", False), ("[1]", False)])
async def test_corpos_invalidos(http: ResilientHttpClient, body: str, retryable: bool) -> None:
    route = respx.get(URL).respond(200, text=body)
    with pytest.raises(ProviderError):
        await http.request_json(HttpCall("GET", URL, idempotent=True))
    assert route.call_count == (3 if retryable else 1)


@respx.mock
async def test_parse_pode_pedir_nova_tentativa(http: ResilientHttpClient) -> None:
    respx.get(URL).respond(200, json={"n": 1})
    seen: list[int] = []

    def parse(data: dict[str, int]) -> int:
        seen.append(data["n"])
        if len(seen) < 2:
            raise ProviderError("conteúdo vazio", retryable=True)
        return data["n"]

    assert await http.request(HttpCall("GET", URL, idempotent=True), parse) == 1
    assert len(seen) == 2


async def test_polling_cresce_ate_o_teto_e_respeita_prazo() -> None:
    sleeper = Sleeper()
    states = iter(["a", "b", "c", "d", "pronto"])

    async def fetch() -> str:
        return next(states)

    assert (
        await poll_until(fetch, lambda s: s == "pronto", timeout_s=60, schedule=sleeper.schedule())
        == "pronto"
    )
    assert sleeper.calls == [2.0, 3.0, 4.5, 5.0]

    async def never() -> str:
        return "rodando"

    with pytest.raises(ProviderTimeout):
        await poll_until(never, lambda s: False, timeout_s=10, schedule=Sleeper().schedule())
