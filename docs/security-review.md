# Revisão de segurança (T-096)

> 2026-11-08 · Escopo: código em `src/`, imagem Docker e configuração. Cada ameaça do design/07 §3
> tem um controle e um teste automatizado (ou uma justificativa).

## Ameaças, controles e evidências

| Ameaça | Controle | Teste |
|---|---|---|
| Vazamento de credenciais em log | `SecretStr` nas configs; formatter de log redige `Authorization`, `*key*`, `*token*`, `sk-…`, `r8_…`; nenhum cabeçalho ou corpo de requisição é logado | `tests/unit/core/test_core.py::test_redacao_de_segredos`, `test_retry_config.py::test_le_arquivo_env_e_esconde_segredos` |
| Credenciais no repositório/imagem | `.env` no `.gitignore` e no `.dockerignore`; imagem não copia `.env` | inspeção do `git diff` a cada commit; `.dockerignore` |
| Acesso não autorizado (gasto de GPU) | `X-API-Key`/cookie com `compare_digest`; sem chave configurada só loopback; `APP_ENV=prod` exige chave | `test_api_support.py::test_autenticacao`, `test_sem_chave_configurada_so_aceita_loopback`, `test_retry_config.py::test_configuracoes_invalidas` |
| Path traversal | `job_id`/`voice_id` por regex; `Workspace` confere `resolve()` dentro da raiz (inclusive symlink); chave de cache precisa ser SHA-256; artefatos achados por hash, nunca por caminho do cliente | `test_disk.py::test_ids_maliciosos_sao_recusados`, `test_symlink_para_fora_do_workspace_e_recusado`, `test_chave_de_cache_deve_ser_sha256`, `test_visao_do_job_nao_vaza_detalhes_internos` |
| SSRF pela URL devolvida pelo provedor | Só `https`, host na allowlist do modelo (revalidada a cada redirect), sem credenciais na URL, tamanho máximo | `test_downloader.py` (IP de metadata, subdomínio enganoso, redirect proibido, limite de bytes) |
| Cobrança duplicada | `remote_id` gravado antes do primeiro poll; submit não idempotente não é repetido após timeout de leitura; single-flight | `test_http.py::test_submit_nao_e_repetido_apos_timeout_de_leitura`, `test_generation_contract.py`, `tests/e2e/test_crash_recovery.py` |
| Upload malicioso | Limite de bytes, extensão, validação por `ffprobe`, reconversão para WAV antes de armazenar | `test_voices.py::test_recusa_referencias_invalidas`, `test_arquivo_que_nao_e_audio` |
| Injeção de comando via texto do LLM | `subprocess` sem shell, argumentos em lista; legenda em arquivo `.ass` referenciado por nome relativo | `test_composer.py::test_runner_sem_shell_erro_e_timeout` |
| Injeção de *override tags* na legenda | `{`, `}` e `\` substituídos antes de escrever o `.ass` | `test_subtitles_filters.py::test_texto_do_llm_nao_injeta_override_tags` |
| XSS pelo texto do LLM | Jinja2 com autoescape; CSP sem `unsafe-inline`/`eval`; HTMX com `allowEval: false` | `test_ui.py::test_texto_do_llm_e_escapado`, `test_pagina_inicial_tem_cabecalhos_de_seguranca` |
| CSRF | Cookie `SameSite=Lax` + `HttpOnly` (POST de outro site não leva o cookie); API exige cabeçalho | `test_ui.py::_login` (atributos do cookie) |
| Open redirect no login | `next` só aceita caminho local (`/…`, nunca `//…`) | `test_ui.py::test_login_protege_paginas_e_fragmentos` |
| Clickjacking | `X-Frame-Options: DENY` e `frame-ancestors 'none'` | `test_pagina_inicial_tem_cabecalhos_de_seguranca` |
| Prompt injection pelo tema | Tema isolado na mensagem do usuário e sem quebras de linha; saída validada por regras determinísticas | `test_prompts_repair.py::test_tema_nao_injeta_instrucoes` |
| Vazamento de detalhes em erro | `problem+json` com contexto por lista branca; 500 genérico | `test_api_support.py::test_erro_inesperado_nao_vaza_detalhes` |
| DoS por parâmetros | `n_cenas ≤ 10`, `tema ≤ 500`, orçamento ≤ US$ 100, semáforos por modelo/FFmpeg/jobs | `test_request_generation.py::test_pedido_invalido`, `test_render.py::test_cenas_rodam_em_paralelo_respeitando_o_limite` |
| Execução como root no container | Usuário `app` (uid 10001) | `docker exec … id -un` ⇒ `app` (verificado manualmente) |
| Dependências de front-end adulteradas | HTMX vendorizado com integridade SHA-512 do npm conferida | `src/videogen/ui/static/VENDOR.md` |

## Riscos aceitos

- **Um único processo e um único usuário**: não há isolamento entre usuários; quem tem a chave vê todos os jobs.
- **Rate limiting por IP** não implementado; mitigado por autenticação obrigatória e orçamento por job.
- **Cookie guarda a própria chave de API** (HttpOnly, não acessível por JS). Para múltiplos usuários, trocar por sessão assinada.
- **Credenciais coladas no chat durante o desenvolvimento** (Replicate e DeepSeek): devem ser **rotacionadas**.
