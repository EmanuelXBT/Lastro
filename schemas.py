"""
Lastro — schemas.py
===================
Modelos de dados compartilhados entre coletores e o engine.

Todos os coletores produzem listas destes tipos. O vault usa estes
modelos para gerar markdown consistente.
"""


from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional

from .tz import get_local_tz

# Sinais de fim/falha por contexto no state.db:
#   `sessions.end_reason == 'compression'` → o gateway deu auto-reset porque a
#     compressão esgotou (sessão apagada);
#   `sessions.compression_failure_error` → registro da falha de compactação do
#     turno (ex.: "backoff:stall_interrupted:strategy=lean: ... tokens=201240").
_MARCADORES_CONTEXTO = (
    "stall_interrupted",
    "context_length_exceeded",
    "compression",
    "compact",
    "context length",
)


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
        """Hora UTC original (HH:MM:SS)."""
        return self.timestamp.strftime("%H:%M:%S")

    @property
    def local_time(self) -> datetime:
        """Timestamp convertido para o timezone local do UmbrelOS."""
        return self.timestamp.astimezone(get_local_tz())

    @property
    def local_time_str(self) -> str:
        """Hora no timezone local (HH:MM)."""
        return self.local_time.strftime("%H:%M")

    @property
    def local_datetime_str(self) -> str:
        """Data e hora no timezone local (YYYY-MM-DD HH:MM)."""
        return self.local_time.strftime("%Y-%m-%d %H:%M")


@dataclass
class SessionWideAuth:
    """Sessão com múltiplas aprovações (possível YOLO ou autorização em lote)."""
    session_id: str
    session_title: str
    date: str
    count: int
    duration_min: float
    first_approval: str  # ISO timestamp ou datetime local formatado
    first_approval_time: str = ""  # HH:MM local


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


@dataclass
class SessionSummary:
    """Resumo de uma sessão do Hermes para o diário de sessões."""
    session_id: str
    title: str
    source: str
    started_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None
    message_count: int = 0
    tool_call_count: int = 0
    model: str = ""
    first_user_msg: str = ""         # Primeira mensagem do usuário (truncada)
    tools_used: list[str] = field(default_factory=list)
    approval_count: int = 0          # Aprovações de terminal nesta sessão
    error_count: int = 0             # Comandos com erro nesta sessão
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    resumo_final: str = ""           # Resumo final da sessão (IA local ou heurística)
    resumo_origem: str = ""          # 'auto' = IA local | 'heuristica' | 'manual'
    relevancia: str = "relevante"    # 'relevante' | 'nao_relevante'
    motivo_nao_relevante: Optional[str] = None
    # 'automacao_cron' | 'teste_trivial' | 'poucas_interacoes' | 'sem_obsidian'
    user_msg_count: int = 999        # Interações do usuário (999 = não enriquecido → mantém)
    tem_obsidian: bool = True        # Alguma mensagem referencia o vault Obsidian
    motivo_fim: str = ""             # state.db sessions.end_reason (ex.: 'compression')
    falha_compressao: str = ""       # state.db sessions.compression_failure_error (truncado)
    compressao_ineficaz: int = 0     # sessions.compression_ineffective_count
    compressao_streak: int = 0       # sessions.compression_fallback_streak
    relevante_por_contexto: bool = False  # exceção do filtro: estouro de contexto em sessão longa

    @property
    def contexto_estourado(self) -> bool:
        """True quando a sessão terminou (ou tentou terminar) por estouro de contexto.

        Três sinais, todos específicos de compressão de contexto:
          1. `end_reason == 'compression'` — auto-reset do gateway (sessão apagada);
          2. contadores de compressão ineficaz/fallback > 0 — o compactador rodou
             e não reduziu o contexto;
          3. `compression_failure_error` com marcador de compressão/estouro
             (stall, context_length_exceeded, compact...). Timeouts genéricos
             ("Request timed out.") NÃO contam — não são falta de contexto.
        """
        if self.motivo_fim == "compression":
            return True
        if self.compressao_ineficaz > 0 or self.compressao_streak > 0:
            return True
        erro = self.falha_compressao.lower()
        return any(m in erro for m in _MARCADORES_CONTEXTO)

    @property
    def tokens_contexto(self) -> int:
        """Maior valor `tokens=N` achado em compression_failure_error (0 se não houver)."""
        return max((int(n) for n in re.findall(r"tokens=(\d+)", self.falha_compressao)),
                   default=0)

    @property
    def short_id(self) -> str:
        if len(self.session_id) > 24:
            return self.session_id[:21] + "..."
        return self.session_id

    @property
    def date(self) -> str:
        if self.started_at:
            return self.started_at.strftime("%Y-%m-%d")
        return "????-??-??"

    @property
    def month_name(self) -> str:
        if not self.started_at:
            return "Desconhecido"
        months_pt = {
            1: "Janeiro", 2: "Fevereiro", 3: "Março", 4: "Abril",
            5: "Maio", 6: "Junho", 7: "Julho", 8: "Agosto",
            9: "Setembro", 10: "Outubro", 11: "Novembro", 12: "Dezembro",
        }
        m = months_pt[self.started_at.month]
        return f"{m} {self.started_at.year}"

    @property
    def duration_min(self) -> float:
        if self.started_at and self.ended_at:
            return (self.ended_at - self.started_at).total_seconds() / 60
        return 0.0

    @property
    def local_time_str(self) -> str:
        if self.started_at:
            lt = self.started_at.astimezone(get_local_tz())
            return lt.strftime("%H:%M")
        return "??:??"
