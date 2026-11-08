"""Layout do workspace em disco (design/02 §3) com proteção contra path traversal.

Ninguém monta caminhos à mão: tudo que vem de fora (job_id, voice_id) passa por aqui e
o caminho final precisa continuar dentro da raiz, mesmo após resolver symlinks.
"""

from pathlib import Path

from videogen.core.errors import NotFound
from videogen.core.ids import ensure_job_id, ensure_voice_id

MAX_SCENES_ON_DISK = 100


class Workspace:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.cache_dir = self.root / "_cache"
        self.voices_dir = self.root / "_voices"
        self.jobs_dir = self.root / "jobs"

    def ensure_layout(self) -> None:
        for directory in (self.cache_dir, self.voices_dir, self.jobs_dir):
            directory.mkdir(parents=True, exist_ok=True)

    def job_dir(self, job_id: str) -> Path:
        return self._inside(self.jobs_dir / ensure_job_id(job_id))

    def job_state_path(self, job_id: str) -> Path:
        return self.job_dir(job_id) / "job_state.json"

    def events_path(self, job_id: str) -> Path:
        return self.job_dir(job_id) / "events.jsonl"

    def script_snapshot_path(self, job_id: str, version: int) -> Path:
        if version < 1:
            raise ValueError("versão do roteiro começa em 1")
        return self.job_dir(job_id) / "script" / f"v{version:04d}.json"

    def job_tmp_dir(self, job_id: str) -> Path:
        return self.job_dir(job_id) / "tmp"

    def scene_dir(self, job_id: str, scene_index: int) -> Path:
        if not 0 <= scene_index < MAX_SCENES_ON_DISK:
            raise ValueError(f"scene_index fora da faixa: {scene_index}")
        return self.job_dir(job_id) / f"scene_{scene_index:02d}"

    def final_path(self, job_id: str) -> Path:
        return self.job_dir(job_id) / "final_render.mp4"

    def voice_dir(self, voice_id: str) -> Path:
        return self._inside(self.voices_dir / ensure_voice_id(voice_id))

    def _inside(self, path: Path) -> Path:
        if not path.resolve().is_relative_to(self.root):
            raise NotFound("recurso fora do workspace", path=path.name)
        return path
