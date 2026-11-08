# Design — VideoGen MKS (visão geral)

> Versão 1.0 · 2026-11-08 · Relacionados: [requirements.md](requirements.md) · [tasks.md](tasks.md)
> Este documento é o **mapa**. O detalhe de cada módulo está em `docs/design/NN-*.md`.

## 1. Princípios

1. **Duas etapas, um portão.** Roteiro barato e editável → aprovação versionada → render caro e idempotente.
2. **Ports & Adapters.** `services` conhecem apenas *Protocols* (`ports/`); provedores, disco e FFmpeg são adapters.
3. **Hash antes de gastar.** Toda chamada paga é precedida de consulta ao cache por hash de conteúdo.
4. **Falhar sem perder dinheiro.** Falha parcial nunca cancela chamadas pagas já em voo; `remote_id` é persistido no submit.
5. **Anti-god-class.** Máx. **300 linhas** por arquivo/classe/função/model/router, verificado por CI (design/07).
6. **Python puro.** Sem Node, Celery, Redis ou ImageMagick. FFmpeg é a única dependência binária.

## 2. Arquitetura em camadas

```
 ┌──────────────────────────────────────────────────────────────────────────┐
 │ ui/  (Jinja2 + HTMX)        api/  (routers finos, DTOs, SSE, auth)        │  ← Controllers
 └───────────────┬──────────────────────────────┬───────────────────────────┘
                 ▼                              ▼
 ┌──────────────────────────────────────────────────────────────────────────┐
 │ services/   script · jobs · cost · render · voices     (casos de uso)     │
 └───────────────┬──────────────────────────────────────────────────────────┘
                 ▼                       depende só de ▼
 ┌─────────────────────────────┐   ┌────────────────────────────────────────┐
 │ ports/  (Protocols)         │◄──│ domain/ (Pydantic, regras puras, hash) │
 └──────────▲──────────────────┘   └────────────────────────────────────────┘
            │ implementam
 ┌──────────┴───────┬──────────────────┬────────────────────────────────────┐
 │ providers/       │ infra/           │ composer/                          │
 │ deepseek·replicate│ repo JSON·cache │ ffmpeg·ffprobe·loudnorm·ASS·concat │
 │ fal·fake         │ eventos·download │                                    │
 └──────────────────┴──────────────────┴────────────────────────────────────┘
 app/  = composition root (único módulo que importa tudo e faz a injeção)
```

## 3. Fluxo em duas etapas

```
Cliente/UI            API                 Services                  Providers / FFmpeg
   │ POST /jobs ──────►│ 202 {job_id}       │                              │
   │                   │──create_job───────►│ status=SCRIPTING             │
   │                   │                    │──LLM.complete(prompt)───────►│ DeepSeek
   │◄── SSE job.status─┤                    │◄─ JSON ── validar/reparar ───│
   │                   │                    │ status=AWAITING_APPROVAL     │
   │ PUT/PATCH script ►│──edit_service──────►│ script_version++ (sem custo) │
   │ POST regenerate ─►│──script_service────►│ LLM (cena ou tudo)           │
   │ GET estimate ────►│──cost_estimator────►│ desconta cache               │
   │ POST approve ────►│──approval──────────►│ valida versão+orçamento      │
   │   {script_version}│                    │ congela, fixa seeds          │
   │                   │                    │ status=APPROVED → runner     │
   │                   │                    │ status=RENDERING             │
   │                   │                    │  ┌─ por cena (gather) ─────┐ │
   │                   │                    │  │ AudioStep ──────────────┼►│ TTS (poll)
   │                   │                    │  │ VideoStep ──────────────┼►│ T2V (poll)
   │◄── SSE scene.step ┤◄── eventos ────────│  │ └► ScenePipeline.compose┼►│ ffmpeg/cena
   │                   │                    │  └─────────────────────────┘ │
   │                   │                    │ status=FINALIZING → concat ─►│ ffmpeg concat
   │◄── SSE completed ─┤                    │ status=COMPLETED             │
   │ GET /artifacts/final.mp4 (Range)       │                              │
```

## 4. Máquina de estados do job

```
            ┌───────── regenerar roteiro ─────────┐
            ▼                                     │
 SCRIPTING ──ok──► AWAITING_APPROVAL ──approve──► APPROVED ──► RENDERING ──► FINALIZING ──► COMPLETED
    │                 ▲   │  (edição: mesmo estado,              │               │             │
    │ erro            │   │   script_version++)                  │ erro          │ erro        │ reopen
    ▼                 │   └──cancel──► CANCELED                  ▼               ▼             │
  FAILED ◄────────────┼──────────────────────────────────────  FAILED ◄──────────┘             │
    │ retry (por failed_stage) ──► SCRIPTING | RENDERING          │ reopen ──► AWAITING_APPROVAL ◄┘
```

Tabela canônica de transições em `domain/status.py` (design/01 §6). Qualquer transição fora da tabela
lança `InvalidTransition` (HTTP 409).

## 5. Decisões arquiteturais (ADR resumidas)

| # | Decisão | Alternativa descartada | Motivo |
|---|---|---|---|
| ADR-01 | `asyncio` + `httpx.AsyncClient` | `ThreadPoolExecutor` + SDKs síncronos | Mesmo *loop* do FastAPI, cancelamento limpo, polling barato. |
| ADR-02 | REST direto (Replicate/Fal) em vez do SDK | `replicate.run()` | Precisamos do `prediction_id` no submit (retomada), `cancel` e controle de *retry*. |
| ADR-03 | Estado em `job_state.json` atômico atrás de `JobRepository` | SQLite/Postgres | Zero infra, inspecionável; trocar por SQLite é só novo adapter. |
| ADR-04 | `JobRunner` em processo (asyncio) | Celery/Redis | "Python puro"; recuperação via varredura no startup. Limite: 1 worker. |
| ADR-05 | Cache **content-addressed** global | `scene_{i}.mp4` | Reordenar/editar reaproveita; *single-flight* por hash. |
| ADR-06 | UI Jinja2 + HTMX vendorizado | SPA React | Sem Node; serviços compartilhados com a API. |
| ADR-07 | Aprovação com `script_version` (otimista) | Lock pessimista na UI | Evita aprovar roteiro diferente do que o usuário viu. |
| ADR-08 | 1 comando ffmpeg por cena (filtergraph único) + concat `-c:v copy` | MoviePy | 10× mais rápido, sem ImageMagick, sem recodificar vídeo duas vezes. |
| ADR-09 | Legendas ASS (libass) | `TextClip` | CPU baixa, estilo rico, timing exato. |
| ADR-10 | `gather(return_exceptions=True)` por cena | `TaskGroup` / `as_completed` | Não cancelar predições pagas das cenas irmãs. |
| ADR-11 | Limite 300 linhas verificado por AST | Convenção verbal | Regra só existe se quebrar o build. |

## 6. Estrutura do repositório (com orçamento de linhas)

Todos os arquivos ≤ 300 linhas; os valores abaixo são **metas de projeto** (≤ o limite rígido).

```
videogen-mks/
├── pyproject.toml · .importlinter · .env.example · .pre-commit-config.yaml
├── Dockerfile · docker-compose.yml
├── config/models.yaml                  # catálogo: modelos, versões, preços, limites
├── assets/fonts/                       # fonte OFL para libass
├── scripts/check_limits.py             # ≤150 · guardião do RNF-05
├── docs/                               # requirements · design · tasks
├── src/videogen/
│   ├── main.py                         # ≤10   app = create_app()
│   ├── app/        factory.py ≤80 · container_*.py (3×≤120) · lifespan.py ≤80
│   ├── core/       config/{app,providers,render,loader}.py ≤90 cada
│   │               errors.py ≤150 · retry.py ≤110 · logging.py ≤90 · ids.py ≤40 · clock.py ≤20
│   ├── domain/     script ≤90 · script_rules ≤110 · request ≤90 · generation ≤110
│   │               status ≤70 · job ≤110 · freeze ≤60 · progress ≤100 · cost ≤90
│   │               hashing ≤70 · sync ≤110 · media ≤60 · render_specs ≤80 · events ≤90
│   │               catalog ≤130 (ModelSpec, preços, limites)
│   ├── ports/      llm · tts · video · composer · repository · cache
│   │               events · downloader · probe · voices        (≤60 cada)
│   ├── infra/      workspace ≤90 · job_repository ≤150 · artifact_cache ≤140
│   │               event_bus ≤120 · event_audit ≤40 · downloader ≤130 · voice_store ≤110
│   │               cleanup ≤90 · atomic_file ≤40 (escrita atômica compartilhada)
│   ├── providers/  http/{client,polling,errors}.py ≤120 cada   (retry vive em core/)
│   │               catalog/{loader,context,builders,registry}.py ≤120 cada
│   │               deepseek/llm.py ≤130 (OpenAI-compatível; também DeepInfra)
│   │               replicate/{client,mapping,runner,tts,video}.py ≤130 cada
│   │               fake/{llm,tts,video,origin,media,behavior}.py ≤90 · (fal: adiado)
│   ├── composer/   ffmpeg_runner ≤110 · probe ≤90 · loudnorm ≤110 · filters ≤150
│   │               scene_composer ≤150 · concat ≤90 · healthcheck ≤70
│   │               subtitles/{chunker,styles,ass_writer}.py ≤110 cada
│   ├── services/
│   │   ├── script/ prompts ≤150 · repair ≤110 · script_service ≤150 · edit_service ≤170
│   │   ├── jobs/   lifecycle ≤160 · approval ≤110 · runner ≤130 · recovery ≤90
│   │   ├── cost/   estimator ≤130 · budget ≤70
│   │   ├── render/ single_flight ≤50 · limiter ≤60 · cached_step ≤120 · audio_step ≤110 · video_step ≤110
│   │   │           progress_tracker ≤150 · scene_pipeline ≤130 · coordinator ≤120 · finalizer ≤100
│   │   └── voices.py ≤110
│   ├── api/        deps ≤80 · auth ≤60 · error_handlers ≤90 · dto/*.py ≤100 cada
│   │               routers/{jobs,script,approval,events,artifacts,voices,catalog,health}.py ≤130 cada
│   └── ui/         routes/{pages,script_partials,progress_partials,voices}.py ≤130 cada
│                   templates/*.html ≤150 cada · static/ (htmx, css vendorizados)
├── tests/          unit/ · contract/ · integration/ · e2e/ · architecture/ · fakes/
└── workspace/      (runtime) _cache/ · _voices/ · jobs/{job_id}/
```

## 7. Regras de dependência (impostas por `import-linter`)

| Camada | Pode importar | Não pode importar |
|---|---|---|
| `domain` | stdlib, `pydantic`, `core` (erros, ids) | `ports`, `services`, adapters, `api`, `ui` |
| `ports` | `domain` | `services`, `infra`, `providers`, `composer`, `api` |
| `services` | `domain`, `ports`, `core` | `providers`, `infra`, `composer`, `api`, `ui`, `httpx`, `subprocess` |
| `providers` / `infra` / `composer` | `domain`, `ports`, `core` | `services`, `api`, `ui`; e não entre si (exceto `providers.http`) |
| `api` / `ui` | `services`, `domain`, `ports` (tipos), `core` | `providers`, `infra`, `composer` |
| `app` | tudo | — (único *composition root*) |

## 8. Índice dos módulos

| Doc | Conteúdo | Tarefas |
|---|---|---|
| [01-dominio-e-contratos](design/01-dominio-e-contratos.md) | Schemas, estados, hashing, `plan_sync`, eventos, *ports* | M1 |
| [02-infra-e-cache](design/02-infra-e-cache.md) | Workspace, repositório, cache, event bus, downloader, config | M0, M2 |
| [03-providers](design/03-providers.md) | HTTP resiliente, catálogo, DeepSeek, Replicate, Fal, fake | M3 |
| [04-composer](design/04-composer.md) | FFmpeg: loudnorm, sync, ASS, cena, concat | M4 |
| [05-servicos-e-orquestracao](design/05-servicos-e-orquestracao.md) | Etapa 1 e Etapa 2, runner, custo, concorrência | M5, M7 |
| [06-api-e-ui](design/06-api-e-ui.md) | Endpoints, DTOs, SSE, erros, telas | M6, M8 |
| [07-qualidade-seguranca-operacao](design/07-qualidade-seguranca-operacao.md) | Limites 300 linhas, testes, segurança, deploy, riscos | M0, M9 |

## 9. Gargalos do protótipo e onde são resolvidos

| Gargalo | Solução | Onde |
|---|---|---|
| Duração da fala ≠ clipe (`set_duration` congela/preto) | `plan_sync` + `setpts`/freeze+zoom/trim | design/01 §8, design/04 §4 |
| `TextClip` lento (ImageMagick) | `.ass` + filtro `ass` | design/04 §5 |
| Cobrança duplicada em falha | Cache por hash + `remote_id` persistido + *single-flight* | design/02 §3, design/05 §5 |
| Alucinação de formato do LLM | Pydantic + regras + *repair loop* | design/05 §2 |
| Acoplamento monolítico | Camadas + *ports* + limites de tamanho | §2, §7, design/07 |
