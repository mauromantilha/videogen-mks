"""ArtifactCache sobre um diretório temporário, com metadados em memória."""

import uuid
from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING

from videogen.domain.media import ArtifactKind


class InMemoryArtifactCache:
    def __init__(self, root: Path) -> None:
        self._root = root
        self.meta: dict[tuple[ArtifactKind, str], dict[str, object]] = {}

    def _final(self, kind: ArtifactKind, key: str) -> Path:
        return self._root / str(kind) / key

    def get(self, kind: ArtifactKind, key: str) -> Path | None:
        path = self._final(kind, key)
        complete = path.is_file() and path.stat().st_size > 0 and (kind, key) in self.meta
        return path if complete else None

    def tmp_path(self, kind: ArtifactKind, key: str) -> Path:
        path = self._root / "tmp" / f"{kind}-{key}.part-{uuid.uuid4().hex}"
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def commit(self, kind: ArtifactKind, key: str, tmp: Path, meta: Mapping[str, object]) -> Path:
        final = self._final(kind, key)
        final.parent.mkdir(parents=True, exist_ok=True)
        tmp.replace(final)
        self.meta[(kind, key)] = dict(meta)
        return final

    def put(self, kind: ArtifactKind, key: str, content: bytes = b"artefato") -> Path:
        """Atalho de teste: pré-povoa o cache."""
        tmp = self.tmp_path(kind, key)
        tmp.write_bytes(content)
        return self.commit(kind, key, tmp, {"source": "test"})


if TYPE_CHECKING:
    from videogen.ports.cache import ArtifactCache

    _conforms: ArtifactCache = InMemoryArtifactCache(Path())
