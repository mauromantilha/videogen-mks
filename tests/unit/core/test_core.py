"""T-005: erros, ids, relógio e logging."""

import json
import logging

import pytest

from videogen.core.clock import SystemClock
from videogen.core.errors import (
    ContentRejected,
    DomainError,
    NotFound,
    ProviderError,
    ProviderTimeout,
)
from videogen.core.ids import JOB_ID_RE, ensure_job_id, new_job_id, new_voice_id
from videogen.core.logging import JsonFormatter, log_context, redact


def test_erro_carrega_codigo_contexto_e_retryable() -> None:
    error = ProviderError("falhou", retryable=True, provider="replicate")
    assert (error.code, error.retryable, error.context) == (
        "PROVIDER_ERROR",
        True,
        {"provider": "replicate"},
    )
    assert ProviderTimeout("lento").retryable is True
    assert ContentRejected("nsfw").retryable is False
    assert isinstance(NotFound("x"), DomainError)


def test_ids_tem_formato_fixo_e_sao_unicos() -> None:
    ids = {new_job_id() for _ in range(100)}
    assert len(ids) == 100
    assert all(JOB_ID_RE.fullmatch(i) for i in ids)
    assert new_voice_id().startswith("voz_")


@pytest.mark.parametrize("bad", ["../etc/passwd", "job_ABC", "job_123", "job_0123456789ab/..", ""])
def test_id_malformado_e_tratado_como_inexistente(bad: str) -> None:
    with pytest.raises(NotFound):
        ensure_job_id(bad)


def test_relogio_do_sistema_e_utc() -> None:
    assert SystemClock().now().utcoffset() is not None


@pytest.mark.parametrize(
    ("text", "secret"),
    [
        ("Authorization: Bearer abc123def456", "abc123def456"),
        ('{"api_key": "chave-super-secreta"}', "chave-super-secreta"),
        ("REPLICATE_API_TOKEN=r8_AbCdEf123456789", "r8_AbCdEf123456789"),
        ("usando sk-1234567890abcdef no header", "sk-1234567890abcdef"),
        ("password=hunter22", "hunter22"),
    ],
)
def test_redacao_de_segredos(text: str, secret: str) -> None:
    redacted = redact(text)
    assert secret not in redacted
    assert "***" in redacted


def _record(message: str, **extra: object) -> logging.LogRecord:
    record = logging.makeLogRecord({"msg": message, "levelname": "INFO", "name": "teste"})
    for key, value in extra.items():
        setattr(record, key, value)
    return record


def test_log_json_inclui_contexto_extras_e_redige() -> None:
    with log_context(job_id="job_0123456789ab", scene_index=2):
        line = JsonFormatter().format(_record("token=segredo123", attempt=1))
    payload = json.loads(line)
    assert payload["job_id"] == "job_0123456789ab"
    assert payload["scene_index"] == 2
    assert payload["attempt"] == 1
    assert "segredo123" not in line


def test_contexto_de_log_e_restaurado_ao_sair() -> None:
    with log_context(job_id="job_0123456789ab"):
        pass
    assert "job_id" not in json.loads(JsonFormatter().format(_record("fora")))
