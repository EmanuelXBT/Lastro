"""
Lastro — collectors/sessions.py
================================
Coletor de sessões do Hermes Agent.

Extrai metadados das sessões do state.db e gera:
  - sessoes/📋 Sessões.md                 — índice mestre por mês (só relevantes)
  - sessoes/YYYY-MM-DD.md                 — notas diárias com detalhes (só relevantes)
  - sessoes/🗄️ Sessões não relevantes.md — arquivo morto auditável

Cada sessão inclui: título, fonte, duração, ferramentas usadas, aprovações,
erros, primeira mensagem do usuário (contexto) e o resumo final (IA local).

Filtro de relevância (decidido pelo usuário em 2026-09):
  - automacao_cron: sessões originadas de cron (sync, lembretes, watchdog)
  - teste_trivial:  títulos tipo "teste"/"?" com pouquíssimas mensagens e
    sem ferramentas, ou sessões vazias (≤2 mensagens, 0 ferramentas)
Sessões não relevantes não entram no diário — vão para o arquivo morto.

O resumo final é gerado pelo módulo resumo.py (Ollama local + fallback
heurístico) e gravado em tb_sessao.resumo_final — preservado entre syncs.
"""

from __future__ import annotations

import os
import re
import sqlite3
from collections import defaultdict
from datetime import datetime, timezone
from typing import Optional

from ..config import ResumoConfig
from ..sanitize import sanitize
from ..schemas import CollectorResult, SessionSummary
from ..tz import get_local_tz_name, local_now
from ..vault import VaultManager

INDEX_FILENAME = "sessoes/📋 Sessões.md"
ARQUIVO_FILENAME = "sessoes/🗄️ Sessões não relevantes.md"
DATE_SUBFOLDER = "sessoes"

# Títulos triviais (case-insensitive, match completo): "teste", "oi", "?", ...
_TITULO_TRIVIAL_RE = re.compile(r"(teste|test|oi|ol[aá]|\?+|\.+)", re.IGNORECASE)

# Rótulos legíveis dos motivos de não relevância
MOTIVO_LABEL: dict[str, str] = {
    "automacao_cron": "automação (cron)",
    "teste_trivial": "teste/trivial",
}

# ── Database loaders ────────────────────────────────────────────────

def _load_sessions(db_path: str) -> list[SessionSummary]:
    """Carrega todas as sessões do state.db com metadados pré-agregados."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute("""
        SELECT id, title, source, started_at, ended_at,
               message_count, tool_call_count, model,
               input_tokens, output_tokens, actual_cost_usd
        FROM sessions
        ORDER BY started_at DESC
    """)

    sessions: list[SessionSummary] = []
    for row in cursor.fetchall():
        started = None
        ended = None
        if row["started_at"]:
            try:
                started = datetime.fromtimestamp(row["started_at"], tz=timezone.utc)
            except (TypeError, ValueError, OSError):
                pass
        if row["ended_at"]:
            try:
                ended = datetime.fromtimestamp(row["ended_at"], tz=timezone.utc)
            except (TypeError, ValueError, OSError):
                pass

        sessions.append(SessionSummary(
            session_id=row["id"],
            title=row["title"] or "(sem título)",
            source=row["source"] or "?",
            started_at=started,
            ended_at=ended,
            message_count=row["message_count"] or 0,
            tool_call_count=row["tool_call_count"] or 0,
            model=row["model"] or "",
            tokens_in=row["input_tokens"] or 0,
            tokens_out=row["output_tokens"] or 0,
            cost_usd=row["actual_cost_usd"] or 0.0,
        ))
    conn.close()
    return sessions


def _enrich_sessions(sessions: list[SessionSummary], db_path: str) -> None:
    """Enriquece sessões com dados que exigem query nas mensagens."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    # First user message per session
    cursor = conn.execute("""
        SELECT m.session_id, m.content
        FROM messages m
        WHERE m.role = 'user'
          AND m.id IN (
              SELECT MIN(m2.id) FROM messages m2
              WHERE m2.session_id = m.session_id AND m2.role = 'user'
              GROUP BY m2.session_id
          )
    """)
    first_msgs: dict[str, str] = {}
    for row in cursor:
        content = row["content"] or ""
        first_msgs[row["session_id"]] = sanitize(content)[:200]

    # Tools used per session
    cursor = conn.execute("""
        SELECT session_id, tool_name, COUNT(*) as cnt
        FROM messages
        WHERE tool_name IS NOT NULL
        GROUP BY session_id, tool_name
        ORDER BY session_id, cnt DESC
    """)
    tools_map: dict[str, list[str]] = defaultdict(list)
    for row in cursor:
        if len(tools_map[row["session_id"]]) < 8:
            tools_map[row["session_id"]].append(row["tool_name"])

    # Approval count per session (matches hermes_approvals collector)
    cursor = conn.execute("""
        SELECT session_id, COUNT(*) as cnt
        FROM messages
        WHERE tool_name = 'terminal'
          AND content LIKE '%"approval"%'
        GROUP BY session_id
    """)
    approval_counts: dict[str, int] = {}
    for row in cursor:
        approval_counts[row["session_id"]] = row["cnt"]

    # Error count per session (terminal non-zero exit + exceptions)
    cursor = conn.execute("""
        SELECT session_id, COUNT(*) as cnt
        FROM messages
        WHERE tool_name = 'terminal'
          AND (content LIKE '%"exit_code": 1%'
               OR content LIKE '%"exit_code": 2%'
               OR content LIKE '%Exception%'
               OR content LIKE '%Traceback%')
          AND content NOT LIKE '%"exit_code": 0%'
        GROUP BY session_id
    """)
    error_counts: dict[str, int] = {}
    for row in cursor:
        error_counts[row["session_id"]] = row["cnt"]

    conn.close()

    # Apply enrichment
    for s in sessions:
        sid = s.session_id
        s.first_user_msg = first_msgs.get(sid, "")
        s.tools_used = tools_map.get(sid, [])
        s.approval_count = approval_counts.get(sid, 0)
        s.error_count = error_counts.get(sid, 0)


# ── Filtro de relevância ────────────────────────────────────────────

def _classificar_relevancia(s: SessionSummary) -> tuple[str, Optional[str]]:
    """Classifica a sessão como relevante ou não (filtro do diário).

    Retorna (relevancia, motivo): ('relevante', None) ou
    ('nao_relevante', 'automacao_cron' | 'teste_trivial').
    """
    if s.source == "cron":
        return "nao_relevante", "automacao_cron"

    tl = (s.title or "").strip().lower()
    trivial = bool(_TITULO_TRIVIAL_RE.fullmatch(tl))
    if (s.message_count <= 2 and s.tool_call_count == 0) or \
       (trivial and s.message_count <= 4 and s.tool_call_count <= 1):
        return "nao_relevante", "teste_trivial"
    return "relevante", None


# ── Renderers ───────────────────────────────────────────────────────

def _render_index(sessions: list[SessionSummary], total: int,
                  arquivadas: int) -> str:
    """Renderiza o índice mestre de sessões (apenas relevantes)."""
    by_month: dict[str, list[SessionSummary]] = defaultdict(list)
    for s in sessions:
        by_month[s.month_name].append(s)

    today = local_now().strftime("%Y-%m-%d")
    arquivo_link = VaultManager.wikilink(ARQUIVO_FILENAME.removesuffix(".md"))
    lines = [
        "---",
        "domínio: sistema",
        "status: definitivo",
        "tags:",
        "  - sessoes",
        "  - Lastro",
        "  - diario",
        f"última_revisão: {today}",
        "---",
        "",
        "# 📋 Diário de Sessões — Hermes Agent",
        "",
        VaultManager.backlink("Sistema/Lastro", "← 🛰️ Hub Lastro"),
        "",
        "> Registro **automatizado** das sessões do Hermes Agent.",
        f"> Última sincronização: {local_now().strftime('%Y-%m-%d %H:%M')} {get_local_tz_name()}",
        f"> Total: {total} sessões registradas · {arquivadas} arquivadas (não relevantes)",
        "",
        "---",
        "",
    ]

    # Stats summary
    total_msgs = sum(s.message_count for s in sessions)
    total_tools = sum(s.tool_call_count for s in sessions)
    total_cost = sum(s.cost_usd for s in sessions)

    lines.extend([
        "## 📊 Estatísticas",
        "",
        "| Métrica | Valor |",
        "|---|---|",
        f"| Sessões no diário | {len(sessions)} |",
        f"| Arquivadas (não relevantes) | {arquivadas} |",
        f"| Mensagens | {total_msgs:,} |".replace(",", "."),
        f"| Chamadas de ferramenta | {total_tools:,} |".replace(",", "."),
        f"| Sessões com erro | {sum(1 for s in sessions if s.error_count > 0)} |",
        f"| Custo estimado | ${total_cost:.4f} |",
        "",
        "---",
        "",
    ])

    # Per-month index
    for month_name in sorted(by_month.keys(), reverse=True):
        month_sessions = by_month[month_name]
        lines.append(f"## {month_name}")
        lines.append("")
        lines.append("| Data | Hora | Sessão | Msgs | Ferramentas | ⚠️ |")
        lines.append("|---|---|---|---|---|---|")
        for s in sorted(month_sessions,
                        key=lambda x: x.started_at or datetime.min.replace(tzinfo=timezone.utc),
                        reverse=True):
            date_link = VaultManager.wikilink(f"{DATE_SUBFOLDER}/{s.date}")
            tools_str = ", ".join(s.tools_used[:4])
            if len(s.tools_used) > 4:
                tools_str += f" +{len(s.tools_used) - 4}"
            error_icon = f" {s.error_count}⚠️" if s.error_count > 0 else ""
            lines.append(
                f"| {date_link} | {s.local_time_str} "
                f"| {s.title[:60]} "
                f"| {s.message_count} "
                f"| {tools_str} "
                f"| {error_icon} |"
            )
        lines.append("")

    lines.extend([
        "---",
        "",
        f"> 🗄️ Fora do diário: {arquivadas} sessão(ões) insignificante(s) — ver {arquivo_link}",
        "> **Fonte:** `state.db` → `sessions` + `messages`",
        "> **Sistema:** Lastro — organização para a era da IA",
        "",
    ])
    return "\n".join(lines)


def _render_date_note(date_str: str, sessions: list[SessionSummary]) -> str:
    """Renderiza nota diária com detalhes das sessões da data."""
    lines = [
        "---",
        "domínio: sistema",
        "status: definitivo",
        "tags:",
        "  - sessoes",
        "  - Lastro",
        f"última_revisão: {date_str}",
        "---",
        "",
        f"# 📅 Sessões de {date_str}",
        "",
        VaultManager.backlink(INDEX_FILENAME.removesuffix(".md"), "← 📋 Diário de Sessões"),
        "",
        f"> **{len(sessions)} sessão(ões)** iniciada(s) nesta data.",
        "",
        "---",
        "",
    ]

    for i, s in enumerate(sessions, 1):
        # Session header
        lines.extend([
            f"## {i}. {s.title}",
            "",
            "| Campo | Valor |",
            "|---|---|",
            f"| ID | `{s.short_id}` |",
            f"| Fonte | {s.source} |",
            f"| Modelo | {s.model} |",
            f"| Duração | {s.duration_min:.0f} min |",
            f"| Mensagens | {s.message_count} |",
            f"| Chamadas de ferramenta | {s.tool_call_count} |",
            f"| Tokens | {s.tokens_in:,} in / {s.tokens_out:,} out |".replace(",", "."),
        ])
        if s.cost_usd > 0:
            lines.append(f"| Custo | ${s.cost_usd:.4f} |")
        lines.append("")

        # First user message (context)
        if s.first_user_msg:
            lines.extend([
                "**Contexto inicial:**",
                "",
                f"> {s.first_user_msg}",
                "",
            ])

        # Final summary (IA local / heurística / manual)
        if s.resumo_final:
            rotulo = {
                "auto": "IA local",
                "heuristica": "heurística",
                "manual": "manual",
            }.get(s.resumo_origem, "IA local")
            resumo = " ".join(s.resumo_final.split())
            lines.extend([
                f"**Resumo final** *({rotulo})*:",
                "",
                f"> {resumo}",
                "",
            ])

        # Tools used
        if s.tools_used:
            lines.extend([
                f"**Ferramentas:** {', '.join(f'`{t}`' for t in s.tools_used)}",
                "",
            ])

        # Alerts
        alerts = []
        if s.error_count > 0:
            alerts.append(f"⚠️ **{s.error_count} erro(s)** detectado(s)")
        if s.approval_count > 0:
            alerts.append(f"🔐 **{s.approval_count} aprovação(ões)** de terminal")
        if alerts:
            lines.append(" | ".join(alerts))
            lines.append("")

        lines.append("---")
        lines.append("")

    return "\n".join(lines)


def _render_arquivo(arquivadas: list[SessionSummary], total: int) -> str:
    """Renderiza o arquivo morto das sessões não relevantes (auditável)."""
    today = local_now().strftime("%Y-%m-%d")
    por_motivo: dict[str, int] = defaultdict(int)
    for s in arquivadas:
        por_motivo[s.motivo_nao_relevante or "?"] += 1

    lines = [
        "---",
        "domínio: sistema",
        "status: definitivo",
        "tags:",
        "  - sessoes",
        "  - Lastro",
        "  - arquivo-morto",
        f"última_revisão: {today}",
        "---",
        "",
        "# 🗄️ Sessões não relevantes",
        "",
        VaultManager.backlink(INDEX_FILENAME.removesuffix(".md"), "← 📋 Diário de Sessões"),
        "",
        "> Arquivo morto: sessões detectadas como **insignificantes** pelo filtro de",
        "> relevância do Lastro. Não entram no diário — ficam registradas aqui para",
        "> auditoria (dados completos no `lastro.db`, tabela `tb_sessao`).",
        "",
        f"> Total auditado: **{total}** · Arquivadas: **{len(arquivadas)}**",
        "",
        "| Motivo | Sessões |",
        "|---|---|",
    ]
    for mot, cnt in sorted(por_motivo.items()):
        lines.append(f"| {MOTIVO_LABEL.get(mot, mot)} | {cnt} |")

    lines.extend([
        "",
        "---",
        "",
        "| Data | Hora | Título | Fonte | Motivo | Msgs |",
        "|---|---|---|---|---|---|",
    ])
    for s in sorted(arquivadas,
                    key=lambda x: x.started_at or datetime.min.replace(tzinfo=timezone.utc),
                    reverse=True):
        titulo = " ".join((s.title or "").split()).replace("|", "/")[:70]
        fonte = (s.source or "?").replace("|", "/")
        motivo = MOTIVO_LABEL.get(s.motivo_nao_relevante or "", s.motivo_nao_relevante or "")
        lines.append(
            f"| {s.date} | {s.local_time_str} | {titulo} | {fonte} | {motivo} | {s.message_count} |"
        )

    lines.extend([
        "",
        "---",
        "",
        "> **Fonte:** `state.db` → `sessions` · **Sistema:** Lastro",
        "",
    ])
    return "\n".join(lines)


def _notas_diarias_orfas(vault: VaultManager, datas_ativas: set) -> list[str]:
    """Notas diárias (YYYY-MM-DD.md) que ficaram sem sessões relevantes."""
    folder = vault.note_path(DATE_SUBFOLDER)
    if not os.path.isdir(folder):
        return []
    orfas: list[str] = []
    for name in sorted(os.listdir(folder)):
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}\.md", name) and name[:-3] not in datas_ativas:
            orfas.append(name)
    return orfas


# ── Entry point ─────────────────────────────────────────────────────

def run(state_db: str, vault_path: str,
        db_path: str = "",
        resumo_cfg: Optional[ResumoConfig] = None) -> CollectorResult:
    """Coleta sessões, gera resumos finais (IA local), filtra relevância e renderiza.

    Renderiza: índice (só relevantes), notas diárias (só relevantes) e o
    arquivo morto das sessões não relevantes. Notas diárias que ficarem sem
    sessões relevantes são removidas (o registro vai para o arquivo morto).
    """
    vault = VaultManager(vault_path)
    errors: list[str] = []

    try:
        sessions = _load_sessions(state_db)
    except Exception as e:
        return CollectorResult(
            collector_name="sessions",
            files_written={},
            events_processed=0,
            errors=[f"Falha ao carregar sessões: {e}"],
        )

    try:
        _enrich_sessions(sessions, state_db)
    except Exception as e:
        errors.append(f"Falha ao enriquecer sessões: {e}")

    # Filtro de relevância
    for s in sessions:
        s.relevancia, s.motivo_nao_relevante = _classificar_relevancia(s)

    relevantes = [s for s in sessions if s.relevancia == "relevante"]
    arquivadas = [s for s in sessions if s.relevancia != "relevante"]

    # Persistência no lastro.db + resumos finais (IA local)
    resumos_map: dict[str, dict] = {}
    if db_path:
        try:
            from ..db import DatabaseManager
            db = DatabaseManager(db_path)
            db.upsert_sessoes(sessions)

            if resumo_cfg is not None and resumo_cfg.ativo and resumo_cfg.limite_por_sync > 0:
                from ..resumo import processar_resumos
                stats = processar_resumos(state_db, db_path, resumo_cfg,
                                          limite=resumo_cfg.limite_por_sync)
                if stats["falhas"]:
                    errors.append(f"Resumos: {stats['falhas']} falha(s) na geração")

            resumos_map = db.get_resumos()
        except Exception as e:
            errors.append(f"Falha ao gravar sessões no lastro.db: {e}")

    for s in sessions:
        r = resumos_map.get(s.session_id)
        if r:
            s.resumo_final = r.get("resumo_final") or ""
            s.resumo_origem = r.get("resumo_origem") or ""

    written: dict[str, str] = {}

    # Index file (apenas relevantes)
    try:
        index_content = _render_index(relevantes, total=len(sessions),
                                      arquivadas=len(arquivadas))
        vault.write(INDEX_FILENAME, index_content)
        written[INDEX_FILENAME] = f"{len(index_content)} bytes"
    except Exception as e:
        errors.append(f"Falha ao renderizar índice: {e}")

    # Date notes (apenas relevantes)
    by_date: dict[str, list[SessionSummary]] = defaultdict(list)
    for s in relevantes:
        by_date[s.date].append(s)

    for date_str, date_sessions in sorted(by_date.items()):
        try:
            content = _render_date_note(date_str, date_sessions)
            filename = f"{DATE_SUBFOLDER}/{date_str}.md"
            vault.write(filename, content)
            written[filename] = f"{len(content)} bytes"
        except Exception as e:
            errors.append(f"Falha ao renderizar {date_str}: {e}")

    # Limpeza: notas diárias que ficaram apenas com sessões não relevantes
    try:
        orfas = _notas_diarias_orfas(vault, set(by_date.keys()))
        removidas = 0
        for name in orfas:
            if vault.remove(f"{DATE_SUBFOLDER}/{name}"):
                removidas += 1
        if removidas:
            written["sessoes/(limpeza)"] = f"{removidas} nota(s) diária(s) removida(s)"
    except Exception as e:
        errors.append(f"Falha na limpeza de notas diárias: {e}")

    # Arquivo morto (não relevantes)
    try:
        arq_content = _render_arquivo(arquivadas, total=len(sessions))
        vault.write(ARQUIVO_FILENAME, arq_content)
        written[ARQUIVO_FILENAME] = f"{len(arq_content)} bytes"
    except Exception as e:
        errors.append(f"Falha ao renderizar arquivo morto: {e}")

    return CollectorResult(
        collector_name="sessions",
        files_written=written,
        events_processed=len(sessions),
        errors=errors,
    )
