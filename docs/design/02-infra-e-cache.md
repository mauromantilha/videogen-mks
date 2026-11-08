# Design 02 — Infra, cache e configuração

> Pacotes: `core/`, `infra/`, `app/` · Tarefas: M0 (T-004, T-005), M2 · Voltar: [design.md](../design.md)

## 1. Configuração — `core/config/`

Settings é um *god object* clássico. Aqui ele é **dividido por responsabilidade**, cada grupo com
`pydantic-settings` e leitura do mesmo `.env`:

| Arquivo | Classe | Conteúdo |
|---|---|---|
| `app.py` | `AppSettings` | `APP_ENV`, `APP_API_KEY`, `WORKSPACE_DIR`, `LOG_LEVEL`, `MODELS_CONFIG` |
| `providers.py` | `ProviderSettings` | `DEEPSEEK_API_KEY`, `REPLICATE_API_TOKEN`, `FAL_KEY`, `DEEPINFRA_API_TOKEN` (`SecretStr`), `PROVIDER_MODE=real\|fake` |
| `render.py` | `RenderSettings` | paralelismo, timeouts, `LOUDNESS_LUFS`, `SYNC_*`, `HTTP_MAX_ATTEMPTS`, `DEFAULT_MAX_BUDGET_USD` |
| `loader.py` | `load_settings()` | agrega os três em `Settings` (dataclass imutável) e valida combinações |

```dotenv
# .env.example
APP_ENV=dev
APP_API_KEY=troque-por-um-segredo-longo
WORKSPACE_DIR=./workspace
MODELS_CONFIG=./config/models.yaml
PROVIDER_MODE=real                  # fake = custo zero
DEEPSEEK_API_KEY=
REPLICATE_API_TOKEN=
FAL_KEY=
DEEPINFRA_API_TOKEN=
MAX_PARALLEL_JOBS=2
MAX_PARALLEL_TTS=6
MAX_PARALLEL_VIDEO=4
MAX_PARALLEL_FFMPEG=2
HTTP_MAX_ATTEMPTS=3
VIDEO_TIMEOUT_S=300
DEFAULT_MAX_BUDGET_USD=2.00
LOUDNESS_LUFS=-14
SYNC_TOLERANCE_S=0.2
SYNC_STRETCH_MIN=0.85
SYNC_STRETCH_MAX=1.35
```

Os modelos (versões, preços, limites) ficam em `config/models.yaml` (design/03 §2), **não** no `.env`.

## 2. Núcleo — `core/`

| Arquivo | Responsabilidade |
|---|---|
| `errors.py` | Hierarquia: `DomainError` → `NotFound`, `AlreadyExists`, `InvalidTransition`, `VersionConflict`, `ValidationFailed` (base do `ScriptValidationError`, que vive em `domain/script_rules.py` por carregar `RuleViolation`), `BudgetExceeded`, `ProviderError` (`retryable: bool`), `ProviderTimeout`, `ContentRejected`, `MediaError`. Cada uma com `code` estável e `http_status` sugerido (o mapeamento HTTP fica em `api/error_handlers.py`). |
| `logging.py` | Formatter JSON stdlib; `contextvars` (`job_id`, `scene_index`, `step`); filtro que redige segredos. |
| `retry.py` | `RetryPolicy` + `retry_async()` — backoff exponencial com *jitter*, compartilhado por providers e downloader (design/03 §1). |
| `ids.py` | `new_job_id()` → `job_<12 hex>`; `JOB_ID_RE`; `new_voice_id()`. |
| `clock.py` | `Clock` (Protocol) + `SystemClock`; permite testes determinísticos. |

## 3. Workspace e layout em disco — `infra/workspace.py`

```
workspace/
├── _cache/{audio_raw|audio_norm|video_raw|clip}/{hash[:2]}/{hash}.{wav|mp4}
│                                                  └── {hash}.meta.json   # provedor, remote_id, custo, spec
├── _voices/{voice_id}/{ref.wav, voice.json}
└── jobs/{job_id}/
    ├── job_state.json            # manifesto (fonte da verdade)
    ├── events.jsonl              # auditoria append-only
    ├── script/v0001.json …       # histórico de revisões do roteiro
    ├── tmp/                      # parciais; limpo no startup
    ├── scene_00/ …               # *views* (symlink/hardlink) para audio.wav, video.mp4, clip.mp4
    └── final_render.mp4
```

`Workspace` só resolve caminhos e garante segurança: `job_dir(job_id)` valida `JOB_ID_RE` e confere
que `resolve()` permanece dentro de `WORKSPACE_DIR` (anti *path traversal*). Mantém a convenção
`scene_{i}/` do documento-base como *views* para pré-visualização, mas a **fonte** é o cache por hash.

## 4. `JsonJobRepository` — `infra/job_repository.py`

- Um arquivo por job. **Escrita atômica:** gravar `job_state.json.tmp` → `flush` + `fsync` → `os.replace`.
- `update(job_id, mutator)` executa sob `asyncio.Lock` por job: lê → aplica `mutator(state)` → valida
  Pydantic → `revision += 1` → grava. I/O em `asyncio.to_thread` (RNF-11).
- `mutator` é função **síncrona e curta** (sem `await` dentro do lock) → sem *deadlock*.
- Falha de validação do estado resultante aborta a escrita (nunca persiste estado inválido).
- `list()` lê só o cabeçalho necessário; a lista da UI usa um índice leve em memória reconstruído no startup.
- Trocar por SQLite/S3 = novo adapter do mesmo port.

```python
async def update(self, job_id: str, mutator: Callable[[JobState], None]) -> JobState:
    async with self._locks.for_job(job_id):
        state = await self._read(job_id)
        mutator(state)
        state.revision += 1; state.updated_at = self._clock.now()
        JobState.model_validate(state.model_dump())          # invariantes
        await self._write_atomic(job_id, state)
        return state
```

## 5. `FileArtifactCache` — `infra/artifact_cache.py`

Cache **content-addressed** (ADR-05):

- `get(kind, key)`: retorna o caminho se existir **e** `size > 0` e houver `.meta.json` (arquivo parcial
  nunca é considerado hit).
- `tmp_path(kind, key)`: arquivo `…/{hash}.part-<uuid>` na mesma partição do destino.
- `commit(kind, key, tmp)`: `fsync` + `os.replace` (atômico) → grava `.meta.json` → retorna caminho final.
  Duas escritas concorrentes do mesmo hash são seguras (última vence, conteúdo equivalente).
- `link_into(job_dir, scene_index, ...)`: cria *views* por symlink (fallback hardlink/cópia).
- Evicção/TTL em `infra/cleanup.py` (por *mtime*, nunca apaga artefato referenciado por job ativo).

### Single-flight (em `services/render/single_flight.py`, ver design/05)

O cache evita repetição **entre execuções**; o *single-flight* evita repetição **dentro da mesma
execução** (duas cenas com o mesmo prompt/seed ⇒ uma só predição).

## 6. `InMemoryEventBus` — `infra/event_bus.py`

- Por job: lista de assinantes (`asyncio.Queue(maxsize=256)`) + *ring buffer* dos últimos 200 eventos.
- `publish` é não bloqueante; assinante lento que enche a fila é descartado (cliente reconecta e recebe
  *snapshot* + eventos).
- `seq` monotônico por job em memória. `subscribe(job_id, last_event_id)` reenvia o que estiver no
  *ring buffer* com `seq > last_event_id`; se o ponto for anterior ao buffer (ou após restart), o router
  SSE envia primeiro um evento `snapshot` com o `JobView` completo — **o manifesto é a verdade**.
- Um assinante interno grava cada evento em `events.jsonl` (auditoria; desacoplado do publish).

## 7. `HttpDownloader` — `infra/downloader.py`

Responsabilidade única: baixar URL → arquivo, com segurança.

- Só `https`; host deve estar em `allowed_hosts` do provedor (ex.: `replicate.delivery`,
  `*.fal.media`) — a URL vem do JSON do provedor, tratada como **não confiável** (anti-SSRF).
- `follow_redirects` limitado e revalidando o host a cada salto; sem credenciais encaminhadas.
- *Streaming* em *chunks* para `dest.part`, com `max_bytes` (padrão 500 MB) e *timeout* de leitura.
- Retry com a mesma `RetryPolicy` dos providers, importada de `core/retry.py` (nunca de `providers`).
- Validação do conteúdo (`MediaProbe`) fica no `CachedStep`, não aqui.

## 8. `FileVoiceStore` — `infra/voice_store.py`

`save()` recebe bytes já validados pelo `VoiceService`; grava `ref.wav` normalizado (mono, 24 kHz —
exigência típica do F5-TTS) e `voice.json` `{voice_id, ref_text, sha256, duration_s, created_at}`.
O `sha256` do **conteúdo** compõe o hash do áudio (`TTSRequest.ref_audio_sha256`).

## 9. Recuperação no startup — `services/jobs/recovery.py` (consumida por `app/lifespan.py`)

1. Limpa `jobs/*/tmp/` e `_cache/**/*.part-*` órfãos.
2. Varre `jobs/*/job_state.json`; para status em `{scripting, approved, rendering, finalizing}`
   chama `JobRunner.submit(job_id, stage)`.
3. `rendering/finalizing` reentram no `RenderCoordinator`; steps com `remote_id` gravado e sem artefato
   **retomam o polling** da mesma predição (nada é reenviado). `scripting` simplesmente refaz a chamada
   ao LLM (custo desprezível).
4. Jobs `awaiting_approval/completed/failed/canceled` não são tocados.

## 10. Composition root — `app/`

| Arquivo | Papel |
|---|---|
| `factory.py` | `create_app()`: instancia FastAPI, registra routers/handlers/estáticos, anexa `Container`. |
| `container_infra.py` | Monta `Workspace`, repositório, cache, event bus, downloader, voice store. |
| `container_providers.py` | Monta `ProviderRegistry` a partir de `models.yaml` + `ProviderSettings` (real ou fake). |
| `container_services.py` | Monta serviços injetando *ports*; expõe objeto imutável `Container`. |
| `lifespan.py` | Startup: `ToolchainCheck`, recovery, `JobRunner.start()`; shutdown: drena/cancela com *grace*. |

Regra: **nenhuma lógica** no composition root, só *wiring*; cada arquivo ≤ 120 linhas.
