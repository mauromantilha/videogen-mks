"""Port de inspeção de mídia (ffprobe)."""

from pathlib import Path
from typing import Protocol, runtime_checkable

from videogen.domain.media import ArtifactKind, MediaInfo


@runtime_checkable
class MediaProbe(Protocol):
    async def probe(self, path: Path) -> MediaInfo: ...

    async def validate(self, path: Path, kind: ArtifactKind) -> MediaInfo:
        """Levanta `MediaError` se o arquivo não for uma mídia íntegra do tipo esperado."""
        ...
