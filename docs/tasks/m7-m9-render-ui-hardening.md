# Marcos M7–M9 — Render (Etapa 2), UI e Hardening

> Voltar: [tasks.md](../tasks.md) · Design: [05](../design/05-servicos-e-orquestracao.md), [06](../design/06-api-e-ui.md), [07](../design/07-qualidade-seguranca-operacao.md)

## M7 — Renderização (Etapa 2)

### T-070 — SingleFlight e ProviderLimiter · S · dep: T-017 · cobre: RNF-01, RNF-02
- **Entrega:** `services/render/single_flight.py` (≤ 50), `services/render/limiter.py` (≤ 60).
- **DoD:** 10 chamadas concorrentes com a mesma chave executam `produce` **uma** vez e compartilham resultado
  (e exceção); semáforo por modelo respeita `concurrency`; cancelamento libera o slot.

### T-071 — ProgressTracker · M · dep: T-013, T-021, T-023, T-054 · cobre: RF-10, RNF-10
- **Entrega:** `services/render/progress_tracker.py` (≤ 150): `begin_render`, `step_started/_cached/_done/_failed`,
  `remote_id_saved/remote_id`, `fail_render`, ledger, eventos, `BudgetGuard`.
- **DoD:** cada método = 1 `repo.update` + 1 evento; `remote_id_saved` persiste antes de qualquer `poll`;
  orçamento excedido bloqueia **novas tentativas** mas não derruba predição em voo.

### T-072 — CachedStep · L · dep: T-070, T-071, T-022, T-024, T-041 · cobre: RNF-02, RNF-09
- **Entrega:** `services/render/cached_step.py` (≤ 120): algoritmo do design/05 §5.4.
- **DoD:** hit ⇒ 0 chamadas e `cached=true`; miss ⇒ 1 chamada, download, validação, commit; `resume_remote_id`
  presente ⇒ 0 submits; mídia corrompida ⇒ não vai ao cache; falha mantém `remote_id`, `failed`/`canceled`
  do provedor o limpa.

### T-073 — AudioStep · M · dep: T-072, T-042, T-014 · cobre: RF-02
- **Entrega:** `services/render/audio_step.py` (≤ 110): monta `TTSRequest` (voz, `ref_text`, sha), hash,
  `CachedStep` para `audio_raw`, normalização cacheada `audio_norm`.
- **DoD:** mudar só o alvo de LUFS refaz `audio_norm` **sem** nova chamada de TTS; texto idêntico em duas
  cenas ⇒ 1 chamada.

### T-074 — VideoStep · M · dep: T-072, T-014 · cobre: RF-03
- **Entrega:** `services/render/video_step.py` (≤ 110): `prompt_video + estilo_visual`, `width/height/
  num_frames/fps` do `ModelSpec`, seed fixa.
- **DoD:** mesma entrada ⇒ mesmo hash entre execuções; trocar `video: cogvideox-5b` muda hash e parâmetros
  sem alterar código do serviço (AC-09).

### T-075 — ScenePipeline · M · dep: T-073, T-074, T-045 · cobre: RNF-01, RF-04, RF-05
- **Entrega:** `services/render/scene_pipeline.py` (≤ 130): áudio ∥ vídeo → compose (cacheado por `clip_hash`).
- **DoD:** com latências falsas (TTS 1 s, vídeo 3 s) a cena leva ≈ 3 s (não 4 s); se o vídeo falha, o
  áudio já pago permanece em cache; clip reaproveitado quando nada mudou.

### T-076 — Finalizer · S · dep: T-046, T-071 · cobre: RF-06
- **Entrega:** `services/render/finalizer.py` (≤ 100): `final_hash`, concat, `probe`, `COMPLETED`, `job.completed`.
- **DoD:** reexecução sem mudanças não roda ffmpeg (link do cache); duração final ≈ soma dos clipes.

### T-077 — RenderCoordinator · M · dep: T-075, T-076 · cobre: RNF-01, RF-11
- **Entrega:** `services/render/coordinator.py` (≤ 120): `gather(return_exceptions=True)`, política de falha.
- **DoD:** cena 3 falha ⇒ cenas 1, 2, 4, 5 concluem e ficam em cache; job `FAILED(rendering)` listando a
  cena 3; `retry` só refaz a cena 3 (AC-03); com N=10 o tempo ≈ cena mais lenta.

### T-078 — Cancelamento ponta a ponta · M · dep: T-077, T-057, T-035 · cobre: RF-11
- **Entrega:** propagação `JobRunner.cancel → Coordinator → providers.cancel(remote_id)`.
- **DoD:** cancelar durante o polling chama `cancel` remoto, estado `CANCELED`, artefatos concluídos
  preservados, nenhuma task órfã (`asyncio.all_tasks` limpo).

## M8 — UI

### T-080 — Base da UI e login · S · dep: T-060, T-061 · cobre: RF-15
- **Entrega:** `ui/templates/{base,login}.html`, `ui/static/` (HTMX + extensão SSE + CSS vendorizados),
  `ui/filters.py` (≤ 60), rotas de login.
- **DoD:** nenhuma dependência de CDN/Node; cookie `HttpOnly`; página protegida redireciona ao login.

### T-081 — Novo job e lista · S · dep: T-080, T-063, T-066 · cobre: RF-15
- **Entrega:** `ui/routes/pages.py` (≤ 130), `index.html`, `job.html`.
- **DoD:** formulário valida no servidor e mostra erros por campo; lista de jobs com status e custo.

### T-082 — Editor de roteiro e aprovação · L · dep: T-081, T-064 · cobre: RF-07, RF-08, RF-09
- **Entrega:** `ui/routes/script_partials.py` (≤ 130), `_script_editor.html`, `_scene_card.html`, `_estimate.html`.
- **DoD:** edição salva com debounce; contador de palavras e violações por cena; `409` recarrega e avisa;
  estimativa atualiza a cada mudança; "Aprovar" envia a `script_version` exibida; botões
  adicionar/remover/mover/🎲 funcionam.

### T-083 — Progresso e resultado · M · dep: T-081, T-065, T-067 · cobre: RF-10, RF-13
- **Entrega:** `ui/routes/progress_partials.py` (≤ 130), `_progress.html`, `_scene_progress.html`, `_player.html`.
- **DoD:** grade por cena com chips áudio/vídeo/clipe; atualização via SSE e reconexão; custo vs. orçamento;
  player + download; Cancelar/Retry/Reopen.

### T-084 — UI de vozes · S · dep: T-081, T-066 · cobre: RF-12
- **Entrega:** `ui/routes/voices.py` (≤ 100), `voices.html`.
- **DoD:** upload com `ref_text`, *preview* de áudio, exclusão; erros de validação legíveis.

## M9 — Hardening

### T-090 — E2E dos dois estágios · M · dep: M7, M6 · cobre: AC-01, AC-02
- **Entrega:** `tests/e2e/test_two_stage_flow.py`: criar → rascunho → editar → estimar → aprovar → render → baixar.
- **DoD:** com `fake` + FFmpeg real; editar 1 cena e reaprovar custa só 1 cena (contadores); arquivo final
  tem N cenas, legendas, −14 LUFS ± 1.

### T-091 — Falha parcial e idempotência · M · dep: T-077 · cobre: AC-03, RNF-02
- **Entrega:** `tests/e2e/test_partial_failure.py`.
- **DoD:** cena 3 falha 2× e depois passa; `submit_count` das demais = 1; reabrir + reordenar cenas reutiliza
  100 % dos artefatos.

### T-092 — Recuperação após crash · M · dep: T-057, T-072 · cobre: AC-04, RNF-09
- **Entrega:** `tests/e2e/test_crash_recovery.py`.
- **DoD:** mata o runner com `remote_id` gravado; novo `Container` + recovery conclui o job com `submit_count == 1`
  para as predições existentes.

### T-093 — Smoke live opt-in · S · dep: M7 · cobre: RNF-03
- **Entrega:** `tests/live/test_live_smoke.py` (`RUN_LIVE=1`), job de 2 cenas, teto de US$ 0,50 (aborta acima).
- **DoD:** documentado no README; nunca roda no CI padrão.

### T-094 — Docker e runbook · M · dep: M6 · cobre: RNF-13
- **Entrega:** `Dockerfile` (`python:3.12-slim` + ffmpeg/libass + fonte), `docker-compose.yml`, `README.md` (≤ 200) com
  runbook (variáveis, modo fake, retomar job, limpar cache, URLs expiram em ~1 h).
- **DoD:** `docker compose up` ⇒ `/readyz` 200 em modo `fake`; imagem roda com `--workers 1`.

### T-095 — Métricas (C) · S · dep: T-071 · cobre: RNF-08
- **Entrega:** `api/routers/metrics.py` (≤ 80): contadores em texto.
- **DoD:** jobs por estado, cache hit/miss, tentativas por provedor, custo acumulado.

### T-096 — Revisão de segurança · M · dep: M6, M8 · cobre: RNF-07
- **Entrega:** checklist executado + testes: *path traversal*, SSRF no downloader, segredos em logs, upload
  malicioso, `{\fs200}` em legenda, CSRF no login da UI.
- **DoD:** todos os itens do design/07 §3 têm teste automatizado ou justificativa registrada.

### T-097 — Teste de concorrência/latência · S · dep: T-077 · cobre: RNF-01
- **Entrega:** `tests/integration/test_parallelism.py` com latências simuladas.
- **DoD:** N=10 cenas (TTS 1 s, vídeo 3 s, `MAX_PARALLEL_VIDEO=10`) ⇒ tempo de rede ≈ 3 s ± 0,5 s; com
  `MAX_PARALLEL_VIDEO=2` ⇒ ≈ 15 s; semáforos respeitados (pico de concorrência medido).

### T-098 — Avaliação de qualidade do roteiro · S · dep: T-052 · cobre: RF-01
- **Entrega:** `scripts/eval_scripts.py` + 20 temas de exemplo: taxa de aprovação do `ScriptRepairLoop` e de
  reparos necessários por modelo (`deepseek-chat` × `deepseek-reasoner`) — uso manual, com custo.
- **DoD:** relatório com % válido de primeira, % após reparo, palavras/cena; resultado guia o modelo padrão.

### T-099 — Smoke de UI em navegador · S · dep: M8 · cobre: RF-15
- **Entrega:** roteiro manual (e opcionalmente Playwright) cobrindo criar → editar → aprovar → baixar em `fake`.
- **DoD:** sem erros de console; SSE reconecta ao recarregar a página durante o render.
