"""Fachada que implementa o port `MediaComposer` juntando as peças do composer."""

from collections.abc import Sequence
from pathlib import Path

from videogen.composer.concat import Concatenator
from videogen.composer.loudnorm import LoudnessNormalizer
from videogen.composer.scene_composer import SceneComposer
from videogen.domain.render_specs import ClipSpec, ConcatParams, LoudnessParams


class FfmpegMediaComposer:
    def __init__(
        self, loudness: LoudnessNormalizer, scenes: SceneComposer, concatenator: Concatenator
    ) -> None:
        self._loudness = loudness
        self._scenes = scenes
        self._concatenator = concatenator

    async def normalize_audio(self, src: Path, dst: Path, params: LoudnessParams) -> None:
        await self._loudness.normalize(src, dst, params)

    async def compose_clip(self, spec: ClipSpec) -> Path:
        return await self._scenes.compose(spec)

    async def concat(self, clips: Sequence[Path], dst: Path, params: ConcatParams) -> Path:
        return await self._concatenator.concat(clips, dst, params)
