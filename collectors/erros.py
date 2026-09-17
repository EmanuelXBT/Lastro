"""
Lastro — collectors/erros.py
=============================
Coletor de padrões de erro do Hermes Agent.

Varre as mensagens de terminal com exit_code != 0,
extrai o tipo de erro e agrupa por padrão recorrente.

Saída no vault:
  - Sistema/Erros.md — ranking de erros por frequência
  - tb_erro_padrao no lastro.db — histórico com sessões afetadas
"""

from __future__ import annotations

import json
import sqlite3

from ..sanitize import sanitize
from ..schemas import CollectorResult
from ..tz import get_local_tz_name, local_now
from ..vault import VaultManager

ERROS_FILENAME = "Sistema/Erros.md"


def _extract_error_type(output: str) -> str:
    """Extrai o tipo de erro de uma saída de terminal.

    Heurística em 3 níveis:
    1. Última linha com Error/Exception (exceção Python)
    2. Mensagem de erro do shell
    3. Primeira linha da saída
    """
    lines = [l.strip() for l in output.strip().split("\n") if l.strip()]
    if not lines:
        return "(saída vazia)"

    # Nível 1: Última linha com tipo de exceção
    for line in reversed(lines):
        if not line.startswith(("File ", "During ")) and ("Error" in line or "Exception" in line):
                return line[:150]

    # Nível 2: Erro do shell
    for line in lines:
        if "command not found" in line:
            return line[:150]
        if "Permission denied" in line:
            return line[:150]
        if "No such file" in line:
            return line[:150]
        if "cannot" in line.lower() and "error" in line.lower():
            return line[:150]
        if "E:" in line and "Could not" in line:
            return line[:150]

    # Nível 3: Primeira linha não-Traceback
    for line in lines:
        if line != "Traceback (most recent call last):" and not line.startswith("[Command"):
            return line[:150]

    return lines[0][:150]


def _load_errors(db_path: str) -> list[dict]:
    """Carrega e agrupa erros do state.db."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    rows = conn.execute("""
        SELECT m.content, m.session_id, m.timestamp,
               s.title as session_title
        FROM messages m
        LEFT JOIN sessions s ON m.session_id = s.id
        WHERE m.tool_name = 'terminal'
          AND (m.content LIKE '%"exit_code": 1%'
               OR m.content LIKE '%"exit_code": 2%'
               OR m.content LIKE '%Exception%'
               OR m.content LIKE '%Traceback%')
          AND m.content NOT LIKE '%"exit_code": 0%'
        ORDER BY m.timestamp ASC
    """).fetchall()
    conn.close()

    # Agrupa por padrão
    patterns: dict[str, dict] = {}
    for row in rows:
        try:
            data = json.loads(row["content"])
            output = data.get("output", "")
        except (json.JSONDecodeError, TypeError):
            output = str(row["content"])

        error_type = _extract_error_type(output)
        if not error_type:
            continue

        # Chave de agrupamento: primeiros 80 chars do tipo
        key = error_type[:80]

        if key not in patterns:
            patterns[key] = {
                "padrao": key,
                "tipo_erro": error_type,
                "mensagem": sanitize(output)[:300],
                "frequencia": 0,
                "sessoes": set(),
                "primeira": row["timestamp"],
                "ultima": row["timestamp"],
            }

        p = patterns[key]
        p["frequencia"] += 1
        p["sessoes"].add(row["session_id"])
        p["primeira"] = min(p["primeira"], row["timestamp"])
        p["ultima"] = max(p["ultima"], row["timestamp"])

    # Ordena por frequência
    result = sorted(patterns.values(), key=lambda x: -x["frequencia"])
    for p in result:
        p["sessoes"] = sorted(p["sessoes"])
    return result


def _render_erros(patterns: list[dict]) -> str:
    """Renderiza nota de erros no vault."""
    now = local_now()
    tz = get_local_tz_name()
    total_errors = sum(p["frequencia"] for p in patterns)

    lines = [
        "---",
        "domínio: sistema",
        "status: definitivo",
        "tags:",
        "  - erros",
        "  - Lastro",
        "  - debug",
        f"última_revisão: {now.strftime('%Y-%m-%d')}",
        "---",
        "",
        "# 🐛 Padrões de Erro — Hermes Agent",
        "",
        VaultManager.backlink("Sistema/Lastro", "← 🛰️ Hub Lastro"),
        "",
        f"> Snapshot automático — {now.strftime('%Y-%m-%d %H:%M')} {tz}",
        f"> {len(patterns)} padrões únicos | {total_errors} ocorrências totais",
        "",
        "---",
        "",
        "## 📊 Ranking por Frequência",
        "",
        "| # | Padrão | Ocorrências | Sessões | Primeira | Última |",
        "|---|---|---|---|---|---|",
    ]

    for i, p in enumerate(patterns[:50], 1):
        tipo = p["tipo_erro"][:60]
        freq = p["frequencia"]
        sessoes = len(p["sessoes"])
        primeira = p["primeira"][:10] if isinstance(p["primeira"], str) else str(p["primeira"])[:10]
        ultima = p["ultima"][:10] if isinstance(p["ultima"], str) else str(p["ultima"])[:10]
        lines.append(
            f"| {i} | {tipo} | {freq} | {sessoes} | {primeira} | {ultima} |"
        )

    lines.append("")

    # Detalhes dos top 10
    lines.extend([
        "---",
        "",
        "## 🔍 Top 10 — Detalhes",
        "",
    ])

    for i, p in enumerate(patterns[:10], 1):
        lines.extend([
            f"### {i}. {p['tipo_erro'][:80]}",
            "",
            f"- **Ocorrências:** {p['frequencia']}",
            f"- **Sessões afetadas:** {len(p['sessoes'])}",
            f"- **Primeira:** {p['primeira']}",
            f"- **Última:** {p['ultima']}",
            "",
            "**Exemplo da mensagem:**",
            "",
            "```",
            p["mensagem"][:400],
            "```",
            "",
        ])

    lines.extend([
        "---",
        "",
        "> **Sistema:** Lastro — organização para a era da IA",
        "> **Fonte:** `state.db` → `messages` (terminal, exit_code ≠ 0)",
    ])
    return "\n".join(lines)


def run(state_db: str, vault_path: str,
        db_path: str = "") -> CollectorResult:
    """Coleta padrões de erro e renderiza ranking."""
    vault = VaultManager(vault_path)
    errors: list[str] = []

    try:
        patterns = _load_errors(state_db)
    except Exception as e:
        return CollectorResult(
            collector_name="erros",
            files_written={},
            events_processed=0,
            errors=[f"Falha ao carregar erros: {e}"],
        )

    # Persistência no lastro.db
    if db_path:
        try:
            from ..db import DatabaseManager
            db = DatabaseManager(db_path)
            conn = __import__("sqlite3").connect(db.db_path)
            # Limpa padrões antigos antes de inserir
            conn.execute("DELETE FROM tb_erro_padrao")
            for p in patterns:
                conn.execute("""
                    INSERT INTO tb_erro_padrao (
                        padrao, tipo_erro, mensagem, frequencia,
                        primeira_ocorrencia, ultima_ocorrencia,
                        sessoes_afetadas, ultimo_sync
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))
                """, (
                    p["padrao"],
                    p["tipo_erro"],
                    p["mensagem"],
                    p["frequencia"],
                    p["primeira"],
                    p["ultima"],
                    json.dumps(p["sessoes"], ensure_ascii=False),
                ))
            conn.commit()
            conn.close()
        except Exception as e:
            errors.append(f"Falha ao gravar erros no lastro.db: {e}")

    # Render markdown
    written: dict[str, str] = {}
    try:
        content = _render_erros(patterns)
        vault.write(ERROS_FILENAME, content)
        written[ERROS_FILENAME] = f"{len(content)} bytes"
    except Exception as e:
        errors.append(f"Falha ao renderizar erros: {e}")

    return CollectorResult(
        collector_name="erros",
        files_written=written,
        events_processed=len(patterns),
        errors=errors,
    )
