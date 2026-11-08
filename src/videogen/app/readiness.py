"""`/readyz`: toolchain, workspace gravável e algum modelo de roteiro utilizável."""

import asyncio
import os
from pathlib import Path

from videogen.composer.healthcheck import ToolchainCheck
from videogen.providers.catalog.registry import ProviderRegistry


class ReadinessCheck:
    def __init__(
        self, toolchain: ToolchainCheck, jobs_dir: Path, registry: ProviderRegistry
    ) -> None:
        self._toolchain = toolchain
        self._jobs_dir = jobs_dir
        self._registry = registry

    async def problems(self) -> list[str]:
        problems = list((await self._toolchain.run()).problems)
        if problem := await asyncio.to_thread(_workspace_problem, self._jobs_dir):
            problems.append(problem)
        if not self._registry.available("llm"):
            problems.append("nenhum modelo de roteiro disponível (credenciais?)")
        return problems


def _workspace_problem(directory: Path) -> str | None:
    if not directory.is_dir():
        return f"workspace inexistente: {directory}"
    if not os.access(directory, os.W_OK):
        return f"workspace sem permissão de escrita: {directory}"
    return None
