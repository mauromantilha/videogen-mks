# Design 07 — Qualidade, limites de tamanho, segurança e operação

> Tarefas: M0 (T-002, T-003), M9 · Voltar: [design.md](../design.md)

## 1. Política anti-god-class (RNF-05)

### 1.1 Limites

| Alvo | Limite **rígido** (build quebra) | Meta (aviso) |
|---|---|---|
| Arquivo (`.py`, `.html`, `.yaml`, `.md`, `.sh`) | **300 linhas** | ≤ 200 |
| Função / método | **300 linhas** | ≤ 50 linhas, complexidade ≤ 10, ≤ 6 parâmetros |
| Classe (inclui *model* Pydantic) | **300 linhas** | ≤ 150 linhas, ≤ 10 métodos públicos |
| Controller (arquivo de router) | **300 linhas** | ≤ 130 linhas, ≤ 8 endpoints, rota ≤ 25 linhas |
| Port (`Protocol`) | — | ≤ 5 métodos |

"Linhas" = linhas físicas do arquivo/nó AST (`end_lineno - lineno + 1`). **Sem exceções** ao limite
rígido: ao se aproximar de 250, divide-se o módulo. Metas só admitem exceção com comentário
`# limits: allow <regra> — <motivo>` revisado em PR.

### 1.2 Regras de design que previnem o problema

1. **Uma razão para mudar** por classe; nome de classe = substantivo do papel (`CachedStep`, não `Manager`).
2. **Proibidos** nomes `*Manager`, `*Helper`, `*Util(s)`, `*Handler` genérico, `*Processor`, e arquivos
   `utils.py`, `helpers.py`, `common.py`, `misc.py` (o `check_limits` sinaliza).
3. **Composição > herança**; sem herança além de `Protocol`/`BaseModel`/`StrEnum`/exceções.
4. **Controllers finos** (design/06); regra de negócio só em `services`/`domain`.
5. **Funções puras** no `domain` (`plan_sync`, `freeze`, `content_hash`) — estado e I/O ficam nas bordas.
6. **Settings, container e repositório não crescem sem dividir** (já nascem fatiados: design/02).
7. **Constantes mágicas** viram campos de `SyncConfig`/`ModelSpec`/`RenderSettings`.

### 1.3 Enforcement (3 camadas)

| Camada | Ferramenta | Quando |
|---|---|---|
| Local | `pre-commit`: `ruff`, `mypy`, `scripts/check_limits.py --changed` | a cada commit |
| Teste | `tests/architecture/test_limits.py` (executa `check_limits` no repo inteiro) e `test_layers.py` (`import-linter`) | `pytest` |
| CI | pipeline: `ruff` → `mypy --strict` → `lint-imports` → `check_limits` → `pytest --cov` | a cada PR |

**`scripts/check_limits.py` (≤ 150 linhas):** percorre `src/ tests/ scripts/ docs/ config/`; para `.py`
usa `ast` (arquivo, `FunctionDef/AsyncFunctionDef`, `ClassDef`, contagem de métodos públicos); para os
demais, conta linhas. Saída: tabela de violações `rígido`/`meta`; *exit code* 1 se houver rígido (ou meta
com `--strict`). Cada função de verificação do script também respeita o limite (autoaplicável).

**Ruff** (`pyproject.toml`): `select = ["E","F","I","UP","B","C90","PLR","ASYNC","S","RUF"]`,
`mccabe.max-complexity = 10`, `pylint.max-args = 6`, `max-statements = 50`, `max-branches = 12`.

**`.importlinter`:**

```ini
[importlinter]
root_package = videogen

[importlinter:contract:camadas]
name = Camadas
type = layers
layers =
    videogen.app
    videogen.api | videogen.ui
    videogen.services
    videogen.providers | videogen.infra | videogen.composer
    videogen.ports
    videogen.domain
    videogen.core

[importlinter:contract:services-sem-adapters]
name = services nunca importam adapters nem libs de I/O
type = forbidden
source_modules = videogen.services
forbidden_modules = videogen.providers, videogen.infra, videogen.composer, httpx, subprocess

[importlinter:contract:adapters-independentes]
name = Adapters não se importam
type = independence
modules = videogen.providers, videogen.infra, videogen.composer
```

O import-linter **não rastreia a stdlib**, então I/O direto (`subprocess`, `socket`, `sqlite3`,
`urllib`, `http`, `shutil`) em `domain`, `ports` e `services` é barrado por um teste AST em
`tests/architecture/test_layers.py`. Os nomes genéricos proibidos (§1.2) são **erro**, não meta.

(`RetryPolicy` vive em `core/retry.py`, usada por `providers.http` e `infra.downloader`, o que preserva a
independência entre adapters — ver T-024 e T-030.)

## 2. Estratégia de testes

| Nível | Escopo | Ferramentas | Alvo |
|---|---|---|---|
| Unit | `domain`, `plan_sync`, hashing, chunker, ASS, filtergraph, retry, prompts, mapping | `pytest` | cobertura ≥ 90 % |
| Contrato | cada port com `Fake*` e adapters (`respx`) | suíte parametrizada | todos os adapters passam a mesma suíte |
| Integração | repositório/cache (disco real em `tmp_path`), composer (FFmpeg real, `lavfi`) | `pytest -m ffmpeg` | 4 estratégias de sync + concat |
| Serviço | `ScriptService`, `Approval`, `RenderCoordinator` com fakes | `pytest-asyncio` | cenários AC-02…AC-07 |
| API/UI | `ASGITransport`, SSE, fragmentos HTML | `httpx` | cada rota: sucesso + erro |
| E2E | dois estágios completos com fakes + FFmpeg real | `pytest -m e2e` | AC-01…AC-06, AC-09 |
| Arquitetura | limites + camadas | `check_limits`, `lint-imports` | AC-08 |
| Live (opt-in) | 1 job de 2 cenas, orçamento ≤ US$ 0,50 | `RUN_LIVE=1` | smoke manual/semanal |

Testes de **idempotência** usam contadores dos fakes: "cena 3 falha → *retry* → `submit_count` das cenas
1, 2, 4, 5 permanece 1". Teste de **crash**: derruba o `JobRunner` com `remote_id` gravado, reinicia, e
verifica `submit_count == 1` e conclusão.

## 3. Segurança (RNF-07)

| Ameaça | Controle |
|---|---|
| Vazamento de chaves | `SecretStr`; filtro de log que redige `Authorization`, `*_KEY`, `*_TOKEN`; `.env` no `.gitignore`. |
| Acesso não autorizado (endpoint gasta dinheiro) | `X-API-Key`/cookie; sem chave ⇒ apenas loopback; limite de jobs simultâneos e `max_budget_usd` (teto global `≤ 100`). |
| *Path traversal* | `job_id`/`voice_id` por regex; `Workspace` confere `resolve()` dentro da raiz; nomes de arquivo do cliente nunca usados. |
| SSRF no download | `https` + *allowlist* de hosts por provedor, revalidada a cada redirect; tamanho máx.; sem enviar credenciais. |
| Upload malicioso | Limite de bytes em *streaming*, extensão + `ffprobe` (codec de áudio, duração), reencode para WAV mono antes de armazenar. |
| Injeção via LLM | Saída tratada como dado: Pydantic `extra=forbid`, escape ASS, `subprocess` sem shell, nenhum texto do LLM em caminho de arquivo. |
| Prompt-injection no tema | O tema vai como mensagem de usuário delimitada; o schema e as regras são validadores determinísticos, não instruções. |
| DoS por parâmetros | `n_cenas ≤ 10`, `tema ≤ 500`, semáforos globais, orçamento. |

## 4. Observabilidade (RNF-08)

- **Logs JSON** (`ts, level, msg, job_id, scene_index, step, provider, attempt, duration_ms`), nunca com
  payloads completos de prompt em nível INFO.
- **`events.jsonl`** por job: auditoria de estados, custos e erros.
- **Custo:** `CostLedger` por job (estimado vs. real quando o provedor informa `predict_time`); resumo na
  UI e em `job.cost`.
- **Métricas (C):** `GET /metrics` em formato texto (contadores: jobs por estado, cache hit/miss, tentativas
  por provedor, custo acumulado) sem dependência externa.

## 5. Operação e deploy

- **Docker** (`python:3.12-slim-trixie` — o bookworm traz FFmpeg 5.1 — + `ffmpeg` 7 com libass +
  `fonts-dejavu-core`, usuário sem privilégios): `uvicorn videogen.main:app --workers 1`. Validado.
  Volume em `/workspace`. `HEALTHCHECK` em `/readyz`.
- **`/readyz`** falha se: FFmpeg/libass ausente, workspace não gravável, `models.yaml` inválido ou nenhum
  provedor com credencial (exceto `PROVIDER_MODE=fake`).
- **Limpeza:** `infra/cleanup.py` por TTL (jobs concluídos 14 dias; cache 30 dias; `tmp` no startup).
- **Backup:** `workspace/jobs/*/job_state.json` + `_voices/`; o cache é reconstruível (a um custo).
- **Runbook** (README): variáveis, como rodar em modo `fake`, como retomar job, como limpar cache.

## 6. Riscos e mitigações

| Risco | Impacto | Mitigação |
|---|---|---|
| Inconsistência visual entre clipes independentes | Vídeo "colcha de retalhos" | `estilo_visual` + descrição consistente + seeds fixas; evolução: I2V com frame de referência. |
| T2V sem lip-sync | Pessoa "falando" fora de sincronia | Regra no prompt/validador proibindo fala em câmera. |
| Qualidade PT-BR do TTS | Sotaque/erros | A/B entre F5-TTS e Fish Speech; voz de referência curta e limpa; revisar com `ref_text`. |
| URLs de saída expiram (~1 h) | Re-cobrança após crash tardio | Download imediato; documentado no runbook. |
| Cobrança dupla em retry de submit | Custo | `remote_id` no submit; retry só em falhas pré-criação; idempotência quando houver. |
| Mudança de preço/versão de modelo | Estimativa errada, resultado diferente | Versão fixada no YAML; preço no YAML; teste de contrato alerta quebra de schema. |
| *Cold start* > 300 s | Falha de cena | Timeout por modelo; classificação retryable; retomar via `remote_id`. |
| FFmpeg sem libass | Sem legendas | `ToolchainCheck` no startup/`readyz`. |
| Estado em 1 processo | Sem HA/escala horizontal | Ports (`JobRepository`, `EventBus`, `JobRunner`) permitem trocar por Redis/DB depois. |
| Qualidade do roteiro varia | Retrabalho | Edição manual + regeneração por cena (RF-07) antes de gastar GPU. |
