-- Membros do VideoGen (autorização). Rodar como dono do banco `videogen` (Neon, projeto videogen-mks).
-- A identidade (senha, códigos, sessões) fica no schema neon_auth, gerido pelo Neon Auth.
CREATE SCHEMA IF NOT EXISTS app;

CREATE TABLE IF NOT EXISTS app.members (
    email       text PRIMARY KEY CHECK (email = lower(email) AND position('@' in email) > 1),
    name        text NOT NULL CHECK (length(name) BETWEEN 1 AND 120),
    role        text NOT NULL DEFAULT 'member' CHECK (role IN ('admin', 'member')),
    active      boolean NOT NULL DEFAULT true,
    created_at  timestamptz NOT NULL DEFAULT now(),
    created_by  text
);

-- Papel da aplicação: só o necessário (sem DELETE, sem DDL).
GRANT USAGE ON SCHEMA app TO videogen_app;
GRANT SELECT, INSERT, UPDATE ON app.members TO videogen_app;
