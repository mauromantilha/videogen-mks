"""Contrato do LLMProvider: adapter OpenAI-compatível (respx) e FakeLLM (T-033, T-036)."""

import json
from pathlib import Path

import httpx
import pytest
import respx

from tests.fakes.net import FAST_POLICY, Sleeper
from videogen.core.errors import ContentRejected, ProviderError
from videogen.domain.catalog import ModelSpec
from videogen.domain.script import VideoScriptSchema
from videogen.ports.llm import ChatMessage, LLMProvider
from videogen.providers.catalog.loader import load_catalog
from videogen.providers.deepseek.llm import OpenAICompatibleLLM
from videogen.providers.fake.llm import FakeLLM
from videogen.providers.http.client import ResilientHttpClient

URL = "https://api.deepseek.com/chat/completions"
CATALOG = load_catalog(Path(__file__).resolve().parents[2] / "config/models.yaml")
MESSAGES = [
    ChatMessage(role="system", content="Responda em json."),
    ChatMessage(role="user", content="Tema: Seguro de vida\nGere 4 cenas."),
]


def _completion(content: str, finish: str = "stop") -> dict[str, object]:
    return {
        "choices": [{"message": {"content": content}, "finish_reason": finish}],
        "usage": {"prompt_tokens": 1000, "completion_tokens": 500},
    }


def _llm(key: str = "deepseek-flash") -> OpenAICompatibleLLM:
    http = ResilientHttpClient(
        httpx.AsyncClient(), FAST_POLICY, provider="deepseek", sleep=Sleeper()
    )
    return OpenAICompatibleLLM(http, CATALOG.get(key, "llm"))


@respx.mock
async def test_flash_envia_json_mode_temperatura_e_thinking_desligado() -> None:
    route = respx.post(URL).respond(200, json=_completion('{"a": 1}'))
    result = await _llm().complete(MESSAGES, json_mode=True, temperature=0.7)
    body = json.loads(route.calls.last.request.content)
    assert body["model"] == "deepseek-flash"
    assert body["response_format"] == {"type": "json_object"}
    assert body["thinking"] == {"type": "disabled"}
    assert (body["temperature"], body["max_tokens"], body["stream"]) == (0.7, 4096, False)
    assert result.text == '{"a": 1}'
    assert result.cost_usd == pytest.approx((1000 * 0.30 + 500 * 1.20) / 1_000_000)


@respx.mock
async def test_pro_com_thinking_nao_envia_temperatura_nem_json_mode() -> None:
    route = respx.post(URL).respond(200, json=_completion("ok"))
    await _llm("deepseek-v4-pro").complete(MESSAGES, json_mode=True, temperature=0.7)
    body = json.loads(route.calls.last.request.content)
    assert body["thinking"] == {"type": "enabled"}
    assert "temperature" not in body and "response_format" not in body


@respx.mock
async def test_conteudo_so_com_espacos_e_repetido() -> None:
    route = respx.post(URL)
    route.side_effect = [
        httpx.Response(200, json=_completion("   ")),
        httpx.Response(200, json=_completion('{"ok": 1}')),
    ]
    assert (await _llm().complete(MESSAGES, json_mode=True, temperature=None)).text == '{"ok": 1}'
    assert route.call_count == 2


@respx.mock
async def test_filtro_de_conteudo_vira_content_rejected() -> None:
    respx.post(URL).respond(200, json=_completion("", finish="content_filter"))
    with pytest.raises(ContentRejected):
        await _llm().complete(MESSAGES, json_mode=True, temperature=None)


@respx.mock
@pytest.mark.parametrize(("status", "calls"), [(401, 1), (402, 1), (503, 3)])
async def test_erros_http(status: int, calls: int) -> None:
    route = respx.post(URL).respond(status, json={"error": {"message": "x"}})
    with pytest.raises(ProviderError):
        await _llm().complete(MESSAGES, json_mode=True, temperature=None)
    assert route.call_count == calls


async def test_fake_llm_gera_roteiro_valido_com_n_cenas_pedido() -> None:
    llm = FakeLLM()
    assert isinstance(llm, LLMProvider)
    result = await llm.complete(MESSAGES, json_mode=True, temperature=0.7)
    script = VideoScriptSchema.model_validate_json(result.text)
    assert (len(script.cenas), script.produto_tema) == (4, "Seguro de vida")


async def test_fake_llm_devolve_respostas_roteirizadas_em_ordem() -> None:
    llm = FakeLLM(["primeira", "segunda"])
    texts = [
        (await llm.complete(MESSAGES, json_mode=True, temperature=None)).text for _ in range(3)
    ]
    assert texts[:2] == ["primeira", "segunda"]
    assert len(llm.calls) == 3


def test_spec_llm_usa_base_url_configuravel() -> None:
    spec = ModelSpec(
        key="x",
        kind="llm",
        provider="deepinfra",
        remote_ref="m",
        capabilities={"base_url": "https://api.deepinfra.com/v1/openai/"},
        price={"unit": "per_call"},
    )  # type: ignore[arg-type]
    http = ResilientHttpClient(httpx.AsyncClient(), FAST_POLICY, provider="deepinfra")
    assert OpenAICompatibleLLM(http, spec)._url == (
        "https://api.deepinfra.com/v1/openai/chat/completions"
    )
