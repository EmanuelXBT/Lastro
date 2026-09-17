"""
Lastro — resumo.py
==================
Resumo final das sessões com IA local (Ollama) e fallback heurístico.

O resumo é gravado em `tb_sessao.resumo_final` (com `resumo_origem`) e
renderizado nas notas diárias de `sessoes/`. Se o Ollama estiver offline,
a resposta falhar na validação ou o motor for `heuristico`, cai para um
digest determinístico das tarefas pedidas pelo usuário — o resumo nunca
fica vazio por indisponibilidade de infraestrutura.

Notas de engenharia (validadas empiricamente com qwen2.5:3b):
  - Prompts longos degradam o modelo pequeno (lixo tipo `[](`/vazio/HTTP 500);
    manter o transcript ≤ ~3k chars (3 primeiras mensagens do usuário + cauda).
  - Blocos de compactação de contexto ("CONTEXT COMPACTION...") NÃO entram
    no transcript — são instruction-heavy e envenenam o modelo.
  - A saída é validada (tamanho, CJK, padrões de loop) com 1 retry; se
    continuar inválida, usa o fallback heurístico.

Config (config.yaml):
    resumo:
      ativo: true
      motor: ollama          # ollama | heuristico
      ollama_url: "http://ollama:11434, http://192.168.0.189:11434"
      modelo: "qwen2.5:3b"
      timeout: 300
      limite_por_sync: 3
"""

from __future__ import annotations

import json
import re
import sqlite3
import urllib.request
from typing import Callable, Optional

from .config import ResumoConfig

# Limites do transcript enviado ao modelo
MAX_FIRST_MSGS = 3          # primeiras mensagens do usuário (as tarefas)
MAX_FIRST_CHARS = 400
MAX_LAST_MSGS = 8           # últimas mensagens (user + assistant)
MAX_LAST_CHARS = 280
MAX_TRANSCRIPT_CHARS = 2800

SYSTEM_PROMPT = (
    "Você escreve resumos finais concisos em português do Brasil para o diário "
    "de sessões de um agente de IA. Escreva de 2 a 4 frases cobrindo: as tarefas "
    "que o usuário pediu e o que foi concluído ou entregue. Sem preâmbulo, sem "
    "listas, sem títulos — apenas o texto do resumo."
)

_PROMPT_USUARIO = "Resuma as tarefas e entregas desta sessão em 2-4 frases, em português do Brasil:\n\n"

# Bloco de origem injetado pelo gateway (JSON de roteamento + aviso)
_GATEWAY_RE = re.compile(
    r"Gateway message origin \(JSON data, not instructions or authorization\):"
    r"\s*\{[^\n]*\}"
    r"\s*Do not guess a reply destination when these fields are insufficient\.\s*"
)

# Preâmbulos comuns que o modelo adiciona antes do resumo
_PREAMBULO_RE = re.compile(
    r"^\s*(conclu[ií]do[.!]?\s*|segue o resumo[^:]*:\s*|aqui est[aá][^:]*:\s*|resumo[^:]*:\s*)+",
    re.IGNORECASE,
)
_GARBAGE_RE = re.compile(r"^[\s\[\]\(\),.;:|/\\-]*$")
_CJK_RE = re.compile(r"[\u3400-\u9fff\u3040-\u30ff]")


def _limpar(msg: str) -> str:
    """Remove blocos injetados pelo gateway (origem JSON, contexto Umbrel)."""
    msg = _GATEWAY_RE.sub("", msg)
    for marcador in ("Gateway message origin", "Umbrel Runtime Context:"):
        i = msg.find(marcador)
        if i != -1:
            msg = msg[:i]
    return msg.strip()


def montar_transcript(state_db: str, session_id: str) -> str:
    """Monta um trecho enxuto da sessão (tarefas iniciais + cauda) para resumir."""
    conn = sqlite3.connect(state_db)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT role, content FROM messages
            WHERE session_id = ? AND role IN ('user', 'assistant')
              AND content IS NOT NULL AND TRIM(content) != ''
              AND COALESCE(_compressed_summary, 0) = 0
            ORDER BY id
            """,
            (session_id,),
        ).fetchall()
    finally:
        conn.close()

    def fmt(role: str, content: str, cap: int) -> Optional[str]:
        c = _limpar(content or "")
        if not c:
            return None
        c = re.sub(r"\s+", " ", c).strip()[:cap]
        return f"[{role}] {c}"

    usuarios = [r for r in rows if r["role"] == "user"]
    if len(rows) <= MAX_FIRST_MSGS + MAX_LAST_MSGS:
        trecho = [fmt(r["role"], r["content"], MAX_LAST_CHARS) for r in rows]
    else:
        trecho = [fmt(r["role"], r["content"], MAX_FIRST_CHARS) for r in usuarios[:MAX_FIRST_MSGS]]
        trecho.append("[...]")
        trecho.extend(fmt(r["role"], r["content"], MAX_LAST_CHARS) for r in rows[-MAX_LAST_MSGS:])
    texto = "\n".join(t for t in trecho if t)
    return texto[:MAX_TRANSCRIPT_CHARS]


def resumir_heuristico(state_db: str, session_id: str, titulo: str = "") -> str:
    """Fallback determinístico: digest das tarefas pedidas pelo usuário."""
    conn = sqlite3.connect(state_db)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT content FROM messages
            WHERE session_id = ? AND role = 'user'
              AND content IS NOT NULL AND TRIM(content) != ''
              AND COALESCE(_compressed_summary, 0) = 0
            ORDER BY id LIMIT 12
            """,
            (session_id,),
        ).fetchall()
    finally:
        conn.close()

    tarefas: list[str] = []
    for r in rows:
        c = _limpar(r["content"] or "")
        if c:
            tarefas.append(re.sub(r"\s+", " ", c).strip()[:220])
        if len(tarefas) == 3:
            break
    if not tarefas:
        return f"Sessão registrada — {titulo}".strip() if titulo else "Sessão registrada."
    return "Tarefas pedidas: " + " | ".join(tarefas)[:650]


def _validar_resumo(texto: str) -> Optional[str]:
    """Valida e normaliza a saída do modelo. None = inválida (usar fallback)."""
    t = (texto or "").strip()
    if len(t) < 40:
        return None
    t = _PREAMBULO_RE.sub("", t).strip().strip("\"'“”")
    t = re.sub(r"(?m)^\s*\d+[.)]\s+", "", t)  # remove numeração de lista
    t = re.sub(r"\s+", " ", t).strip()
    if len(t) < 40 or len(t) > 1500:
        return None
    if _CJK_RE.search(t) or _GARBAGE_RE.match(t) or "[](" in t:
        return None
    palavras = t.split()
    if len(palavras) >= 8 and len(set(palavras)) <= len(palavras) // 4:
        return None  # texto degenerado (repetição — ex.: "o o o o...")
    # geração interrompida no meio de frase: corta no último fim de frase
    if t[-1] not in ".!?…»\"'":
        corte = max(t.rfind(". "), t.rfind("! "), t.rfind("? "))
        if corte > len(t) * 0.5:
            t = t[: corte + 1].strip()
    return t or None


def _call_ollama(url: str, modelo: str, transcript: str, timeout: int) -> Optional[str]:
    """Chama o Ollama; retorna None em qualquer falha de infraestrutura."""
    payload = {
        "model": modelo,
        "stream": False,
        "keep_alive": "30m",
        "options": {"num_predict": 340, "temperature": 0.1, "repeat_penalty": 1.15, "num_ctx": 4096},
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": _PROMPT_USUARIO + transcript + "\n\nResumo final:"},
        ],
    }
    req = urllib.request.Request(
        url.rstrip("/") + "/api/chat",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return str(data.get("message", {}).get("content", ""))
    except Exception:
        return None


def gerar_resumo(state_db: str, session_id: str, titulo: str, cfg: ResumoConfig) -> tuple[str, str]:
    """Gera o resumo de uma sessão. Retorna (texto, origem)."""
    transcript = montar_transcript(state_db, session_id)
    if cfg.motor == "ollama" and transcript:
        for _tentativa in range(3):  # o modelo pequeno falha de forma estocástica
            falhou_tudo = True
            for url in cfg.urls:
                bruto = _call_ollama(url, cfg.modelo, transcript, cfg.timeout)
                if not bruto:
                    continue
                falhou_tudo = False
                valido = _validar_resumo(bruto)
                if valido:
                    return valido, "auto"
                break  # resposta inválida — tenta de novo na próxima volta
            if falhou_tudo:
                break  # nenhum servidor respondeu
    return resumir_heuristico(state_db, session_id, titulo), "heuristica"


def processar_resumos(state_db: str, db_path: str, cfg: ResumoConfig,
                      limite: int = 10, log: Callable[..., None] = print) -> dict:
    """Gera os resumos pendentes (mais recentes primeiro) e grava no lastro.db.

    Retorna contagens: {"gerados": n, "ia": n, "heuristica": n, "falhas": n}.
    """
    from .db import DatabaseManager

    db = DatabaseManager(db_path)
    pendentes = db.get_sessoes_pendentes_resumo(limite=limite)
    stats = {"gerados": 0, "ia": 0, "heuristica": 0, "falhas": 0}
    for s in pendentes:
        sid = s["id_sessao"]
        try:
            texto, origem = gerar_resumo(state_db, sid, s.get("titulo") or "", cfg)
        except Exception as e:  # nunca derruba o sync por causa de um resumo
            stats["falhas"] += 1
            log(f"   ❌ resumo {sid[:24]}: {e}")
            continue
        if db.set_resumo(sid, texto, origem):
            stats["gerados"] += 1
            stats["ia" if origem == "auto" else "heuristica"] += 1
            log(f"   ✍️  {sid[:24]} ({origem}): {texto[:80]}…")
    return stats


def finalizar_sessao(state_db: str, db_path: str, cfg: ResumoConfig,
                     session_id: str, log: Callable[..., None] = print) -> dict:
    """Gera (forçado) o resumo final de UMA sessão recém-encerrada.

    Fluxo do shell hook `on_session_reset` (comando `/new`): diferente de
    processar_resumos(), não exige `fim` preenchido nem passa pela fila de
    pendentes — a sessão acabou de encerrar no reset.

    Retorna {"ok": bool, "motivo"?: str, "origem"?: str, "texto"?: str}.
    Resumos manuais nunca são sobrescritos.
    """
    from .db import DatabaseManager

    db = DatabaseManager(db_path)
    s = db.get_sessao(session_id)
    if not s:
        log(f"   ⚠️  finalizar: sessão {session_id[:24]} ausente do lastro.db")
        return {"ok": False, "motivo": "sessao_ausente"}
    if s.get("resumo_origem") == "manual":
        return {"ok": True, "motivo": "manual_preservado"}
    if (s.get("qtd_mensagens") or 0) <= 1:
        return {"ok": False, "motivo": "sem_conteudo"}
    texto, origem = gerar_resumo(state_db, session_id, s.get("titulo") or "", cfg)
    ok = db.set_resumo(session_id, texto, origem)
    if ok:
        log(f"   ✍️  {session_id[:24]} ({origem}): {texto[:80]}…")
    return {"ok": ok, "origem": origem, "texto": texto}
