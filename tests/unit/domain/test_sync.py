"""T-015: plano de sincronização — tabela do design/01 §8 e propriedades."""

import itertools

import pytest
from pydantic import ValidationError

from videogen.core.errors import MediaError
from videogen.domain.sync import SyncConfig, SyncStrategy, plan_sync

CFG = SyncConfig()
T_VIDEO = 5.06  # Wan 2.1: 81 frames a 16 fps


@pytest.mark.parametrize(
    ("t_audio", "strategy", "factor", "freeze"),
    [
        (5.10, SyncStrategy.NONE, 1.0, 0.04),
        (5.00, SyncStrategy.NONE, 1.0, 0.0),
        (6.20, SyncStrategy.STRETCH, 6.20 / T_VIDEO, 0.0),
        (4.40, SyncStrategy.STRETCH, 4.40 / T_VIDEO, 0.0),
        (8.50, SyncStrategy.FREEZE_ZOOM, 1.35, 8.50 - T_VIDEO * 1.35),
        (3.50, SyncStrategy.TRIM, 0.85, 0.0),
    ],
)
def test_casos_do_design(
    t_audio: float, strategy: SyncStrategy, factor: float, freeze: float
) -> None:
    plan = plan_sync(t_audio, T_VIDEO, CFG)
    assert plan.strategy is strategy
    assert plan.setpts_factor == pytest.approx(factor)
    assert plan.freeze_extra_s == pytest.approx(freeze)
    assert plan.target_duration_s == t_audio


def test_limites_das_faixas_sao_inclusivos() -> None:
    assert plan_sync(T_VIDEO * 1.35, T_VIDEO, CFG).strategy is SyncStrategy.STRETCH
    assert plan_sync(T_VIDEO * 0.85, T_VIDEO, CFG).strategy is SyncStrategy.STRETCH


@pytest.mark.parametrize(
    ("t_audio", "t_video"),
    list(itertools.product([0.5, 2.0, 3.9, 5.0, 6.7, 9.9, 15.0], [1.0, 3.3, 5.06, 8.0])),
)
def test_propriedades(t_audio: float, t_video: float) -> None:
    plan = plan_sync(t_audio, t_video, CFG)
    assert plan.target_duration_s == t_audio  # o clipe sempre dura o mesmo que a fala
    assert CFG.stretch_min <= plan.setpts_factor <= CFG.stretch_max
    assert plan.freeze_extra_s >= 0
    visible = t_video * plan.setpts_factor + plan.freeze_extra_s
    if plan.strategy is SyncStrategy.TRIM:
        assert visible > t_audio  # há vídeo de sobra para cortar
    else:
        assert visible == pytest.approx(t_audio, abs=CFG.tolerance_s)  # nunca tela preta


@pytest.mark.parametrize(("t_audio", "t_video"), [(0, 5.0), (5.0, 0), (-1, 5.0)])
def test_duracoes_invalidas(t_audio: float, t_video: float) -> None:
    with pytest.raises(MediaError):
        plan_sync(t_audio, t_video, CFG)


@pytest.mark.parametrize(
    "overrides", [{"stretch_min": 1.2}, {"stretch_max": 0.9}, {"tolerance_s": -0.1}]
)
def test_configuracao_invalida(overrides: dict[str, float]) -> None:
    with pytest.raises(ValidationError):
        SyncConfig.model_validate(overrides)
