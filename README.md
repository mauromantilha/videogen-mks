# videogen-mks

Gerador de vídeos curtos a partir de **linguagem natural**, para criadores e designers.
Você descreve o tema ou produto, revisa o roteiro e aprova; a ferramenta narra, gera as cenas e entrega um MP4 pronto.

> **Status: especificação concluída, implementação ainda não iniciada.**
> Requisitos, design e plano de tarefas estão definidos. Não há ainda código executável nem *quickstart*;
> as seções abaixo descrevem o que será construído.

## Como funciona: duas etapas com portão de aprovação

```
 Etapa 1 — ROTEIRO (barata)                         Etapa 2 — RENDER (GPU, paga)
 Tema ─► LLM ─► roteiro ─► UI: revisar/editar ─► APROVAR ─► TTS ∥ vídeo por cena ─► sync ─► legenda ─► MP4
                              + estimativa de custo   (gate)
```

1. **Roteiro.** Um LLM (DeepSeek V3/R1) gera N cenas, cada uma com narração em PT-BR (até 12 palavras)
   e prompt visual em inglês. A saída é validada por schema e regras; se vier fora do contrato, é reparada automaticamente.
2. **Revisão na UI.** Edite textos e prompts, adicione, remova ou reordene cenas, regenere o roteiro inteiro
   ou uma só cena. Veja a estimativa de custo antes de gastar.
3. **Aprovação.** Fixa a versão do roteiro e o orçamento máximo. **Nenhuma chamada de GPU acontece antes disso.**
4. **Renderização.** Para cada cena, voz (clonagem com áudio de referência) e vídeo são gerados em paralelo,
   sincronizados, legendados e concatenados em `final_render.mp4`.

## Funcionalidades planejadas

- Vídeos **9:16** ou **16:9**, H.264/AAC, 24 ou 30 FPS, áudio normalizado em **−14 LUFS**.
- **Somente GPU serverless pay-as-you-go** e modelos open-source via API: sem assinatura fixa nem GPU local.
- Modelos e provedores **trocáveis por configuração** (`config/models.yaml`):

| Componente | Modelo principal | Alternativa | Provedores |
|---|---|---|---|
| Roteirista (LLM) | `deepseek-flash` | `deepseek-v4-pro` | DeepSeek, DeepInfra |
| Locução (TTS) | F5-TTS | — | Replicate |
| Vídeo (T2V) | Wan 2.1 (480p/720p) | CogVideoX-5B (só 16:9) | Replicate |

- **Idempotência e economia:** artefatos endereçados por hash de conteúdo. Se uma cena falhar, a nova execução
  reaproveita tudo que já foi pago. Editar uma cena re-renderiza só ela.
- **Resiliência:** *retry* com *backoff* exponencial (3 tentativas), *timeouts* por modelo para *cold start*,
  retomada de predições após *crash* sem cobrança dupla.
- **Sincronização áudio/vídeo:** ajuste de velocidade (`setpts`) quando a diferença é moderada; *freeze-frame*
  com zoom suave ou corte com *fade-out* nos extremos.
- **Legendas** em `.ass` queimadas via FFmpeg, respeitando a *safe zone* de Reels/TikTok (sem MoviePy nem ImageMagick).
- **Progresso em tempo real** por cena (SSE), cancelamento, retomada e reabertura de jobs concluídos.
- **Modo simulado** (`PROVIDER_MODE=fake`) para desenvolver e testar a custo zero.

## Arquitetura

Python 3.12, **FastAPI** + `asyncio` + `httpx` + **FFmpeg**. UI server-rendered com Jinja2 + HTMX (sem Node).

```
 ui/ · api/            controllers finos (HTTP, SSE, auth)
 services/             casos de uso: script · jobs · cost · render · voices
 ports/ + domain/      contratos (Protocols) e regras puras (Pydantic, hash, plan_sync)
 providers/ infra/ composer/   adapters: APIs de IA · disco/cache/eventos · FFmpeg
```

Princípios: *Ports & Adapters*; "hash antes de gastar"; falha parcial nunca descarta chamadas pagas;
um único processo (fila e eventos em memória, atrás de *ports* substituíveis).

### Regra anti-god-class

**Nenhum arquivo, classe, função, *model* Pydantic ou *controller* pode ter mais de 300 linhas.** A regra é verificada
por script (AST) no CI, junto com contratos de camadas (`import-linter`), e quebra o build.

## Estrutura prevista

```
config/models.yaml        catálogo de modelos, versões, preços e limites
src/videogen/
  core/  domain/  ports/  infra/  providers/  composer/  services/  api/  ui/  app/
scripts/check_limits.py   guardião do limite de 300 linhas
workspace/                cache por hash, vozes e jobs (runtime)
```

## Esboço da API

| Rota | Função |
|---|---|
| `POST /api/v1/jobs` | Cria o job e dispara a geração do roteiro (202) |
| `PUT/PATCH /api/v1/jobs/{id}/script…` | Edita o roteiro (versionado, sem custo de GPU) |
| `GET /api/v1/jobs/{id}/estimate` | Estimativa de custo, descontando o cache |
| `POST /api/v1/jobs/{id}/approve` | Aprova uma `script_version` e inicia o render |
| `GET /api/v1/jobs/{id}/events` | Progresso por SSE |
| `GET /api/v1/jobs/{id}/artifacts/final` | Baixa o MP4 final (suporta `Range`) |
| `POST /api/v1/voices` | Cadastra voz de referência para clonagem |

## Configuração prevista

Chaves e parâmetros via `.env`:

```dotenv
DEEPSEEK_API_KEY=      REPLICATE_API_TOKEN=      FAL_KEY=
PROVIDER_MODE=real     # fake = custo zero
MAX_PARALLEL_VIDEO=4   VIDEO_TIMEOUT_S=300   DEFAULT_MAX_BUDGET_USD=2.00
```

Requisitos de sistema: Python ≥ 3.12 e FFmpeg ≥ 6 com `libass`.

## Roadmap

| Marco | Tema |
|---|---|
| M0 | Fundações e guardiões (scaffold, limite de 300 linhas, camadas, CI) |
| M1–M2 | Domínio, ports e infra (repositório atômico, cache por hash, eventos) |
| M3–M4 | Providers (DeepSeek, Replicate, fake) e composer FFmpeg |
| M5–M6 | Etapa 1 completa via API: roteiro, edição, estimativa, aprovação |
| M7 | Etapa 2: renderização idempotente e resiliente |
| M8–M9 | UI web, E2E, recuperação de *crash*, Docker e *smoke test* real |

Ao fim do M6 a Etapa 1 inteira já funciona sem custo de GPU.

## Licença

[MIT](LICENSE) © 2026 mauro mantilha
