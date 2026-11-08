# Marcos M5–M6 — Serviços da Etapa 1 e API

> Voltar: [tasks.md](../tasks.md) · Design: [05](../design/05-servicos-e-orquestracao.md), [06](../design/06-api-e-ui.md)

Ao fim do M6 a **Etapa 1 inteira** funciona via HTTP com provedores `fake` ou reais (sem GPU).

## M5 — Serviços (roteiro, custo, aprovação, ciclo de vida)

### T-050 — PromptBuilder · M · dep: T-010 · cobre: RF-01
- **Entrega:** `services/script/prompts.py` (≤ 150): mensagens do LLM (puro) para roteiro completo e para
  uma cena com feedback; schema embutido via `model_json_schema()`.
- **DoD:** snapshots; o prompt contém `n_cenas`, `max_words`, regras de inglês/estilo, proibição de texto em
  tela e de fala em câmera; `tema` isolado em mensagem de usuário delimitada.

### T-051 — ScriptRepairLoop · M · dep: T-050, T-017 · cobre: RF-01
- **Entrega:** `services/script/repair.py` (≤ 110): limpeza de *fences*, `json.loads`, validação Pydantic +
  `validate_rules`, até 2 reparos com lista de violações por cena.
- **DoD:** LLM falso devolve: JSON com fences ✓; 15 palavras → reparo ✓; lixo 3× → `ScriptValidationError`
  com violações; contagem de chamadas = 1 + reparos; custo somado.

### T-052 — ScriptService · M · dep: T-051, T-021 · cobre: RF-01, RF-07
- **Entrega:** `services/script/script_service.py` (≤ 150): `draft`, `regenerate(feedback, scene_index?)`;
  grava `script`, `script_version`, `ledger.llm_usd`, estado, eventos.
- **DoD:** `SCRIPTING → AWAITING_APPROVAL`; regenerar 1 cena preserva as demais e incrementa a versão;
  falha ⇒ `FAILED(failed_stage="scripting")`.

### T-053 — ScriptEditService · M · dep: T-010, T-021 · cobre: RF-07
- **Entrega:** `services/script/edit_service.py` (≤ 170): `replace_script`, `patch_scene`, `add_scene`,
  `remove_scene`, `move_scene`, `bump_seed`; snapshot `script/vNNNN.json`.
- **DoD:** versão obsoleta ⇒ `VersionConflict`; estado ≠ `AWAITING_APPROVAL` ⇒ `InvalidTransition`;
  reordenar renumera `scene_index`; violações retornadas por cena; **nenhuma** chamada a LLM/GPU (teste com
  provedores que explodem se chamados).

### T-054 — CostEstimator e BudgetGuard · M · dep: T-014, T-022, T-032 · cobre: RF-08, RNF-10
- **Entrega:** `services/cost/estimator.py` (≤ 130), `services/cost/budget.py` (≤ 70).
- **DoD:** com cache pré-povoado para 2 de 5 cenas, estimativa = 3 × (tts + vídeo) e `cached=true` nas 2;
  seed provisória gera o mesmo hash do render; `BudgetGuard` cobre limites exatos.

### T-055 — JobLifecycleService · M · dep: T-012, T-021, T-057 · cobre: RF-11
- **Entrega:** `services/jobs/lifecycle.py` (≤ 160): `create`, `cancel`, `retry`, `reopen`, `clone`.
- **DoD:** `retry` respeita `failed_stage`; `reopen` zera `approval` e preserva cache; `clone` copia pedido+roteiro;
  transições inválidas ⇒ `InvalidTransition`.

### T-056 — ApprovalService · M · dep: T-012, T-054, T-057 · cobre: RF-09, RNF-10, AC-05, AC-06
- **Entrega:** `services/jobs/approval.py` (≤ 110): fluxo do design/05 §4.
- **DoD:** versão errada ⇒ 409 e **zero** chamadas a provedores; orçamento insuficiente ⇒ 422 sem mudar
  estado; sucesso: seeds fixadas, `scenes[]` criado, `APPROVED`, runner acionado **uma** vez; aprovações
  concorrentes: só uma vence.

### T-057 — JobRunner e Recovery · M · dep: T-021 · cobre: RNF-09, RF-11
- **Entrega:** `services/jobs/runner.py` (≤ 130), `services/jobs/recovery.py` (≤ 90).
- **DoD:** limite de jobs simultâneos; exceção inesperada ⇒ `FAILED` com `failed_stage`; `cancel` cancela a
  task; *recovery* re-enfileira apenas `scripting/approved/rendering/finalizing` e limpa `.part`.

### T-058 — VoiceService · S · dep: T-025, T-041 · cobre: RF-12
- **Entrega:** `services/voices.py` (≤ 110): validação (formato, 10 MB, 3–30 s via probe), normalização,
  `ref_text` obrigatório.
- **DoD:** arquivo de 11 MB, áudio de 1 s, `ref_text` vazio e arquivo não-áudio são recusados com `code` próprio.

## M6 — API

### T-060 — App factory, container e lifespan · M · dep: T-004, T-032, T-057 · cobre: RNF-06
- **Entrega:** `app/factory.py` (≤ 80), `app/container_{infra,providers,services}.py` (≤ 120 cada),
  `app/lifespan.py` (≤ 80), `main.py`.
- **DoD:** só `app/` importa adapters; *startup* roda `ToolchainCheck` + recovery; *shutdown* drena com
  *grace*; app sobe com `PROVIDER_MODE=fake` sem credenciais.

### T-061 — Auth e tratamento de erros · S · dep: T-005, T-060 · cobre: RNF-07
- **Entrega:** `api/auth.py` (≤ 60), `api/error_handlers.py` (≤ 90): `problem+json` com mapa único (design/06 §5).
- **DoD:** `compare_digest`; sem chave configurada só loopback; todas as exceções de domínio mapeadas (teste
  parametrizado); detalhe interno nunca vaza em 500.

### T-062 — DTOs da API · S · dep: T-013 · cobre: RF-10
- **Entrega:** `api/dto/{jobs,script,voices,events}.py` (≤ 100 cada): `JobView` (sem `remote_id`/caminhos),
  `ScriptView`, requests.
- **DoD:** teste confirma que campos internos não aparecem; links (`events`, `artifacts`) corretos.

### T-063 — Router de jobs · M · dep: T-055, T-061, T-062 · cobre: RF-01, RF-11
- **Entrega:** `api/routers/jobs.py` (≤ 130): `POST/GET /jobs`, `cancel/retry/reopen/clone`.
- **DoD:** `POST /jobs` responde 202 em ≤ 200 ms (LLM não bloqueia); rotas ≤ 25 linhas; 404/409 mapeados.

### T-064 — Routers de roteiro e aprovação · M · dep: T-053, T-056, T-054, T-062 · cobre: RF-07, RF-08, RF-09
- **Entrega:** `api/routers/script.py` (≤ 130), `api/routers/approval.py` (≤ 80).
- **DoD:** `PUT/PATCH/add/remove/move/regenerate`, `estimate`, `approve` conforme design/06 §2; 409 traz
  `current_version`; 422 traz `violations` por cena.

### T-065 — SSE de eventos · M · dep: T-023, T-062 · cobre: RF-10
- **Entrega:** `api/routers/events.py` (≤ 100): `snapshot` inicial, *replay* por `Last-Event-ID`, *heartbeat* 15 s,
  encerramento nos eventos terminais.
- **DoD:** teste lê N eventos; cliente que desconecta libera a assinatura; reconexão não duplica eventos.

### T-066 — Routers de vozes, catálogo e saúde · S · dep: T-058, T-032, T-047 · cobre: RF-12, RF-14
- **Entrega:** `api/routers/{voices,catalog,health}.py` (≤ 100 cada); `/readyz` usa `ToolchainCheck`.
- **DoD:** upload multipart em *streaming* respeita o limite; `/readyz` 503 sem libass; catálogo omite
  modelos sem credencial.

### T-067 — Artefatos com Range · M · dep: T-020, T-061 · cobre: RF-13
- **Entrega:** `api/routers/artifacts.py` (≤ 130): final e *previews* por cena, `Range`/`206`, `ETag`.
- **DoD:** `Range: bytes=0-99` ⇒ 206 com 100 bytes; job sem final ⇒ 404; `scene_index` fora da faixa ⇒ 404;
  nenhum caminho vindo do cliente é usado no disco.
