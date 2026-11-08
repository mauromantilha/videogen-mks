"""Fábricas de adapter por (tipo, provedor). Adicionar um provedor = uma linha aqui."""

from collections.abc import Callable

from videogen.domain.catalog import ModelKind, ModelSpec
from videogen.providers.catalog.context import ProviderContext
from videogen.providers.deepseek.llm import OpenAICompatibleLLM
from videogen.providers.fake.llm import FakeLLM
from videogen.providers.fake.tts import FakeTTS
from videogen.providers.fake.video import FakeVideo
from videogen.providers.replicate.client import ReplicateClient
from videogen.providers.replicate.runner import PredictionRunner
from videogen.providers.replicate.tts import ReplicateTTS
from videogen.providers.replicate.video import ReplicateVideo

Builder = Callable[[ModelSpec, ProviderContext], object]


def _openai_compatible(spec: ModelSpec, ctx: ProviderContext) -> object:
    return OpenAICompatibleLLM(ctx.http(spec.provider), spec)


def _replicate_runner(ctx: ProviderContext) -> PredictionRunner:
    client = ReplicateClient(ctx.http("replicate"))
    return PredictionRunner(client, max_attempts=ctx.policy.max_attempts)


def _replicate_tts(spec: ModelSpec, ctx: ProviderContext) -> object:
    return ReplicateTTS(_replicate_runner(ctx), spec)


def _replicate_video(spec: ModelSpec, ctx: ProviderContext) -> object:
    return ReplicateVideo(_replicate_runner(ctx), spec)


def _fake_llm(_: ModelSpec, __: ProviderContext) -> object:
    return FakeLLM()


def _fake_tts(_: ModelSpec, ctx: ProviderContext) -> object:
    return FakeTTS(ctx.fake_origin, ctx.fake_behavior)


def _fake_video(_: ModelSpec, ctx: ProviderContext) -> object:
    return FakeVideo(ctx.fake_origin, ctx.fake_behavior)


DEFAULT_BUILDERS: dict[tuple[ModelKind, str], Builder] = {
    ("llm", "deepseek"): _openai_compatible,
    ("llm", "deepinfra"): _openai_compatible,  # T-038: mesma API, outro base_url
    ("tts", "replicate"): _replicate_tts,
    ("t2v", "replicate"): _replicate_video,
    ("llm", "fake"): _fake_llm,
    ("tts", "fake"): _fake_tts,
    ("t2v", "fake"): _fake_video,
}
