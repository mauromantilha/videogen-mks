# Marcos M0–M2 — Fundações, Domínio, Infra

> Voltar: [tasks.md](../tasks.md) · Design: [01](../design/01-dominio-e-contratos.md), [02](../design/02-infra-e-cache.md), [07](../design/07-qualidade-seguranca-operacao.md)

## M0 — Fundações e guardiões

### T-001 — Scaffold do projeto · S · dep: — · cobre: RNF-12, RNF-13
- **Entrega:** `pyproject.toml` (Python ≥ 3.12, deps do requirements §6, ruff/mypy/pytest configurados),
  layout `src/videogen/*` com `__init__.py`, `src/videogen/main.py`, `.gitignore`, `.env.example`
  (design/02 §1), `Makefile` (`lint`, `types`, `test`, `limits`, `run`), `.pre-commit-config.yaml`.
- **DoD:** `make lint types test` roda (vazio) e passa; `uvicorn videogen.main:app` sobe com `/healthz` mínimo.

### T-002 — Guardião de tamanho `check_limits.py` · M · dep: T-001 · cobre: RNF-05
- **Entrega:** `scripts/check_limits.py` (≤ 150) + `tests/architecture/test_limits.py`. Regras do design/07 §1:
  arquivo/classe/função > 300 ⇒ erro; metas ⇒ aviso (`--strict` torna erro); nomes proibidos
  (`*Manager`, `utils.py`…). Flag `--changed` (git) para pre-commit.
- **DoD:** testes com arquivos sintéticos (299/300/301 linhas, função e classe gigantes, método público
  11) provam cada regra; o próprio script respeita o limite; falha o CI em violação (AC-08).

### T-003 — Contratos de camadas + CI · S · dep: T-001 · cobre: RNF-06, RNF-12
- **Entrega:** `.importlinter` (design/07 §1.3), job de CI (`ruff → mypy → lint-imports → check_limits →
  pytest --cov`), `tests/architecture/test_layers.py` chamando `lint-imports`.
- **DoD:** import proibido de teste (`services` importando `httpx`) quebra o contrato.

### T-004 — Configuração fatiada · S · dep: T-001 · cobre: RNF-03, RNF-07
- **Entrega:** `core/config/{app,providers,render,loader}.py` (≤ 90 cada), `SecretStr`, validação de
  combinações (ex.: `PROVIDER_MODE=real` exige ao menos uma chave).
- **DoD:** testes de leitura de env/`.env`, valores padrão, erro claro em configuração inválida;
  `repr(settings)` não exibe segredos.

### T-005 — Núcleo: erros, logging, ids, clock · S · dep: T-001 · cobre: RNF-08
- **Entrega:** `core/{errors,logging,ids,clock}.py` (design/02 §2). Hierarquia com `code` e `retryable`.
- **DoD:** formatter JSON com `contextvars`; filtro de segredos testado; `JOB_ID_RE` rejeita `../x`.

## M1 — Domínio e ports (puro, sem I/O)

### T-010 — Roteiro e regras · M · dep: T-005 · cobre: RF-01, RF-07
- **Entrega:** `domain/script.py` (≤ 90), `domain/script_rules.py` (≤ 110) conforme design/01 §1–2.
- **DoD:** testes: índices não contíguos, `extra=forbid`, 12 vs 13 palavras, narração vazia, prompt pedindo
  texto em tela/pessoa falando ⇒ violação com `scene_index` correto; `ensure_valid` agrega todas.

### T-011 — Pedido do job e requests de geração · S · dep: T-010 · cobre: RF-01, RF-02, RF-03, RNF-02
- **Entrega:** `domain/request.py` (≤ 90), `domain/generation.py` (≤ 110): `JobRequest`, `TTSRequest`,
  `VideoRequest`, `RunContext`, `GenerationResult`.
- **DoD:** `ref_audio_path` excluído do `model_dump`; limites de `n_cenas`/`max_budget_usd` testados.

### T-012 — Estados e Job · M · dep: T-010, T-011 · cobre: RF-09, RF-11
- **Entrega:** `domain/status.py` (≤ 70), `domain/job.py` (≤ 110), `domain/freeze.py` (≤ 60: `freeze()` puro).
- **DoD:** teste exaustivo da tabela `TRANSITIONS` (todas as 8×8 combinações); `FAILED→SCRIPTING` só com
  `failed_stage="scripting"`; `freeze` é determinístico e preenche seeds sem sobrescrever as existentes.

### T-013 — Progresso, custo, erros de step · S · dep: T-012 · cobre: RF-08, RF-10, RNF-10
- **Entrega:** `domain/progress.py` (≤ 100), `domain/cost.py` (≤ 90).
- **DoD:** `CostLedger.add/total`; serialização/desserialização estável do `JobState` (round-trip JSON).

### T-014 — Hashing de conteúdo · S · dep: T-011 · cobre: RNF-02
- **Entrega:** `domain/hashing.py` (≤ 70): `content_hash`, `audio_hash`, `video_hash`, `clip_hash`, `final_hash`.
- **DoD:** *golden vectors* fixos; alterar qualquer campo de `TTSRequest`/`VideoRequest` muda o hash;
  `scene_index`/`job_id` não influenciam; ordem de chaves irrelevante.

### T-015 — Plano de sincronização · S · dep: T-001 · cobre: RF-04
- **Entrega:** `domain/sync.py` (≤ 110): `SyncConfig`, `SyncPlan`, `plan_sync`.
- **DoD:** tabela de casos do design/01 §8 + propriedades (`target_duration == t_audio`; fatores dentro de
  `[stretch_min, stretch_max]`; `t_video == 0` levanta erro claro).

### T-016 — Eventos e mídia · S · dep: T-013 · cobre: RF-10
- **Entrega:** `domain/events.py` (≤ 90, união discriminada), `domain/media.py` (≤ 60: `ArtifactKind`,
  `MediaInfo`, `VoiceRef`), `domain/render_specs.py` (≤ 80: `LoudnessParams`, `ClipParams`, `ClipSpec`,
  `ConcatParams` — os `*Params` entram no hash, os caminhos não).
- **DoD:** serialização SSE (`id/event/data`) coberta por teste.

### T-017 — Ports · M · dep: T-011…T-016 · cobre: RNF-03, RNF-06
- **Entrega:** `ports/{llm,tts,video,composer,repository,cache,events,downloader,probe,voices}.py` (≤ 60 cada,
  ≤ 5 métodos por `Protocol`), conforme design/01 §10.
- **DoD:** `mypy --strict` aceita as implementações de teste; `lint-imports` confirma que `ports` só importa `domain`.

### T-018 — Dublês de teste dos ports · S · dep: T-017 · cobre: RNF-12
- **Entrega:** `tests/fakes/{memory_repository,memory_cache,recording_bus,fake_clock}.py` (≤ 100 cada).
- **DoD:** reutilizados nos testes de serviço; `InMemoryRepository` respeita revisão otimista como o real.

## M2 — Infra

### T-020 — Workspace seguro · S · dep: T-004, T-005 · cobre: RNF-07
- **Entrega:** `infra/workspace.py` (≤ 90): resolução de caminhos, layout do design/02 §3.
- **DoD:** `../`, symlink para fora e `job_id` inválido são rejeitados; criação idempotente de diretórios.

### T-021 — JobRepository JSON atômico · M · dep: T-012, T-017, T-020 · cobre: RNF-09, RNF-11
- **Entrega:** `infra/job_repository.py` (≤ 150): `create/get/list/update` com lock por job, `fsync` +
  `os.replace`, `to_thread`, revisão.
- **DoD:** 50 `update` concorrentes ⇒ 50 incrementos sem perda; *crash* simulado entre `.tmp` e `replace`
  deixa o estado anterior íntegro; estado inválido nunca é persistido.

### T-022 — ArtifactCache content-addressed · M · dep: T-017, T-020 · cobre: RNF-02
- **Entrega:** `infra/artifact_cache.py` (≤ 140): `get/tmp_path/commit/link_into`, `.meta.json`.
- **DoD:** arquivo `.part` ou de tamanho 0 nunca é *hit*; commits concorrentes do mesmo hash seguros;
  *views* `scene_{i}/` criadas por symlink com fallback.

### T-023 — EventBus em memória · M · dep: T-016, T-017 · cobre: RF-10, RNF-08
- **Entrega:** `infra/event_bus.py` (≤ 120): assinantes por job, *ring buffer* 200, `seq`, descarte de
  assinante lento; assinante de auditoria → `events.jsonl`.
- **DoD:** *replay* por `last_event_id`; fila cheia não bloqueia `publish`; N assinantes recebem tudo em ordem.

### T-024 — Downloader seguro · M · dep: T-017, T-030 · cobre: RNF-07, RNF-04
- **Entrega:** `infra/downloader.py` (≤ 130): streaming, `.part` → rename, `allowed_hosts`, `max_bytes`,
  revalidação a cada redirect; usa `core.retry`.
- **DoD:** teste com `respx`: host fora da *allowlist* ⇒ recusa; redirect para host proibido ⇒ recusa;
  corpo > `max_bytes` ⇒ aborta e remove parcial; retry em 503.

### T-025 — VoiceStore · S · dep: T-017, T-020 · cobre: RF-12
- **Entrega:** `infra/voice_store.py` (≤ 110): salva `ref.wav` + `voice.json` (sha256 do conteúdo).
- **DoD:** `save/get/list/delete`; mesmo conteúdo ⇒ mesmo `sha256`; `voice_id` inválido ⇒ `NotFound`.

### T-026 — Limpeza (TTL) · S · dep: T-022 · cobre: RNF-13
- **Entrega:** `infra/cleanup.py` (≤ 90): TTL de jobs/cache, `tmp` órfão; nunca remove artefato referenciado
  por job não terminal.
- **DoD:** teste com relógio falso e jobs em vários estados.
