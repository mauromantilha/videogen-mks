# Design 04 — Composer (FFmpeg)

> Pacote: `composer/` · Tarefas: M4 (T-040…T-047) · Voltar: [design.md](../design.md)

Implementa `MediaComposer` e `MediaProbe`. Substitui o MoviePy do protótipo: **um** comando FFmpeg por
cena + **uma** concatenação final (ADR-08/09).

## 1. Módulos

| Arquivo | Classe / função | Responsabilidade (única) |
|---|---|---|
| `ffmpeg_runner.py` | `FfmpegRunner` | Executa `ffmpeg`/`ffprobe` com `asyncio.create_subprocess_exec` (lista de args, **sem shell**), `-nostdin -hide_banner -loglevel error`, timeout, semáforo `MAX_PARALLEL_FFMPEG`, últimos 4 KB de `stderr` em `MediaError`. |
| `probe.py` | `FfprobeProbe` | `ffprobe -print_format json -show_format -show_streams` → `MediaInfo`. Usado para durações (fonte de verdade) e validação de artefatos/uploads. |
| `loudnorm.py` | `LoudnessNormalizer` | Normalização EBU R128 em duas passadas (§3). |
| `filters.py` | `FilterGraphBuilder` | Constrói a string do `-filter_complex` a partir de `SyncPlan` + `ClipSpec` (função pura, testável sem FFmpeg). |
| `subtitles/chunker.py` | `PhraseChunker` | Quebra `texto_narrado` em linhas curtas e distribui o tempo. |
| `subtitles/styles.py` | `AssStyle` + presets | Estilos por proporção (*safe zones*). |
| `subtitles/ass_writer.py` | `AssWriter` | Serializa o `.ass` (cabeçalho, estilo, `Dialogue`), com escape. |
| `scene_composer.py` | `SceneComposer` | Orquestra: probe → `plan_sync` → `.ass` → filtergraph → ffmpeg → valida saída. |
| `concat.py` | `Concatenator` | Concatenação final. |
| `healthcheck.py` | `ToolchainCheck` | Verifica `ffmpeg`/`ffprobe` ≥ 6, filtro `ass` (libass), `loudnorm`, fonte embarcada. |

## 2. `ClipSpec` (entrada do composer)

```python
class ClipSpec(BaseModel):
    video_path: Path; audio_path: Path; out_path: Path
    texto: str; aspect_ratio: AspectRatio
    width: int; height: int; fps: Literal[24, 30]
    subtitles: bool; sync: SyncConfig; style: str = "default"
```

## 3. Normalização de áudio (RF-02) — `loudnorm.py`

Duas passadas para precisão (±1 LU):

```bash
# passada 1 — medir
ffmpeg -i raw.wav -af loudnorm=I=-14:TP=-1.5:LRA=11:print_format=json -f null -
# passada 2 — aplicar com os valores medidos (linear)
ffmpeg -i raw.wav -af "loudnorm=I=-14:TP=-1.5:LRA=11:measured_I=…:measured_TP=…:measured_LRA=…:measured_thresh=…:offset=…:linear=true" \
       -ar 48000 -ac 1 audio_norm.wav
```

O JSON da passada 1 é extraído do final do `stderr`. Resultado cacheado como `audio_norm` com hash
derivado do `audio_raw` + parâmetros (design/01 §7): o áudio **pago** (`audio_raw`) nunca é regerado só
porque mudou o alvo de loudness.

## 4. Sincronização e composição por cena — `scene_composer.py` + `filters.py`

Fluxo de `compose_clip(spec)`:

1. `t_audio = probe(audio).duration`, `t_video = probe(video).duration` (nunca assumir `81 frames`).
2. `plan = plan_sync(t_audio, t_video, spec.sync)` (design/01 §8).
3. Se `spec.subtitles`: `AssWriter` grava `scene.ass` no diretório temporário da cena.
4. `FilterGraphBuilder.build(plan, spec)` ⇒ `filter_complex`.
5. Um único ffmpeg; saída validada com `probe` (duração ≈ `target_duration_s` ± 1 frame, `has_audio`).

### Filtergraph por estratégia

```text
NONE         [0:v]tpad=stop_mode=clone:stop_duration={extra},fps={fps},scale={W}:{H}:flags=lanczos,setsar=1,{ass}[v]
STRETCH      [0:v]setpts={S}*PTS,fps={fps},scale=…,setsar=1,{ass}[v]
FREEZE_ZOOM  [0:v]setpts={1.35}*PTS,fps={fps},tpad=stop_mode=clone:stop_duration={extra},
             zoompan=z='if(gte(on,{N0}),min(zoom+0.0006,1.12),1)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:s={W}x{H}:fps={fps},
             setsar=1,{ass}[v]
TRIM         [0:v]setpts={0.85}*PTS,fps={fps},trim=duration={T},fade=t=out:st={T-0.3}:d=0.3,scale=…,setsar=1,{ass}[v]
{ass} = ass=scene.ass:fontsdir=fonts            # omitido se legendas=false
```

`N0` = frame em que começa o congelamento (`(t_video·1.35)·fps`). O zoom só cresce depois de `N0`,
logo o trecho animado é suave e a fala nunca "trava" visualmente. **A validar na T-044** com teste de
*golden frames* (extrair frames em t=0, N0, fim e comparar).

Comando final (exemplo STRETCH, 9:16 em 720×1280, 30 fps):

```bash
ffmpeg -nostdin -y -i video.mp4 -i audio_norm.wav \
  -filter_complex "[0:v]setpts=1.23*PTS,fps=30,scale=720:1280:flags=lanczos,setsar=1,ass=scene.ass:fontsdir=fonts[v]" \
  -map "[v]" -map 1:a -t 6.20 \
  -c:v libx264 -preset medium -crf 20 -pix_fmt yuv420p -r 30 \
  -c:a aac -b:a 192k -ar 48000 -ac 2 -movflags +faststart clip.mp4
```

Todos os clipes saem com **parâmetros idênticos** (codec, resolução, SAR, fps, `yuv420p`, 48 kHz) —
pré-condição para o concat sem recodificar vídeo. O comando roda com `cwd` = diretório da cena, de modo
que `scene.ass` e `fonts` são caminhos relativos (evita escape de `:` e `\` do filtro `ass`).

## 5. Legendas ASS — `composer/subtitles/`

- **Chunker:** divide por pontuação e agrupa em linhas de ≤ 3–4 palavras (≤ 28 caracteres em 9:16;
  ≤ 42 em 16:9). Duração de cada linha **proporcional ao nº de caracteres**; soma = `t_audio` (a última
  linha termina exatamente no fim do áudio). Sem alinhamento forçado na v1 (extensão futura).
- **Estilos** (`PlayRes` = resolução de saída, para o tamanho ser independente do scaling):

| Preset | PlayRes | Fonte | `MarginV` (safe zone) | Contorno | Alinhamento |
|---|---|---|---|---|---|
| `9x16` | 720×1280 | 64 pt bold | ~260 (evita UI de Reels/TikTok) | 4 + sombra 1 | 2 (inferior central) |
| `16x9` | 1280×720 | 46 pt bold | 50 | 3 + sombra 1 | 2 |

- **Escape ASS:** `\` → `\\`, `{`/`}` → `\{`/`\}`, quebra de linha → `\N`. Teste com texto malicioso
  (`{\fs200}`) garante que o LLM não injeta *override tags*.
- A fonte OFL fica em `assets/fonts/` e é passada via `fontsdir`; `ToolchainCheck` falha o *readiness*
  se `libass` ou a fonte não existirem.

## 6. Concatenação final (RF-06) — `concat.py`

```bash
# concat.txt:  file '/abs/clip_0.mp4' …   (aspas simples escapadas)
ffmpeg -nostdin -y -f concat -safe 0 -i concat.txt \
       -c:v copy -c:a aac -b:a 192k -ar 48000 -ac 2 -movflags +faststart final_render.mp4
```

Vídeo copiado (sem 2ª recodificação); só o áudio é recodificado para eliminar *pops* do *priming* do AAC
nas emendas. `Concatenator` confere via `probe` que todos os clipes têm o mesmo perfil; se divergirem
(ex.: clipe reaproveitado de uma versão antiga), recodifica o vídeo (caminho lento, logado).
Saída validada: `duração ≈ Σ clipes ± 1 frame`.

## 7. Testes

- **Puros (sem FFmpeg):** `plan_sync`, `FilterGraphBuilder` (snapshot de strings), `PhraseChunker`,
  `AssWriter` (escape, tempos somam `t_audio`).
- **Integração (`@pytest.mark.ffmpeg`)**: mídia sintética por `lavfi` (`testsrc2`, `sine`) cobrindo as 4
  estratégias; asserts por `ffprobe` (duração, codec, fps, `loudnorm` medido em −14 ± 1 LUFS) e *golden
  frames* do freeze/zoom; concat de 3 clipes; fallback de perfil divergente.
- O CI instala FFmpeg com `libass`; os testes `ffmpeg` são obrigatórios no CI e opcionais localmente.

## 8. Estado após a implementação do M4 (2026-11-08, FFmpeg 8.0.1)

| Tema | Como ficou | Por quê |
|---|---|---|
| Escape das legendas | `{`→`(`, `}`→`)`, `\`→`/` (substituição), não `\{`. | Determinístico em qualquer versão do libass; o texto é narração, nada se perde. |
| Fonte | `DejaVu Sans` via fontconfig; `fontsdir` é opcional. | Evita versionar binário de fonte; o Docker instala `fonts-dejavu-core`. |
| Medição do loudnorm | Último bloco JSON com `input_i`, em qualquer posição do stderr. | O FFmpeg 8 imprime progresso depois do JSON. |
| Enquadramento | `scale=…:force_original_aspect_ratio=increase` + `crop` antes do zoom/legenda. | A saída do modelo (ex.: 480×832) raramente bate com a resolução final; cobre o quadro sem distorcer. |
| Perfil de codificação | `composer/encoding.py` (`EncodeSettings`), único para todos os clipes. | Pré-condição do concat com `-c:v copy`. |
| Port | `composer/media_composer.py` (`FfmpegMediaComposer`) junta loudnorm, cena e concat. | Os serviços só veem o port `MediaComposer`. |
| Healthcheck | Versão ≥ 6, filtros `ass`/`loudnorm`/`zoompan`/`tpad`, encoder `libx264`, `ffprobe`, `fontsdir` se configurado. | Tudo que o render usa é verificado antes do primeiro job. |
| Validado com FFmpeg real | As 4 estratégias (duração = áudio ± 2 quadros), −14 ± 1 LUFS medido, silêncio, legenda visível, zoom no freeze, concat por cópia e fallback de perfis diferentes, comando sem shell, timeout. | `tests/integration/composer/`. |
