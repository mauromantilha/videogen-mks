# Requisitos — VideoGen MKS

> Versão 1.0 · 2026-11-08 · Status: proposta para revisão
> Relacionados: [design.md](design.md) · [tasks.md](tasks.md)

## 1. Visão geral e escopo

Ferramenta **100 % Python** (FastAPI + asyncio + FFmpeg) que transforma uma instrução em
linguagem natural (tema/produto) em um vídeo curto **vertical (9:16) ou horizontal (16:9)**,
usando exclusivamente **GPU serverless pay-as-you-go e modelos open-source via API**
(sem assinatura fixa e sem hardware local dedicado).

O fluxo é **em duas etapas separadas por um portão de aprovação humano**:

```
 Etapa 1 — ROTEIRO (barata, ~US$ 0,002)        Etapa 2 — RENDER (cara, GPU)
 ┌────────┐   ┌────────┐   ┌───────────────┐   ┌──────────┐   ┌───────────────────┐   ┌──────┐
 │ Tema + │──►│  LLM   │──►│ UI: revisar,  │──►│ APROVAR  │──►│ TTS ∥ T2V por cena │──►│ MP4  │
 │ opções │   │ roteiro│   │ editar, custo │   │ (gate)   │   │ sync+legenda+concat│   │ final│
 └────────┘   └────────┘   └───────────────┘   └──────────┘   └───────────────────┘   └──────┘
```

**Regra de ouro:** nenhuma chamada paga de TTS ou vídeo acontece antes da aprovação explícita.

## 2. Glossário

| Termo | Definição |
|---|---|
| **Job** | Unidade de trabalho: um vídeo, do tema ao MP4. Tem `job_id` e máquina de estados. |
| **Roteiro** | `VideoScriptSchema`: N cenas com `texto_narrado` (PT-BR) e `prompt_video` (EN). |
| **Revisão do roteiro** | Cada alteração gera `script_version` + 1 (controle de concorrência otimista). |
| **Aprovação** | Ação que congela uma `script_version` e libera a Etapa 2. |
| **Artefato** | Arquivo gerado (áudio, vídeo, clipe, final) endereçado por hash de conteúdo. |
| **Hash de cena** | SHA-256 dos parâmetros determinísticos que produzem um artefato. |
| **Provedor** | Serviço remoto (Replicate, Fal.ai, DeepInfra, DeepSeek) atrás de um adapter. |
| **Voz** | Áudio de referência (`ref_audio` + `ref_text`) cadastrado para clonagem. |

## 3. Requisitos funcionais (EARS)

Prioridade MoSCoW: **M** = Must, **S** = Should, **C** = Could.
`RF-01…RF-06` herdam os IDs do documento-base; `RF-07…RF-16` são novos.

### 3.1 Etapa 1 — Roteiro e aprovação

| ID | P | Requisito |
|---|---|---|
| RF-01 | M | **Quando** um job for criado com tema, `n_cenas` (2–10), `aspect_ratio`, modelos e voz, **o sistema deve** responder `202` imediatamente e, em segundo plano, consultar o LLM (DeepSeek: `deepseek-flash` ou `deepseek-v4-pro`) e produzir um `VideoScriptSchema` válido com `texto_narrado` PT-BR de no máximo `duracao_cena_s × 3` palavras (12 palavras para 4 s) e `prompt_video` EN contendo sujeito, ação, iluminação e câmera. **Se** a saída violar o contrato, **o sistema deve** devolver ao LLM a lista de violações e tentar reparar até 2 vezes antes de marcar o job como `failed`. Ao final, o job vai para `awaiting_approval`. |
| RF-07 | M | **Enquanto** o job estiver em `awaiting_approval`, **o sistema deve** permitir editar `texto_narrado`, `prompt_video` e `seed` de qualquer cena; adicionar, remover e reordenar cenas; e regenerar via LLM o roteiro inteiro ou uma única cena, com instrução de feedback opcional. Toda alteração passa pelas mesmas validações do RF-01 e incrementa `script_version`. Edição manual não pode acionar LLM nem GPU. |
| RF-08 | M | **Enquanto** o job estiver em `awaiting_approval`, **o sistema deve** calcular e exibir a estimativa de custo por cena e total (TTS + vídeo), **descontando artefatos já existentes em cache**, e o custo de LLM já incorrido. |
| RF-09 | M | **Quando** o usuário aprovar informando `script_version`, **o sistema deve** (a) rejeitar com `409` se a versão não for a atual; (b) rejeitar com `422` se a estimativa exceder `max_budget_usd`; (c) revalidar o roteiro; (d) fixar `seed` das cenas que não a tenham; (e) congelar o roteiro e iniciar a Etapa 2. **Antes** disso nenhuma chamada de TTS/T2V é permitida. |

### 3.2 Etapa 2 — Renderização

| ID | P | Requisito |
|---|---|---|
| RF-02 | M | **Quando** o job for aprovado, **o sistema deve** sintetizar, para cada cena, o áudio via TTS (F5-TTS ou Fish Speech) usando o `ref_audio`/`ref_text` da voz escolhida e produzir WAV normalizado em **−14 LUFS (±1 LU)**. |
| RF-03 | M | **Enquanto** o áudio é processado, **o sistema deve** disparar em paralelo a geração do clipe (Wan 2.1 ou CogVideoX) na resolução/`frame_num`/`fps` do catálogo e com `seed` fixa, usando como prompt final `prompt_video + estilo_visual`, e salvar o MP4 bruto. |
| RF-04 | M | **Se** `\|T_audio − T_video\| > 0,2 s`, **o sistema deve** calcular `S = T_audio / T_video` e: (a) `0,85 ≤ S ≤ 1,35` → `setpts=S*PTS`; (b) `S > 1,35` → esticar até 1,35 e completar com *freeze-frame* + zoom suave; (c) `S < 0,85` → acelerar até 0,85, cortar na duração do áudio e aplicar *fade-out*. **Senão** apenas completar/aparar a diferença sem efeito perceptível. Nunca deixar tela preta nem corte abrupto na fala. |
| RF-05 | M | **Quando** áudio e vídeo da cena estiverem prontos, **o sistema deve** gerar legenda `.ass` estilizada (respeitando *safe zone* da proporção) e queimá-la via filtro `ass` do FFmpeg, sem MoviePy/ImageMagick. |
| RF-06 | M | **Quando** todas as cenas estiverem compostas, **o sistema deve** concatená-las em ordem em `final_render.mp4` (H.264/libx264, AAC, `yuv420p`, 24 ou 30 FPS, `+faststart`). |
| RF-10 | M | **Enquanto** o job estiver em execução, **o sistema deve** expor progresso por cena e por etapa (`pending/running/done/failed`, `cached`, custo) via snapshot (`GET`) e *stream* SSE, com reconexão por `Last-Event-ID`. |
| RF-11 | M | **O sistema deve** permitir: **cancelar** (cancelando predições remotas em andamento, sem apagar artefatos já pagos); **retomar** um job `failed` reaproveitando tudo que já foi gerado; **reabrir** um job `completed/failed` para `awaiting_approval` e re-renderizar apenas as cenas alteradas; **clonar** um job. |

### 3.3 Suporte

| ID | P | Requisito |
|---|---|---|
| RF-12 | M | **Quando** o usuário enviar um áudio de referência, **o sistema deve** validar formato (wav/mp3/m4a/flac), tamanho (≤ 10 MB) e duração (3–30 s, configurável) via `ffprobe`, exigir `ref_text`, armazenar com hash de conteúdo e devolver um `voice_id`. |
| RF-13 | M | **O sistema deve** servir o vídeo final e *previews* de áudio/vídeo/clipe por cena, com suporte a HTTP *Range*. |
| RF-14 | S | **O sistema deve** listar os modelos/provedores disponíveis (apenas os com credencial configurada), com limites e preço estimado. |
| RF-15 | M | **O sistema deve** oferecer UI web (Jinja2 + HTMX, sem Node) cobrindo: criar → revisar/editar → estimar/aprovar → acompanhar → baixar. |
| RF-16 | S | **Onde** `PROVIDER_MODE=fake`, **o sistema deve** executar o fluxo completo com provedores simulados a custo zero (dev, testes, demonstração). |

## 4. Requisitos não funcionais

| ID | Requisito (mensurável) |
|---|---|
| RNF-01 | **Paralelismo.** TTS e T2V de todas as N cenas disparam concorrentemente (`asyncio`), limitados por semáforos por provedor. Tempo de espera de rede ≈ cena mais lenta, não a soma. Cada cena é composta assim que seu par A/V termina (*pipeline*), sem esperar as demais. |
| RNF-02 | **Idempotência e cache.** Artefatos endereçados por SHA-256 dos parâmetros (provedor, modelo, versão, prompt/texto, seed, resolução, hash da voz…). Reexecução após falha **não** repete chamada paga já concluída. Reordenar ou editar uma cena invalida somente os hashes afetados. *Single-flight*: duas cenas idênticas geram uma única chamada. |
| RNF-03 | **Abstração de provedores.** Trocar modelo (`wan-2.1` ↔ `cogvideox`) ou provedor (Replicate, Fal.ai, DeepInfra) exige apenas alterar `config/models.yaml`/`.env`; nenhuma mudança em `services/`. |
| RNF-04 | **Resiliência de rede.** Até 3 tentativas com *exponential backoff* + *jitter* (respeitando `Retry-After`), apenas para erros transitórios (408/429/5xx/timeout/conexão). Timeouts configuráveis por modelo (vídeo até 300 s, cobrindo *cold start*). |
| RNF-05 | **Anti-god-class (limite rígido).** Nenhum arquivo, função/método, classe, *model* Pydantic ou *controller* (router) pode ter **mais de 300 linhas**. Verificado automaticamente (`scripts/check_limits.py`) em pre-commit e CI; violação quebra o build. Metas: função ≤ 50, classe ≤ 150 e ≤ 10 métodos públicos, router ≤ 8 endpoints. |
| RNF-06 | **Arquitetura em camadas verificada.** Dependências (`api → services → ports/domain`; `providers/infra/composer` implementam `ports`) impostas por `import-linter`. `services` não importam SDK/HTTP/FFmpeg diretamente. |
| RNF-07 | **Segurança.** Chaves só em env (`SecretStr`, redigidas em log); autenticação por `X-API-Key`/cookie; `job_id` validado por regex (sem *path traversal*); uploads com limite e validação via `ffprobe`; *downloader* só aceita hosts em *allowlist* por provedor (anti-SSRF) e tamanho máximo. |
| RNF-08 | **Observabilidade.** Logs JSON com `job_id`, `scene_index`, `step`, `provider`, `attempt`; `events.jsonl` auditável por job; custo estimado × real registrado por etapa. |
| RNF-09 | **Durabilidade.** Estado persistido a cada transição (escrita atômica). Após *crash*/restart, jobs `scripting/rendering/finalizing` retomam sozinhos; o `remote_id` da predição é gravado **logo após o submit**, evitando cobrança dupla. |
| RNF-10 | **Controle de custo.** Estimativa antes da aprovação, `max_budget_usd` por job, bloqueio de novas tentativas ao estourar orçamento, custo real acumulado em `CostLedger`. |
| RNF-11 | **Responsividade da API.** Endpoints nunca bloqueiam o *event loop*: FFmpeg via `asyncio.create_subprocess_exec`; I/O de arquivo via `to_thread`. Respostas ≤ 200 ms (exceto streaming). |
| RNF-12 | **Qualidade.** `ruff` + `mypy --strict` limpos; cobertura ≥ 85 % em `domain`, `services` e `composer`; testes de arquitetura no CI. |
| RNF-13 | **Portabilidade.** Python ≥ 3.12; FFmpeg ≥ 6 com `libass`; imagem Docker única; 1 processo uvicorn (ver §6). |

## 5. Cenários de aceite (fim a fim)

| ID | Cenário | Resultado esperado |
|---|---|---|
| AC-01 | Caminho feliz: tema → roteiro de 5 cenas → aprovar → render | `final_render.mp4` 9:16, 5 cenas, legendas, áudio −14 LUFS (±1), A/V sincronizados (±1 frame na emenda). |
| AC-02 | Editar 1 cena e reaprovar | Estimativa e cobrança apenas para a cena alterada; as demais `cached=true`. |
| AC-03 | Cena 3 falha no T2V (erro 502 persistente) | Job `failed`; cenas 1, 2, 4, 5 concluídas e preservadas; `retry` só refaz a cena 3. |
| AC-04 | Processo reiniciado no meio do render | Job retoma sem nova submissão das predições já criadas (contagem de submits = 0 para elas). |
| AC-05 | Aprovar com `script_version` desatualizada | `409`; nenhum custo; estado inalterado. |
| AC-06 | Aprovar com custo estimado > orçamento | `422 BUDGET_EXCEEDED`; job continua em `awaiting_approval`. |
| AC-07 | Áudio 6,2 s × vídeo 5,06 s (S = 1,22) | `setpts` aplicado; duração do clipe = duração do áudio ± 1 frame. |
| AC-08 | Arquivo com 301 linhas é commitado | `check_limits.py` falha o CI. |
| AC-09 | Trocar `video: cogvideox-5b` no YAML | Mesmo fluxo roda sem alterar código em `services/`. |

## 6. Premissas e restrições

- Single-tenant, 1 operador/equipe; **um único processo uvicorn** (fila e *event bus* em memória atrás de *ports*; escalar horizontalmente exigirá implementar `JobQueue`/`EventBus` externos — não está no escopo).
- Dependências de runtime Python: `fastapi`, `uvicorn`, `pydantic` v2, `pydantic-settings`, `httpx`, `jinja2`, `python-multipart`, `pyyaml`. Dev: `pytest`, `pytest-asyncio`, `respx`, `ruff`, `mypy`, `import-linter`. Estáticos (HTMX, CSS) **vendorizados**.
- Binários de sistema: `ffmpeg`, `ffprobe` (com `libass`).
- Versões de modelo (hash de versão do Replicate etc.) são **fixadas** em `models.yaml` para reprodutibilidade.

## 7. Fora de escopo (v1)

Multi-tenant/billing; lip-sync; trilha musical e transições (`xfade`); upload de mídia própria; treino de voz; armazenamento S3/R2 (apenas ponto de extensão); fila distribuída; transcrição automática de `ref_text`.

## 8. Diferenças deliberadas em relação ao documento-base

| Base | Aqui | Motivo |
|---|---|---|
| `ThreadPoolExecutor` + `replicate.run()` | `asyncio` + `httpx` + REST do provedor | Controle de *retry*, cancelamento e persistência do `remote_id`; encaixa no *event loop* do FastAPI. |
| `as_completed` propaga 1ª exceção | `gather(return_exceptions=True)` | Falha numa cena não pode descartar chamadas pagas das irmãs. |
| Cache por `cena_{i}.mp4` | Cache por hash de conteúdo | Reordenar/editar cenas reaproveita artefatos. |
| RF-02 "roteiro de uma cena aprovado" | Aprovação do roteiro inteiro (RF-09) | Um único portão, com versão e orçamento. |
| `max_length=110` caracteres | Regra por **palavras** + teto de caracteres | 110 caracteres ≠ 12 palavras. |
| — | `estilo_visual` no roteiro | Coerência visual entre clipes gerados de forma independente. |
| — | Prompts proíbem "pessoa falando" | T2V não faz lip-sync; evita dessincronia visual. |

## 9. Questões em aberto

1. **Qualidade PT-BR do TTS:** F5-TTS base é treinado majoritariamente em EN/ZH; validar com uma voz real. Fish Speech **não está no Replicate** (pesquisa de 2026-11-08), então hoje não há alternativa de TTS com clonagem no catálogo.
2. ~~Disponibilidade no Fal.ai~~ **Resolvido:** Fal não tem Wan 2.1/F5-TTS/CogVideoX (só Wan 2.7); adapter adiado. Ver design/03 §9.
3. **Preços reais** por modelo: DeepSeek conferido; Replicate parcial (F5-TTS ~US$ 0,01, CogVideoX ~US$ 0,50); Wan 2.1 ainda é estimativa. Nomes de campos exigem `scripts/replicate_schema.py` com token.
4. Estilo visual das legendas (fonte, cores, marca) e fonte OFL a embarcar.
5. Política de retenção de artefatos/cache (TTL, limite de disco).
6. Autenticação multiusuário é necessária no futuro?
