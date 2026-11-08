"""Cliente REST do Replicate: criar, consultar, aguardar e cancelar predições (ADR-02)."""

import logging
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from videogen.core.errors import ProviderError
from videogen.providers.http.client import HttpCall, JsonObject, ResilientHttpClient
from videogen.providers.http.polling import PollSchedule, poll_until

logger = logging.getLogger(__name__)
API = "https://api.replicate.com/v1"
Status = Literal["starting", "processing", "succeeded", "failed", "canceled", "aborted"]
TERMINAL: frozenset[str] = frozenset({"succeeded", "failed", "canceled", "aborted"})


class Prediction(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    status: Status
    output: Any = None
    error: Any = None
    metrics: dict[str, float] = Field(default_factory=dict)

    @property
    def terminal(self) -> bool:
        return self.status in TERMINAL


class ReplicateClient:
    def __init__(self, http: ResilientHttpClient, schedule: PollSchedule | None = None) -> None:
        self._http = http
        self._schedule = schedule or PollSchedule()

    async def create(self, remote_ref: str, version: str | None, payload: JsonObject) -> Prediction:
        """Sem `version`, usa o endpoint de modelo oficial (`/models/{owner}/{name}`)."""
        if version:
            call = HttpCall(
                "POST",
                f"{API}/predictions",
                idempotent=False,
                json_body={"version": version, "input": payload},
            )
        else:
            call = HttpCall(
                "POST",
                f"{API}/models/{remote_ref}/predictions",
                idempotent=False,
                json_body={"input": payload},
            )
        return await self._http.request(call, Prediction.model_validate)

    async def get(self, prediction_id: str) -> Prediction:
        call = HttpCall("GET", f"{API}/predictions/{prediction_id}", idempotent=True)
        return await self._http.request(call, Prediction.model_validate)

    async def wait(self, prediction_id: str, *, timeout_s: float) -> Prediction:
        return await poll_until(
            lambda: self.get(prediction_id),
            lambda prediction: prediction.terminal,
            timeout_s=timeout_s,
            schedule=self._schedule,
            label=f"predição {prediction_id}",
        )

    async def cancel(self, prediction_id: str) -> None:
        """Best-effort e idempotente: falha ao cancelar só é logada."""
        call = HttpCall("POST", f"{API}/predictions/{prediction_id}/cancel", idempotent=True)
        try:
            await self._http.request_json(call)
        except ProviderError as exc:
            logger.warning(
                "cancelamento não confirmado",
                extra={"remote_id": prediction_id, "error_code": exc.code},
            )
