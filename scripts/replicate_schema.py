#!/usr/bin/env python3
"""Mostra o schema oficial de um modelo do Replicate para preencher `config/models.yaml`.

Uso:  REPLICATE_API_TOKEN=r8_... python scripts/replicate_schema.py x-lance/f5-tts

Imprime a versão mais recente (para `version:`) e cada campo de entrada com tipo, padrão e
descrição (para `fields:`). Só leitura: não cria predição nem gera custo.
"""

import os
import sys
from typing import Any

import httpx

API = "https://api.replicate.com/v1/models"


def fetch_model(slug: str, token: str) -> dict[str, Any]:
    response = httpx.get(f"{API}/{slug}", headers={"Authorization": f"Bearer {token}"}, timeout=30)
    response.raise_for_status()
    data: dict[str, Any] = response.json()
    return data


def describe(model: dict[str, Any]) -> list[str]:
    latest = model.get("latest_version") or {}
    schemas = (latest.get("openapi_schema") or {}).get("components", {}).get("schemas", {})
    inputs: dict[str, Any] = schemas.get("Input", {}).get("properties", {})
    lines = [
        f"modelo:  {model.get('owner')}/{model.get('name')}",
        f"version: {latest.get('id')}",
        f"saída:   {schemas.get('Output')}",
        "entradas:",
    ]
    for name, prop in sorted(inputs.items(), key=lambda item: item[1].get("x-order", 0)):
        kind = prop.get("type") or _enum(prop, schemas) or "?"
        default = prop.get("default", "—")
        description = str(prop.get("description", "")).replace("\n", " ")[:90]
        lines.append(f"  - {name} ({kind}, padrão={default}): {description}")
    return lines


def _enum(prop: dict[str, Any], schemas: dict[str, Any]) -> str | None:
    """Resolve `allOf: [{$ref: ...}]` para a lista de valores permitidos."""
    for item in prop.get("allOf", []):
        target = schemas.get(str(item.get("$ref", "")).rsplit("/", 1)[-1], {})
        if "enum" in target:
            return "enum " + "|".join(map(str, target["enum"]))
    return None


def main(argv: list[str]) -> int:
    token = os.environ.get("REPLICATE_API_TOKEN", "")
    if len(argv) != 1 or not token:
        print(__doc__)
        return 2
    try:
        print("\n".join(describe(fetch_model(argv[0], token))))
    except httpx.HTTPError as exc:
        print(f"erro ao consultar o Replicate: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
