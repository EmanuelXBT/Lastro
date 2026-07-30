"""
Lastro — engine.py
===================
Orquestrador: descobre coletores, executa, consolida resultados.
"""

import importlib
from typing import Optional

from .schemas import CollectorResult
from .collectors import run_approvals, run_hub

# Registro de coletores disponíveis.
# ORDEM IMPORTA: o hub roda por último para indexar os arquivos
# gerados pelos coletores de dados no mesmo sync.
COLLECTORS = {
    "approvals": run_approvals,
    "hub": lambda state_db, vault_path: run_hub(state_db, vault_path, collectors=list(COLLECTORS.keys())),
}

DEFAULT_STATE_DB = "/opt/data/state.db"
DEFAULT_VAULT = "/opt/data/obsidian-vault"


def run_collector(name: str, 
                  state_db: str = DEFAULT_STATE_DB,
                  vault_path: str = DEFAULT_VAULT) -> CollectorResult:
    """Executa um coletor específico pelo nome."""
    if name not in COLLECTORS:
        return CollectorResult(
            collector_name=name,
            files_written={},
            events_processed=0,
            errors=[f"Coletor '{name}' não encontrado. Disponíveis: {list(COLLECTORS.keys())}"],
        )
    return COLLECTORS[name](state_db, vault_path)


def run_all(state_db: str = DEFAULT_STATE_DB,
            vault_path: str = DEFAULT_VAULT) -> dict[str, CollectorResult]:
    """Executa todos os coletores registrados."""
    results = {}
    for name, collector_fn in COLLECTORS.items():
        results[name] = collector_fn(state_db, vault_path)
    return results


def status(state_db: str = DEFAULT_STATE_DB,
           vault_path: str = DEFAULT_VAULT) -> dict:
    """Retorna status dos coletores sem executar."""
    import os
    return {
        "collectors": list(COLLECTORS.keys()),
        "state_db": state_db,
        "state_db_exists": os.path.exists(state_db),
        "vault_path": vault_path,
        "vault_exists": os.path.isdir(vault_path),
    }
