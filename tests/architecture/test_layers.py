"""T-003: contratos de camadas (import-linter) + I/O de stdlib proibido nas camadas internas."""

import ast
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "src" / "videogen"
LINT_IMPORTS = Path(sys.executable).parent / "lint-imports"

# import-linter não rastreia a stdlib; estas camadas não podem fazer I/O direto.
INNER_LAYERS = ("domain", "ports", "services")
FORBIDDEN_STDLIB = {"subprocess", "socket", "sqlite3", "urllib", "http", "shutil"}


def _lint_imports(cwd: Path, src: Path) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "PYTHONPATH": str(src)}
    return subprocess.run(
        [str(LINT_IMPORTS), "--no-cache"], cwd=cwd, env=env, capture_output=True, text=True
    )


def test_contratos_de_camadas_sao_respeitados() -> None:
    result = _lint_imports(ROOT, ROOT / "src")
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize(
    ("module", "statement", "contract"),
    [
        ("services/__init__.py", "import httpx", "services dependem só de ports/domain"),
        ("services/__init__.py", "import videogen.providers", "services dependem só de ports"),
        ("domain/__init__.py", "import videogen.services", "Camadas"),
        ("api/__init__.py", "import videogen.infra", "api/ui falam com services"),
        ("ports/__init__.py", "import fastapi", "domain e ports sem frameworks"),
    ],
)
def test_import_proibido_quebra_contrato(
    tmp_path: Path, module: str, statement: str, contract: str
) -> None:
    shutil.copytree(PACKAGE, tmp_path / "src" / "videogen")
    shutil.copy(ROOT / ".importlinter", tmp_path)
    target = tmp_path / "src" / "videogen" / module
    target.write_text(target.read_text(encoding="utf-8") + f"\n{statement}\n", encoding="utf-8")

    result = _lint_imports(tmp_path, tmp_path / "src")

    assert result.returncode != 0
    broken = [line for line in result.stdout.splitlines() if line.endswith("BROKEN")]
    assert any(contract in line for line in broken), result.stdout


def _stdlib_imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module.split(".")[0])
    return names & FORBIDDEN_STDLIB


def _inner_layer_files() -> list[Path]:
    return [path for layer in INNER_LAYERS for path in (PACKAGE / layer).rglob("*.py")]


@pytest.mark.parametrize("path", _inner_layer_files(), ids=lambda p: str(p.relative_to(PACKAGE)))
def test_camadas_internas_nao_fazem_io_da_stdlib(path: Path) -> None:
    assert _stdlib_imports(path) == set()


def test_detector_de_io_da_stdlib_funciona(tmp_path: Path) -> None:
    sample = tmp_path / "amostra.py"
    sample.write_text("import json\nimport subprocess\nfrom urllib.request import urlopen\n")
    assert _stdlib_imports(sample) == {"subprocess", "urllib"}
