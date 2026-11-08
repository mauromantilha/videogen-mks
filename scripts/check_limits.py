#!/usr/bin/env python3
"""Guardião do RNF-05 (anti-god-class). Regras completas: docs/design/07, §1.

Uso: check_limits.py [caminhos...] [--changed] [--strict]   (sem caminhos: repositório inteiro)
ERRO: arquivo/classe/função > 300 linhas ou nome genérico. AVISO: metas em TARGETS.
Exceção a META: `# limits: allow <regra> — <motivo>` na definição/acima. ERRO não tem exceção.
"""

from __future__ import annotations

import argparse
import ast
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HARD_LINES = 300
TARGETS = {"file-lines": 200, "function-lines": 50, "class-lines": 150}
TARGETS |= {"public-methods": 10, "router-endpoints": 8}
EXTENSIONS = {".py", ".html", ".yaml", ".yml", ".md", ".sh", ".toml", ".ini"}
SCAN_DIRS = ("src", "tests", "scripts", "docs", "config", ".github")
SKIP_PARTS = {".git", ".venv", "venv", "__pycache__", "workspace", "static", "node_modules"}
FORBIDDEN_FILES = {"utils.py", "helpers.py", "common.py", "misc.py"}
FORBIDDEN_CLASS = re.compile(r"(Manager|Helpers?|Utils?|Handler|Processor)$")
WAIVER = re.compile(r"#\s*limits:\s*allow\s+([\w-]+)\s*(?:—|--|-)\s*\S")
ROUTER_DIRS = ("api/routers/", "ui/routes/")
ROUTE_VERBS = {"get", "post", "put", "patch", "delete", "head", "options", "api_route", "websocket"}
FILE_WAIVER_WINDOW = range(1, 11)
FUNCS = (ast.FunctionDef, ast.AsyncFunctionDef)
Definition = ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef


@dataclass(frozen=True)
class Violation:
    path: Path
    line: int
    rule: str
    detail: str
    hard: bool

    def render(self) -> str:
        level = "ERRO " if self.hard else "AVISO"
        return f"{os.path.relpath(self.path)}:{self.line}: {level} {self.rule}: {self.detail}"


@dataclass(frozen=True)
class FileContext:
    path: Path
    lines: list[str]
    waived: dict[int, set[str]]

    def allows(self, rule: str, window: range) -> bool:
        return any(rule in self.waived.get(number, set()) for number in window)


def default_targets(root: Path = ROOT) -> list[Path]:
    dirs = [root / name for name in SCAN_DIRS if (root / name).is_dir()]
    return dirs + [item for item in root.iterdir() if item.is_file()]


def iter_files(targets: list[Path]) -> list[Path]:
    found: set[Path] = set()
    for target in targets:
        candidates = target.rglob("*") if target.is_dir() else [target]
        found.update(path for path in candidates if _eligible(path))
    return sorted(found)


def _eligible(path: Path) -> bool:
    return path.is_file() and path.suffix in EXTENSIONS and not SKIP_PARTS.intersection(path.parts)


def _waivers(lines: list[str]) -> dict[int, set[str]]:
    found: dict[int, set[str]] = {}
    for number, text in enumerate(lines, start=1):
        for rule in WAIVER.findall(text):
            found.setdefault(number, set()).add(rule)
    return found


def _measure(
    ctx: FileContext, line: int, window: range, count: int, rule: str, label: str
) -> list[Violation]:
    if count > HARD_LINES:
        detail = f"{label} com {count} linhas (limite rígido {HARD_LINES})"
        return [Violation(ctx.path, line, rule, detail, hard=True)]
    if count > TARGETS[rule] and not ctx.allows(rule, window):
        detail = f"{label} com {count} linhas (meta {TARGETS[rule]})"
        return [Violation(ctx.path, line, rule, detail, hard=False)]
    return []


def _length(node: Definition) -> int:
    return (node.end_lineno or node.lineno) - node.lineno + 1


def _window(node: Definition) -> range:
    first = min((decorator.lineno for decorator in node.decorator_list), default=node.lineno)
    return range(first - 1, node.lineno + 1)


def _check_class(ctx: FileContext, node: ast.ClassDef) -> list[Violation]:
    label = f"classe '{node.name}'"
    found = _measure(ctx, node.lineno, _window(node), _length(node), "class-lines", label)
    if FORBIDDEN_CLASS.search(node.name):
        detail = f"{label}: sufixo genérico proibido; nomeie pelo papel"
        found.append(Violation(ctx.path, node.lineno, "forbidden-name", detail, hard=True))
    public = sum(1 for i in node.body if isinstance(i, FUNCS) and not i.name.startswith("_"))
    limit = TARGETS["public-methods"]
    if public > limit and not ctx.allows("public-methods", _window(node)):
        detail = f"{label} com {public} métodos públicos (meta {limit})"
        found.append(Violation(ctx.path, node.lineno, "public-methods", detail, hard=False))
    return found


def _is_route(decorator: ast.expr) -> bool:
    return (
        isinstance(decorator, ast.Call)
        and isinstance(decorator.func, ast.Attribute)
        and decorator.func.attr in ROUTE_VERBS
    )


def _check_router(ctx: FileContext, tree: ast.Module) -> list[Violation]:
    functions = [node for node in ast.walk(tree) if isinstance(node, FUNCS)]
    endpoints = sum(1 for fn in functions for dec in fn.decorator_list if _is_route(dec))
    limit = TARGETS["router-endpoints"]
    if endpoints <= limit or ctx.allows("router-endpoints", FILE_WAIVER_WINDOW):
        return []
    detail = f"router com {endpoints} endpoints (meta {limit})"
    return [Violation(ctx.path, 1, "router-endpoints", detail, hard=False)]


def check_python(ctx: FileContext) -> list[Violation]:
    try:
        tree = ast.parse("\n".join(ctx.lines), filename=str(ctx.path))
    except SyntaxError as exc:
        return [Violation(ctx.path, exc.lineno or 1, "syntax", "arquivo não analisável", True)]
    found: list[Violation] = []
    for node in ast.walk(tree):
        if isinstance(node, FUNCS):
            label = f"função '{node.name}'"
            length = _length(node)
            found += _measure(ctx, node.lineno, _window(node), length, "function-lines", label)
        elif isinstance(node, ast.ClassDef):
            found += _check_class(ctx, node)
    if any(part in ctx.path.as_posix() for part in ROUTER_DIRS):
        found += _check_router(ctx, tree)
    return found


def check_file(path: Path) -> list[Violation]:
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    ctx = FileContext(path, lines, _waivers(lines))
    found = _measure(ctx, 1, FILE_WAIVER_WINDOW, len(lines), "file-lines", "arquivo")
    if path.name in FORBIDDEN_FILES:
        detail = f"arquivo '{path.name}' é proibido; nomeie pelo papel"
        found.append(Violation(path, 1, "forbidden-name", detail, hard=True))
    if path.suffix == ".py":
        found += check_python(ctx)
    return found


def check_paths(targets: list[Path]) -> list[Violation]:
    return [violation for path in iter_files(targets) for violation in check_file(path)]


def staged_files() -> list[Path]:
    command = ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR"]
    output = subprocess.run(command, capture_output=True, text=True, check=True).stdout
    return [Path(name) for name in output.splitlines()]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Limite de 300 linhas (RNF-05).")
    parser.add_argument("paths", nargs="*", type=Path, help="arquivos ou diretórios")
    parser.add_argument("--changed", action="store_true", help="só arquivos em stage")
    parser.add_argument("--strict", action="store_true", help="metas também falham")
    args = parser.parse_args(argv)
    targets = staged_files() if args.changed else (args.paths or default_targets())
    violations = check_paths(targets)
    for violation in violations:
        print(violation.render())
    errors = sum(1 for violation in violations if violation.hard)
    warnings = len(violations) - errors
    print(f"check_limits: {errors} erro(s), {warnings} aviso(s)")
    return 1 if errors or (args.strict and warnings) else 0


if __name__ == "__main__":
    sys.exit(main())
