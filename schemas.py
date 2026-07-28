"""
Lastro — schemas.py
===================
Modelos de dados compartilhados entre coletores e o engine.

Todos os coletores produzem listas destes tipos. O vault usa estes
modelos para gerar markdown consistente.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional


class ApprovalStatus(str, Enum):
    APPROVED = "approved"
    REJECTED = "rejected"
    DENIED = "denied"
    TIMEOUT = "timeout"
    UNKNOWN = "unknown"

    @property
    def emoji(self) -> str:
        return {
            self.APPROVED: "✅",
            self.REJECTED: "❌",
            self.DENIED: "❌",
            self.TIMEOUT: "⏰",
            self.UNKNOWN: "❓",
        }[self]

    @property
    def label(self) -> str:
        return {
            self.APPROVED: "Aprovado",
            self.REJECTED: "Recusado",
            self.DENIED: "Negado",
            self.TIMEOUT: "Timeout",
            self.UNKNOWN: "Desconhecido",
        }[self]


@dataclass
class SessionInfo:
    """Metadados de uma sessão do Hermes."""
    session_id: str
    title: str = "(sem título)"
    source: str = "?"
    started_at: Optional[datetime] = None

    @property
    def short_id(self) -> str:
        if len(self.session_id) > 20:
            return self.session_id[:17] + "..."
        return self.session_id


@dataclass
class ApprovalEvent:
    """Um único evento de aprovação (terminal ou clarify)."""
    event_id: int
    session_id: str
    timestamp: datetime
    status: ApprovalStatus
    risk_summary: str
    risk_full: str
    command: str = ""
    source: str = "terminal"  # "terminal" | "clarify"
    
    @property
    def date(self) -> str:
        return self.timestamp.strftime("%Y-%m-%d")

    @property
    def month_key(self) -> str:
        return self.timestamp.strftime("%Y-%m")

    @property
    def month_name(self) -> str:
        months_pt = {
            1: "Janeiro", 2: "Fevereiro", 3: "Março", 4: "Abril",
            5: "Maio", 6: "Junho", 7: "Julho", 8: "Agosto",
            9: "Setembro", 10: "Outubro", 11: "Novembro", 12: "Dezembro",
        }
        m = months_pt[self.timestamp.month]
        return f"{m} {self.timestamp.year}"

    @property
    def time_str(self) -> str:
        return self.timestamp.strftime("%H:%M:%S")


@dataclass
class SessionWideAuth:
    """Sessão com múltiplas aprovações (possível YOLO ou autorização em lote)."""
    session_id: str
    session_title: str
    date: str
    count: int
    duration_min: float
    first_approval: str  # ISO timestamp


@dataclass
class CollectorResult:
    """Resultado de um coletor após execução."""
    collector_name: str
    files_written: dict[str, str]  # filename → markdown content
    events_processed: int
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return len(self.errors) == 0
