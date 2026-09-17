"""
Lastro — engine.py
===================
Orquestrador: descobre coletores, executa, consolida resultados.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from .collectors import (
    run_approvals,
    run_cron,
    run_erros,
    run_hub,
    run_server,
    run_sessions,
    run_skills,
)
from .config import (
    DEFAULT_STATE_DB,
    DEFAULT_VAULT,
    LastroConfig,
    load_or_default,
)
from .schemas import CollectorResult


def _make_collectors(config: LastroConfig) -> dict:
    """Constrói o registro de coletores a partir da configuração.

    ORDEM IMPORTA: o hub roda por último para indexar os arquivos
    gerados pelos coletores de dados no mesmo sync.
    """
    collectors: dict = {}

    if config.collectors.get("approvals", False):
        collectors["approvals"] = run_approvals

    if config.collectors.get("sessions", False):
        collectors["sessions"] = run_sessions

    if config.collectors.get("server", False):
        collectors["server"] = run_server

    if config.collectors.get("cron", False):
        collectors["cron"] = run_cron

    if config.collectors.get("erros", False):
        collectors["erros"] = run_erros

    if config.collectors.get("skills", False):
        collectors["skills"] = run_skills

    if config.collectors.get("hub", False):
        enabled = list(collectors.keys()) + ["hub"]
        collectors["hub"] = lambda s, v, d="": run_hub(s, v, collectors=enabled)  # type: ignore[has-type]

    return collectors


def _run_one(name: str, fn, state_db: str, vault_path: str,
             db_path: str, config: LastroConfig) -> CollectorResult:
    """Executa um coletor, passando db_path se aplicável."""
    # Coletores de dados aceitam db_path; hub não precisa
    if name == "sessions":
        # sessions também gera/renderiza os resumos finais (IA local)
        return fn(state_db, vault_path, db_path=db_path, resumo_cfg=config.resumo)
    if name in ("approvals", "server", "cron", "erros", "skills"):
        return fn(state_db, vault_path, db_path=db_path)
    return fn(state_db, vault_path)


def run_collector(name: str,
                  state_db: str = DEFAULT_STATE_DB,
                  vault_path: str = DEFAULT_VAULT,
                  config: Optional[LastroConfig] = None) -> CollectorResult:
    """Executa um coletor específico pelo nome."""
    cfg = config or load_or_default()
    collectors = _make_collectors(cfg)

    if name not in collectors:
        return CollectorResult(
            collector_name=name,
            files_written={},
            events_processed=0,
            errors=[f"Coletor '{name}' não encontrado. Disponíveis: {list(collectors.keys())}"],
        )
    return _run_one(name, collectors[name], state_db, vault_path,
                    cfg.db_path, cfg)


def run_all(state_db: str = DEFAULT_STATE_DB,
            vault_path: str = DEFAULT_VAULT,
            config: Optional[LastroConfig] = None) -> dict[str, CollectorResult]:
    """Executa todos os coletores habilitados na configuração."""
    cfg = config or load_or_default()
    collectors = _make_collectors(cfg)
    results: dict[str, CollectorResult] = {}

    inicio = datetime.now(timezone.utc)
    total_eventos = 0
    total_arquivos = 0
    all_errors: list[str] = []

    for name, collector_fn in collectors.items():
        result = _run_one(name, collector_fn, state_db, vault_path,
                          cfg.db_path, cfg)
        results[name] = result
        total_eventos += result.events_processed
        total_arquivos += len(result.files_written)
        all_errors.extend(result.errors)

    fim = datetime.now(timezone.utc)

    # Sync log no lastro.db
    if cfg.db_path:
        try:
            from .db import DatabaseManager
            db = DatabaseManager(cfg.db_path)
            db.log_sync(
                coletores=list(collectors.keys()),
                total_eventos=total_eventos,
                arquivos=total_arquivos,
                erros=all_errors,
                inicio=inicio,
                fim=fim,
            )
        except Exception:  # noqa: S110
            pass  # Log failure is non-fatal

    return results


def status(state_db: str = DEFAULT_STATE_DB,
           vault_path: str = DEFAULT_VAULT,
           config: Optional[LastroConfig] = None) -> dict:
    """Retorna status dos coletores sem executar."""
    import os
    cfg = config or load_or_default()
    collectors = _make_collectors(cfg)
    result = {
        "collectors": list(collectors.keys()),
        "state_db": state_db,
        "state_db_exists": os.path.exists(state_db),
        "vault_path": vault_path,
        "vault_exists": os.path.isdir(vault_path),
        "db_path": cfg.db_path,
        "db_exists": os.path.exists(cfg.db_path),
        "config": cfg.resolve_paths(),
    }
    return result
