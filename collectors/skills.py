"""
Lastro — collectors/skills.py
==============================
Coletor de catálogo de skills do Hermes Agent.

Executa `hermes skills list`, parseia a tabela e cruza
com uso real (skill_view no state.db).

Saída no vault:
  - Sistema/Skills Catalog.md — catálogo completo por categoria
  - tb_skill no lastro.db — dados estruturados
"""

from __future__ import annotations

import json
import sqlite3
import subprocess
from collections import defaultdict

from ..schemas import CollectorResult
from ..tz import get_local_tz_name, local_now
from ..vault import VaultManager

SKILLS_FILENAME = "Sistema/Skills Catalog.md"
HERMES_BIN = "/opt/hermes/bin/hermes"


def _parse_skills_table(text: str) -> list[dict]:
    """Parseia a saída de `hermes skills list` em lista de dicionários."""
    skills: list[dict] = []

    # Encontra linhas da tabela (entre ─ e ─)
    in_table = False
    for line in text.split("\n"):
        line = line.strip()
        if not line:
            continue

        # Detecta início/fim da tabela
        if "┏" in line or "┡" in line or "└" in line or "┴" in line:
            in_table = not in_table if "┏" in line else in_table
            continue
        if "│" not in line and "┃" not in line:
            continue

        # Parseia colunas: │ name │ category │ source │ trust │ status │
        parts = [p.strip() for p in line.split("│")]
        if len(parts) >= 6:
            name = parts[1].replace("…", "").replace("┃", "").strip()
            category = parts[2]
            source = parts[3]
            trust = parts[4]
            status = parts[5]

            skills.append({
                "nome": name,
                "categoria": category,
                "fonte": source,
                "confianca": trust,
                "status": status,
            })

    return skills


def _load_skill_usage(db_path: str) -> dict[str, dict]:
    """Carrega estatísticas de uso de skills do state.db."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    rows = conn.execute("""
        SELECT m.content, COUNT(DISTINCT m.session_id) as sessions,
               MAX(m.timestamp) as last_used
        FROM messages m
        WHERE m.tool_name = 'skill_view'
        GROUP BY m.content
    """).fetchall()
    conn.close()

    usage: dict[str, dict] = {}
    for row in rows:
        try:
            data = json.loads(row["content"])
            name = data.get("name", "")
            if name:
                if name not in usage:
                    usage[name] = {"sessoes": 0, "ultimo_uso": 0}
                usage[name]["sessoes"] += row["sessions"]
                if row["last_used"] and row["last_used"] > usage[name]["ultimo_uso"]:
                    usage[name]["ultimo_uso"] = row["last_used"]
        except (json.JSONDecodeError, TypeError):
            pass

    return usage


def _render_skills(skills: list[dict], usage: dict[str, dict]) -> str:
    """Renderiza catálogo de skills no vault."""
    now = local_now()
    tz = get_local_tz_name()

    # Agrupa por categoria
    by_cat: dict[str, list[dict]] = defaultdict(list)
    for s in skills:
        cat = s["categoria"] or "(sem categoria)"
        by_cat[cat].append(s)

    total = len(skills)
    usadas = sum(1 for s in skills if s["nome"] in usage)
    hubs = sum(1 for s in skills if s["categoria"])

    lines = [
        "---",
        "domínio: sistema",
        "status: definitivo",
        "tags:",
        "  - skills",
        "  - Lastro",
        "  - hermes",
        f"última_revisão: {now.strftime('%Y-%m-%d')}",
        "---",
        "",
        "# 🧰 Skills Catalog — Hermes Agent",
        "",
        VaultManager.backlink("Sistema/Lastro", "← 🛰️ Hub Lastro"),
        "",
        f"> Snapshot automático — {now.strftime('%Y-%m-%d %H:%M')} {tz}",
        f"> {total} skills instaladas | {usadas} já utilizadas em sessões",
        f"> {hubs} skills hub (categorias agregadoras)",
        "",
        "---",
        "",
        "## 📊 Resumo",
        "",
        "| Categoria | Skills | Usadas |",
        "|---|---|---|",
    ]

    for cat in sorted(by_cat.keys(), key=lambda c: (
        0 if c == "(sem categoria)" else 1, c
    )):
        cat_skills = by_cat[cat]
        cat_used = sum(1 for s in cat_skills if s["nome"] in usage)
        lines.append(f"| {cat} | {len(cat_skills)} | {cat_used} |")

    lines.append("")

    # Detalhes por categoria
    for cat in sorted(by_cat.keys(), key=lambda c: (
        0 if c == "(sem categoria)" else 1, c
    )):
        cat_skills = sorted(by_cat[cat], key=lambda s: s["nome"])
        lines.append(f"## {cat}")
        lines.append("")
        lines.append("| Skill | Fonte | Status | Sessões |")
        lines.append("|---|---|---|---|")

        for s in cat_skills:
            nome = s["nome"]
            fonte = s["fonte"]
            status = s["status"]
            usado = usage.get(nome, {})
            n_sessoes = usado.get("sessoes", 0)
            uso_str = str(n_sessoes) if n_sessoes > 0 else "—"
            status_icon = "✅" if status == "enabled" else "⏸️"

            lines.append(
                f"| {nome} | {fonte} | {status_icon} {status} | {uso_str} |"
            )

        lines.append("")

    lines.extend([
        "---",
        "",
        "> **Sistema:** Lastro — organização para a era da IA",
        "> **Fonte:** `hermes skills list` + `state.db` (skill_view)",
    ])
    return "\n".join(lines)


def run(state_db: str, vault_path: str,
        db_path: str = "") -> CollectorResult:
    """Coleta catálogo de skills e renderiza."""
    vault = VaultManager(vault_path)
    errors: list[str] = []

    # Coleta skills do CLI
    try:
        r = subprocess.run(
            [HERMES_BIN, "skills", "list"],
            capture_output=True, text=True, timeout=15, check=False,
        )
        if r.returncode != 0:
            return CollectorResult(
                collector_name="skills",
                files_written={},
                events_processed=0,
                errors=[f"hermes skills list falhou: {r.stderr[:200]}"],
            )
        skills = _parse_skills_table(r.stdout)
    except FileNotFoundError:
        return CollectorResult(
            collector_name="skills",
            files_written={},
            events_processed=0,
            errors=[f"Binário do Hermes não encontrado: {HERMES_BIN}"],
        )
    except Exception as e:
        return CollectorResult(
            collector_name="skills",
            files_written={},
            events_processed=0,
            errors=[f"Falha ao coletar skills: {e}"],
        )

    # Cruza com uso real
    try:
        usage = _load_skill_usage(state_db)
    except Exception as e:
        usage = {}
        errors.append(f"Falha ao carregar uso de skills: {e}")

    # Persistência no lastro.db
    if db_path:
        try:
            from ..db import DatabaseManager
            db = DatabaseManager(db_path)
            conn = __import__("sqlite3").connect(db.db_path)
            for s in skills:
                nome = s["nome"]
                u = usage.get(nome, {})
                conn.execute("""
                    INSERT INTO tb_skill (
                        nome, categoria, descricao, fonte,
                        usado_em_sessoes, ultimo_uso, ultimo_sync
                    ) VALUES (?, ?, ?, ?, ?, ?, datetime('now'))
                    ON CONFLICT(nome) DO UPDATE SET
                        categoria = excluded.categoria,
                        fonte = excluded.fonte,
                        usado_em_sessoes = excluded.usado_em_sessoes,
                        ultimo_uso = excluded.ultimo_uso,
                        ultimo_sync = datetime('now')
                """, (
                    nome,
                    s["categoria"] or "",
                    "",  # descrição disponível apenas via skill_view
                    s["fonte"],
                    u.get("sessoes", 0),
                    u.get("ultimo_uso", ""),
                ))
            conn.commit()
            conn.close()
        except Exception as e:
            errors.append(f"Falha ao gravar skills no lastro.db: {e}")

    # Render markdown
    written: dict[str, str] = {}
    try:
        content = _render_skills(skills, usage)
        vault.write(SKILLS_FILENAME, content)
        written[SKILLS_FILENAME] = f"{len(content)} bytes"
    except Exception as e:
        errors.append(f"Falha ao renderizar catálogo: {e}")

    return CollectorResult(
        collector_name="skills",
        files_written=written,
        events_processed=len(skills),
        errors=errors,
    )
