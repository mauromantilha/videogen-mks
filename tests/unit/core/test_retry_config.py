"""T-030 (retry) e T-004 (configuração fatiada)."""

from pathlib import Path

import pytest

from videogen.core.config import ConfigError, load_settings
from videogen.core.errors import ContentRejected, ProviderError
from videogen.core.retry import RetryPolicy, retry_async

ENV_VARS = [
    "PROVIDER_MODE",
    "DEEPSEEK_API_KEY",
    "REPLICATE_API_TOKEN",
    "FAL_KEY",
    "DEEPINFRA_API_TOKEN",
    "APP_ENV",
    "AUTH_MODE",
    "NEON_AUTH_URL",
    "APP_PUBLIC_URL",
    "DATABASE_URL",
    "MAX_PARALLEL_VIDEO",
    "SYNC_STRETCH_MIN",
    "SYNC_STRETCH_MAX",
]

PROD_NEON = {"APP_ENV": "prod", "AUTH_MODE": "neon", "NEON_AUTH_URL": "https://x/auth"}


class Flaky:
    def __init__(self, failures: list[Exception]) -> None:
        self.failures = failures
        self.calls = 0

    async def __call__(self) -> str:
        self.calls += 1
        if self.failures:
            raise self.failures.pop(0)
        return "ok"


async def _run(operation: Flaky, policy: RetryPolicy | None = None) -> tuple[str, list[float]]:
    sleeps: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    policy = policy or RetryPolicy()
    result = await retry_async(operation, policy, sleep=fake_sleep, rng=lambda: 1.0)
    return result, sleeps


async def test_repete_erros_retryable_com_backoff_exponencial() -> None:
    operation = Flaky([ProviderError("503", retryable=True)] * 2)
    assert await _run(operation) == ("ok", [1.0, 2.0])
    assert operation.calls == 3


async def test_desiste_apos_max_tentativas() -> None:
    operation = Flaky([ProviderError("503", retryable=True)] * 5)
    with pytest.raises(ProviderError):
        await _run(operation)
    assert operation.calls == 3


@pytest.mark.parametrize(
    "error", [ProviderError("422"), ContentRejected("nsfw"), ValueError("bug")]
)
async def test_nao_repete_erro_nao_retryable(error: Exception) -> None:
    operation = Flaky([error])
    with pytest.raises(type(error)):
        await _run(operation)
    assert operation.calls == 1


async def test_respeita_retry_after_com_teto() -> None:
    hinted = [
        ProviderError("429", retryable=True, retry_after_s=7),
        ProviderError("429", retryable=True, retry_after_s=999),
    ]
    _, sleeps = await _run(Flaky(hinted), RetryPolicy(max_delay_s=30))
    assert sleeps == [7.0, 30.0]


def test_jitter_e_teto_do_backoff() -> None:
    policy = RetryPolicy(base_delay_s=1, max_delay_s=5)
    assert policy.backoff(1, lambda: 0.5) == 0.5
    assert policy.backoff(10, lambda: 1.0) == 5.0
    with pytest.raises(ValueError):
        RetryPolicy(max_attempts=0)


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    for name in ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


def test_modo_fake_sobe_sem_credenciais(clean_env: pytest.MonkeyPatch) -> None:
    clean_env.setenv("PROVIDER_MODE", "fake")
    settings = load_settings(env_file=None)
    assert settings.render.max_parallel_video == 4
    assert settings.providers.configured() == frozenset()


def test_modo_real_sem_chave_nao_sobe(clean_env: pytest.MonkeyPatch) -> None:
    with pytest.raises(ConfigError, match="PROVIDER_MODE=fake"):
        load_settings(env_file=None)


def test_le_arquivo_env_e_esconde_segredos(clean_env: pytest.MonkeyPatch, tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text("REPLICATE_API_TOKEN=r8_segredo123\nMAX_PARALLEL_VIDEO=8\nFAL_KEY=\n")
    settings = load_settings(env_file=env)
    assert settings.providers.configured() == frozenset({"replicate"})
    assert settings.render.max_parallel_video == 8
    assert "r8_segredo123" not in repr(settings)


@pytest.mark.parametrize(
    ("variables", "message"),
    [
        ({"APP_ENV": "prod"}, "AUTH_MODE=neon"),
        ({"AUTH_MODE": "neon"}, "NEON_AUTH_URL"),
        (PROD_NEON | {"APP_PUBLIC_URL": "http://inseguro"}, "APP_PUBLIC_URL"),
        (PROD_NEON | {"APP_PUBLIC_URL": "https://video.exemplo.com"}, "DATABASE_URL"),
        (
            PROD_NEON | {"APP_PUBLIC_URL": "https://video.exemplo.com", "DATABASE_URL": " "},
            "DATABASE_URL",
        ),  # vazio no .env = não definido
        ({"MAX_PARALLEL_VIDEO": "0"}, "max_parallel_video"),
        ({"SYNC_STRETCH_MIN": "1.0", "SYNC_STRETCH_MAX": "1.0"}, "SYNC_STRETCH_MIN"),
    ],
)
def test_configuracoes_invalidas(
    clean_env: pytest.MonkeyPatch, variables: dict[str, str], message: str
) -> None:
    clean_env.setenv("PROVIDER_MODE", "fake")
    for name, value in variables.items():
        clean_env.setenv(name, value)
    with pytest.raises(ConfigError, match=message):
        load_settings(env_file=None)
