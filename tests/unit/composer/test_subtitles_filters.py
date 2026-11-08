"""T-043/T-044 (puros): quebra de linhas, tempos, escape ASS, estilos e filtergraph."""

import itertools
from typing import Any

import pytest

from videogen.composer.filters import SubtitleRef, build_video_filter
from videogen.composer.subtitles.ass_writer import ass_time, render_ass, sanitize
from videogen.composer.subtitles.chunker import TimedLine, chunk_phrases, timed_lines
from videogen.composer.subtitles.styles import style_for
from videogen.domain.render_specs import ClipParams
from videogen.domain.sync import SyncConfig, plan_sync

TEXT = "Imagine proteger o seu futuro, com um clique e sem burocracia nenhuma."


def test_linhas_respeitam_limites() -> None:
    lines = chunk_phrases(TEXT, max_words=4, max_chars=28)
    assert lines == ["Imagine proteger o seu", "futuro, com um clique", "e sem burocracia nenhuma."]
    assert " ".join(lines) == TEXT


def test_quebra_apos_pontuacao_quando_a_linha_tem_ao_menos_duas_palavras() -> None:
    lines = chunk_phrases("Olá mundo, tudo bem? Sim.", max_words=4, max_chars=28)
    assert lines == ["Olá mundo,", "tudo bem?", "Sim."]


def test_palavra_maior_que_o_limite_nao_some() -> None:
    assert chunk_phrases("Inconstitucionalissimamente ok", max_words=4, max_chars=10) == [
        "Inconstitucionalissimamente",
        "ok",
    ]


def test_tempos_somam_a_duracao_e_sao_contiguos() -> None:
    lines = timed_lines(TEXT, 4.37, max_words=4, max_chars=28)
    assert lines[0].start_s == 0 and lines[-1].end_s == 4.37
    assert all(a.end_s == pytest.approx(b.start_s) for a, b in itertools.pairwise(lines))
    assert timed_lines("", 3, max_words=4, max_chars=28) == []


@pytest.mark.parametrize(
    ("seconds", "text"), [(0, "0:00:00.00"), (4.37, "0:00:04.37"), (3725.5, "1:02:05.50")]
)
def test_formato_de_tempo_ass(seconds: float, text: str) -> None:
    assert ass_time(seconds) == text


def test_texto_do_llm_nao_injeta_override_tags() -> None:
    assert (
        sanitize("Olá {\\fs200\\c&H0000FF&} mundo\\N\nfim") == "Olá (/fs200/c&H0000FF&) mundo/N fim"
    )
    ass = render_ass([TimedLine(0, 1, "{\\pos(0,0)}ataque")], style_for("9:16", 720, 1280))
    assert "{" not in ass.split("[Events]")[1]


def test_estilos_por_proporcao_escalam_com_a_resolucao() -> None:
    vertical = style_for("9:16", 720, 1280)
    assert (vertical.font_size, vertical.margin_v, vertical.max_chars) == (64, 256, 28)
    assert style_for("9:16", 360, 640).font_size == 32
    horizontal = style_for("16:9", 1280, 720)
    assert (horizontal.max_chars, horizontal.margin_v) == (42, 50)
    ass = render_ass([TimedLine(0, 1, "x")], vertical)
    assert "PlayResX: 720" in ass and "PlayResY: 1280" in ass and "Dialogue: 0,0:00:00.00" in ass


def _params(**overrides: Any) -> ClipParams:
    data: dict[str, Any] = {
        "texto": "x",
        "aspect_ratio": "9:16",
        "width": 720,
        "height": 1280,
        "fps": 30,
    }
    return ClipParams.model_validate(data | overrides)


CFG = SyncConfig()
COVER = "scale=720:1280:force_original_aspect_ratio=increase:flags=lanczos,crop=720:1280,setsar=1"


@pytest.mark.parametrize(
    ("t_audio", "expected"),
    [
        (5.10, f"[0:v]tpad=stop_mode=clone:stop_duration=0.040,fps=30,{COVER}[v]"),
        (6.20, f"[0:v]setpts=1.225296*PTS,fps=30,{COVER}[v]"),
        (
            3.50,
            f"[0:v]setpts=0.850000*PTS,fps=30,{COVER},trim=duration=3.500,"
            "fade=t=out:st=3.200:d=0.300[v]",
        ),
    ],
)
def test_filtergraph_por_estrategia(t_audio: float, expected: str) -> None:
    plan = plan_sync(t_audio, 5.06, CFG)
    assert build_video_filter(plan, _params(), t_video=5.06, subtitles=None) == expected


def test_freeze_com_zoom_comeca_no_quadro_certo() -> None:
    plan = plan_sync(8.5, 5.06, CFG)
    graph = build_video_filter(plan, _params(), t_video=5.06, subtitles=None)
    assert "setpts=1.350000*PTS,tpad=stop_mode=clone:stop_duration=1.669" in graph
    assert "gte(on\\,205)" in graph  # 5,06 s * 1,35 * 30 fps
    assert graph.endswith(":d=1:s=720x1280:fps=30[v]")


def test_legenda_e_fontes_no_fim_da_cadeia() -> None:
    plan = plan_sync(5.0, 5.0, CFG)
    graph = build_video_filter(
        plan, _params(), t_video=5.0, subtitles=SubtitleRef("scene.ass", "/fonts")
    )
    assert graph.endswith(",ass=filename=scene.ass:fontsdir=/fonts[v]")
    assert "tpad" not in graph and "setpts" not in graph
