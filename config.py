"""
Lastro — config.py
==================
Configuração centralizada via arquivo YAML (subset, zero dependências).

Suporta o subconjunto YAML necessário para o Lastro:
  - Comentários (#)
  - Chaves escalares (key: value)
  - Seções aninhadas com indentação (2 espaços)
  - Booleanos (true/false)
  - Inteiros e strings

Paths de busca do arquivo de configuração (primeiro que existir):
  1. --config passado na CLI
  2. ./config.yaml (diretório do projeto)
  3. ~/.config/lastro/config.yaml
  4. /opt/data/lastro/config.yaml (Umbrel)
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Optional

# ── Paths padrão ────────────────────────────────────────────────────

def _project_root() -> str:
    """Diretório raiz do projeto Lastro (onde está __init__.py)."""
    return os.path.dirname(os.path.abspath(__file__))


DEFAULT_CONFIG_SEARCH = [
    os.path.join(_project_root(), "config.yaml"),
    os.path.expanduser("~/.config/lastro/config.yaml"),
    "/opt/data/lastro/config.yaml",
]

DEFAULT_STATE_DB = "/opt/data/state.db"
DEFAULT_VAULT = "/opt/data/obsidian-vault"
DEFAULT_DB_PATH = "/opt/data/lastro/lastro.db"
DEFAULT_OLLAMA_URL = "http://localhost:11434"


# ── Resumo config ────────────────────────────────────────────────────

@dataclass
class ResumoConfig:
    """Configuração do resumo final de sessões (IA local + fallback)."""
    ativo: bool = True
    motor: str = "ollama"          # ollama | heuristico
    ollama_url: str = DEFAULT_OLLAMA_URL
    modelo: str = "qwen2.5:3b"
    timeout: int = 300
    limite_por_sync: int = 3

    @property
    def urls(self) -> list[str]:
        """URLs do Ollama — aceita fallback separado por vírgula."""
        return [u.strip().rstrip("/") for u in self.ollama_url.split(",") if u.strip()]


# ── Config dataclass ─────────────────────────────────────────────────

@dataclass
class LastroConfig:
    """Configuração centralizada do Lastro."""
    state_db: str = DEFAULT_STATE_DB
    vault_path: str = DEFAULT_VAULT
    db_path: str = DEFAULT_DB_PATH
    timezone: str = ""          # "" = auto-detect
    collectors: dict[str, bool] = field(default_factory=lambda: {
        "approvals": True,
        "hub": True,
    })
    resumo: ResumoConfig = field(default_factory=ResumoConfig)

    @property
    def enabled_collectors(self) -> list[str]:
        """Retorna lista de coletores habilitados, na ordem correta."""
        # Ordem fixa: dados primeiro, indexadores por último
        known_order = ["approvals", "sessions", "server", "cron", "erros", "skills", "hub"]
        ordered = [n for n in known_order if self.collectors.get(n, False)]
        # Inclui coletores desconhecidos (habilitados) no final
        for name in self.collectors:
            if self.collectors[name] and name not in known_order:
                ordered.append(name)
        return ordered

    def resolve_paths(self, project_root: str = "") -> dict[str, str]:
        """Retorna paths absolutos resolvidos para debug/status."""
        return {
            "config_file": "config.yaml",
            "state_db": os.path.abspath(self.state_db),
            "vault_path": os.path.abspath(self.vault_path),
            "timezone": self.timezone or "(auto-detect)",
        }


# ── YAML subset parser (zero deps) ───────────────────────────────────

def _parse_yaml_value(raw: str):
    """Converte string YAML para tipo Python."""
    raw = raw.strip()
    if raw.lower() == "true":
        return True
    if raw.lower() == "false":
        return False
    if raw == "~" or raw.lower() == "null":
        return None
    # Inteiro
    try:
        return int(raw)
    except ValueError:
        pass
    # Float
    try:
        return float(raw)
    except ValueError:
        pass
    # String: remove aspas se existirem
    if (raw.startswith('"') and raw.endswith('"')) or \
       (raw.startswith("'") and raw.endswith("'")):
        return raw[1:-1]
    return raw


def load_config(path: Optional[str] = None) -> LastroConfig:
    """Carrega configuração do primeiro arquivo YAML encontrado.

    Args:
        path: Caminho explícito para o arquivo de configuração.
              Se None, busca nos paths padrão.

    Returns:
        LastroConfig com os valores carregados.

    Raises:
        FileNotFoundError: Se nenhum arquivo de config for encontrado
            e path foi explicitamente solicitado.
    """
    # Determina qual arquivo carregar
    config_path: Optional[str] = None

    if path:
        if os.path.isfile(path):
            config_path = path
        else:
            raise FileNotFoundError(f"Arquivo de configuração não encontrado: {path}")
    else:
        for candidate in DEFAULT_CONFIG_SEARCH:
            if os.path.isfile(candidate):
                config_path = candidate
                break

    if config_path is None:
        # Nenhum arquivo encontrado — usa defaults
        return LastroConfig()

    # Parse do arquivo
    with open(config_path, "r") as f:
        lines = f.readlines()

    config = LastroConfig()
    current_section: Optional[str] = None

    for line in lines:
        stripped = line.strip()

        # Ignora comentários e linhas vazias
        if not stripped or stripped.startswith("#"):
            continue

        # Detecta indentação (seções aninhadas)
        indent = len(line) - len(line.lstrip())

        if indent == 0:
            # Top-level key: value
            if ":" in stripped:
                key, _, value = stripped.partition(":")
                key = key.strip()
                value = value.strip()
                current_section = None

                if key == "state_db" and value:
                    config.state_db = str(_parse_yaml_value(value))
                elif key == "vault_path" and value:
                    config.vault_path = str(_parse_yaml_value(value))
                elif key == "db_path" and value:
                    config.db_path = str(_parse_yaml_value(value))
                elif key == "timezone" and value:
                    config.timezone = str(_parse_yaml_value(value))
                elif key == "collectors":
                    current_section = "collectors"
                elif key == "resumo":
                    current_section = "resumo"
        elif indent == 2 and current_section == "collectors":
            # Seção collectors: key: true/false
            if ":" in stripped:
                key, _, value = stripped.partition(":")
                key = key.strip()
                value = value.strip()
                if key and value:
                    config.collectors[key] = bool(_parse_yaml_value(value))
        elif indent == 2 and current_section == "resumo" and ":" in stripped:
            # Seção resumo: parâmetros do resumo final (IA local)
            key, _, value = stripped.partition(":")
            key = key.strip()
            value = value.strip()
            if key and value:
                parsed = _parse_yaml_value(value)
                if key == "ativo":
                    config.resumo.ativo = bool(parsed)
                elif key == "motor":
                    config.resumo.motor = str(parsed)
                elif key == "ollama_url":
                    config.resumo.ollama_url = str(parsed)
                elif key == "modelo":
                    config.resumo.modelo = str(parsed)
                elif key == "timeout" and isinstance(parsed, int):
                    config.resumo.timeout = parsed
                elif key == "limite_por_sync" and isinstance(parsed, int):
                    config.resumo.limite_por_sync = parsed

    return config


def load_or_default(path: Optional[str] = None) -> LastroConfig:
    """Carrega config ou retorna default silenciosamente (sem exceções)."""
    try:
        return load_config(path)
    except FileNotFoundError:
        return LastroConfig()
