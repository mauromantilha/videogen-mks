# videogen-mks

Gerador de vídeos curtos a partir de **linguagem natural**, para criadores e designers.
Você descreve o tema ou produto, revisa o roteiro e aprova; a ferramenta narra com a sua voz,
gera as cenas, legenda e entrega um MP4 pronto (9:16 ou 16:9).

## Como funciona: duas etapas com portão de aprovação

```
 Etapa 1 — ROTEIRO (centavos)                       Etapa 2 — RENDER (GPU, paga)
 Tema ─► LLM ─► roteiro ─► UI: revisar/editar ─► APROVAR ─► voz ∥ vídeo por cena ─► sync ─► legenda ─► MP4
                              + estimativa de custo   (gate)
```

- **Nenhuma chamada de GPU antes da aprovação.** A estimativa já desconta o que está em cache.
- **Idempotente:** tudo é endereçado por hash. Reabrir, editar uma cena e reaprovar paga só o que mudou.
- **Resiliente:** retry com backoff, retomada de predições após queda do processo (sem cobrança dupla),
  falha de uma cena não descarta o que as outras já pagaram.

| Componente | Modelo padrão | Alternativa | Provedor |
|---|---|---|---|
| Roteirista | `deepseek-flash` (DeepSeek-V4.1-Flash) | `deepseek-v4-pro` | DeepSeek |
| Voz (clonagem) | F5-TTS (`x-lance/f5-tts`) | — | Replicate |
| Vídeo | Wan 2.1 480p/720p (`wavespeedai/…`) | CogVideoX-5B (só 16:9, ~US$ 0,50/cena) | Replicate |

## Início rápido

Requisitos: Python ≥ 3.12 e FFmpeg ≥ 6 com `libass` (Ubuntu: `sudo apt install ffmpeg`).

```bash
python -m venv .venv && make install          # dependências + ferramentas de dev
cp .env.example .env                          # ajuste as variáveis (veja abaixo)
PROVIDER_MODE=fake make run                    # http://127.0.0.1:8000 — custo zero
```

Com Docker (FFmpeg 7 incluso; modo fake se `PROVIDER_MODE` não estiver definido):

```bash
docker compose up --build                     # http://localhost:8000
```

Abra a interface, cadastre uma **voz** (3 a 12 s de áudio limpo + a transcrição exata), crie um
vídeo, revise o roteiro e aprove. A API REST está em `/docs`.

## Configuração (`.env`)

| Variável | Para quê |
|---|---|
| `APP_API_KEY` | Chave de acesso à UI/API. **Obrigatória em produção** (`APP_ENV=prod`); sem ela, só conexões locais. |
| `PROVIDER_MODE` | `fake` (simulado, custo zero) ou `real`. |
| `DEEPSEEK_API_KEY`, `REPLICATE_API_TOKEN` | Credenciais dos provedores (modo real). |
| `MAX_PARALLEL_VIDEO`, `MAX_PARALLEL_TTS`, `MAX_PARALLEL_FFMPEG` | Paralelismo. |
| `VIDEO_TIMEOUT_S`, `HTTP_MAX_ATTEMPTS` | Tolerância a cold start e falhas de rede. |
| `DEFAULT_MAX_BUDGET_USD` | Orçamento padrão por vídeo. |
| `LOUDNESS_LUFS`, `SYNC_*` | Áudio (−14 LUFS) e sincronização voz × vídeo. |

Modelos, versões fixadas, preços e limites ficam em `config/models.yaml`. Um modelo com
`verified: false` é **recusado** no modo real até alguém conferir os campos com o schema oficial:
`REPLICATE_API_TOKEN=… python scripts/replicate_schema.py <dono>/<modelo>` (só leitura).

## Runbook

| Situação | O que fazer |
|---|---|
| Job falhou numa cena | Página do job → **Tentar de novo** (ou `POST /api/v1/jobs/{id}/retry`): refaz só o que falhou. |
| Conteúdo recusado pelo provedor | **Editar o roteiro** (reabre), ajuste o prompt da cena e reaprove. |
| Processo caiu no meio do render | Basta subir de novo: o startup retoma os jobs pelas predições já criadas. Saídas do Replicate expiram em ~1 h — retome dentro desse prazo para não pagar de novo. |
| Quero outra versão de uma cena | Botão ⟳ no cartão da cena (nova seed) e reaprovar: só aquela cena é gerada. |
| Verificar a instalação | `GET /readyz` (FFmpeg, filtros, workspace, modelos disponíveis). |
| Limpar disco | Jobs concluídos/cancelados há 14 dias e cache sem uso há 30 dias (`infra/cleanup.py`; nunca toca job ativo). |
| Trocar de modelo/provedor | Edite `config/models.yaml`; nenhuma mudança de código. |
| Medir a qualidade do roteiro | `python scripts/eval_scripts.py --models deepseek-flash --yes` (gera custo pequeno). |

Limitações conhecidas: um único processo (`--workers 1`; fila e eventos em memória); referência de
voz de no máximo 12 s; qualidade do F5-TTS em português ainda não avaliada com voz real.

## Desenvolvimento

```bash
make check     # ruff + mypy --strict + contratos de camadas + limite de 300 linhas + testes
make cov       # cobertura
RUN_LIVE=1 LIVE_VOICE_FILE=voz.wav LIVE_VOICE_TEXT="…" .venv/bin/pytest tests/live -s   # smoke real (≤ US$ 0,50)
```

- **Arquitetura:** `domain` (regras puras) → `ports` (contratos) → `services` (casos de uso) →
  adapters em `providers/`, `infra/`, `composer/` → `api/` e `ui/` finos → `app/` (montagem).
  Camadas verificadas pelo `import-linter`.
- **Anti-god-class:** nenhum arquivo, classe ou função passa de **300 linhas** (`scripts/check_limits.py`
  quebra o build); metas de 200/50/150 linhas e 10 métodos públicos.
- **Testes:** unitários, contratos (dublê e adapter real passam nos mesmos testes), integração com
  FFmpeg real, API e UI contra o app real em modo fake, E2E (duas etapas, falha parcial, queda do processo).
- **Documentação:** [requisitos](docs/requirements.md) · [design](docs/design.md) ·
  [tarefas](docs/tasks.md) · [revisão de segurança](docs/security-review.md).

## Licença

[MIT](LICENSE) © 2026 mauro mantilha
