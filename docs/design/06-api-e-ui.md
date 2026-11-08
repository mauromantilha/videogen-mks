# Design 06 — API HTTP e UI

> Pacotes: `api/`, `ui/` · Tarefas: M6 e M8 · Voltar: [design.md](../design.md)

**Controller fino:** cada endpoint valida entrada (Pydantic), chama **um** método de serviço e serializa
o resultado. Sem regra de negócio, sem acesso a disco, sem `try/except` de domínio (os *handlers* globais
cuidam). Meta: função de rota ≤ 25 linhas; arquivo de router ≤ 8 endpoints e ≤ 130 linhas.

## 1. Convenções

- Prefixo `/api/v1`; JSON; datas ISO-8601 UTC; `job_id = job_<12 hex>`.
- Autenticação: `X-API-Key` (ou cookie HttpOnly `vg_key` na UI), `secrets.compare_digest`.
- Operações longas respondem **`202`** + `Location`; o cliente acompanha por SSE ou `GET`.
- Erros: `application/problem+json` (§5). Concorrência otimista via `script_version`/`expected_version`.
- DTOs em `api/dto/`: reutilizam os modelos do `domain` quando idênticos (`VideoScriptSchema`) e só criam
  DTO quando a visão difere (ex.: `JobView` oculta `remote_id` e caminhos internos).

## 2. Endpoints

### Etapa 1 — Roteiro e aprovação

| Método e rota | Router | Serviço | Resposta |
|---|---|---|---|
| `POST /jobs` | `jobs.py` | `JobLifecycle.create` | `202` `JobView` (`status=scripting`) |
| `GET /jobs` · `GET /jobs/{id}` | `jobs.py` | repo (leitura) | `JobView` (status, script, cenas, custo, links) |
| `GET /jobs/{id}/script` | `script.py` | leitura | `{script_version, script, violations[]}` |
| `PUT /jobs/{id}/script` | `script.py` | `ScriptEdit.replace_script` | `200` novo `script_version` · `409` versão · `422` regras |
| `PATCH /jobs/{id}/script/scenes/{i}` | `script.py` | `ScriptEdit.patch_scene` | idem |
| `POST /jobs/{id}/script/scenes` · `DELETE …/scenes/{i}` · `POST …/scenes/{i}/move` | `script.py` | `add/remove/move_scene` | idem |
| `POST /jobs/{id}/script/regenerate` `{feedback?, scene_index?}` | `script.py` | `ScriptService.regenerate` | `202` |
| `GET /jobs/{id}/estimate` | `approval.py` | `CostEstimator` | `CostEstimate` |
| `POST /jobs/{id}/approve` `{script_version, max_budget_usd?}` | `approval.py` | `ApprovalService` | `202` · `409` · `422 BUDGET_EXCEEDED` |

### Etapa 2 — Execução e artefatos

| Método e rota | Router | Serviço | Resposta |
|---|---|---|---|
| `GET /jobs/{id}/events` | `events.py` | `EventBus.subscribe` | `text/event-stream` |
| `POST /jobs/{id}/cancel` · `/retry` · `/reopen` · `/clone` | `jobs.py` | `JobLifecycle.*` | `202` / `201` (clone) |
| `GET /jobs/{id}/artifacts/final` | `artifacts.py` | `Workspace` (stream) | `video/mp4` com `Range` |
| `GET /jobs/{id}/scenes/{i}/{audio\|video\|clip}` | `artifacts.py` | idem | mídia com `Range` |

### Suporte

| Método e rota | Router | Observação |
|---|---|---|
| `POST /voices` (multipart: `audio`, `ref_text`, `name`) · `GET /voices` · `DELETE /voices/{id}` | `voices.py` | `VoiceService` valida com `ffprobe` |
| `GET /catalog/models?kind=llm\|tts\|t2v` | `catalog.py` | só modelos com credencial |
| `GET /healthz` (vivo) · `GET /readyz` (toolchain, workspace gravável, catálogo) | `health.py` | sem auth |

## 3. Exemplos

```http
POST /api/v1/jobs
{ "tema": "Seguro de vida para jovens profissionais", "aspect_ratio": "9:16", "n_cenas": 5,
  "models": {"llm": "deepseek-chat", "tts": "f5-tts", "video": "wan-2.1-t2v-480p"},
  "voice_id": "voz_9f3a1c", "options": {"resolution": "480p", "fps": 30}, "max_budget_usd": 1.5 }
→ 202  { "job_id": "job_a1b2c3d4e5f6", "status": "scripting", "links": {"events": "/api/v1/jobs/job_a1b2c3d4e5f6/events"} }
```

```http
GET /api/v1/jobs/job_a1b2c3d4e5f6/estimate
→ 200 { "scenes": [{"scene_index":0,"tts_usd":0.003,"video_usd":0.09,"cached":false}, …],
        "total_usd": 0.47, "spent_usd": 0.002 }

POST /api/v1/jobs/job_a1b2c3d4e5f6/approve   { "script_version": 3, "max_budget_usd": 1.5 }
→ 202 | 409 { "code":"VERSION_CONFLICT", "current_version": 4 } | 422 { "code":"BUDGET_EXCEEDED", … }
```

## 4. SSE — `routers/events.py`

- Cabeçalhos: `Content-Type: text/event-stream`, `Cache-Control: no-cache`, `X-Accel-Buffering: no`.
- Formato: `id: <seq>` · `event: <type>` · `data: <json>`; *heartbeat* `: ping` a cada 15 s.
- Ao conectar: envia `event: snapshot` com o `JobView` atual; depois eventos novos (e *replay* se
  `Last-Event-ID` estiver no *ring buffer*).
- Encerra com `job.completed` / `job.failed` / `canceled`. Desconexão do cliente libera a assinatura.

## 5. Erros — `api/error_handlers.py`

`application/problem+json`: `{ "type", "title", "status", "code", "detail", "job_id?", "violations?" }`.

| Exceção de domínio | HTTP | `code` |
|---|---|---|
| `NotFound` | 404 | `NOT_FOUND` |
| `InvalidTransition` | 409 | `INVALID_STATE` |
| `VersionConflict` | 409 | `VERSION_CONFLICT` |
| `ScriptValidationError` | 422 | `SCRIPT_INVALID` (com `violations` por cena) |
| `BudgetExceeded` | 422 | `BUDGET_EXCEEDED` |
| `ProviderError` / `ProviderTimeout` | 502 / 504 | `PROVIDER_ERROR` / `PROVIDER_TIMEOUT` |
| `ContentRejected` | 422 | `CONTENT_REJECTED` |
| validação Pydantic | 422 | `VALIDATION_ERROR` |
| não autenticado | 401 | `UNAUTHORIZED` |

Um único mapa `{ExceptionClass: (status, code)}` — nada de `if/elif` gigante.

## 6. UI — Jinja2 + HTMX (vendorizados em `ui/static/`)

A UI chama **os mesmos serviços** que a API (injeção por `Depends`), nunca a API via HTTP.
Rotas em `ui/routes/`: `pages.py` (páginas completas), `script_partials.py`, `progress_partials.py`,
`voices.py` (fragmentos HTML).

| Página | Conteúdo |
|---|---|
| `/` | Formulário "Novo vídeo" (tema, proporção, nº de cenas, modelos, voz, orçamento) + lista de jobs. |
| `/jobs/{id}` | Renderiza por `status`: *scripting* (spinner + SSE) · *awaiting_approval* (editor) · *rendering/finalizing* (progresso) · *completed* (player) · *failed* (erro + Retry/Reopen). |
| `/voices` | Upload de referência (áudio + texto) e lista com *preview*. |

### Tela de revisão do roteiro (o centro do fluxo)

```
┌ Job job_a1b2c3 · "Seguro de vida para jovens" · 9:16 · roteiro v3 ───────────────────────┐
│ Estilo visual: [ cinematic, warm light, shallow depth of field, consistent young woman ] │
│ ┌ Cena 1 ───────────────────────────────────────────────── [↑][↓][🎲 outra versão][🗑] ┐ │
│ │ Narração (PT-BR)  [ Imagine proteger o seu futuro com um clique. ]        8/12 ✓   │ │
│ │ Prompt (EN)       [ A young woman smiles at her phone in a sunlit apartment … ]     │ │
│ │ Seed [ 48213 ]    [Regenerar esta cena c/ feedback ▾]                  custo ~US$0,09 │ │
│ └─────────────────────────────────────────────────────────────────────────────────────┘ │
│ [+ Adicionar cena]   [Regenerar tudo ▾ feedback: "tom mais jovem"]                      │
│ ─────────────────────────────────────────────────────────────────────────────────────── │
│ Estimativa: TTS US$0,015 + Vídeo US$0,45 = US$ 0,47   (2 cenas em cache)  Orçamento [1,50]│
│                                                  [ Aprovar e gerar vídeo ▶ ]  (v3)       │
└──────────────────────────────────────────────────────────────────────────────────────────┘
```

Comportamento (HTMX): cada campo salva com `hx-patch` + `hx-trigger="change delay:600ms"` e troca só o
cartão da cena (contador de palavras e violações vindos do servidor); `expected_version` viaja num
`hx-vals`; em `409`, a UI recarrega o editor e avisa. O bloco de estimativa usa `hx-get` a cada
alteração. "Aprovar" faz `hx-post` e a página passa à visão de progresso.

### Tela de progresso

Grade de N cartões; cada cartão mostra 3 *chips* (`áudio`, `vídeo`, `clipe`) com estado
(`pendente · rodando · cache · ok · erro`) e custo; barra geral; custo acumulado vs. orçamento; botões
Cancelar/Retry. Atualização por `hx-ext="sse"` consumindo os eventos `scene.step` e `job.status`
(trocando fragmentos prontos do servidor). Ao concluir: `<video controls>` do final + download + "Reabrir
para editar".

### Templates

`base.html` · `index.html` · `job.html` (casca) · `_script_editor.html` · `_scene_card.html` ·
`_estimate.html` · `_progress.html` · `_scene_progress.html` · `_player.html` · `voices.html`.
Cada ≤ 150 linhas; lógica de apresentação em filtros Jinja registrados em `ui/filters.py` (≤ 60 linhas).

## 7. Autenticação na UI

`GET /login` (formulário da chave) → `POST /login` valida e define cookie `vg_key` (HttpOnly, SameSite=Lax,
`Secure` fora de dev). Dependência única `require_auth` serve API e UI. Sem `APP_API_KEY`, só aceita
`127.0.0.1` (modo dev) e loga aviso.

## 8. Testes

API: `httpx.AsyncClient(transport=ASGITransport(app))` com `PROVIDER_MODE=fake`; cada rota tem teste de
sucesso + erro mapeado; SSE testado lendo as primeiras N linhas. UI: testes de *rendering* de fragmentos
(HTML contém contador, violação, estado) sem navegador; smoke manual com Playwright/Chrome opcional (T-099).

## 9. Estado após a implementação do M6 (2026-11-08)

| Tema | Como ficou |
|---|---|
| Fronteira API ↔ app | `api/deps.py` declara `ApiServices` (dataclass imutável tipada por ports e serviços); o container (`app/`) o preenche. Nenhuma rota importa adapter (import-linter). |
| Composition root | `app/container_{infra,providers,services}.py` + `container.py` (`startup`: layout, parciais, toolchain, recuperação; `shutdown`: drena o runner e fecha clientes HTTP) + `readiness.py` (port `HealthCheck`). |
| Erros | `problem+json`; o status vem de `DomainError.http_status`; contexto exposto só por lista branca; `ConfigError` ⇒ 503 `NOT_CONFIGURED`; erro inesperado ⇒ 500 sem detalhes. |
| Edição | Respostas `200` com `violations` (aviso por cena); só erro de estrutura dá 422 (ver design/05 §8). |
| Rotas extras | `POST …/script/scenes/{i}/reseed` ("gerar outra versão"); `DELETE …/scenes/{i}?expected_version=`. |
| Artefatos por cena | `GET …/scenes/{i}/{audio\|video\|clip}` ⇒ `audio_norm`, `video_raw`, `clip` pelo hash do step (M7 grava esses hashes). Range via `FileResponse`. |
| SSE | `snapshot` → replay por `Last-Event-ID` → eventos ao vivo; heartbeat 15 s; encerra em `job.status` final (`completed`/`failed`/`canceled`). |
| Auth | `X-API-Key` ou cookie `vg_key`; sem chave configurada, só loopback. |
| Validado | Testes HTTP contra o container real (modo fake, disco real) e smoke com `uvicorn` real percorrendo a Etapa 1. |

## 10. Estado após a implementação do M8 (2026-11-08)

| Tema | Como ficou |
|---|---|
| Front-end | Jinja2 (autoescape) + HTMX 2.0.11 + extensão SSE 2.2.4 **vendorizados** em `ui/static/vendor/` (integridade SHA-512 do npm conferida; ver `ui/static/VENDOR.md`). CSS próprio (`app.css`), claro/escuro. Sem Node, sem CDN. |
| Segurança | CSP sem `unsafe-inline`/`eval` (HTMX com `allowEval: false`), `X-Frame-Options: DENY`, cookie `HttpOnly` + `SameSite=Lax` (protege POSTs de CSRF), `next` só aceita caminho local (sem open redirect). Fragmento HTMX sem sessão recebe `HX-Redirect` para o login. |
| Editor | Salvamento automático por campo (`input changed delay:800ms`, fila única `hx-sync`); a resposta atualiza só o contador/avisos da cena e a versão oculta (*out-of-band*). Operações estruturais e aprovação respondem `HX-Refresh`. Erros vão para a faixa `#flash`. |
| Tempo real | `sse-connect` só em estados ativos; `job.status` recarrega a página; `scene.step`/`job.cost` atualizam o painel de progresso (throttle 400 ms). |
| Validado no navegador (Chrome) | Login → novo vídeo → revisão → salvamento automático (contador e aviso ao vivo) → aprovação recusada com violação → correção → aprovação → progresso ao vivo por cena → recarga automática no fim → player com a legenda editada. Sem violações de CSP; o único erro de console é o fechamento intencional do SSE no estado final. |
