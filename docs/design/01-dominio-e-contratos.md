# Design 01 — Domínio e contratos

<!-- # limits: allow file-lines — catálogo de contratos; dividir se passar de 280 linhas -->

> Pacotes: `domain/` e `ports/` · Tarefas: M1 (T-010…T-018) · Voltar: [design.md](../design.md)

`domain/` é **puro**: sem I/O, sem *async*, apenas `pydantic` + stdlib. Tudo aqui é trivialmente testável.

## 1. Roteiro — `domain/script.py`

```python
AspectRatio = Literal["9:16", "16:9"]

class SceneSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    scene_index: int = Field(ge=0)
    texto_narrado: str = Field(min_length=1, max_length=120)        # teto de segurança
    prompt_video: str = Field(min_length=20, max_length=1200)
    seed: int | None = Field(default=None, ge=0, lt=2**31)          # fixada na aprovação

class VideoScriptSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")
    produto_tema: str = Field(min_length=3, max_length=200)
    aspect_ratio: AspectRatio = "9:16"
    estilo_visual: str = Field(default="", max_length=400)          # âncora de coerência
    cenas: list[SceneSpec] = Field(min_length=2, max_length=10)

    @model_validator(mode="after")
    def _indices_contiguos(self) -> Self:
        if [c.scene_index for c in self.cenas] != list(range(len(self.cenas))):
            raise ValueError("scene_index deve ser 0..N-1, sem lacunas e em ordem")
        return self
```

Extensões ao contrato do documento-base: `estilo_visual`, `seed`, `extra="forbid"` (rejeita campos
inventados pelo LLM) e `max_length` apenas como teto — a regra de negócio é por **palavras**.

## 2. Regras de negócio — `domain/script_rules.py`

```python
@dataclass(frozen=True)
class ScriptLimits:
    scene_seconds: float = 4.0
    words_per_second: float = 3.0
    @property
    def max_words(self) -> int: return int(self.scene_seconds * self.words_per_second)   # 12

@dataclass(frozen=True)
class RuleViolation:
    scene_index: int | None      # None = violação global
    code: str                    # TOO_MANY_WORDS | EMPTY_NARRATION | PROMPT_HAS_SPEECH | ...
    message: str

def validate_rules(script: VideoScriptSchema, limits: ScriptLimits) -> list[RuleViolation]: ...
def ensure_valid(script: VideoScriptSchema, limits: ScriptLimits) -> None:   # levanta ScriptValidationError
```

Regras: ≤ `max_words` palavras por cena; narração não vazia; `prompt_video` em inglês (heurística de
stop-words); `prompt_video` sem pedido de texto em tela nem de pessoa falando para a câmera (T2V não
tem *lip-sync*). Retorna **lista** de violações para a UI exibir por cena e para o *repair loop*.

## 3. Pedido do job — `domain/request.py`

```python
class ModelChoice(BaseModel):         # chaves do models.yaml
    llm: str; tts: str; video: str

class RenderOptions(BaseModel):
    resolution: Literal["480p", "720p"] = "480p"
    fps: Literal[24, 30] = 30
    duracao_cena_s: float = Field(4.0, ge=2, le=8)
    legendas: bool = True

class JobRequest(BaseModel):
    tema: str = Field(min_length=3, max_length=500)
    aspect_ratio: AspectRatio = "9:16"
    n_cenas: int = Field(5, ge=2, le=10)
    models: ModelChoice
    voice_id: str
    options: RenderOptions = RenderOptions()
    max_budget_usd: float = Field(2.0, gt=0, le=100)
```

## 4. Progresso e custo — `domain/progress.py`, `domain/cost.py`

```python
class StepStatus(StrEnum): PENDING="pending"; RUNNING="running"; DONE="done"; FAILED="failed"

class StepState(BaseModel):
    status: StepStatus = StepStatus.PENDING
    artifact_hash: str | None = None
    remote_id: str | None = None        # id da predição no provedor (retomada)
    cached: bool = False
    attempts: int = 0
    cost_usd: float = 0.0
    error: ErrorInfo | None = None

class SceneProgress(BaseModel):
    scene_index: int
    audio: StepState = StepState()      # TTS + loudnorm
    video: StepState = StepState()      # T2V
    clip: StepState = StepState()       # sync + legenda + encode da cena

class CostLedger(BaseModel):
    llm_usd: float = 0.0; tts_usd: float = 0.0; video_usd: float = 0.0
    @property
    def total(self) -> float: ...
    def add(self, kind: Literal["llm", "tts", "video"], usd: float) -> None: ...

class SceneEstimate(BaseModel): scene_index: int; tts_usd: float; video_usd: float; cached: bool
class CostEstimate(BaseModel): scenes: list[SceneEstimate]; total_usd: float; spent_usd: float
```

## 5. Job — `domain/job.py`

```python
class Approval(BaseModel):
    script_version: int; approved_at: datetime; max_budget_usd: float

class JobState(BaseModel):
    job_id: str
    revision: int = 0                       # concorrência otimista do manifesto
    status: JobStatus
    failed_stage: Literal["scripting", "rendering", "finalizing"] | None = None
    request: JobRequest
    script_version: int = 0
    script: VideoScriptSchema | None = None
    approval: Approval | None = None        # preenchido ⇒ roteiro congelado
    scenes: list[SceneProgress] = []        # criado na aprovação
    final_hash: str | None = None
    ledger: CostLedger = CostLedger()
    error: ErrorInfo | None = None
    created_at: datetime; updated_at: datetime
```

## 6. Estados — `domain/status.py`

```python
class JobStatus(StrEnum):
    SCRIPTING="scripting"; AWAITING_APPROVAL="awaiting_approval"; APPROVED="approved"
    RENDERING="rendering"; FINALIZING="finalizing"; COMPLETED="completed"
    FAILED="failed"; CANCELED="canceled"

TRANSITIONS: dict[JobStatus, frozenset[JobStatus]] = {
    SCRIPTING:         {AWAITING_APPROVAL, FAILED, CANCELED},
    AWAITING_APPROVAL: {SCRIPTING, APPROVED, CANCELED},
    APPROVED:          {RENDERING, CANCELED},
    RENDERING:         {FINALIZING, FAILED, CANCELED},
    FINALIZING:        {COMPLETED, FAILED, CANCELED},
    FAILED:            {SCRIPTING, RENDERING, AWAITING_APPROVAL, CANCELED},   # retry | reopen
    COMPLETED:         {AWAITING_APPROVAL},                                   # reopen
    CANCELED:          set(),
}
def ensure_transition(src: JobStatus, dst: JobStatus) -> None: ...   # InvalidTransition
```

Regras adicionais: `FAILED → SCRIPTING` só se `failed_stage == "scripting"`; `FAILED → RENDERING` só se
`failed_stage in {"rendering", "finalizing"}`. **Editar** roteiro não muda o estado (só `script_version`).

## 7. Pedidos de geração e hash — `domain/generation.py`, `domain/hashing.py`

Os *requests* enviados ao provedor **são** a fonte do hash; é impossível esquecer um parâmetro.

```python
class TTSRequest(BaseModel):
    model_key: str; model_version: str
    text: str                      # NFC + strip
    language: str = "pt-BR"
    ref_text: str
    ref_audio_sha256: str          # conteúdo da voz, não o caminho
    speed: float = 1.0
    ref_audio_path: Path = Field(exclude=True)    # necessário ao provedor, fora do hash

class VideoRequest(BaseModel):
    model_key: str; model_version: str
    prompt: str                    # prompt_video + estilo_visual já combinados
    negative_prompt: str = ""
    width: int; height: int; num_frames: int; fps: int
    seed: int
    extra: dict[str, JsonScalar] = {}

class RunContext(BaseModel):                       # entregue pelo CachedStep ao provedor
    resume_remote_id: str | None = None
    on_submitted: Callable[[str], Awaitable[None]] = Field(exclude=True)
    timeout_s: float

class GenerationResult(BaseModel):
    remote_id: str; output_url: str
    cost_usd: float | None = None; provider_seconds: float | None = None
```

```python
HASH_SCHEMA_VERSION = 1
def content_hash(kind: str, payload: Mapping[str, Any]) -> str:
    blob = json.dumps({"v": HASH_SCHEMA_VERSION, "kind": kind, **payload},
                      sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(blob.encode()).hexdigest()

def audio_hash(r: TTSRequest) -> str:   return content_hash("tts_raw", r.model_dump())
def video_hash(r: VideoRequest) -> str: return content_hash("t2v_raw", r.model_dump())
def clip_hash(audio_norm: str, video: str, spec: ClipSpec) -> str: ...
def final_hash(clip_hashes: Sequence[str], spec: ConcatSpec) -> str: ...
```

`scene_index` e `job_id` **não** entram no hash (reordenar/clonar reaproveita). Encadeamento:
`audio_norm_hash = h(audio_raw_hash + loudnorm params)`; `clip_hash = h(audio_norm + video + sync cfg +
estilo de legenda + texto + saída)`; `final_hash = h(lista ordenada de clip_hash + params de concat)`.
Testes com *golden vectors* travam a estabilidade do formato (mudar ⇒ subir `HASH_SCHEMA_VERSION`).

## 8. Plano de sincronização — `domain/sync.py` (função pura)

```python
class SyncStrategy(StrEnum): NONE="none"; STRETCH="stretch"; FREEZE_ZOOM="freeze_zoom"; TRIM="trim"

@dataclass(frozen=True)
class SyncConfig:
    tolerance_s: float = 0.2; stretch_min: float = 0.85; stretch_max: float = 1.35; fade_out_s: float = 0.3

@dataclass(frozen=True)
class SyncPlan:
    strategy: SyncStrategy
    setpts_factor: float       # multiplicador de PTS (1.0 = sem efeito)
    freeze_extra_s: float      # tempo de congelamento + zoom ao final
    target_duration_s: float   # duração final do clipe = duração do áudio

def plan_sync(t_audio: float, t_video: float, cfg: SyncConfig) -> SyncPlan:
    if abs(t_audio - t_video) <= cfg.tolerance_s:
        return SyncPlan(NONE, 1.0, max(0.0, t_audio - t_video), t_audio)
    s = t_audio / t_video
    if cfg.stretch_min <= s <= cfg.stretch_max:
        return SyncPlan(STRETCH, s, 0.0, t_audio)
    if s > cfg.stretch_max:      # áudio bem mais longo: estica ao máximo e congela com zoom
        return SyncPlan(FREEZE_ZOOM, cfg.stretch_max, t_audio - t_video * cfg.stretch_max, t_audio)
    return SyncPlan(TRIM, cfg.stretch_min, 0.0, t_audio)   # áudio bem mais curto: acelera e corta
```

`S > 1` desacelera (*slow-motion*), `S < 1` acelera. Tabela de casos (T_video = 5,06 s):

| T_audio | S | Estratégia | Efeito |
|---|---|---|---|
| 5,10 | 1,01 | NONE | completa 0,04 s com último frame |
| 6,20 | 1,23 | STRETCH | `setpts=1.23*PTS` |
| 8,50 | 1,68 | FREEZE_ZOOM | estica ×1,35 (6,83 s) + 1,67 s de freeze com zoom |
| 3,50 | 0,69 | TRIM | acelera ×0,85, corta em 3,50 s, fade-out 0,3 s |

## 9. Eventos — `domain/events.py`

Envelope `Event(seq, job_id, type, data, ts)`. Tipos: `job.status`, `script.updated`,
`scene.step` (`scene_index`, `step: audio|video|clip`, `status`, `cached`, `cost_usd`),
`job.cost`, `job.completed`, `job.failed`. Cada tipo tem um modelo Pydantic próprio (união
discriminada por `type`) — contrato único usado pelo SSE e pelo `events.jsonl`.

## 10. Ports (`ports/`) — assinaturas

| Port | Métodos |
|---|---|
| `LLMProvider` | `async complete(messages: list[ChatMessage], *, json_mode: bool, temperature: float \| None) -> LLMResult(text, usage, cost_usd)` |
| `TTSProvider` | `async synthesize(req: TTSRequest, ctx: RunContext) -> GenerationResult` · `async cancel(remote_id)` |
| `VideoProvider` | `async generate(req: VideoRequest, ctx: RunContext) -> GenerationResult` · `async cancel(remote_id)` |
| `MediaComposer` | `async normalize_audio(src, dst) -> None` · `async compose_clip(spec: ClipSpec) -> Path` · `async concat(clips, dst, spec) -> Path` |
| `MediaProbe` | `async probe(path) -> MediaInfo(duration_s, has_video, has_audio, fps, width, height)` |
| `JobRepository` | `create` · `get` · `list` · `update(job_id, mutator) -> JobState` (lock + revisão) |
| `ArtifactCache` | `get(kind, key) -> Path \| None` · `tmp_path(kind, key) -> Path` · `commit(kind, key, tmp) -> Path` |
| `Downloader` | `async fetch(url, dest, *, allowed_hosts, max_bytes) -> None` |
| `EventBus` | `publish(job_id, event)` · `subscribe(job_id, last_event_id) -> AsyncIterator[Event]` |
| `VoiceStore` | `save(audio, ref_text) -> VoiceRef` · `get(voice_id) -> VoiceRef` · `delete` · `list` |

Princípio de segregação: cada port tem ≤ 5 métodos; nenhum "port-deus".
