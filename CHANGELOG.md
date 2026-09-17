# Changelog

Todas as mudanças notáveis do Lastro são documentadas neste arquivo.

O formato segue [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/),
e o versionamento segue [Semantic Versioning](https://semver.org/lang/pt-BR/).

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
