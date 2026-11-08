"""Port de composição de mídia (FFmpeg): loudnorm, clipe da cena e concatenação."""

from collections.abc import Sequence
from pathlib import Path
from typing import Protocol, runtime_checkable

from videogen.domain.render_specs import ClipSpec, ConcatParams, LoudnessParams


@runtime_checkable
class MediaComposer(Protocol):
    async def normalize_audio(self, src: Path, dst: Path, params: LoudnessParams) -> None: ...

    async def compose_clip(self, spec: ClipSpec) -> Path: ...

    async def concat(self, clips: Sequence[Path], dst: Path, params: ConcatParams) -> Path: ...
