#!/usr/bin/env python3
"""T-098: avalia a qualidade do roteiro por modelo (GERA CUSTO: ~US$ 0,003 por tema no flash).

Uso:  .venv/bin/python scripts/eval_scripts.py --models deepseek-flash deepseek-v4-pro --yes

Mede: % válido de primeira, % válido após reparo, nº médio de chamadas, palavras por cena e
custo. Sem `--yes` só mostra o plano. Usa as chaves do `.env`.
"""

import argparse
import asyncio
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from videogen.core.config import load_settings
from videogen.core.retry import RetryPolicy
from videogen.domain.request import JobRequest, ModelChoice
from videogen.domain.script_rules import count_words
from videogen.providers.catalog.context import ProviderContext
from videogen.providers.catalog.loader import load_catalog
from videogen.providers.catalog.registry import ProviderRegistry
from videogen.services.script.prompts import draft_messages
from videogen.services.script.repair import ScriptRepairLoop

THEMES = (
    "Seguro de vida para jovens profissionais",
    "Plano de saúde para pequenas empresas",
    "Seguro auto com assistência 24 horas",
    "Previdência privada para autônomos",
    "Seguro residencial contra enchentes",
    "Seguro viagem para intercâmbio",
    "Seguro para celular contra roubo",
    "Consórcio de imóveis para o primeiro apartamento",
    "Seguro de responsabilidade civil para médicos",
    "Seguro pet para cães e gatos",
)


async def evaluate(model: str, themes: list[str], registry: ProviderRegistry) -> dict[str, float]:
    loop, llm = ScriptRepairLoop(), registry.llm(model)
    first_try = valid = calls = 0
    cost, words = 0.0, []
    for theme in themes:
        request = JobRequest(
            tema=theme,
            n_cenas=5,
            voice_id="voz_000000000000",
            models=ModelChoice(llm=model, tts="f5-tts", video="wan-2.1-t2v-480p"),
        )
        limits = request.script_limits(enforce_scene_count=True)
        outcome = await loop.run(llm, draft_messages(request, limits), limits, "9:16")
        calls, cost = calls + outcome.calls, cost + outcome.cost_usd
        if outcome.script is not None:
            valid += 1
            first_try += outcome.calls == 1
            words += [count_words(scene.texto_narrado) for scene in outcome.script.cenas]
        print(
            f"  {model} | {theme[:45]:45} | chamadas={outcome.calls} | "
            f"{'ok' if outcome.script else 'FALHOU: ' + outcome.violations[0].message[:40]}"
        )
    n = len(themes)
    return {
        "valido_1a": first_try / n,
        "valido": valid / n,
        "chamadas": calls / n,
        "palavras": statistics.mean(words) if words else 0.0,
        "custo": cost,
    }


async def main(models: list[str], count: int) -> None:
    settings = load_settings()
    context = ProviderContext(settings.providers, RetryPolicy(), Path("workspace/_eval"))
    registry = ProviderRegistry(load_catalog(settings.app.models_config), context, mode="real")
    try:
        for model in models:
            r = await evaluate(model, list(THEMES[:count]), registry)
            print(
                f"{model}: válido de primeira {r['valido_1a']:.0%} | válido {r['valido']:.0%} | "
                f"{r['chamadas']:.1f} chamadas/tema | {r['palavras']:.1f} palavras/cena | "
                f"custo US$ {r['custo']:.4f}"
            )
    finally:
        await context.aclose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--models", nargs="+", default=["deepseek-flash"])
    parser.add_argument("--count", type=int, default=len(THEMES), choices=range(1, len(THEMES) + 1))
    parser.add_argument("--yes", action="store_true", help="confirma o gasto com chamadas reais")
    args = parser.parse_args()
    if not args.yes:
        print(f"Plano: {args.count} temas x {args.models} (chamadas reais). Rode com --yes.")
        sys.exit(0)
    asyncio.run(main(args.models, args.count))
