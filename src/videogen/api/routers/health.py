"""Sondas sem autenticação: `/healthz` (vivo) e `/readyz` (pronto para trabalhar)."""

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from videogen.api.deps import Services
from videogen.api.error_handlers import problem

router = APIRouter(tags=["health"])


@router.get("/healthz")
async def healthz() -> dict[str, str]:
    """Processo vivo e respondendo."""
    return {"status": "ok"}


@router.get("/readyz", response_model=None)
async def readyz(services: Services) -> dict[str, str] | JSONResponse:
    problems = await services.health.problems()
    if problems:
        return problem(503, "NOT_READY", "dependências indisponíveis", problems=problems)
    return {"status": "ready"}
