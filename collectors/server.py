"""
Lastro — collectors/server.py
==============================
Coletor de métricas do servidor.

Server-agnostic: funciona em qualquer Linux com /proc e /sys.
Coleta disco, RAM, CPU, uptime e containers Docker (se disponível).

Saída no vault:
  - Sistema/Server Status.md — snapshot atual
  - tb_server_metric no lastro.db — histórico
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from datetime import datetime, timezone

from ..schemas import CollectorResult
from ..tz import get_local_tz_name, local_now
from ..vault import VaultManager

STATUS_FILENAME = "Sistema/Server Status.md"


def _collect_metrics() -> dict:
    """Coleta métricas do servidor. Retorna dicionário com os valores."""
    metrics: dict = {
        "data_hora": datetime.now(timezone.utc).isoformat(),
        "hostname": os.uname().nodename,
    }

    # Disco
    try:
        disk = shutil.disk_usage("/")
        gb = 1024 ** 3
        metrics.update({
            "disco_total_gb": round(disk.total / gb, 1),
            "disco_usado_gb": round(disk.used / gb, 1),
            "disco_livre_gb": round(disk.free / gb, 1),
            "disco_pct": round(disk.used / disk.total * 100, 1),
        })
    except Exception:  # noqa: S110
        pass

    # RAM
    try:
        mem = {}
        with open("/proc/meminfo") as f:
            for line in f:
                parts = line.split(":")
                if len(parts) == 2:
                    mem[parts[0].strip()] = int(parts[1].strip().split()[0])
        total_mb = mem.get("MemTotal", 0) // 1024
        avail_mb = mem.get("MemAvailable", 0) // 1024
        metrics.update({
            "ram_total_mb": total_mb,
            "ram_usada_mb": total_mb - avail_mb,
            "ram_livre_mb": avail_mb,
            "ram_pct": round((total_mb - avail_mb) / total_mb * 100, 1) if total_mb else 0,
        })
    except Exception:  # noqa: S110
        pass

    # CPU load
    try:
        with open("/proc/loadavg") as f:
            parts = f.read().strip().split()
            metrics.update({
                "cpu_load_1min": float(parts[0]),
                "cpu_load_5min": float(parts[1]),
                "cpu_load_15min": float(parts[2]),
            })
    except Exception:  # noqa: S110
        pass

    # Uptime
    try:
        with open("/proc/uptime") as f:
            uptime_s = float(f.read().split()[0])
            metrics["uptime_dias"] = int(uptime_s // 86400)
    except Exception:  # noqa: S110
        pass

    # Docker (optional, may not be available)
    try:
        r = subprocess.run(
            ["docker", "ps", "--format", "{{.Names}}"],
            capture_output=True, text=True, timeout=5, check=False,
        )
        if r.returncode == 0:
            names = [n.strip() for n in r.stdout.strip().split("\n") if n.strip()]
            metrics["docker_containers"] = len(names)
            metrics["docker_names"] = json.dumps(names[:20], ensure_ascii=False)
    except Exception:
        metrics["docker_containers"] = 0
        metrics["docker_names"] = "[]"

    return metrics


def _render_status(metrics: dict) -> str:
    """Renderiza nota de status do servidor."""
    now = local_now()
    tz = get_local_tz_name()
    lines = [
        "---",
        "domínio: sistema",
        "status: definitivo",
        "tags:",
        "  - server",
        "  - Lastro",
        "  - metrics",
        f"última_revisão: {now.strftime('%Y-%m-%d')}",
        "---",
        "",
        "# 🖥️ Server Status",
        "",
        VaultManager.backlink("Sistema/Lastro", "← 🛰️ Hub Lastro"),
        "",
        f"> Snapshot automático — {now.strftime('%Y-%m-%d %H:%M')} {tz}",
        "",
        "## 💾 Disco",
        "",
        "| Métrica | Valor |",
        "|---|---|",
    ]
    if "disco_total_gb" in metrics:
        lines.extend([
            f"| Total | {metrics['disco_total_gb']} GB |",
            f"| Usado | {metrics['disco_usado_gb']} GB ({metrics['disco_pct']}%) |",
            f"| Livre | {metrics['disco_livre_gb']} GB |",
        ])
    else:
        lines.append("| Status | ❌ Não disponível |")
    lines.append("")

    lines.extend([
        "## 🧠 RAM",
        "",
        "| Métrica | Valor |",
        "|---|---|",
    ])
    if "ram_total_mb" in metrics:
        lines.extend([
            f"| Total | {metrics['ram_total_mb']} MB |",
            f"| Usada | {metrics['ram_usada_mb']} MB ({metrics['ram_pct']}%) |",
            f"| Livre | {metrics['ram_livre_mb']} MB |",
        ])
    else:
        lines.append("| Status | ❌ Não disponível |")
    lines.append("")

    lines.extend([
        "## ⚡ CPU",
        "",
        "| Métrica | Valor |",
        "|---|---|",
    ])
    if "cpu_load_1min" in metrics:
        lines.extend([
            f"| Load 1min | {metrics['cpu_load_1min']} |",
            f"| Load 5min | {metrics['cpu_load_5min']} |",
            f"| Load 15min | {metrics['cpu_load_15min']} |",
        ])
    lines.append("")

    lines.extend([
        "## ⏱️ Uptime",
        "",
        f"**{metrics.get('uptime_dias', '?')} dias** — desde o último boot.",
        "",
    ])

    # Docker
    if metrics.get("docker_containers", 0) > 0:
        lines.extend([
            "## 🐳 Docker",
            "",
            f"**{metrics['docker_containers']} containers** em execução.",
            "",
        ])

    lines.extend([
        "---",
        "",
        f"**Hostname:** `{metrics.get('hostname', '?')}`",
        "",
        "> **Sistema:** Lastro — organização para a era da IA",
    ])
    return "\n".join(lines)


def run(state_db: str, vault_path: str,
        db_path: str = "") -> CollectorResult:
    """Coleta métricas e renderiza status."""
    vault = VaultManager(vault_path)
    errors: list[str] = []

    try:
        metrics = _collect_metrics()
    except Exception as e:
        return CollectorResult(
            collector_name="server",
            files_written={},
            events_processed=0,
            errors=[f"Falha ao coletar métricas: {e}"],
        )

    # Persistência no lastro.db
    if db_path:
        try:
            from ..db import DatabaseManager
            db = DatabaseManager(db_path)
            conn = __import__("sqlite3").connect(db.db_path)
            conn.execute("""
                INSERT INTO tb_server_metric (
                    data_hora, hostname,
                    disco_total_gb, disco_usado_gb, disco_livre_gb, disco_pct,
                    ram_total_mb, ram_usada_mb, ram_livre_mb, ram_pct,
                    cpu_load_1min, cpu_load_5min, cpu_load_15min,
                    uptime_dias, docker_containers, docker_names
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                metrics.get("data_hora"),
                metrics.get("hostname"),
                metrics.get("disco_total_gb"),
                metrics.get("disco_usado_gb"),
                metrics.get("disco_livre_gb"),
                metrics.get("disco_pct"),
                metrics.get("ram_total_mb"),
                metrics.get("ram_usada_mb"),
                metrics.get("ram_livre_mb"),
                metrics.get("ram_pct"),
                metrics.get("cpu_load_1min"),
                metrics.get("cpu_load_5min"),
                metrics.get("cpu_load_15min"),
                metrics.get("uptime_dias"),
                metrics.get("docker_containers"),
                metrics.get("docker_names", "[]"),
            ))
            conn.commit()
            conn.close()
        except Exception as e:
            errors.append(f"Falha ao gravar métricas no lastro.db: {e}")

    # Render markdown
    written: dict[str, str] = {}
    try:
        content = _render_status(metrics)
        vault.write(STATUS_FILENAME, content)
        written[STATUS_FILENAME] = f"{len(content)} bytes"
    except Exception as e:
        errors.append(f"Falha ao renderizar status: {e}")

    return CollectorResult(
        collector_name="server",
        files_written=written,
        events_processed=1,
        errors=errors,
    )
