"""
Lastro — collectors/hub.py
==========================
Coletor do hub central — gera e mantém `Lastro.md`, o nó MOC
(Map of Content) que organiza tudo que o pipeline produz no grafo
do Obsidian.

Diferente dos demais coletores, o hub é **vault-driven**: não lê o
state.db. Ele varre o vault (aprovacoes/, notas mestras) e monta o
índice navegável com wikilinks e âncoras de seção.

Deve rodar POR ÚLTIMO no engine, após os coletores de dados, para
enxergar os arquivos recém-gerados.
"""

import os
import re

from ..schemas import CollectorResult
from ..vault import VaultManager
from ..tz import get_local_tz_name, local_now

HUB_FILENAME = "Lastro.md"
HUB_TITLE = "🛰️ Lastro"
DATE_SUBFOLDER = "aprovacoes"
HISTORICO_FILENAME = "Historico_Aprovacoes.md"
RECENT_DATES_LIMIT = 7

# Nota mestra do harness e suas âncoras de seção.
# Se a nota for renomeada/reestruturada, ajustar aqui.
HARNESS_NOTE = "⚙️ Hermes Harness — SOUL · Skills · Runtime"
HARNESS_SECTIONS = [
    ("🧬 SOUL — Identidade", "🧬 SOUL — identidade do agente"),
    ("🧰 SKILLS — Conhecimento Procedural (51)", "🧰 Skills — conhecimento procedural"),
    ("⚡ HARNESS — Runtime", "⚡ Harness — runtime e capacidades"),
]


def _list_date_notes(vault: VaultManager) -> list[str]:
    """Lista datas (YYYY-MM-DD) com notas em aprovacoes/, mais recentes primeiro."""
    folder = vault.note_path(DATE_SUBFOLDER)
    if not os.path.isdir(folder):
        return []
    dates = []
    for fname in os.listdir(folder):
        m = re.match(r"^(\d{4}-\d{2}-\d{2})\.md$", fname)
        if m:
            dates.append(m.group(1))
    return sorted(dates, reverse=True)


def _render_hub(vault: VaultManager, collectors: list[str]) -> tuple[str, list[str]]:
    """Renderiza o conteúdo do hub. Retorna (markdown, warnings)."""
    warnings = []
    now = local_now()
    tz_name = get_local_tz_name()

    date_notes = _list_date_notes(vault)
    recent = date_notes[:RECENT_DATES_LIMIT]

    # Verifica se as notas mestras existem — links quebrados silenciosos
    # são o pior cenário num hub de navegação.
    if not vault.exists(HISTORICO_FILENAME):
        warnings.append(f"Nota mestra ausente: {HISTORICO_FILENAME}")
    if not vault.exists(f"{HARNESS_NOTE}.md"):
        warnings.append(f"Nota do harness ausente: {HARNESS_NOTE}.md")

    lines = [
        "---",
        "tags: [moc, hub, lastro]",
        "---",
        "",
        f"# {HUB_TITLE}",
        "",
        "> **Hub central do pipeline** Hermes → Obsidian.",
        "> Tudo que o Lastro coleta, organiza e mantém parte deste nó.",
        "",
        "---",
        "",
        "## ✅ Aprovações do Hermes",
        "",
    ]

    if vault.exists(HISTORICO_FILENAME):
        historico_target = HISTORICO_FILENAME.removesuffix(".md")
        lines.append(
            f"- {VaultManager.wikilink(historico_target, '📋 Histórico de Aprovações')}"
            " — registro completo por mês e projeto"
        )
    if date_notes:
        lines.append(
            f"- 📅 **{len(date_notes)} dias** com registros em `{DATE_SUBFOLDER}/`"
        )
    if recent:
        lines.extend(["", "### Últimos registros", ""])
        for d in recent:
            lines.append(f"- {VaultManager.wikilink(f'{DATE_SUBFOLDER}/{d}', d)}")
    lines.append("")

    lines.extend([
        "---",
        "",
        "## ⚙️ Hermes Harness",
        "",
        "> Identidade, conhecimento procedural e runtime do agente —",
        "> documentados na nota mestra abaixo.",
        "",
        f"- {VaultManager.wikilink(HARNESS_NOTE)}",
    ])
    for anchor, alias in HARNESS_SECTIONS:
        lines.append(
            f"  - {VaultManager.wikilink(f'{HARNESS_NOTE}#{anchor}', alias)}"
        )
    lines.append("")

    lines.extend([
        "---",
        "",
        "## 🔧 Pipeline",
        "",
        "| Componente | Valor |",
        "|---|---|",
        "| Fonte de dados | `state.db` (SQLite) |",
        f"| Coletores ativos | {', '.join(f'`{c}`' for c in collectors)} |",
        "| Frequência | a cada 6h via cron |",
        f"| Timezone | `{tz_name}` |",
        f"| Último sync | {now.strftime('%Y-%m-%d %H:%M')} {tz_name} |",
        "",
        "---",
        "",
        "> **Sistema:** Lastro — organização para a era da IA.",
        "> Este hub é **regenerado a cada sync** — edições manuais serão perdidas.",
        "",
    ])
    return "\n".join(lines), warnings


def run(state_db: str, vault_path: str, collectors: list[str] = None) -> CollectorResult:
    """Gera o hub central `Lastro.md` no vault."""
    vault = VaultManager(vault_path)
    errors = []
    try:
        content, warnings = _render_hub(vault, collectors or [])
        errors.extend(warnings)
    except Exception as e:
        return CollectorResult(
            collector_name="hub", files_written={},
            events_processed=0, errors=[f"Falha ao renderizar hub: {e}"],
        )
    try:
        vault.write(HUB_FILENAME, content)
    except Exception as e:
        errors.append(f"Falha ao escrever {HUB_FILENAME}: {e}")
    return CollectorResult(
        collector_name="hub",
        files_written={HUB_FILENAME: f"{len(content)} bytes"},
        events_processed=1,
        errors=errors,
    )
