# Plano de tarefas — VideoGen MKS

> Versão 1.0 · 2026-11-08 · Relacionados: [requirements.md](requirements.md) · [design.md](design.md)
> Detalhe por marco em `docs/tasks/`.

## 1. Marcos

| Marco | Tema | Arquivo | Tarefas | Resultado verificável |
|---|---|---|---|---|
| **M0** | Fundações e guardiões | [m0-m2](tasks/m0-m2-fundacao-dominio-infra.md) | T-001…T-005 | CI verde com `check_limits` e `import-linter` já ativos |
| **M1** | Domínio e ports | idem | T-010…T-018 | Contratos, estados, hash e `plan_sync` testados (sem I/O) |
| **M2** | Infra | idem | T-020…T-026 | Repositório atômico, cache por hash, bus, downloader |
| **M3** | Providers | [m3-m4](tasks/m3-m4-providers-composer.md) | T-030…T-039 | Adapters passam na suíte de contrato; `fake` operacional |
| **M4** | Composer | idem | T-040…T-047 | Cena composta com 4 estratégias de sync + concat |
| **M5** | Serviços da Etapa 1 | [m5-m6](tasks/m5-m6-etapa1-servicos-api.md) | T-050…T-058 | Roteiro → edição → estimativa → aprovação (sem GPU) |
| **M6** | API | idem | T-060…T-067 | Fluxo da Etapa 1 completo via HTTP + SSE |
| **M7** | Render (Etapa 2) | [m7-m9](tasks/m7-m9-render-ui-hardening.md) | T-070…T-078 | Job aprovado vira MP4 com `fake`; idempotência provada |
| **M8** | UI | idem | T-080…T-084 | Fluxo completo no navegador |
| **M9** | Hardening | idem | T-090…T-099 | E2E, crash-recovery, Docker, smoke live |

## 2. Convenções das tarefas

Cada tarefa: `ID — título · tam · dep · cobre`, **Entrega** (arquivos + orçamento de linhas) e **DoD**.
Tamanho: **S** ≤ ½ dia · **M** ≈ 1 dia · **L** ≈ 2 dias (uma tarefa L deve ser dividida se passar disso).

### Definição de pronto (vale para toda tarefa)

1. Código em `src/videogen/…` conforme o design, **nenhum arquivo/classe/função > 300 linhas**
   (`python scripts/check_limits.py` limpo; metas respeitadas ou justificadas).
2. `ruff` e `mypy --strict` limpos; `lint-imports` limpo.
3. Testes da própria tarefa (unit e/ou contrato) escritos **junto** e passando; cobertura da unidade ≥ 85 %.
4. Sem segredos em log; erros usam a hierarquia de `core/errors.py`.
5. Docstring curta nas classes públicas; sem `TODO` sem tarefa associada.
6. Se alterar contrato (schema/hash/port), atualizar o doc de design correspondente no mesmo PR.

### Regra de PR

PR pequeno (1 tarefa, idealmente ≤ 400 linhas de diff). PR que cria arquivo > 250 linhas é devolvido
para divisão antes da revisão.

## 3. Ordem sugerida e caminho crítico

```
M0 ─► M1 ─┬─► M2 ─┬─► M5 ─► M6 ─────────────┐
          ├─► M3 ─┤                          ├─► M8 ─► M9
          └─► M4 ─┴─► M7 ───────────────────┘
```

- **Primeiro:** T-002 e T-003 (guardiões) — a regra de 300 linhas vale desde o 1º arquivo.
- **Paralelizáveis após M1:** M2, M3 (exceto T-036 `fake`, necessário cedo), M4.
- **Caminho crítico:** T-001 → T-002 → M1 → T-021/T-022 → T-036 (fake) → M5 → M6 → M7 → M9.
- **Entrega incremental:** após M6 já existe a **Etapa 1 inteira** utilizável via API (roteiro
  editável e aprovável, sem custo de GPU); M7 liga a Etapa 2.

## 4. Matriz de rastreabilidade (requisito → tarefas)

| Requisito | Tarefas |
|---|---|
| RF-01 Roteiro estruturado | T-010, T-050, T-051, T-052, T-033, T-063 |
| RF-02 TTS + −14 LUFS | T-035, T-042, T-073 |
| RF-03 Vídeo T2V | T-034, T-035, T-074 |
| RF-04 Sincronização A/V | T-015, T-044, T-045 |
| RF-05 Legendas ASS | T-043, T-045 |
| RF-06 Concat final | T-046, T-076 |
| RF-07 Edição do roteiro | T-053, T-064, T-082 |
| RF-08 Estimativa de custo | T-054, T-064, T-082 |
| RF-09 Aprovação (gate) | T-012, T-056, T-064 |
| RF-10 Progresso / SSE | T-023, T-065, T-071, T-083 |
| RF-11 Cancelar/retomar/reabrir/clonar | T-055, T-057, T-078 |
| RF-12 Vozes | T-025, T-058, T-066, T-084 |
| RF-13 Artefatos / Range | T-067 |
| RF-14 Catálogo | T-032, T-066 |
| RF-15 UI | T-080…T-084, T-099 |
| RF-16 Modo `fake` | T-036 |
| RNF-01 Paralelismo | T-070, T-075, T-077, T-097 |
| RNF-02 Idempotência/cache | T-014, T-022, T-070, T-072, T-091 |
| RNF-03 Abstração de provedores | T-032, T-039 |
| RNF-04 Resiliência | T-030, T-031 |
| RNF-05 Limite 300 linhas | T-002 (+ DoD global) |
| RNF-06 Camadas | T-003 |
| RNF-07 Segurança | T-020, T-024, T-061, T-096 |
| RNF-08 Observabilidade | T-005, T-023, T-095 |
| RNF-09 Durabilidade | T-021, T-057, T-072, T-092 |
| RNF-10 Controle de custo | T-054, T-071, T-056 |
| RNF-11 Responsividade | T-021, T-040 |
| RNF-12 Qualidade | T-001, T-003, DoD global |
| RNF-13 Portabilidade | T-047, T-094 |

Cenários de aceite: AC-01 → T-090 · AC-02 → T-090/T-091 · AC-03 → T-091 · AC-04 → T-092 ·
AC-05/06 → T-056/T-064 · AC-07 → T-015/T-045 · AC-08 → T-002 · AC-09 → T-039.

## 5. Primeiro passo executável

Executar **T-001 → T-002 → T-003**: scaffold, `check_limits.py` com seus testes e contratos
`import-linter`. Só depois começar M1. O `main.py` solto na raiz do repositório é substituído por
`src/videogen/main.py` em T-001.
