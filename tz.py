"""
Lastro — tz.py
==============
Detecção automática do timezone local do UmbrelOS.

Estratégia (ordem de prioridade):
1. Variável de ambiente TZ (ex: TZ=America/Sao_Paulo)
2. Arquivo /etc/timezone (Debian/Ubuntu)
3. Symlink /etc/localtime → extrai o nome da zoneinfo
4. Arquivo de config local /opt/data/lastro/.tz
5. Fallback: UTC

Funciona em qualquer instalação Umbrel do mundo — basta o host
ter o timezone configurado e montado no container, ou o usuário
criar o arquivo .tz manualmente.
"""


from __future__ import annotations

import os
import zoneinfo
from datetime import datetime
from datetime import timezone as dt_timezone
from pathlib import Path
from typing import Optional

CONFIG_TZ_FILE = "/opt/data/lastro/.tz"


def _resolve_symlink_tz() -> Optional[str]:
    """Tenta extrair o timezone do symlink /etc/localtime."""
    localtime = Path("/etc/localtime")
    if not localtime.is_symlink():
        return None
    target = os.readlink("/etc/localtime")
    # Ex: /usr/share/zoneinfo/America/Sao_Paulo
    parts = target.split("zoneinfo/")
    if len(parts) == 2:
        candidate = parts[1]
        if candidate and candidate != "Etc/UTC":
            return candidate
    return None


def _read_timezone_file() -> Optional[str]:
    """Lê /etc/timezone (formato Debian/Ubuntu)."""
    try:
        with open("/etc/timezone") as f:
            content = f.read().strip()
            if content:
                return content
    except (FileNotFoundError, PermissionError):
        pass
    return None


def _read_config_file() -> Optional[str]:
    """Lê o arquivo de config local .tz."""
    try:
        with open(CONFIG_TZ_FILE) as f:
            content = f.read().strip()
            if content:
                return content
    except (FileNotFoundError, PermissionError):
        pass
    return None


def _validate_tz(tz_name: str) -> bool:
    """Verifica se o nome de timezone é válido no banco zoneinfo."""
    try:
        zoneinfo.ZoneInfo(tz_name)
        return True
    except (zoneinfo.ZoneInfoNotFoundError, KeyError, ValueError):
        return False


def detect_timezone_name() -> str:
    """
    Detecta o nome do timezone local (ex: 'America/Sao_Paulo').

    Ordem de prioridade:
    1. $TZ
    2. /etc/timezone
    3. symlink /etc/localtime (se não for Etc/UTC)
    4. /opt/data/lastro/.tz
    5. 'UTC'
    """
    # 1. Variável de ambiente
    tz_env = os.environ.get("TZ", "").strip()
    if tz_env and _validate_tz(tz_env):
        return tz_env

    # 2. /etc/timezone
    tz_file = _read_timezone_file()
    if tz_file and _validate_tz(tz_file):
        return tz_file

    # 3. Symlink /etc/localtime
    tz_symlink = _resolve_symlink_tz()
    if tz_symlink and _validate_tz(tz_symlink):
        return tz_symlink

    # 4. Config local
    tz_config = _read_config_file()
    if tz_config and _validate_tz(tz_config):
        return tz_config

    # 5. Fallback
    return "UTC"


# Cache: detecta uma vez por processo
_LOCAL_TZ: Optional[dt_timezone] = None
_LOCAL_TZ_NAME: Optional[str] = None


def get_local_tz() -> dt_timezone:
    """Retorna o objeto timezone local (com cache)."""
    global _LOCAL_TZ, _LOCAL_TZ_NAME
    if _LOCAL_TZ is not None:
        return _LOCAL_TZ

    name = detect_timezone_name()
    _LOCAL_TZ_NAME = name
    try:
        _LOCAL_TZ = zoneinfo.ZoneInfo(name)  # type: ignore[assignment]
    except Exception:
        _LOCAL_TZ = dt_timezone.utc
        _LOCAL_TZ_NAME = "UTC"
    return _LOCAL_TZ  # type: ignore[return-value]


def get_local_tz_name() -> str:
    """Retorna o nome do timezone local detectado."""
    if _LOCAL_TZ_NAME is None:
        get_local_tz()  # força detecção
    return _LOCAL_TZ_NAME or "UTC"


def local_now() -> datetime:
    """Retorna datetime.now() no timezone local."""
    return datetime.now(get_local_tz())


def utc_to_local(dt_utc: datetime) -> datetime:
    """Converte um datetime UTC para o timezone local."""
    if dt_utc.tzinfo is None:
        dt_utc = dt_utc.replace(tzinfo=dt_timezone.utc)
    return dt_utc.astimezone(get_local_tz())
