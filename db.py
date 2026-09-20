"""
Lastro — db.py
==============
DatabaseManager: gerencia o lastro.db (SQLite) com schema versionado,
migrações automáticas e CRUD para coletores.

Padrões SQL seguem as convenções do QAwler (UC5 — SENAC):
  - Prefixo tb_ para tabelas
  - CONSTRAINT pk_/fk_/uk_ nomeadas explicitamente
  - Comentários de bloco documentando cada estrutura
  - Surrogate keys (id INTEGER PRIMARY KEY AUTOINCREMENT)
  - DEFAULT CURRENT_TIMESTAMP para colunas de auditoria

Schema:
  v1 — estrutura inicial (sessões, aprovações, sync log, métricas, cron, erros, skills)
  v2 — resumo final por sessão (IA local / heurística) + relevância (filtro do diário)
"""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime
from typing import Optional

from .schemas import ApprovalEvent, SessionSummary

DB_VERSION = 3

DDL = """
-- ============================================
-- Lastro — Schema v2
-- Motor: SQLite 3 | Encoding: UTF-8
-- ============================================

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;
PRAGMA encoding = 'UTF-8';

-- ============================================
-- 1. tb_sessao
--    Sessões do Hermes Agent processadas pelo
--    coletor sessions. Enriquece a tabela raw
--    sessions do state.db com: error_count,
--    approval_count, tools_used, first_user_msg,
--    user_notes (preservada entre syncs),
--    resumo_final (IA local/heurística/manual) e
--    relevancia (filtro do diário).
-- ============================================
CREATE TABLE IF NOT EXISTS tb_sessao (
    id_sessao        TEXT NOT NULL,
    titulo           TEXT,
    fonte            TEXT,
    inicio           TEXT,           -- ISO 8601
    fim              TEXT,
    qtd_mensagens    INTEGER DEFAULT 0,
    qtd_ferramentas  INTEGER DEFAULT 0,
    modelo           TEXT,
    tokens_in        INTEGER DEFAULT 0,
    tokens_out       INTEGER DEFAULT 0,
    custo_usd        REAL DEFAULT 0.0,
    qtd_erros        INTEGER DEFAULT 0,
    qtd_aprovacoes   INTEGER DEFAULT 0,
    ferramentas      TEXT,           -- JSON array
    primeira_msg     TEXT,           -- Primeira mensagem do usuário (truncada)
    notas_usuario    TEXT,           -- 👈 Preservada entre syncs
    resumo_final     TEXT,           -- Resumo final (IA local / heurística / manual)
    resumo_origem    TEXT,           -- 'auto' | 'heuristica' | 'manual' (manual preservado)
    relevancia       TEXT DEFAULT 'relevante',  -- 'relevante' | 'nao_relevante'
    motivo_nao_relevante TEXT,       -- 'automacao_cron' | 'teste_trivial'
    motivo_fim       TEXT,           -- state.db sessions.end_reason (ex.: 'compression' = auto-reset por contexto)
    falha_compressao TEXT,           -- state.db sessions.compression_failure_error (falha de compactação)
    ultimo_sync      TEXT NOT NULL DEFAULT (datetime('now')),
    CONSTRAINT pk_sessao PRIMARY KEY (id_sessao)
);

-- ============================================
-- 2. tb_aprovacao
--    Eventos de aprovação do Hermes Agent
--    (terminal + clarify). Cada registro
--    representa um comando ou autorização que
--    exigiu intervenção do usuário.
--    status: approved | rejected | denied | timeout | unknown
-- ============================================
CREATE TABLE IF NOT EXISTS tb_aprovacao (
    id_aprovacao   INTEGER NOT NULL,
    id_sessao      TEXT,
    data_hora      TEXT NOT NULL,    -- ISO 8601 UTC
    status         TEXT NOT NULL,
    resumo_risco   TEXT,
    risco_completo TEXT,
    comando        TEXT,
    fonte          TEXT DEFAULT 'terminal',
    titulo_sessao  TEXT,
    ultimo_sync    TEXT NOT NULL DEFAULT (datetime('now')),
    CONSTRAINT pk_aprovacao PRIMARY KEY (id_aprovacao),
    CONSTRAINT fk_aprovacao_sessao
        FOREIGN KEY (id_sessao) REFERENCES tb_sessao (id_sessao)
        ON DELETE SET NULL ON UPDATE CASCADE
);

-- ============================================
-- 3. tb_sync_log
--    Histórico de execuções do Lastro. Cada
--    linha registra uma chamada a lastro sync
--    com: coletores executados, eventos
--    processados, arquivos gerados e erros.
--    status: ok | partial | error
-- ============================================
CREATE TABLE IF NOT EXISTS tb_sync_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    inicio          TEXT NOT NULL DEFAULT (datetime('now')),
    fim             TEXT,
    coletores       TEXT,            -- JSON array
    total_eventos   INTEGER DEFAULT 0,
    arquivos_gerados INTEGER DEFAULT 0,
    erros           TEXT,            -- JSON array
    status          TEXT NOT NULL DEFAULT 'ok',
    duracao_seg     REAL DEFAULT 0.0
);

-- ============================================
-- 4. tb_server_metric
CREATE TABLE IF NOT EXISTS tb_server_metric (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    data_hora       TEXT NOT NULL DEFAULT (datetime('now')),
    hostname        TEXT,
    disco_total_gb  REAL,
    disco_usado_gb  REAL,
    disco_livre_gb  REAL,
    disco_pct       REAL,
    ram_total_mb    INTEGER,
    ram_usada_mb    INTEGER,
    ram_livre_mb    INTEGER,
    ram_pct         REAL,
    cpu_load_1min   REAL,
    cpu_load_5min   REAL,
    cpu_load_15min  REAL,
    uptime_dias     INTEGER,
    docker_containers INTEGER DEFAULT 0,
    docker_names    TEXT
);

-- ============================================
-- 5. tb_cron_execucao
CREATE TABLE IF NOT EXISTS tb_cron_execucao (
    job_id          TEXT NOT NULL,
    nome            TEXT,
    schedule        TEXT,
    status          TEXT DEFAULT 'active',
    next_run        TEXT,
    last_run        TEXT,
    last_status     TEXT,
    last_error      TEXT,
    ultimo_sync     TEXT NOT NULL DEFAULT (datetime('now')),
    CONSTRAINT pk_cron_execucao PRIMARY KEY (job_id)
);

-- ============================================
-- 6. tb_erro_padrao
--    Padrões de erro detectados nas sessões.
--    Agrupados por tipo de erro similar.
-- ============================================
CREATE TABLE IF NOT EXISTS tb_erro_padrao (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    padrao              TEXT NOT NULL,
    tipo_erro           TEXT,
    mensagem            TEXT,
    frequencia          INTEGER DEFAULT 1,
    primeira_ocorrencia TEXT,
    ultima_ocorrencia   TEXT,
    sessoes_afetadas    TEXT,
    ultimo_sync         TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ============================================
-- 7. tb_skill
--    Catálogo de skills do Hermes Agent com
--    estatísticas de uso por sessão.
--    status: enabled | disabled
-- ============================================
CREATE TABLE IF NOT EXISTS tb_skill (
    nome                TEXT NOT NULL,
    categoria           TEXT,
    descricao           TEXT,
    fonte               TEXT,
    usado_em_sessoes    INTEGER DEFAULT 0,
    ultimo_uso          TEXT,
    ultimo_sync         TEXT NOT NULL DEFAULT (datetime('now')),
    CONSTRAINT pk_skill PRIMARY KEY (nome)
);


"""

# Migrações incrementais (aplicadas a bancos existentes de versão anterior).
# O DDL acima já cria o schema completo para bancos novos.
MIGRATIONS: dict[int, list[str]] = {
    2: [
        "ALTER TABLE tb_sessao ADD COLUMN resumo_final TEXT",
        "ALTER TABLE tb_sessao ADD COLUMN resumo_origem TEXT",
        "ALTER TABLE tb_sessao ADD COLUMN relevancia TEXT DEFAULT 'relevante'",
        "ALTER TABLE tb_sessao ADD COLUMN motivo_nao_relevante TEXT",
    ],
    3: [
        "ALTER TABLE tb_sessao ADD COLUMN motivo_fim TEXT",
        "ALTER TABLE tb_sessao ADD COLUMN falha_compressao TEXT",
    ],
}


class DatabaseManager:
    """Gerencia o banco SQLite do Lastro."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._ensure_db()

    # ── Setup ─────────────────────────────────────────────────────

    def _ensure_db(self) -> None:
        """Cria o banco e aplica migrações se necessário."""
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        current = conn.execute("PRAGMA user_version").fetchone()[0]
        conn.executescript(DDL)

        # Migrações para bancos existentes (DDL só age em tabelas ausentes)
        if 0 < current < DB_VERSION:
            for version in range(current + 1, DB_VERSION + 1):
                for stmt in MIGRATIONS.get(version, []):
                    try:
                        conn.execute(stmt)
                    except sqlite3.OperationalError:
                        pass  # coluna já existe (migração parcial) — idempotente

        if current < DB_VERSION:
            conn.execute(f"PRAGMA user_version = {DB_VERSION}")
        conn.commit()
        conn.close()

    # ── Sessões ───────────────────────────────────────────────────

    def upsert_sessoes(self, sessoes: list[SessionSummary]) -> int:
        """Insere ou atualiza sessões. Retorna contagem de afetadas.

        As colunas de resumo (resumo_final/resumo_origem) NÃO são tocadas
        aqui — são gravadas por set_resumo() e sobrevivem a re-syncs.
        """
        conn = sqlite3.connect(self.db_path)
        count = 0
        for s in sessoes:
            conn.execute("""
                INSERT INTO tb_sessao (
                    id_sessao, titulo, fonte, inicio, fim,
                    qtd_mensagens, qtd_ferramentas, modelo,
                    tokens_in, tokens_out, custo_usd,
                    qtd_erros, qtd_aprovacoes,
                    ferramentas, primeira_msg,
                    relevancia, motivo_nao_relevante,
                    motivo_fim, falha_compressao, ultimo_sync
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
                ON CONFLICT(id_sessao) DO UPDATE SET
                    titulo = excluded.titulo,
                    fonte = excluded.fonte,
                    inicio = excluded.inicio,
                    fim = excluded.fim,
                    qtd_mensagens = excluded.qtd_mensagens,
                    qtd_ferramentas = excluded.qtd_ferramentas,
                    modelo = excluded.modelo,
                    tokens_in = excluded.tokens_in,
                    tokens_out = excluded.tokens_out,
                    custo_usd = excluded.custo_usd,
                    qtd_erros = excluded.qtd_erros,
                    qtd_aprovacoes = excluded.qtd_aprovacoes,
                    ferramentas = excluded.ferramentas,
                    primeira_msg = excluded.primeira_msg,
                    relevancia = excluded.relevancia,
                    motivo_nao_relevante = excluded.motivo_nao_relevante,
                    motivo_fim = excluded.motivo_fim,
                    falha_compressao = excluded.falha_compressao,
                    ultimo_sync = datetime('now')
            """, (
                s.session_id, s.title, s.source,
                s.started_at.isoformat() if s.started_at else None,
                s.ended_at.isoformat() if s.ended_at else None,
                s.message_count, s.tool_call_count, s.model,
                s.tokens_in, s.tokens_out, s.cost_usd,
                s.error_count, s.approval_count,
                json.dumps(s.tools_used, ensure_ascii=False),
                s.first_user_msg,
                s.relevancia, s.motivo_nao_relevante,
                s.motivo_fim, s.falha_compressao,
            ))
            count += 1
        conn.commit()
        conn.close()
        return count

    def get_sessoes(self) -> list[dict]:
        """Retorna todas as sessões como dicionários."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM tb_sessao ORDER BY inicio DESC"
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def get_sessoes_por_data(self) -> dict[str, list[dict]]:
        """Agrupa sessões por data (YYYY-MM-DD)."""
        from collections import defaultdict
        result: dict[str, list[dict]] = defaultdict(list)
        for s in self.get_sessoes():
            if s["inicio"]:
                date = s["inicio"][:10]
                result[date].append(s)
        return dict(result)

    def get_sessao(self, id_sessao: str) -> Optional[dict]:
        """Retorna uma sessão de tb_sessao como dicionário (ou None)."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM tb_sessao WHERE id_sessao = ?", (id_sessao,)
        ).fetchone()
        conn.close()
        return dict(row) if row else None

    # ── Resumos finais ────────────────────────────────────────────

    def get_sessoes_pendentes_resumo(self, limite: int = 10) -> list[dict]:
        """Sessões relevantes sem resumo final, mais recentes primeiro."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute("""
            SELECT id_sessao, titulo, inicio, qtd_mensagens,
                   qtd_ferramentas, primeira_msg
            FROM tb_sessao
            WHERE resumo_final IS NULL
              AND relevancia = 'relevante'
              AND qtd_mensagens > 0
              AND fim IS NOT NULL
            ORDER BY inicio DESC
            LIMIT ?
        """, (limite,)).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def contar_pendentes_resumo(self) -> int:
        """Quantas sessões relevantes ainda não têm resumo final."""
        conn = sqlite3.connect(self.db_path)
        n = conn.execute("""
            SELECT COUNT(*) FROM tb_sessao
            WHERE resumo_final IS NULL
              AND relevancia = 'relevante'
              AND qtd_mensagens > 0
              AND fim IS NOT NULL
        """).fetchone()[0]
        conn.close()
        return int(n)

    def set_resumo(self, id_sessao: str, resumo: str, origem: str) -> bool:
        """Grava o resumo final de uma sessão. Nunca sobrescreve resumo manual."""
        conn = sqlite3.connect(self.db_path)
        cur = conn.execute("""
            UPDATE tb_sessao
            SET resumo_final = ?, resumo_origem = ?
            WHERE id_sessao = ?
              AND (resumo_origem IS NULL OR resumo_origem != 'manual')
        """, (resumo, origem, id_sessao))
        conn.commit()
        changed = cur.rowcount > 0
        conn.close()
        return changed

    def get_resumos(self) -> dict[str, dict]:
        """Mapa id_sessao → {resumo_final, resumo_origem} para renderização."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute("""
            SELECT id_sessao, resumo_final, resumo_origem
            FROM tb_sessao
            WHERE resumo_final IS NOT NULL
        """).fetchall()
        conn.close()
        return {
            r["id_sessao"]: {
                "resumo_final": r["resumo_final"],
                "resumo_origem": r["resumo_origem"],
            }
            for r in rows
        }

    def limpar_resumos_heuristicos(self) -> int:
        """Zera resumos heurísticos para permitir regeneração (manuais são intocáveis)."""
        conn = sqlite3.connect(self.db_path)
        cur = conn.execute("""
            UPDATE tb_sessao
            SET resumo_final = NULL, resumo_origem = NULL
            WHERE resumo_origem = 'heuristica'
        """)
        conn.commit()
        n = cur.rowcount
        conn.close()
        return int(n)

    # ── Aprovações ────────────────────────────────────────────────

    def upsert_aprovacoes(self, aprovacoes: list[ApprovalEvent],
                          sessoes: dict) -> int:
        """Insere ou atualiza aprovações. Retorna contagem."""
        conn = sqlite3.connect(self.db_path)
        count = 0
        for a in aprovacoes:
            s = sessoes.get(a.session_id)
            titulo = s.title if s else ""
            conn.execute("""
                INSERT INTO tb_aprovacao (
                    id_aprovacao, id_sessao, data_hora, status,
                    resumo_risco, risco_completo, comando, fonte,
                    titulo_sessao, ultimo_sync
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
                ON CONFLICT(id_aprovacao) DO UPDATE SET
                    status = excluded.status,
                    resumo_risco = excluded.resumo_risco,
                    risco_completo = excluded.risco_completo,
                    comando = excluded.comando,
                    titulo_sessao = excluded.titulo_sessao,
                    ultimo_sync = datetime('now')
            """, (
                a.event_id, a.session_id,
                a.timestamp.isoformat(), a.status.value,
                a.risk_summary, a.risk_full, a.command, a.source,
                titulo,
            ))
            count += 1
        conn.commit()
        conn.close()
        return count

    def get_aprovacoes(self) -> list[dict]:
        """Retorna todas as aprovações."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM tb_aprovacao ORDER BY data_hora DESC"
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def get_aprovacoes_por_mes(self) -> dict[str, list[dict]]:
        """Agrupa aprovações por mês (YYYY-MM)."""
        from collections import defaultdict
        result: dict[str, list[dict]] = defaultdict(list)
        for a in self.get_aprovacoes():
            if a["data_hora"]:
                mes = a["data_hora"][:7]
                result[mes].append(a)
        return dict(result)

    # ── Sync Log ──────────────────────────────────────────────────

    def log_sync(self, coletores: list[str], total_eventos: int,
                 arquivos: int, erros: list[str],
                 inicio: datetime, fim: datetime) -> int:
        """Registra uma execução de sync. Retorna o id do log."""
        conn = sqlite3.connect(self.db_path)
        duracao = (fim - inicio).total_seconds()
        status = "error" if erros else "ok"
        cursor = conn.execute("""
            INSERT INTO tb_sync_log (
                inicio, fim, coletores, total_eventos,
                arquivos_gerados, erros, status, duracao_seg
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            inicio.isoformat(), fim.isoformat(),
            json.dumps(coletores), total_eventos,
            arquivos, json.dumps(erros, ensure_ascii=False),
            status, duracao,
        ))
        conn.commit()
        log_id = cursor.lastrowid
        conn.close()
        return log_id or 0

    def get_sync_logs(self, limit: int = 10) -> list[dict]:
        """Retorna os últimos N registros de sync."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM tb_sync_log ORDER BY inicio DESC LIMIT ?",
            (limit,)
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    # ── Query (read-only para usuário/agente) ─────────────────────

    def query(self, sql: str) -> list[dict]:
        """Executa query SQL read-only. Retorna lista de dicionários."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(sql).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    # ── Utilitários ───────────────────────────────────────────────

    def stats(self) -> dict:
        """Estatísticas rápidas do banco."""
        conn = sqlite3.connect(self.db_path)
        sessoes = conn.execute("SELECT COUNT(*) FROM tb_sessao").fetchone()[0]
        aprovs = conn.execute("SELECT COUNT(*) FROM tb_aprovacao").fetchone()[0]
        syncs = conn.execute("SELECT COUNT(*) FROM tb_sync_log").fetchone()[0]
        erros = conn.execute(
            "SELECT COUNT(*) FROM tb_sessao WHERE qtd_erros > 0"
        ).fetchone()[0]
        cost = conn.execute(
            "SELECT COALESCE(SUM(custo_usd), 0) FROM tb_sessao"
        ).fetchone()[0]
        resumos = conn.execute(
            "SELECT COUNT(*) FROM tb_sessao WHERE resumo_final IS NOT NULL"
        ).fetchone()[0]
        pendentes = conn.execute(
            "SELECT COUNT(*) FROM tb_sessao WHERE resumo_final IS NULL "
            "AND relevancia = 'relevante' AND qtd_mensagens > 0 AND fim IS NOT NULL"
        ).fetchone()[0]
        nao_relevantes = conn.execute(
            "SELECT COUNT(*) FROM tb_sessao WHERE relevancia != 'relevante'"
        ).fetchone()[0]
        last = conn.execute(
            "SELECT MAX(inicio) FROM tb_sync_log WHERE status = 'ok'"
        ).fetchone()[0]
        conn.close()
        return {
            "sessoes": sessoes,
            "aprovacoes": aprovs,
            "syncs": syncs,
            "sessoes_com_erro": erros,
            "custo_total": round(cost, 4),
            "resumos": resumos,
            "resumos_pendentes": pendentes,
            "sessoes_nao_relevantes": nao_relevantes,
            "ultimo_sync_ok": last or "nunca",
        }
