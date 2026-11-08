"""T-032: catálogo (YAML real e inválidos), preços e registry real/fake."""

from pathlib import Path
from typing import Any

import pytest
from pydantic import SecretStr, ValidationError

from tests.fakes.net import FAST_POLICY
from videogen.core.config import ConfigError, ProviderSettings
from videogen.core.errors import NotFound, ValidationFailed
from videogen.domain.catalog import ModelCatalog, ModelSpec, Price, VideoLimits
from videogen.ports.llm import LLMProvider
from videogen.providers.catalog.context import ProviderContext
from videogen.providers.catalog.loader import load_catalog, parse_catalog
from videogen.providers.catalog.registry import ProviderRegistry
from videogen.providers.deepseek.llm import OpenAICompatibleLLM
from videogen.providers.fake.llm import FakeLLM
from videogen.providers.fake.tts import FakeTTS
from videogen.providers.fake.video import FakeVideo
from videogen.providers.replicate.tts import ReplicateTTS
from videogen.providers.replicate.video import ReplicateVideo

ROOT = Path(__file__).resolve().parents[3]
CATALOG = load_catalog(ROOT / "config/models.yaml")
TTS_SPEC: dict[str, Any] = {
    "key": "t",
    "kind": "tts",
    "provider": "replicate",
    "remote_ref": "o/n",
    "fields": {"text": "gen_text", "ref_audio": "ref_audio"},
    "price": {"unit": "per_run"},
    "allowed_hosts": ["replicate.delivery"],
}


def _registry(
    tmp_path: Path, mode: str, catalog: ModelCatalog = CATALOG, **keys: str
) -> ProviderRegistry:
    settings = ProviderSettings(
        _env_file=None, provider_mode=mode, **{k: SecretStr(v) for k, v in keys.items()}
    )
    context = ProviderContext(settings, FAST_POLICY, tmp_path)
    return ProviderRegistry(catalog, context, mode=mode)  # type: ignore[arg-type]


def _with_unverified(key: str) -> ModelCatalog:
    models = dict(CATALOG.models)
    models[key] = models[key].model_copy(update={"verified": False})
    return ModelCatalog(models=models)


def test_catalogo_do_repositorio_e_valido() -> None:
    assert {"deepseek-flash", "f5-tts", "wan-2.1-t2v-480p"} <= CATALOG.models.keys()
    assert CATALOG.get("wan-2.1-t2v-480p", "t2v").limits is not None


def test_modelos_do_replicate_tem_versao_fixada() -> None:
    for spec in CATALOG.models.values():
        if spec.provider == "replicate":
            assert spec.verified and spec.version and len(spec.version) == 64, spec.key


@pytest.mark.parametrize(
    "raw",
    [
        None,
        {"version": 2, "models": {"x": {}}},
        {"version": 1, "models": {}},
        {"version": 1, "models": {"x": {"kind": "llm"}}},
    ],
)
def test_catalogo_invalido_nao_sobe(raw: object) -> None:
    with pytest.raises(ConfigError):
        parse_catalog(raw)


@pytest.mark.parametrize(
    "overrides",
    [{"fields": {"text": "gen_text"}}, {"allowed_hosts": []}, {"kind": "t2v"}],
)
def test_spec_real_incompleta(overrides: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        ModelSpec.model_validate(TTS_SPEC | overrides)


def test_busca_por_tipo() -> None:
    with pytest.raises(NotFound):
        CATALOG.get("nao-existe", "llm")
    with pytest.raises(ValidationFailed):
        CATALOG.get("f5-tts", "llm")
    with pytest.raises(ValidationFailed, match="proporção"):
        CATALOG.get("cogvideox-5b", "t2v").limits.size_for("9:16")  # type: ignore[union-attr]


def test_precos() -> None:
    assert Price(unit="per_run", usd=0.09).estimate() == 0.09
    per_second = Price(unit="per_second", usd=0.001, estimated_seconds=40)
    assert per_second.estimate() == pytest.approx(0.04)
    assert per_second.actual(seconds=12) == pytest.approx(0.012)
    tokens = Price(unit="per_mtok", input_usd=0.3, output_usd=1.2, usd=0.003)
    assert tokens.actual(prompt_tokens=1_000_000, completion_tokens=500_000) == pytest.approx(0.9)
    assert tokens.actual() == 0.003
    assert VideoLimits(fps=16, num_frames=81, sizes={}).duration_s == pytest.approx(5.0625)


def test_modo_fake_usa_simuladores_e_reaproveita_instancia(tmp_path: Path) -> None:
    registry = _registry(tmp_path, "fake")
    assert isinstance(registry.llm("deepseek-v4-pro"), FakeLLM)
    assert isinstance(registry.tts("f5-tts"), FakeTTS)
    assert isinstance(registry.video("cogvideox-5b"), FakeVideo)
    assert registry.tts("f5-tts") is registry.tts("f5-tts")
    assert len(registry.available("t2v")) == 3


def test_modo_real_monta_adapters_reais(tmp_path: Path) -> None:
    registry = _registry(tmp_path, "real", deepseek_api_key="sk-x", replicate_api_token="r8_x")
    llm = registry.llm("deepseek-flash")
    assert isinstance(llm, OpenAICompatibleLLM) and isinstance(llm, LLMProvider)
    assert isinstance(registry.tts("f5-tts"), ReplicateTTS)
    assert isinstance(registry.video("wan-2.1-t2v-480p"), ReplicateVideo)
    assert len(registry.available("t2v")) == 3


def test_modo_real_recusa_modelo_nao_verificado(tmp_path: Path) -> None:
    catalog = _with_unverified("f5-tts")
    registry = _registry(tmp_path, "real", catalog, replicate_api_token="r8_x")
    with pytest.raises(ConfigError, match="verificado"):
        registry.tts("f5-tts")
    assert registry.available("tts") == []


def test_modo_real_sem_credencial(tmp_path: Path) -> None:
    registry = _registry(tmp_path, "real", replicate_api_token="r8_x")
    assert [spec.key for spec in registry.available("llm")] == []
    with pytest.raises(ConfigError, match="DEEPSEEK_API_KEY"):
        registry.llm("deepseek-flash")
