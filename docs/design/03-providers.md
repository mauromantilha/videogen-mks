# Design 03 — Providers (LLM, TTS, T2V)

> Pacote: `providers/` · Tarefas: M3 (T-030…T-038) · Voltar: [design.md](../design.md)

Cada provedor é um **adapter fino** que traduz `TTSRequest`/`VideoRequest`/mensagens do domínio para a
API remota. Toda a política de rede (retry, timeout, polling) vive em `providers/http/` e é reutilizada.

## 1. HTTP resiliente — `providers/http/`

| Arquivo | Classe | Responsabilidade |
|---|---|---|
| `errors.py` | `classify_response()` | Converte status/corpo em `ProviderError(retryable=…)`: 408/425/429/5xx e *timeouts/conexão* → retryable; 400/401/403/404/422 → não; recusa por política de conteúdo → `ContentRejected` (não retryable). |
| `core/retry.py` | `RetryPolicy`, `retry_async()` | (fora de `providers/`, para o `infra/downloader` reutilizar sem acoplar adapters) `max_attempts=3`, atraso `base * 2^n` com *jitter* total, respeita `Retry-After`, só repete `retryable`. `async def retry_async(fn, policy, on_retry)`. |
| `client.py` | `ResilientHttpClient` | Envolve `httpx.AsyncClient` (pool compartilhado): `request_json(method, url, ...)`, perfis de timeout (`connect=10s`, `read=60s`), logging sem segredos, métricas de tentativas. |
| `polling.py` | `PredictionPoller` | `await poll(get_status, is_done, *, total_timeout_s, interval=2→5s)`; erros de rede transitórios durante o polling têm retry **próprio** e não consomem as tentativas de submissão. |

### Política de tentativas (RNF-04)

| Chamada | Timeouts | Tentativas | Observação |
|---|---|---|---|
| LLM | connect 10 s · total 120–180 s | 3 | `deepseek-reasoner` é lento; total vem do `models.yaml`. |
| TTS submit/poll | submit 30 s · total 120 s | 3 | |
| T2V submit/poll | submit 30 s · total **300 s** (config.) | 3 | Cobre *cold start*. |
| Download | read 60 s | 3 | Retoma só o download; **não** repete a predição. |

**Cuidado com cobrança dupla:** repetir um *submit* cuja resposta se perdeu pode criar duas predições.
Por isso o retry de submissão só ocorre em falhas **comprovadamente anteriores à criação** (erro de
conexão antes do envio, `429`, `5xx` com corpo de erro do provedor) ou quando o provedor aceita chave de
idempotência (usada quando disponível). Falha *dentro* da predição (`status=failed` transitório, ex.: OOM
de *cold start*) vira nova submissão — contada nas 3 tentativas e registrada em `StepState.attempts`.

## 2. Catálogo — `providers/catalog/`

```yaml
# config/models.yaml  (valores de preço/versão são placeholders: preencher e FIXAR a versão)
version: 1
models:
  deepseek-chat:
    kind: llm
    provider: deepseek
    remote_ref: deepseek-chat
    capabilities: { json_mode: true, temperature: true }
    price: { unit: per_call, usd: 0.002 }
    timeouts: { total_s: 120 }

  deepseek-reasoner:
    kind: llm
    provider: deepseek
    remote_ref: deepseek-reasoner
    capabilities: { json_mode: false, temperature: false }   # validar na implementação
    price: { unit: per_call, usd: 0.004 }
    timeouts: { total_s: 180 }

  f5-tts:
    kind: tts
    provider: replicate
    remote_ref: x-lance/f5-tts            # confirmar
    version: "<sha-da-versão>"
    defaults: { speed: 1.0 }
    price: { unit: per_run, usd: 0.003 }
    concurrency: 6
    timeouts: { total_s: 120 }
    allowed_hosts: ["replicate.delivery", "*.replicate.delivery"]

  wan-2.1-t2v-480p:
    kind: t2v
    provider: replicate
    remote_ref: wavespeedai/wan-2.1-t2v-480p     # confirmar
    version: "<sha-da-versão>"
    limits:
      fps: 16
      num_frames: 81
      sizes: { "9:16": [480, 832], "16:9": [832, 480] }
    price: { unit: per_run, usd: 0.09 }
    concurrency: 4
    timeouts: { total_s: 300 }
    allowed_hosts: ["replicate.delivery", "*.replicate.delivery"]
```

| Arquivo | Classe | Responsabilidade |
|---|---|---|
| `model_spec.py` | `ModelSpec`, `Price`, `Limits` | Modelos Pydantic do YAML (validação forte: `kind`, preço, limites, `allowed_hosts`). |
| `loader.py` | `load_catalog(path)` | Lê YAML, valida, devolve `ModelCatalog` (dict imutável por chave). Falha o startup em YAML inválido. |
| `registry.py` | `ProviderRegistry` | `llm(key) / tts(key) / video(key)`: lê o `ModelSpec`, escolhe o *builder* pelo campo `provider` (mapa `{"replicate": build_replicate_tts, …}`) e devolve a instância (cacheada). Em `PROVIDER_MODE=fake` devolve os `fake/*`. |

Trocar de modelo/provedor = editar YAML (RNF-03). Adicionar provedor = novo pacote + 1 linha no mapa.

## 3. DeepSeek — `providers/deepseek/llm.py`

- API compatível com OpenAI: `POST {base}/chat/completions` via `ResilientHttpClient` (sem SDK).
- `capabilities` do `ModelSpec` decidem os parâmetros: `json_mode` ⇒ `response_format={"type":"json_object"}`;
  `temperature=False` ⇒ omite o parâmetro (modelos de raciocínio podem ignorá-lo/rejeitá-lo).
- Ignora `reasoning_content`; devolve apenas `content` + `usage`; custo = `Price` (por chamada) ou tokens.
- Resposta com *fences* ```` ```json ```` é limpa **no serviço** (`services/script/repair.py`), não aqui.

## 4. Replicate — `providers/replicate/`

| Arquivo | Responsabilidade |
|---|---|
| `client.py` | `ReplicateClient`: `create(version|model, input) -> id`, `get(id)`, `cancel(id)`. Endpoints `/v1/predictions`, `/v1/predictions/{id}`, `/v1/predictions/{id}/cancel`, ou `/v1/models/{owner}/{name}/predictions` para modelos oficiais. Mapeia estados `starting/processing/succeeded/failed/canceled`. |
| `mapping.py` | Funções puras `tts_input(req, spec)` / `video_input(req, spec)` → dict `input` do modelo (nomes de campo diferem entre F5-TTS, Fish, Wan, CogVideoX). Testáveis sem rede. |
| `tts.py` | `ReplicateTTS.synthesize`: `ctx.resume_remote_id` ⇒ só `poll`; senão `create` → **`await ctx.on_submitted(id)`** → `poll` → `GenerationResult(output_url, cost from metrics.predict_time)`. |
| `video.py` | Idem para T2V, `timeout_s` de `ctx`. |

**Contrato de retomada** (RNF-09): `on_submitted(remote_id)` é chamado *imediatamente* após o `create`
e **antes** do primeiro `poll`; o `CachedStep` o persiste no manifesto. Após *crash*, o novo processo
chama o provedor com `resume_remote_id` e apenas continua o polling.

Uploads de `ref_audio`: o campo de áudio de referência aceita data-URI/URL; o adapter envia como
*data URI* quando ≤ ~10 MB (limite já imposto no upload) ou via endpoint de *files* do provedor.

## 5. Fal.ai — `providers/fal/` (S)

Fila `queue.fal.run`: *submit* (`request_id`, `status_url`, `response_url`) → *status* → *result*.
Mesma estrutura de 3 arquivos (`client/tts/video`), mesmo contrato de `RunContext`. Validar antes de
implementar quais modelos TTS/T2V estão disponíveis (questão em aberto nº 2).

## 6. DeepInfra — (C)

Usado primeiro como **LLM alternativo** (API compatível com OpenAI — reutiliza o adapter `deepseek`
parametrizado por `base_url`). TTS/T2V só se o catálogo atual os oferecer; caso contrário, fora de escopo.

## 7. Provedores falsos — `providers/fake/` (RF-16)

- `FakeLLM`: devolve roteiro determinístico a partir do tema (respeita `n_cenas`, ≤ 12 palavras).
- `FakeTTS`/`FakeVideo`: geram, via `ffmpeg -f lavfi` (`sine`, `testsrc2`), mídia real e curta com
  duração configurável (para exercitar o `plan_sync`), fingem `remote_id`, latência configurável e
  **falhas injetáveis** (ex.: "cena 3 falha 2×"). Contadores de chamadas expostos para os testes de
  idempotência (AC-03, AC-04).
- Servem aos testes, ao desenvolvimento da UI e ao modo demonstração.

## 8. Testes dos providers

- **Contrato:** suíte parametrizada que roda contra `Fake*` e contra cada adapter real com `respx`
  (mock HTTP): sucesso, retry em 429/503 com `Retry-After`, não retry em 422, timeout total, retomada
  por `resume_remote_id`, `cancel`, `ContentRejected`.
- **Mapping:** testes puros de `tts_input`/`video_input` (snapshot do JSON enviado).
- **Live (opt-in):** `RUN_LIVE=1`, com teto de gasto de US$ 0,50; nunca roda no CI padrão.
