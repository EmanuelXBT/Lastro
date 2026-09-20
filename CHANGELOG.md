# Changelog

Todas as mudanças notáveis do Lastro são documentadas neste arquivo.

O formato segue [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/),
e o versionamento segue [Semantic Versioning](https://semver.org/lang/pt-BR/).

---

## [0.4.0] — 2026-09-20

### Added
- **Detecção de fim por estouro de contexto** — o coletor `sessions` passa a ler `end_reason`, `compression_failure_error`, `compression_ineffective_count` e `compression_fallback_streak` do `state.db`: sessões que morreram por compressão esgotada (auto-reset do gateway, `end_reason='compression'`) ou que falharam ao compactar no turno ganham 🧠 no diário, linha **Motivo do fim** (18 rótulos legíveis) e citação do registro bruto do Hermes para auditoria
- Índice mestre: estatística **Sessões com estouro de contexto** e coluna de sinais (antes só o ⚠️ de erro)
- Campos `motivo_fim` e `falha_compressao` em `tb_sessao` — migração **3** (`PRAGMA user_version` 2 → 3, idempotente em bancos existentes)
- **Exceção de relevância para estouro de contexto**: sessão com estouro que seja importante (≥30 mensagens ou ≥100 mil tokens de entrada) volta ao diário mesmo sem referência ao vault, marcada com "mantida no diário pela exceção de contexto" — sem isso o filtro `sem_obsidian` escondia justamente as sessões apagadas por tamanho
- `SessionSummary.contexto_estourado`, `.tokens_contexto`, `.relevante_por_contexto` e contadores de compressão no modelo

### Fixed
- Timeout genérico de requisição (`Request timed out.`) não é mais confundido com estouro de contexto — os marcadores aceitos são específicos de compressão (`stall_interrupted`, `context_length_exceeded`, `compression`, `compact`, `context length`)

### Changed
- Auditoria retroativa nas 414 sessões: **3 marcadas** — `20260920_124802_6c9280bd` (stall em 201.240 tokens), `20260629_133749_da86150f` (611.800 tokens de entrada) e `20260703_094846_e91ae3` (177 mensagens); as duas últimas voltaram do arquivo morto, onde estavam como `nao_relevante/sem_obsidian`, e agora têm nota diária

---

## [0.3.0] — 2026-09-17

### Added
- **Hook de ciclo de vida `/new`** — o evento `on_session_reset` do gateway dispara `python3 -m lastro finalizar --sessao <id>` em background (script `/opt/data/bin/hooks/on-session-reset.py`, com allowlist própria): a sessão encerrada ganha o resumo final na hora e o vault é re-renderizado antes de a nova sessão engatar
- Comando `python3 -m lastro finalizar --sessao ID` — resumo forçado (não exige `fim` preenchido) + classificação + render único
- Filtro de relevância **v2**: novos motivos `poucas_interacoes` (≤2 mensagens do usuário, ≤10 totais e ≤3 ferramentas) e `sem_obsidian` (nenhuma referência ao vault em nenhuma mensagem) — subagentes permanecem no diário
- `DatabaseManager.get_sessao(id)` · `resumo.finalizar_sessao()` · `sessions.run(..., renderizar=False)`

### Changed
- Auditoria retroativa com os critérios v2: 388 sessões → **142 relevantes · 246 no arquivo morto** (48 `sem_obsidian` + 14 `poucas_interacoes` movidas nesta rodada)

---

## [0.1.0] — 2026-07-30

### Added
- Coletor `approvals` — extrai histórico de aprovações do Hermes Agent do `state.db`
- Coletor `hub` — gera `Lastro.md` como MOC central do grafo no Obsidian
- Detecção automática de timezone do UmbrelOS (5 níveis de fallback)
- Conversão de timestamps UTC → hora local nas notas
- Notas diárias em `aprovacoes/YYYY-MM-DD.md` com detalhes de cada aprovação
- Detecção de sessões YOLO (autorização em lote)
- Backlinks navegáveis entre notas (Histórico ↔ datas)
- CLI: `python3 -m lastro sync`, `status`, `list`
- `.env.example` com variáveis de ambiente documentadas
- `pyproject.toml` — metadados do pacote, setuptools, classificadores
- `CONTRIBUTING.md` com guia de contribuição
- `CHANGELOG.md` (este arquivo)
- GitHub Actions: workflow `build.yml` com lint (ruff) + type-check (mypy)
- Templates de Issue (bug report, feature request) e Pull Request
- Badges no README (Python version, licença)

### Changed
- `engine.py`: registro de coletores simplificado — hub inline no dict
- `README.md`: removida referência a `templates/` inexistente
- `cli.py`: type hints adicionados em `_print_result`

---

## [0.2.0] — 2026-09-17

### Added
- Coletor `sessions` — diário automático de sessões no vault (`📋 Sessões.md` + notas diárias)
- **Resumo final por sessão** via LLM local (Ollama, `qwen2.5:3b`) com fallback heurístico — gravado em `tb_sessao.resumo_final` (preservado entre syncs; manuais intocáveis)
- **Filtro de relevância** — sessões insignificantes (cron, testes/triviais) saem do diário e vão para o arquivo morto auditável `sessoes/🗄️ Sessões não relevantes.md`
- Comando `python3 -m lastro resumos [--continuo] [--refazer] [--limite N]`
- Coletor `server` — métricas do host (disco, RAM, CPU, docker)
- Coletor `cron` — cron jobs do Hermes (agenda e última execução)
- Coletor `erros` — padrões de erro detectados nas sessões
- Coletor `skills` — catálogo de skills com estatísticas de uso
- `config.yaml` — configuração centralizada (paths, timezone, coletores, resumo)
- `lastro.db` — banco SQLite persistente com schema versionado (`PRAGMA user_version`) e migrações automáticas
- CLI: comandos `query` (SQL read-only) e `stats`

### Changed
- `engine.py` — coletores recebem `db_path`; `sessions` gera/renderiza os resumos finais
- Schema do `lastro.db` **v2** — novas colunas: `resumo_final`, `resumo_origem`, `relevancia`, `motivo_nao_relevante`
- `vault.py` — suporte a remoção de notas (`remove`)

### Planned
- Decisões estruturadas por sessão (roadmap)
- Templates Jinja2 customizáveis

---

[0.1.0]: https://github.com/EmanuelXBT/Lastro/releases/tag/v0.1.0
[0.2.0]: https://github.com/EmanuelXBT/Lastro/releases/tag/v0.2.0
