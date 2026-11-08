"""Cache de artefatos endereçado por conteúdo (ADR-05, RNF-02).

Layout: `_cache/{kind}/{hash[:2]}/{hash}{ext}` + `{hash}.meta.json`. O meta é gravado por
último: arquivo sem meta (crash no meio) nunca é hit. Temporários mantêm a extensão para o
FFmpeg reconhecer o formato.
"""

import json
import os
import re
import shutil
import uuid
from collections.abc import Mapping
from pathlib import Path

from videogen.domain.media import ArtifactKind
from videogen.infra.atomic_file import fsync_dir, write_atomic

_KEY = re.compile(r"^[0-9a-f]{64}$")
_EXTENSIONS = {
    ArtifactKind.AUDIO_RAW: ".wav",
    ArtifactKind.AUDIO_NORM: ".wav",
    ArtifactKind.VIDEO_RAW: ".mp4",
    ArtifactKind.CLIP: ".mp4",
    ArtifactKind.FINAL: ".mp4",
}
PARTIAL_MARKER = ".part-"


class FileArtifactCache:
    def __init__(self, root: Path) -> None:
        self._root = root

    def path_for(self, kind: ArtifactKind, key: str) -> Path:
        if not _KEY.fullmatch(key):
            raise ValueError("chave de cache deve ser um SHA-256 hexadecimal")
        return self._root / str(kind) / key[:2] / f"{key}{_EXTENSIONS[kind]}"

    def get(self, kind: ArtifactKind, key: str) -> Path | None:
        path = self.path_for(kind, key)
        complete = path.is_file() and path.stat().st_size > 0 and _meta_path(path).is_file()
        return path if complete else None

    def tmp_path(self, kind: ArtifactKind, key: str) -> Path:
        final = self.path_for(kind, key)
        final.parent.mkdir(parents=True, exist_ok=True)
        return final.with_name(f"{key}{PARTIAL_MARKER}{uuid.uuid4().hex}{final.suffix}")

    def commit(self, kind: ArtifactKind, key: str, tmp: Path, meta: Mapping[str, object]) -> Path:
        final = self.path_for(kind, key)
        if not tmp.is_file() or tmp.stat().st_size == 0:
            raise ValueError(f"artefato temporário vazio ou ausente: {tmp.name}")
        with tmp.open("rb") as handle:
            os.fsync(handle.fileno())
        os.replace(tmp, final)
        fsync_dir(final.parent)
        record = {**meta, "kind": str(kind), "key": key, "size": final.stat().st_size}
        write_atomic(_meta_path(final), json.dumps(record, default=str, indent=2).encode())
        return final

    def meta(self, kind: ArtifactKind, key: str) -> dict[str, object] | None:
        path = _meta_path(self.path_for(kind, key))
        return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None

    def link_into(self, target: Path, kind: ArtifactKind, key: str) -> Path:
        """Cria uma *view* (symlink; fallback hardlink/cópia) para pré-visualização."""
        source = self.get(kind, key)
        if source is None:
            raise FileNotFoundError(f"artefato {kind}/{key[:12]}… não está no cache")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.unlink(missing_ok=True)
        try:
            target.symlink_to(source)
        except OSError:
            try:
                os.link(source, target)
            except OSError:
                shutil.copy2(source, target)
        return target

    def remove_partials(self) -> int:
        """Apaga temporários órfãos (rodar no startup, antes de qualquer render)."""
        partials = [p for p in self._root.rglob(f"*{PARTIAL_MARKER}*") if p.is_file()]
        for path in partials:
            path.unlink(missing_ok=True)
        return len(partials)

    def entries(self) -> list[tuple[ArtifactKind, str, Path]]:
        """Artefatos completos (kind, hash, caminho) — usado pela limpeza por TTL."""
        found: list[tuple[ArtifactKind, str, Path]] = []
        for kind in ArtifactKind:
            for meta in (self._root / str(kind)).glob("*/*.meta.json"):
                key = meta.name.removesuffix(".meta.json")
                if (path := self.get(kind, key)) is not None:
                    found.append((kind, key, path))
        return found


def _meta_path(artifact: Path) -> Path:
    return artifact.with_name(f"{artifact.stem}.meta.json")
