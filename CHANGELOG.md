# Changelog

Todas as mudanças notáveis do Lastro são documentadas neste arquivo.

O formato segue [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/),
e o versionamento segue [Semantic Versioning](https://semver.org/lang/pt-BR/).

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

## [Unreleased]

### Planned
- Coletor `sessions` — diário automático de sessões
- Coletor `cron` — log de cron jobs executados
- Coletor `skills` — catálogo de skills instaladas
- Coletor `sistema` — métricas do Umbrel (disco, RAM, uptime)
- Templates Jinja2 customizáveis
- `config.yaml` para paths e preferências

---

[0.1.0]: https://github.com/EmanuelXBT/Lastro/releases/tag/v0.1.0
