"""
Lastro — collectors/cron.py
============================
Coletor de estado dos cron jobs do Hermes Agent.

Executa `hermes cron list` e parseia a saída estruturada.
Coleta: job_id, nome, schedule, status, last_run, last_status.

Saída no vault:
  - Sistema/Cron Jobs.md — tabela de status
  - tb_cron_execucao no lastro.db — histórico
"""

from __future__ import annotations

import re
import subprocess

from ..schemas import CollectorResult
from ..tz import get_local_tz_name, local_now
from ..vault import VaultManager

CRON_FILENAME = "Sistema/Cron Jobs.md"
HERMES_BIN = "/opt/hermes/bin/hermes"


def _parse_cron_output(text: str) -> list[dict]:
    """Parseia a saída de `hermes cron list` em lista de dicionários."""
    jobs: list[dict] = []
    current: dict = {}

    for line in text.split("\n"):
        line = line.strip()
        if not line:
            continue

        # New job: starts with job_id [status]
        m = re.match(r"^([a-f0-9]{10,})\s+\[(\w+)\]", line)
        if m:
            if current:
                jobs.append(current)
            current = {
                "job_id": m.group(1),
                "status": m.group(2),
                "nome": "",
                "schedule": "",
                "next_run": "",
                "last_run": "",
                "last_status": "",
                "last_error": "",
            }
            continue

        # Key-value lines
        m = re.match(r"^\s*(\w[\w\s]*?):\s*(.*)", line)
        if m and current:
            key = m.group(1).strip().lower().replace(" ", "_")
            val = m.group(2).strip()
            if key == "name":
                current["nome"] = val
            elif key == "schedule":
                current["schedule"] = val
            elif key == "next_run":
                current["next_run"] = val
            elif key == "last_run":
                # Pode ter "ok" ou "error" depois
                parts = val.split(None, 1)
                current["last_run"] = parts[0] if parts else val
                if len(parts) > 1 and parts[1].startswith("ok"):
                    current["last_status"] = "ok"
                elif len(parts) > 1 and parts[1].startswith("error"):
                    current["last_status"] = "failed"
            elif key == "last_status":
                current["last_status"] = val

        # Error line
        m = re.match(r"^\s*Execution:\s*(failed|completed)\s+", line)
        if m and current:
            current["last_status"] = "ok" if m.group(1) == "completed" else "failed"

        # Error details
        m = re.match(r"^\s*error:\s*(.*)", line, re.IGNORECASE)
        if m and current:
            current["last_error"] = m.group(1)[:500]

    if current:
        jobs.append(current)

    return jobs


def _render_cron(jobs: list[dict]) -> str:
    """Renderiza nota de status dos cron jobs."""
    now = local_now()
    tz = get_local_tz_name()
    lines = [
        "---",
        "domínio: sistema",
        "status: definitivo",
        "tags:",
        "  - cron",
        "  - Lastro",
        f"última_revisão: {now.strftime('%Y-%m-%d')}",
        "---",
        "",
        "# ⏰ Cron Jobs — Hermes Agent",
        "",
        VaultManager.backlink("Sistema/Lastro", "← 🛰️ Hub Lastro"),
        "",
        f"> Snapshot automático — {now.strftime('%Y-%m-%d %H:%M')} {tz}",
        f"> Total: {len(jobs)} jobs configurados",
        "",
        "| Job | Schedule | Status | Última execução | Resultado |",
        "|---|---|---|---|---|",
    ]

    for j in jobs:
        name = j.get("nome", j.get("job_id", "?"))[:40]
        schedule = j.get("schedule", "?")
        status = j.get("status", "?")
        last_run = j.get("last_run", "?")[:19]
        last_status = j.get("last_status", "?")
        icon = "✅" if last_status == "ok" else "❌" if last_status == "failed" else "⏳"

        lines.append(
            f"| {name} | {schedule} | {status} "
            f"| {last_run} | {icon} {last_status} |"
        )

    lines.append("")

    # Detalhes de jobs com erro
    errored = [j for j in jobs if j.get("last_error")]
    if errored:
        lines.append("## ⚠️ Jobs com Erro")
        lines.append("")
        for j in errored:
            lines.extend([
                f"### {j.get('nome', j['job_id'])}",
                "",
                f"> {j['last_error'][:300]}",
                "",
            ])

    lines.extend([
        "---",
        "",
        "> **Sistema:** Lastro — organização para a era da IA",
        "> **Fonte:** `hermes cron list`",
    ])
    return "\n".join(lines)


def run(state_db: str, vault_path: str,
        db_path: str = "") -> CollectorResult:
    """Coleta estado dos cron jobs e renderiza status."""
    vault = VaultManager(vault_path)
    errors: list[str] = []

    try:
        r = subprocess.run(
            [HERMES_BIN, "cron", "list"],
            capture_output=True, text=True, timeout=15, check=False,
        )
        if r.returncode != 0:
            return CollectorResult(
                collector_name="cron",
                files_written={},
                events_processed=0,
                errors=[f"hermes cron list falhou (exit {r.returncode}): {r.stderr[:200]}"],
            )
        jobs = _parse_cron_output(r.stdout)
    except FileNotFoundError:
        return CollectorResult(
            collector_name="cron",
            files_written={},
            events_processed=0,
            errors=[f"Binário do Hermes não encontrado: {HERMES_BIN}"],
        )
    except Exception as e:
        return CollectorResult(
            collector_name="cron",
            files_written={},
            events_processed=0,
            errors=[f"Falha ao coletar cron jobs: {e}"],
        )

    # Persistência no lastro.db
    if db_path:
        try:
            from ..db import DatabaseManager
            db = DatabaseManager(db_path)
            conn = __import__("sqlite3").connect(db.db_path)
            for j in jobs:
                conn.execute("""
                    INSERT INTO tb_cron_execucao (
                        job_id, nome, schedule, status,
                        next_run, last_run, last_status, last_error, ultimo_sync
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
                    ON CONFLICT(job_id) DO UPDATE SET
                        nome = excluded.nome,
                        schedule = excluded.schedule,
                        status = excluded.status,
                        next_run = excluded.next_run,
                        last_run = excluded.last_run,
                        last_status = excluded.last_status,
                        last_error = excluded.last_error,
                        ultimo_sync = datetime('now')
                """, (
                    j["job_id"], j["nome"], j["schedule"], j["status"],
                    j["next_run"], j["last_run"], j["last_status"],
                    j["last_error"],
                ))
            conn.commit()
            conn.close()
        except Exception as e:
            errors.append(f"Falha ao gravar cron jobs no lastro.db: {e}")

    # Render markdown
    written: dict[str, str] = {}
    try:
        content = _render_cron(jobs)
        vault.write(CRON_FILENAME, content)
        written[CRON_FILENAME] = f"{len(content)} bytes"
    except Exception as e:
        errors.append(f"Falha ao renderizar cron jobs: {e}")

    return CollectorResult(
        collector_name="cron",
        files_written=written,
        events_processed=len(jobs),
        errors=errors,
    )
