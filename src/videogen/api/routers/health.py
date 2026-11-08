"""Sondas de saúde. `/readyz` (toolchain, workspace, catálogo) chega na T-066."""

from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/healthz")
async def healthz() -> dict[str, str]:
    """Processo vivo e respondendo."""
    return {"status": "ok"}
