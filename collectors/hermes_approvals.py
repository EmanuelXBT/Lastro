"""
Lastro — collectors/hermes_approvals.py
========================================
Coletor de aprovações do Hermes Agent.

Extrai eventos de aprovação do state.db (terminal + clarify),
renderiza Historico_Aprovacoes.md e notas de data no vault Obsidian.
"""

import json
import re
import sqlite3
from collections import defaultdict
from datetime import datetime, timezone

from ..schemas import (
    ApprovalEvent,
    ApprovalStatus,
    CollectorResult,
    SessionInfo,
    SessionWideAuth,
)
from ..tz import get_local_tz_name, local_now
from ..vault import VaultManager

HISTORICO_FILENAME = "aprovacoes/Histórico de Aprovações.md"
HUB_FILENAME = "Lastro.md"
DATE_SUBFOLDER = "aprovacoes"

# ── Parsing ─────────────────────────────────────────────────────────

def _parse_terminal_approval(approval_str: str) -> tuple:
    if not approval_str:
        return ApprovalStatus.UNKNOWN, "Comando com aprovação", approval_str

    if 'rejected' in approval_str:
        status = ApprovalStatus.REJECTED
    elif 'denied' in approval_str:
        status = ApprovalStatus.DENIED
    elif 'timeout' in approval_str.lower():
        status = ApprovalStatus.TIMEOUT
    elif 'approved' in approval_str:
        status = ApprovalStatus.APPROVED
    else:
        status = ApprovalStatus.UNKNOWN

    m = re.match(
        r'Command required approval \((.+?)\) and was (?:approved|rejected|denied)',
        approval_str, re.DOTALL
    )
    risk_full = m.group(1).strip() if m else approval_str

    if 'Pipe to interpreter' in risk_full:
        summary = 'Pipe para interpretador'
    elif 'script execution' in risk_full:
        summary = 'Execução de script'
    elif 'recursive delete' in risk_full:
        summary = 'Remoção recursiva'
    elif 'kill' in risk_full.lower():
        summary = 'Kill de processo'
    elif 'git reset' in risk_full:
        summary = 'Git reset --hard'
    elif 'SQL DROP' in risk_full:
        summary = 'SQL DROP'
    elif 'overwrite system file' in risk_full:
        summary = 'Sobrescrita de arquivo de sistema'
    elif 'Archive extraction' in risk_full:
        summary = 'Extração de arquivo'
    elif 'Package has live OSV' in risk_full:
        summary = 'Pacote com vulnerabilidade OSV'
    elif 'delete in root path' in risk_full:
        summary = 'Remoção em path raiz'
    elif 'URL uses raw IP' in risk_full:
        summary = 'Acesso a IP raw'
    elif 'Schemeless URL' in risk_full:
        summary = 'URL sem scheme'
    elif 'Invalid characters in hostname' in risk_full:
        summary = 'Hostname inválido'
    else:
        summary = risk_full[:80]

    return status, summary, risk_full


def _extract_command(content_json: str) -> str:
    try:
        data = json.loads(content_json)
        cmd = data.get('command', '')
        if cmd:
            cmd = cmd.replace('\n', ' ').replace('\r', '').strip()
            return cmd[:120] + ('...' if len(cmd) > 120 else '')
    except (json.JSONDecodeError, TypeError):
        pass
    return ''


# ── Database loaders ────────────────────────────────────────────────

def _load_sessions(db_path: str) -> dict:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT id, title, source, started_at FROM sessions")
    sessions = {}
    for row in cursor.fetchall():
        started = None
        if row['started_at']:
            try:
                started = datetime.fromtimestamp(row['started_at'], tz=timezone.utc)
            except (TypeError, ValueError, OSError):
                pass
        sessions[row['id']] = SessionInfo(
            session_id=row['id'],
            title=row['title'] or '(sem título)',
            source=row['source'] or '?',
            started_at=started,
        )
    conn.close()
    return sessions


def _load_terminal_events(db_path: str) -> list:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("""
        SELECT m.id, m.session_id, m.timestamp, m.content
        FROM messages m
        WHERE m.tool_name = 'terminal'
          AND m.content LIKE '%"approval"%'
        ORDER BY m.timestamp ASC
    """)
    events = []
    for row in cursor.fetchall():
        try:
            data = json.loads(row['content'])
            approval_str = data.get('approval', '')
        except json.JSONDecodeError:
            match = re.search(r'"approval"\s*:\s*"((?:[^"\\]|\\.)*)"', row['content'])
            approval_str = match.group(1) if match else ''
        if not approval_str:
            continue
        status, summary, risk_full = _parse_terminal_approval(approval_str)
        command = _extract_command(row['content'])
        try:
            ts = datetime.fromtimestamp(row['timestamp'], tz=timezone.utc)
        except (TypeError, ValueError, OSError):
            ts = datetime.now(tz=timezone.utc)
        events.append(ApprovalEvent(
            event_id=row['id'], session_id=row['session_id'],
            timestamp=ts, status=status, risk_summary=summary,
            risk_full=risk_full, command=command, source='terminal',
        ))
    conn.close()
    return events


def _load_clarify_events(db_path: str) -> list:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("""
        SELECT m.id, m.session_id, m.role, m.content, m.timestamp
        FROM messages m
        WHERE (m.tool_name = 'clarify' OR m.tool_calls LIKE '%clarify%')
          AND m.role = 'tool'
        ORDER BY m.timestamp DESC
    """)
    auth_keywords = ['autoriz', 'approv', 'permiss', 'destrutiv',
                     'segurança', 'terminal', 'comando', 'yolo',
                     'execut', 'bloquead']
    events = []
    for row in cursor.fetchall():
        try:
            data = json.loads(row['content'])
        except json.JSONDecodeError:
            continue
        if not isinstance(data, dict):
            continue
        question = data.get('question', '')
        answer = data.get('answer', data.get('choice', ''))
        if not any(w in question.lower() for w in auth_keywords):
            continue
        answer_str = str(answer).lower()
        is_positive = any(w in answer_str for w in
                         ['sim', 'yes', 'autorizo', 'aprovo', 'ok', 'confirm'])
        is_negative = any(w in answer_str for w in
                         ['não', 'no', 'recuso', 'nego', 'cancel'])
        status = (ApprovalStatus.APPROVED if is_positive
                  else ApprovalStatus.REJECTED if is_negative
                  else ApprovalStatus.UNKNOWN)
        try:
            ts = datetime.fromtimestamp(row['timestamp'], tz=timezone.utc)
        except (TypeError, ValueError, OSError):
            ts = datetime.now(tz=timezone.utc)
        events.append(ApprovalEvent(
            event_id=row['id'], session_id=row['session_id'],
            timestamp=ts, status=status,
            risk_summary='Autorização de sessão (clarify)',
            risk_full=f"Pergunta: {question}\\nResposta: {answer}",
            command='', source='clarify',
        ))
    conn.close()
    return events


def _infer_clarify_status(clarify_events: list, terminal_events: list) -> list:
    for ce in clarify_events:
        if ce.status == ApprovalStatus.UNKNOWN:
            for te in terminal_events:
                if te.session_id == ce.session_id and te.timestamp > ce.timestamp:
                    ce.status = ApprovalStatus.APPROVED
                    ce.risk_summary = 'Autorização de sessão (clarify → aprovada)'
                    break
    return clarify_events


def _detect_session_wide(terminal_events: list, sessions: dict) -> list:
    by_session = defaultdict(list)
    for e in terminal_events:
        by_session[e.session_id].append(e)
    results = []
    for sid, sess_events in by_session.items():
        if len(sess_events) < 3:
            continue
        sess_events.sort(key=lambda x: x.timestamp)
        duration_min = (sess_events[-1].timestamp - sess_events[0].timestamp).total_seconds() / 60
        s = sessions.get(sid, SessionInfo(session_id=sid))
        results.append(SessionWideAuth(
            session_id=sid, session_title=s.title,
            date=sess_events[0].date, count=len(sess_events),
            duration_min=round(duration_min, 1),
            first_approval=sess_events[0].local_datetime_str,
            first_approval_time=sess_events[0].local_time_str,
        ))
    return results


# ── Collector interface ─────────────────────────────────────────────

def collect(state_db: str) -> tuple:
    sessions = _load_sessions(state_db)
    terminal_events = _load_terminal_events(state_db)
    clarify_events = _load_clarify_events(state_db)
    clarify_events = _infer_clarify_status(clarify_events, terminal_events)
    all_events = terminal_events + clarify_events
    all_events.sort(key=lambda x: x.timestamp)
    session_wide = _detect_session_wide(terminal_events, sessions)
    return all_events, sessions, session_wide


# ── Renderers ───────────────────────────────────────────────────────

def _render_historico(all_events: list, sessions: dict, wide_auths: list) -> str:
    by_month = defaultdict(list)
    for e in all_events:
        by_month[e.month_name].append(e)

    today = local_now().strftime('%Y-%m-%d')
    lines = [
        "---",
        "domínio: aprovacoes",
        "status: definitivo",
        "tags:",
        "  - aprovacoes/diario",
        "  - lastro",
        "  - historico",
        f"última_revisão: {today}",
        "---",
        "",
        "# 📋 Histórico de Aprovações — Hermes Agent", "",
        VaultManager.backlink(HUB_FILENAME.removesuffix(".md"), "← 🛰️ Hub Lastro"), "",
        "> Registro **automatizado** de comandos que exigiram aprovação do usuário.",
        f"> Última sincronização: {local_now().strftime('%Y-%m-%d %H:%M')} {get_local_tz_name()}",
        f"> Total: {len(all_events)} eventos de aprovação registrados", "",
        "---", "",
    ]

    by_session = defaultdict(list)
    for e in all_events:
        by_session[e.session_id].append(e)

    for month_name in sorted(by_month.keys(), reverse=True):
        month_events = by_month[month_name]
        lines.append(f"## {month_name}")
        lines.append("")

        month_by_project = defaultdict(list)
        for e in month_events:
            s = sessions.get(e.session_id, SessionInfo(session_id=e.session_id))
            title = s.title
            proj = title.split(' — ')[0] if ' — ' in title else (
                title.split(':')[0] if ':' in title else title)
            month_by_project[proj].append(e)

        for proj, proj_events in sorted(month_by_project.items()):
            lines.append(f"### 🔧 {proj}")
            lines.append("")
            lines.append("| Data | Hora | Comando/Ação | Status | Sessão |")
            lines.append("|---|---|---|---|---|")
            for e in sorted(proj_events, key=lambda x: x.timestamp):
                date_link = VaultManager.wikilink(f"{DATE_SUBFOLDER}/{e.date}", e.date)
                s = sessions.get(e.session_id, SessionInfo(session_id=e.session_id))
                lines.append(
                    f"| {date_link} | {e.local_time_str} "
                    f"| {e.risk_summary[:80]} "
                    f"| {e.status.emoji} {e.status.label} | `{s.short_id}` |"
                )
            lines.append("")
        lines.append("---")
        lines.append("")

    lines.extend([
        "## 📊 Resumo", "",
        "| Mês | ✅ Aprovados | ❌ Recusados | ⏰ Timeout |",
        "|---|---|---|---|",
    ])
    for month_name in sorted(by_month.keys()):
        month_events = by_month[month_name]
        approved = sum(1 for e in month_events if e.status == ApprovalStatus.APPROVED)
        rejected = sum(1 for e in month_events
                      if e.status in (ApprovalStatus.REJECTED, ApprovalStatus.DENIED))
        timeout = sum(1 for e in month_events if e.status == ApprovalStatus.TIMEOUT)
        lines.append(f"| {month_name} | {approved} | {rejected} | {timeout} |")
    lines.append("")

    if wide_auths:
        lines.extend([
            "## 🔓 Sessões com Autorização em Lote", "",
            ("> Sessões onde múltiplos comandos foram autorizados em sequência "
             "(possível YOLO / aprovação para sessão inteira)."), "",
            "| Data | Hora | Sessão | Comandos | Duração |",
            "|---|---|---|---|---|",
        ])
        for sw in sorted(wide_auths, key=lambda x: x.date, reverse=True):
            lines.append(
                f"| {VaultManager.wikilink(f'{DATE_SUBFOLDER}/{sw.date}', sw.date)} | {sw.first_approval_time} "
                f"| {sw.session_title} "
                f"| {sw.count} | {sw.duration_min} min |"
            )
        lines.append("")

    lines.extend([
        "---", "",
        "> **Fonte:** `state.db` → `messages` (terminal + clarify)",
        "> **Sistema:** Lastro — organização para a era da IA",
        "> IDs de sessão podem ser consultados via `session_search(session_id=\"...\")`.", "",
    ])
    return "\n".join(lines)


def _render_date_note(date_str: str, events: list, sessions: dict,
                      wide_auths: list) -> str:
    lines = ["---",
             "domínio: aprovacoes",
             "status: definitivo",
             "tags:",
             "  - aprovacoes/diario",
             "  - lastro",
             f"última_revisão: {date_str}",
             "---",
             "",
             f"# 📅 {date_str}", "",
             "> Registro de aprovações do Hermes Agent nesta data.", ""]

    sw_on_date = [sw for sw in wide_auths if sw.date == date_str]
    if sw_on_date:
        lines.append("## 🔓 Autorizações de Sessão")
        lines.append("")
        for sw in sw_on_date:
            lines.append(
                f"- **{sw.session_title}** — {sw.count} comandos "
                f"autorizados em {sw.duration_min} min "
                f"(sessão `{sw.session_id}`)"
            )
        lines.append("")

    terminal = [e for e in events if e.source == 'terminal']
    clarify = [e for e in events if e.source == 'clarify']

    if terminal:
        lines.extend(["## 🖥️ Comandos de Terminal", "",
                      "| # | Sessão | Risco | Status |",
                      "|---|---|---|---|"])
        for i, e in enumerate(terminal, 1):
            s = sessions.get(e.session_id, SessionInfo(session_id=e.session_id))
            risk = e.risk_summary.replace('|', '\\|')
            lines.append(
                f"| {i} | {s.title} | {risk} "
                f"| {e.status.emoji} {e.status.label} |"
            )
        lines.append("")
        lines.append("### Detalhes")
        lines.append("")
        for i, e in enumerate(terminal, 1):
            s = sessions.get(e.session_id, SessionInfo(session_id=e.session_id))
            lines.extend([
                f"#### {i}. {e.status.emoji} {e.risk_summary}", "",
                f"- **Sessão:** {s.title} (`{e.session_id}`)",
            ])
            if e.command:
                lines.append(f"- **Comando:** `{e.command}`")
            lines.extend([
                f"- **Horário:** {e.local_datetime_str} {get_local_tz_name()}",
                f"- **Fonte:** {e.source}", "",
                "```", e.risk_full, "```", "",
            ])

    if clarify:
        lines.append("## 🔐 Autorizações de Sessão")
        lines.append("")
        for e in clarify:
            lines.extend([
                f"### {e.status.emoji} {e.risk_summary}", "",
                f"- **Sessão:** `{e.session_id}`",
                f"- **Horário:** {e.local_datetime_str} {get_local_tz_name()}", "",
                "```", e.risk_full, "```", "",
            ])

    lines.extend(["---", VaultManager.backlink(HISTORICO_FILENAME, "← Histórico de Aprovações"), ""])
    return "\n".join(lines)


def render(all_events: list, sessions: dict, wide_auths: list) -> dict:
    files = {HISTORICO_FILENAME: _render_historico(all_events, sessions, wide_auths)}
    by_date = defaultdict(list)
    for e in all_events:
        by_date[e.date].append(e)
    for date_str, date_events in sorted(by_date.items()):
        files[f"{DATE_SUBFOLDER}/{date_str}.md"] = _render_date_note(date_str, date_events, sessions, wide_auths)
    return files


# ── Entry point ─────────────────────────────────────────────────────

def run(state_db: str, vault_path: str) -> CollectorResult:
    vault = VaultManager(vault_path)
    errors = []
    try:
        all_events, sessions, wide_auths = collect(state_db)
    except Exception as e:
        return CollectorResult(
            collector_name="hermes_approvals", files_written={},
            events_processed=0, errors=[f"Falha ao coletar eventos: {e}"],
        )
    try:
        files = render(all_events, sessions, wide_auths)
    except Exception as e:
        return CollectorResult(
            collector_name="hermes_approvals", files_written={},
            events_processed=len(all_events),
            errors=[f"Falha ao renderizar markdown: {e}"],
        )
    written = {}
    for filename, content in files.items():
        try:
            vault.write(filename, content)
            written[filename] = f"{len(content)} bytes"
        except Exception as e:
            errors.append(f"Falha ao escrever {filename}: {e}")
    return CollectorResult(
        collector_name="hermes_approvals", files_written=written,
        events_processed=len(all_events), errors=errors,
    )
