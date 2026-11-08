"""Port do cache de artefatos endereçado por conteúdo (RNF-02)."""

from collections.abc import Mapping
from pathlib import Path
from typing import Protocol, runtime_checkable

from videogen.domain.media import ArtifactKind


@runtime_checkable
class ArtifactCache(Protocol):
    def get(self, kind: ArtifactKind, key: str) -> Path | None:
        """Caminho do artefato completo, ou None (parciais e vazios nunca são hit)."""
        ...

    def tmp_path(self, kind: ArtifactKind, key: str) -> Path:
        """Arquivo temporário exclusivo, na mesma partição do destino final."""
        ...

    def commit(self, kind: ArtifactKind, key: str, tmp: Path, meta: Mapping[str, object]) -> Path:
        """Move `tmp` para o destino de forma atômica e grava os metadados."""
        ...
