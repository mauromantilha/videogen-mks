"""T-002: o guardião do RNF-05 detecta cada regra e o repositório o respeita."""

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("check_limits", ROOT / "scripts/check_limits.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["check_limits"] = module
    spec.loader.exec_module(module)
    return module


cl = _load_script()


def _write(base: Path, name: str, text: str) -> Path:
    path = base / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _function(lines: int, name: str = "f") -> str:
    return f"def {name}():\n" + "    x = 1\n" * (lines - 1)


def _rules(path: Path, *, hard: bool) -> set[str]:
    return {v.rule for v in cl.check_paths([path]) if v.hard is hard}


@pytest.mark.parametrize(("lines", "is_error"), [(299, False), (300, False), (301, True)])
def test_limite_rigido_de_arquivo(tmp_path: Path, lines: int, is_error: bool) -> None:
    path = _write(tmp_path, "doc.md", "linha\n" * lines)
    assert ("file-lines" in _rules(path, hard=True)) is is_error


def test_funcao_acima_de_300_linhas_e_erro(tmp_path: Path) -> None:
    path = _write(tmp_path, "grande.py", _function(301))
    assert "function-lines" in _rules(path, hard=True)


def test_classe_acima_de_300_linhas_e_erro(tmp_path: Path) -> None:
    path = _write(tmp_path, "grande.py", "class Deus:\n" + "    x = 1\n" * 300)
    assert "class-lines" in _rules(path, hard=True)


def test_meta_gera_aviso_e_so_falha_com_strict(tmp_path: Path) -> None:
    path = _write(tmp_path, "media.py", _function(60))
    assert _rules(path, hard=False) == {"function-lines"}
    assert cl.main([str(path)]) == 0
    assert cl.main([str(path), "--strict"]) == 1


def test_erro_rigido_falha_o_build(tmp_path: Path) -> None:
    path = _write(tmp_path, "doc.md", "linha\n" * 301)
    assert cl.main([str(path)]) == 1


@pytest.mark.parametrize(("methods", "warns"), [(10, False), (11, True)])
def test_metodos_publicos(tmp_path: Path, methods: int, warns: bool) -> None:
    body = "".join(f"    def m{i}(self): ...\n" for i in range(methods))
    path = _write(tmp_path, "servico.py", f"class Servico:\n    def _privado(self): ...\n{body}")
    assert ("public-methods" in _rules(path, hard=False)) is warns


@pytest.mark.parametrize("name", ["JobManager", "MediaHelper", "StringUtils", "VideoProcessor"])
def test_sufixo_generico_de_classe_e_proibido(tmp_path: Path, name: str) -> None:
    path = _write(tmp_path, "modulo.py", f"class {name}:\n    pass\n")
    assert "forbidden-name" in _rules(path, hard=True)


def test_arquivo_utils_e_proibido(tmp_path: Path) -> None:
    path = _write(tmp_path, "pkg/utils.py", "X = 1\n")
    assert "forbidden-name" in _rules(path, hard=True)


def test_excecao_documentada_silencia_meta(tmp_path: Path) -> None:
    waiver = "# limits: allow function-lines — tabela gerada a partir do catálogo\n"
    path = _write(tmp_path, "tabela.py", waiver + _function(60))
    assert cl.check_paths([path]) == []


def test_excecao_sem_motivo_e_ignorada(tmp_path: Path) -> None:
    path = _write(tmp_path, "tabela.py", "# limits: allow function-lines\n" + _function(60))
    assert _rules(path, hard=False) == {"function-lines"}


def test_excecao_nunca_vale_para_limite_rigido(tmp_path: Path) -> None:
    waiver = "# limits: allow function-lines — tentativa de burlar\n"
    path = _write(tmp_path, "grande.py", waiver + _function(301))
    assert "function-lines" in _rules(path, hard=True)


def test_excecao_acima_de_decorador(tmp_path: Path) -> None:
    text = "# limits: allow function-lines — ok\n@decorador\n" + _function(60)
    path = _write(tmp_path, "decorado.py", text)
    assert cl.check_paths([path]) == []


def test_router_com_mais_de_8_endpoints_gera_aviso(tmp_path: Path) -> None:
    routes = "".join(f"@router.get('/r{i}')\nasync def r{i}(): ...\n" for i in range(9))
    path = _write(tmp_path, "api/routers/grande.py", routes)
    assert "router-endpoints" in _rules(path, hard=False)


def test_diretorios_ignorados(tmp_path: Path) -> None:
    _write(tmp_path, ".venv/lib/pacote.py", _function(400))
    _write(tmp_path, "src/__pycache__/x.py", _function(400))
    assert cl.check_paths([tmp_path]) == []


def test_repositorio_respeita_limites_rigidos() -> None:
    errors = [v.render() for v in cl.check_paths(cl.default_targets(ROOT)) if v.hard]
    assert errors == [], "\n".join(errors)
