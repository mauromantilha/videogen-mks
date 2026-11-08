# Design 05 — Serviços e orquestração (Etapa 1 e Etapa 2)

<!-- # limits: allow file-lines — cobre as duas etapas; dividir se passar de 280 linhas -->

> Pacote: `services/` · Tarefas: M5 e M7 · Voltar: [design.md](../design.md)

Serviços dependem **apenas** de `ports` e `domain`. Cada classe tem uma responsabilidade; o
orquestrador "deus" do documento-base (`orchestrator.py`) é dividido em 14 componentes pequenos.

## 1. Mapa de responsabilidades

| Serviço | Responsabilidade única | Depende de (ports) |
|---|---|---|
| `ScriptService` | Gerar/regenerar roteiro via LLM | `LLMProvider`, `JobRepository`, `EventBus` |
| `PromptBuilder` | Montar mensagens do LLM (puro) | — |
| `ScriptRepairLoop` | Parse + validação + reparo da saída do LLM | `LLMProvider` |
| `ScriptEditService` | Editar roteiro à mão (sem custo) | `JobRepository`, `EventBus` |
| `CostEstimator` | Estimar custo descontando cache | `ArtifactCache`, `ModelCatalog` |
| `BudgetGuard` | Decidir se há orçamento para nova chamada | — |
| `ApprovalService` | Portão de aprovação | `JobRepository`, `CostEstimator`, `JobRunner` |
| `JobLifecycleService` | Criar, cancelar, retomar, reabrir, clonar | `JobRepository`, `JobRunner` |
| `JobRunner` | Executar jobs em segundo plano (asyncio) | — |
| `RecoveryService` | Re-enfileirar jobs interrompidos | `JobRepository`, `JobRunner` |
| `RenderCoordinator` | Fan-out por cena + política de falha | `ScenePipeline`, `Finalizer` |
| `ScenePipeline` | Uma cena: áudio ∥ vídeo → clipe | `AudioStep`, `VideoStep`, `MediaComposer` |
| `AudioStep` / `VideoStep` | Montar request, hash e chamar o provedor | `CachedStep`, providers |
| `CachedStep` | Cache → retomada → provedor → download → commit | `ArtifactCache`, `Downloader`, `MediaProbe` |
| `ProgressTracker` | Atualizar estado + publicar eventos + custo | `JobRepository`, `EventBus` |
| `Finalizer` | Concat final + `COMPLETED` | `MediaComposer`, `ProgressTracker` |

## 2. Etapa 1 — Geração de roteiro (RF-01)

`ScriptService.draft(job_id)` (executado pelo `JobRunner`, nunca no request HTTP):

1. Lê o job; `PromptBuilder.build(request, limits)` → mensagens.
2. `ScriptRepairLoop.run(messages)` → `VideoScriptSchema` válido (ou erro).
3. `repo.update`: grava `script`, `script_version = 1`, `status = AWAITING_APPROVAL`, `ledger.llm_usd`.
4. Publica `script.updated` + `job.status`.

**PromptBuilder** (conteúdo do *system prompt*): N cenas exatas; arco *gancho → desenvolvimento → CTA*;
`texto_narrado` em PT-BR com no máximo `max_words` palavras, sem emojis, sem números por extenso confusos;
`prompt_video` em **inglês**, estruturado `sujeito · ação · cenário · iluminação · câmera · estilo`;
**proibido**: texto/logos na imagem, pessoas falando para a câmera, marcas registradas; descrever de forma
**consistente** personagens/estilo em todas as cenas e resumir isso em `estilo_visual`; responder **apenas**
JSON no schema (embutido via `VideoScriptSchema.model_json_schema()`).

**ScriptRepairLoop** (≤ 110 linhas):

```python
async def run(self, messages) -> tuple[VideoScriptSchema, LLMResult]:
    for attempt in range(1 + self._max_repairs):             # 1 chamada + 2 reparos
        result = await self._llm.complete(messages, json_mode=self._json_mode, temperature=0.7)
        problems = self._parse_and_check(result.text)         # -> (script | None, list[str])
        if not problems.items:
            return problems.script, result
        messages = [*messages, assistant(result.text), user(self._repair_prompt(problems.items))]
    raise ScriptValidationError(problems.items)
```

`_parse_and_check` remove *fences*, `json.loads`, `VideoScriptSchema.model_validate`, depois
`validate_rules`. A mensagem de reparo lista violações **por cena** ("cena 2: 15 palavras, máx 12").

**Regeneração** (`regenerate(job_id, feedback, scene_index=None)`): estado volta a `SCRIPTING`; para
uma cena, o prompt inclui o roteiro atual e pede **somente** aquela cena, preservando as demais; o
resultado é enxertado e revalidado; `script_version += 1`.

## 3. Edição manual (RF-07) — `ScriptEditService`

Operações (cada uma ≤ 25 linhas, todas via `repo.update` atômico): `replace_script(script,
expected_version)`, `patch_scene(index, fields, expected_version)`, `add_scene(after_index)`,
`remove_scene(index)`, `move_scene(from, to)` (com renumeração de `scene_index`), `bump_seed(index)`
(botão "gerar outra versão"). Regras comuns: status deve ser `AWAITING_APPROVAL`
(`InvalidTransition` caso contrário); `expected_version != script_version` ⇒ `VersionConflict`; resultado
validado por `ensure_valid` — violações retornam `422` com a lista **por cena**; sucesso ⇒
`script_version += 1`, evento `script.updated`, snapshot em `script/vNNNN.json`.

## 4. Custo e aprovação (RF-08, RF-09)

**CostEstimator.estimate(job)** — para cada cena calcula `audio_hash`/`video_hash` (os mesmos que o render
usaria) e consulta `ArtifactCache.get`: hit ⇒ custo 0 e `cached=true`; miss ⇒ `Price` do `ModelSpec`.
Usa `seed` provisória determinística quando ainda não fixada, para o hash da estimativa coincidir com o
real. Retorna `CostEstimate` (cenas + total + `spent_usd`).

**ApprovalService.approve(job_id, script_version, max_budget_usd)**:

```python
state = await repo.get(job_id)
ensure_status(state, AWAITING_APPROVAL)
if state.script_version != script_version:  raise VersionConflict(...)
ensure_valid(state.script, limits)
estimate = await estimator.estimate(state)
BudgetGuard.ensure_within(estimate.total_usd, max_budget_usd)      # BudgetExceeded → 422
await repo.update(job_id, lambda s: freeze(s, script_version, max_budget_usd))  # seeds, scenes[], APPROVED
runner.submit(job_id, stage="render")
```

`freeze` é função pura em `domain`: preenche `seed` ausente (`seed = int(sha256(job_id+index)[:8],16)`),
cria `scenes: list[SceneProgress]`, seta `approval`. A mesma operação de leitura+gravação é atômica.

## 5. Etapa 2 — Renderização (RF-02…RF-06)

### 5.1 `JobRunner` (ADR-04)

Mantém `dict[job_id, asyncio.Task]` e um `Semaphore(MAX_PARALLEL_JOBS)`. `submit(job_id, stage)` cria a
task que chama `ScriptService.draft` ou `RenderCoordinator.run`; erros inesperados viram `FAILED` com
`failed_stage`. `cancel(job_id)` cancela a task e dispara `cancel` best-effort nas predições abertas.
`start()/shutdown(grace_s)` ligados ao *lifespan*. Sem estado além do dicionário de tasks.

### 5.2 `RenderCoordinator.run(job_id)` — fan-out (RNF-01)

Versão assíncrona do `executar_geracao_paralela` do documento-base, com política de falha corrigida:

```python
async def run(self, job_id: str) -> None:
    job = await self._tracker.begin_render(job_id)                    # RENDERING
    results = await asyncio.gather(
        *(self._pipeline.run(job, scene) for scene in job.script.cenas),
        return_exceptions=True,            # ← falha de uma cena NÃO cancela as pagas das outras
    )
    failures = [(s.scene_index, r) for s, r in zip(job.script.cenas, results)
                if isinstance(r, BaseException)]
    if failures:
        await self._tracker.fail_render(job_id, failures)             # FAILED(rendering)
        return
    await self._finalizer.run(job_id)                                 # FINALIZING → COMPLETED
```

### 5.3 `ScenePipeline.run(job, scene)` — pipeline por cena

```python
audio_t = asyncio.create_task(self._audio.ensure(job, scene))       # TTS + loudnorm
video_t = asyncio.create_task(self._video.ensure(job, scene))       # T2V
audio, video = await asyncio.gather(audio_t, video_t)               # ambos terminam (ou erram) – sem cancelar o par
return await self._compose(job, scene, audio, video)                # sync + .ass + ffmpeg (cacheado por clip_hash)
```

A cena compõe assim que **seu** par A/V termina; não espera as outras (RNF-01). Se áudio ou vídeo falha,
o outro **ainda termina e fica em cache** (já foi pago) antes de a cena reportar erro.

### 5.4 `CachedStep.ensure(kind, key, produce, step_ref)` — o coração da idempotência

```python
if hit := cache.get(kind, key):                     await tracker.step_cached(ref); return hit
async with single_flight.guard(key):                # mesma chave concorrente → uma só execução
    if hit := cache.get(kind, key):                 await tracker.step_cached(ref); return hit
    await tracker.step_started(ref)
    resume = await tracker.remote_id(ref)           # ← retomada após crash/retry
    result = await produce(RunContext(resume_remote_id=resume,
                                      on_submitted=lambda rid: tracker.remote_id_saved(ref, rid),
                                      timeout_s=spec.timeouts.total_s))
    tmp = cache.tmp_path(kind, key)
    await downloader.fetch(result.output_url, tmp, allowed_hosts=spec.allowed_hosts)   # baixa já (URLs expiram)
    await probe.validate(tmp, kind)                 # mídia íntegra? duração > 0?
    path = cache.commit(kind, key, tmp)
    await tracker.step_done(ref, cost_usd=result.cost_usd, key=key)
    return path
```

Qualquer exceção ⇒ `tracker.step_failed(ref, error)` e *re-raise*. O `remote_id` permanece gravado para a
próxima tentativa (que retoma em vez de reenviar). Se o provedor devolver `failed`/`canceled`, o
`remote_id` é limpo para permitir nova submissão.

### 5.5 `AudioStep` / `VideoStep`

Responsabilidade: **montar o request** (a partir de `JobRequest`, cena, `ModelSpec`, `VoiceRef`),
calcular o hash (`domain.hashing`), chamar `CachedStep.ensure` com o `produce` do provedor. `AudioStep`
ainda encadeia `MediaComposer.normalize_audio` → `audio_norm` (também via cache). `VideoStep` combina
`prompt_video + estilo_visual`, escolhe `width/height/num_frames/fps` de `ModelSpec.limits` e a `seed`.

### 5.6 Limites de concorrência

`ProviderLimiter` (Semáforo por *chave de modelo*, tamanho = `ModelSpec.concurrency`, ou
`MAX_PARALLEL_*`) é adquirido **apenas durante submit+poll**; downloads e ffmpeg têm limites próprios
(`MAX_PARALLEL_FFMPEG`). Isso impede estouro de *rate limit* sem serializar o job.

### 5.7 `ProgressTracker`

Único ponto que muda `scenes[i].{audio,video,clip}`, `ledger` e `status` do job: cada método
(`step_started/_cached/_done/_failed`, `remote_id_saved`, `begin_render`, `fail_render`…) faz
`repo.update(mutator)` + `bus.publish(evento)`. `BudgetGuard` é consultado em `step_started`: se
`ledger.total` já excedeu `approval.max_budget_usd`, novas **tentativas** são bloqueadas
(`BudgetExceeded`), mas predições em voo concluem.

### 5.8 `Finalizer.run(job_id)`

`FINALIZING` → coleta `clip` de cada cena (ordem do roteiro) → `final_hash` → se `cache.get("final", h)`
existir, apenas linka; senão `MediaComposer.concat` → `probe` → `final_render.mp4` → `COMPLETED` →
evento `job.completed`.

## 6. Cancelamento, retry, reopen (RF-11) — `JobLifecycleService`

| Ação | Efeito |
|---|---|
| `cancel` | `JobRunner.cancel`; provedores `cancel(remote_id)` (best-effort); `CANCELED`; artefatos preservados no cache. |
| `retry` | Só de `FAILED`: `failed_stage` decide `SCRIPTING` ou `RENDERING`; steps `failed` voltam a `pending` (artefatos `done` ficam). |
| `reopen` | De `COMPLETED/FAILED` → `AWAITING_APPROVAL`; `approval = None`; roteiro editável; reaprovar re-renderiza só o delta (hash). |
| `clone` | Novo job com `request`+`script` copiados, `script_version = 1`, em `AWAITING_APPROVAL`. |

## 7. Estratégia de falhas

| Falha | Tratamento |
|---|---|
| LLM devolve JSON inválido | Reparo ×2 → `FAILED(scripting)` com violações. |
| Provedor 429/5xx/timeout | `retry_async` (3×, backoff) dentro do adapter. |
| Predição `failed` transitória | Nova submissão (conta nas 3 tentativas). |
| Conteúdo rejeitado pelo provedor | `ContentRejected` (sem retry) → cena `failed`; usuário `reopen` e edita o prompt. |
| Download corrompido/expirado | Retry do download; se a URL expirou, `GET` na predição devolve URL nova. |
| Crash do processo | Recovery (design/02 §9) retoma pelo `remote_id`. |
| Falha de composição FFmpeg | `MediaError` com `stderr`; cena `failed`; áudio/vídeo brutos permanecem em cache. |

## 8. Estado após a implementação do M5 (2026-11-08)

| Tema | Como ficou | Por quê |
|---|---|---|
| Edição manual | Erro de **estrutura** ⇒ 422, nada salvo. Violação de **regra** (ex.: 13 palavras) ⇒ salva e devolvida como aviso por cena; a **aprovação** bloqueia. | Editor com salvamento automático não pode perder o que foi digitado. |
| Ciclo de vida | Dividido em `JobCreationService` (criar, clonar) e `JobControlService` (regenerar, cancelar, retomar, reabrir, crash). | O serviço único acumulava 9 dependências. |
| Pedidos de geração | `domain/render_plan.py` monta TTS/vídeo para a estimativa **e** para o render. | Hash da estimativa = hash do render; cena em cache custa zero nos dois. |
| Novos ports | `ProviderResolver` (LLM/TTS/vídeo por chave; o registry o satisfaz) e `ScriptHistory` (`script/vNNNN.json`). | Serviços não importam adapters. |
| Regeneração que falha | Volta a `awaiting_approval` com o roteiro anterior e `error` preenchido; não derruba o job. | O roteiro anterior continua válido. |
| Regenerar uma cena | O LLM devolve o roteiro inteiro; o serviço enxerta só a cena pedida. | Mesmo parser para todos os casos; as outras cenas ficam idênticas. |
| Reparo barato | Cercas de código, numeração, `seed` inventada e proporção são corrigidas sem nova chamada. | Erros triviais não gastam LLM. |
| Recuperação | `scripting` sem roteiro ⇒ refaz o rascunho; com roteiro (regeneração perdida) ⇒ volta à revisão; render ⇒ reentra no render. | A instrução de regeneração não é persistida. |
| Voz de referência | 3 a 12 s, WAV mono 24 kHz normalizado (≤ ~576 KB). | F5-TTS aceita ~30 s de referência + fala; o Replicate recebe a referência inline (≤ 1 MB). |

## 9. Estado após a implementação do M7 (2026-11-08)

| Tema | Como ficou |
|---|---|
| Tracker | Dividido em `StepTracker` (estado de cada etapa, `remote_id`, orçamento) e `JobTracker` (render → finalizing → completed/failed). O único `ProgressTracker` teria 12 métodos públicos. |
| CachedStep | Só busca/produz (`PaidCall` → `Produced(path, custo, fresh)`); quem marca a etapa como `done`/`cached` é a etapa, com o hash final dela. Falha do provedor limpa o `remote_id`; falha no download o mantém; cancelamento cancela a predição remota. |
| Hash gravado por etapa | áudio = `audio_norm` (o que a API serve e o clipe usa), vídeo = `video_raw`, clipe = `clip`. |
| Etapas | `AudioStep` (TTS pago + loudnorm cacheado), `VideoStep`, `ClipStep` (local, sem orçamento) e `ScenePipeline` (áudio ∥ vídeo → clipe). `RenderContext` agrupa as dependências. |
| Single-flight | Futuro compartilhado por hash: valor **e** exceção são compartilhados; quem esperava não paga de novo. |
| Retomada no meio da concatenação | Coordenador vê `finalizing` e chama só o `Finalizer`. |
| Resolução de saída | `domain/render_plan.output_size`: lado menor 480/720, dimensões pares. |
| Montagem | `services/render/factory.py` (`RenderPorts`, `RenderTuning`); no container, `render = coordinator.run` alimenta aprovação, retry e recuperação. Modo fake usa `FakeMediaOrigin` como downloader. |
| Validado | Render real (FFmpeg) com provedores fake: MP4 final 480×854; mesma narração ⇒ 1 TTS; rerender ⇒ 0 chamadas pagas; falha parcial + retry refaz só a cena; retomada por `remote_id` sem reenvio; cancelamento cancela predições; pico de paralelismo medido e limite respeitado. |
