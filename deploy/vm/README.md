# Deploy no mks-server (OCI)

VM `VM.Standard.A1.Flex` (ARM64, 2 OCPU, 12 GB) em us-phoenix-1, compartilhada com CRM, n8n e
assinaturas. O VideoGen roda limitado a **1 vCPU e 2 GB** e fica atrás do Caddy do `pdf-api`.

## Primeira instalação

```bash
git clone https://github.com/mauromantilha/videogen-mks ~/apps/videogen-mks
cd ~/apps/videogen-mks
umask 077 && cat > deploy/vm/.env <<ENV
APP_ENV=prod
AUTH_MODE=neon
NEON_AUTH_URL=https://<endpoint>.neonauth.<região>.aws.neon.tech/videogen/auth
APP_PUBLIC_URL=https://video.mksseguros.com
DATABASE_URL=postgresql://videogen_app:<senha>@<endpoint>.<região>.aws.neon.tech/videogen?sslmode=require
AUTH_BOOTSTRAP_ADMIN=         # e-mail do primeiro admin (só age se ainda não houver admin)
PROVIDER_MODE=fake            # trocar para real ao configurar as chaves abaixo
DEEPSEEK_API_KEY=
REPLICATE_API_TOKEN=
ENV
docker compose -f deploy/vm/docker-compose.yml up -d --build
docker exec videogen python -c "import urllib.request as u; print(u.urlopen('http://127.0.0.1:8000/readyz').read())"
```

## Neon (login e membros)

Projeto `videogen-mks` (org `mksseguros`, AWS us-west-2 — o Neon Auth ainda não existe no Azure),
banco `videogen`. Neon Auth: e-mail/senha e código por e-mail, **cadastro aberto desligado**,
domínio confiável `https://video.mksseguros.com`. Tabela de membros: `deploy/sql/001_members.sql`
(rodar como dono); o papel `videogen_app` tem só SELECT/INSERT/UPDATE em `app.members`.

## Expor em video.mksseguros.com

1. DNS (Cloudflare): registro `A video → 132.226.81.51`, **sem proxy** (igual a crm/sub).
2. Acrescentar `Caddyfile.snippet` ao `~/apps/pdf-api/Caddyfile` (backup antes), validar e recarregar:
   `docker exec pdf-api-caddy-1 caddy validate --config /etc/caddy/Caddyfile`
   `docker exec pdf-api-caddy-1 caddy reload --config /etc/caddy/Caddyfile`

## Operação

| Tarefa | Comando |
|---|---|
| Atualizar | `git pull && docker compose -f deploy/vm/docker-compose.yml up -d --build` |
| Logs | `docker logs -f videogen` |
| Prontidão | `docker exec videogen python -c "import urllib.request as u; print(u.urlopen('http://127.0.0.1:8000/readyz').read())"` |
| Backup do estado | volume `videogen_workspace` (jobs, vozes, cache) — até a fase 2 (Neon + bucket) |
