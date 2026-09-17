#!/usr/bin/env python3
"""CÓPIA DE REFERÊNCIA — hook `on_session_reset` do Hermes → Lastro.

O arquivo canônico executado em produção é /opt/data/bin/hooks/on-session-reset.py
(esta cópia existe para recuperação a partir do repo; se editar um, sincronize o outro).

Registro: bloco `hooks:` no config.yaml do Hermes (HERMES_HOME) + allowlist em
/opt/data/shell-hooks-allowlist.json (reaprovar após editar, pois o mtime muda).
Ativação: restart do gateway (s6-svc -t /run/service/gateway-default).
"""

import json
import shlex
import subprocess
import sys
from datetime import datetime, timezone

LOG = "/opt/data/logs/lastro-session-hook.log"


def log(msg: str) -> None:
    try:
        with open(LOG, "a", encoding="utf-8") as fh:
            ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            fh.write(f"[{ts}] {msg}\n")
    except OSError:
        pass


def main() -> int:
    raw = sys.stdin.read()
    try:
        payload = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        payload = {}

    event = payload.get("hook_event_name") or "?"
    extra = payload.get("extra") or {}
    old_sid = str(extra.get("old_session_id") or "").strip()
    new_sid = str(payload.get("session_id") or extra.get("new_session_id") or "-")
    reason = str(extra.get("reason") or "-")
    log(f"event={event} reason={reason} old={old_sid or '-'} new={new_sid}")

    if event != "on_session_reset" or not old_sid:
        return 0

    cmd = (
        "cd /opt/data && exec /usr/bin/python3 -m lastro finalizar --sessao "
        + shlex.quote(old_sid)
        + f" >> {LOG} 2>&1"
    )
    subprocess.Popen(
        ["/bin/bash", "-c", cmd],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    log(f"worker disparado para {old_sid}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
