# Marcos M3–M4 — Providers e Composer

> Voltar: [tasks.md](../tasks.md) · Design: [03](../design/03-providers.md), [04](../design/04-composer.md)

## M3 — Providers

### T-030 — Retry e classificação de erros · M · dep: T-005 · cobre: RNF-04
- **Entrega:** `core/retry.py` (≤ 110: `RetryPolicy`, `retry_async`), `providers/http/errors.py` (≤ 100:
  `classify_response`). `retry` fica em `core` para ser usado também por `infra/downloader` sem criar
  dependência entre adapters.
- **DoD:** 3 tentativas, backoff `base·2ⁿ` com *jitter* (relógio e RNG injetáveis), respeita `Retry-After`,
  não repete erro não retryable; tabela de status → `ProviderError(retryable)` coberta.

### T-031 — Cliente HTTP resiliente e polling · M · dep: T-030 · cobre: RNF-04
- **Entrega:** `providers/http/client.py` (≤ 120: `ResilientHttpClient`, perfis de timeout, log sem
  segredos), `providers/http/polling.py` (≤ 100: `PredictionPoller`).
- **DoD:** `respx`: timeout total estoura em `ProviderTimeout`; erro de rede transitório durante o polling
  não consome as tentativas de submissão; intervalo de polling 2→5 s (relógio falso).

### T-032 — Catálogo de modelos e registry · M · dep: T-004, T-017 · cobre: RNF-03, RF-14
- **Entrega:** `providers/catalog/{model_spec,loader,registry}.py` (≤ 120 cada), `config/models.yaml`
  inicial (design/03 §2).
- **DoD:** YAML inválido derruba o startup com mensagem objetiva; `registry.video("cogvideox-5b")` troca
  de modelo sem tocar em serviços; só lista modelos com credencial (RF-14).

### T-033 — Adapter DeepSeek (LLM) · M · dep: T-031, T-032 · cobre: RF-01
- **Entrega:** `providers/deepseek/llm.py` (≤ 130): `chat/completions`, `capabilities` (json_mode,
  temperature), custo por chamada/uso.
- **DoD:** `respx`: com `json_mode` envia `response_format`; sem `temperature` omite o campo; 429 → retry;
  401 → erro sem retry; `reasoning_content` ignorado.

### T-034 — Replicate: cliente + mapping · M · dep: T-031, T-032 · cobre: RF-03, RNF-09
- **Entrega:** `providers/replicate/client.py` (≤ 130: `create/get/cancel`), `providers/replicate/mapping.py`
  (≤ 130: `tts_input`, `video_input` para F5-TTS, Fish Speech, Wan 2.1, CogVideoX).
- **DoD:** snapshots do JSON de `input` por modelo; estados `starting/processing/succeeded/failed/canceled`
  mapeados; `cancel` idempotente.

### T-035 — Replicate: TTS e T2V · M · dep: T-034, T-017 · cobre: RF-02, RF-03
- **Entrega:** `providers/replicate/{tts,video}.py` (≤ 130 cada) com `on_submitted` imediatamente após o
  `create` e retomada por `resume_remote_id`.
- **DoD:** teste "crash simulado": segunda chamada com `resume_remote_id` **não** faz `POST`; falha
  transitória resubmete (até 3); `ContentRejected` não repete.

### T-036 — Provedores `fake` · M · dep: T-017 · cobre: RF-16, RNF-12
- **Entrega:** `providers/fake/{llm,tts,video}.py` (≤ 90 cada): mídia real via `ffmpeg lavfi`, duração/latência
  configuráveis, **falhas injetáveis**, contadores de submit.
- **DoD:** gera roteiro válido para qualquer tema; áudio/vídeo com durações distintas exercitam as 4
  estratégias de sync; `PROVIDER_MODE=fake` no registry. *(Prioridade alta: destrava M5–M9.)*

### T-037 — Adapter Fal.ai (S) · M · dep: T-031, T-032 · cobre: RNF-03
- **Entrega:** `providers/fal/{client,tts,video}.py` (≤ 130 cada): fila submit → status → result.
- **DoD:** mesma suíte de contrato (T-039); **antes de começar**, confirmar modelos TTS/T2V disponíveis
  (requirements §9 nº 2); se indisponíveis, registrar decisão e encerrar a tarefa.

### T-038 — LLM DeepInfra (C) · S · dep: T-033 · cobre: RNF-03
- **Entrega:** configuração `provider: deepinfra` reutilizando o adapter OpenAI-compatível com `base_url` próprio.
- **DoD:** trocar `llm: deepinfra-…` no YAML roda o fluxo de roteiro com `respx`.

### T-039 — Suíte de contrato dos providers · M · dep: T-035, T-036 · cobre: RNF-03, AC-09
- **Entrega:** `tests/contract/test_{llm,tts,video}_contract.py` parametrizados por adapter (Fake + reais com `respx`).
- **DoD:** todos os adapters passam: sucesso, retry 429/503, sem retry 422, timeout, retomada, cancel.

## M4 — Composer

### T-040 — Runner FFmpeg · M · dep: T-005 · cobre: RNF-11, RNF-07
- **Entrega:** `composer/ffmpeg_runner.py` (≤ 110): `create_subprocess_exec` (sem shell), timeout,
  semáforo `MAX_PARALLEL_FFMPEG`, `stderr` truncado em `MediaError`.
- **DoD:** teste: argumento com `;`/espaços não é interpretado; timeout mata o processo filho; loop de
  eventos continua responsivo durante a execução.

### T-041 — Probe · S · dep: T-040 · cobre: RF-04, RF-12
- **Entrega:** `composer/probe.py` (≤ 90): `FfprobeProbe.probe/validate` → `MediaInfo`.
- **DoD:** arquivo truncado/zerado ⇒ `MediaError`; duração e fps corretos em mídia `lavfi`.

### T-042 — Normalização de loudness · M · dep: T-040, T-041 · cobre: RF-02
- **Entrega:** `composer/loudnorm.py` (≤ 110): duas passadas, parsing do JSON no `stderr`.
- **DoD:** áudio sintético medido em **−14 ± 1 LUFS** (medição independente por `ebur128`); sem alterar o
  arquivo de entrada.

### T-043 — Legendas ASS · M · dep: T-001 · cobre: RF-05
- **Entrega:** `composer/subtitles/{chunker,styles,ass_writer}.py` (≤ 110 cada).
- **DoD:** soma das durações das linhas = `t_audio`; ≤ 28/42 caracteres por linha; escape de `{\fs200}`,
  `\`, quebras; presets `9x16` e `16x9` com *safe zone*; arquivo `.ass` aceito pelo libass (teste de integração).

### T-044 — Construtor de filtergraph · M · dep: T-015, T-043 · cobre: RF-04
- **Entrega:** `composer/filters.py` (≤ 150): string do `-filter_complex` por estratégia (design/04 §4).
- **DoD:** snapshots das 4 estratégias; teste com FFmpeg real e *golden frames* validando o zoom do
  `FREEZE_ZOOM` (frame em t=0 sem zoom, no fim com zoom ≤ 1,12); ajustar expressão se divergir.

### T-045 — Composição de cena · L · dep: T-041, T-042, T-044 · cobre: RF-04, RF-05, AC-07
- **Entrega:** `composer/scene_composer.py` (≤ 150) implementando `compose_clip`; `cwd` na pasta da cena.
- **DoD:** 4 cenários (áudio 5,1/6,2/8,5/3,5 s sobre vídeo 5,06 s): saída com duração = áudio ± 1 frame,
  perfil uniforme (h264, yuv420p, 30 fps, AAC 48 kHz), legenda visível (frame diferente com/sem `.ass`).

### T-046 — Concatenação · S · dep: T-045 · cobre: RF-06
- **Entrega:** `composer/concat.py` (≤ 90): concat demuxer, `-c:v copy`, áudio AAC, fallback de recodificação.
- **DoD:** 3 clipes ⇒ duração ≈ soma ± 1 frame; clipe com perfil divergente aciona o fallback (logado);
  aspas simples em caminhos escapadas.

### T-047 — Verificação do toolchain · S · dep: T-040 · cobre: RNF-13
- **Entrega:** `composer/healthcheck.py` (≤ 70): versão FFmpeg ≥ 6, filtros `ass` e `loudnorm`, fonte presente.
- **DoD:** falha de `libass` produz mensagem acionável; integrado ao `/readyz` (T-066).
