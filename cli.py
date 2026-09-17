"""
Lastro — CLI
============
Interface de linha de comando.

Uso:
    python3 -m lastro sync              # Executa todos os coletores
    python3 -m lastro sync approvals    # Executa só o coletor de aprovações
    python3 -m lastro status            # Status dos coletores
    python3 -m lastro list              # Lista coletores disponíveis
    python3 -m lastro resumos           # Gera resumos finais pendentes (IA local)
    python3 -m lastro resumos --continuo --limite 25   # Drena a fila em lotes

Flags:
    --config PATH    Caminho para arquivo de configuração YAML
    --continuo       (resumos) Processa a fila até drenar
    --refazer        (resumos) Regenera resumos heurísticos (manuais são preservados)
    --limite N       (resumos) Máximo de resumos por execução (default: 10)
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import Optional

# Adiciona o diretório pai ao path para suporte a execução direta do script
_parent = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _parent not in sys.path:
    sys.path.insert(0, _parent)

from lastro.config import LastroConfig, load_or_default
from lastro.schemas import CollectorResult


def _parse_args(argv: list[str]) -> tuple[str, list[str], Optional[str]]:
    """Parse argv retornando (comando, args_restantes, config_path)."""
    parser = argparse.ArgumentParser(
        prog="lastro",
        description="Lastro — Organização para a era da IA",
        add_help=False,
    )
    parser.add_argument("--config", type=str, default=None,
                        help="Caminho para config.yaml")
    parser.add_argument("command", nargs="?", default="sync",
                        choices=["sync", "status", "list", "query", "stats", "resumos"],
                        help="Comando (default: sync)")
    parser.add_argument("collector", nargs="?", default=None,
                        help="Nome do coletor (sync)")
    parser.add_argument("--continuo", action="store_true", default=False,
                        help="(resumos) Processa a fila até drenar")
    parser.add_argument("--refazer", action="store_true", default=False,
                        help="(resumos) Regenera resumos heurísticos")
    parser.add_argument("--limite", type=int, default=None,
                        help="(resumos) Máximo de resumos por execução")
    # Captura --help manualmente
    if "-h" in argv or "--help" in argv:
        parser.print_help()
        sys.exit(0)

    ns, unknown = parser.parse_known_args(argv)
    rest = [ns.collector] if ns.collector else []
    if ns.continuo:
        rest.append("--continuo")
    if ns.refazer:
        rest.append("--refazer")
    if ns.limite is not None:
        rest.extend(["--limite", str(ns.limite)])
    rest.extend(unknown)
    return ns.command, rest, ns.config


def cmd_sync(args: list[str], config: LastroConfig) -> None:
    """Executa coletores."""
    from lastro.engine import run_all, run_collector

    if args:
        collector_name = args[0]
        print(f"🔄 Lastro → executando coletor '{collector_name}'...")
        result = run_collector(collector_name,
                               state_db=config.state_db,
                               vault_path=config.vault_path,
                               config=config)
        _print_result(result)
    else:
        print("🔄 Lastro → executando todos os coletores...")
        results = run_all(state_db=config.state_db,
                          vault_path=config.vault_path,
                          config=config)
        if not results:
            print("   ⚠️  Nenhum coletor habilitado na configuração.")
            return
        for result in results.values():
            _print_result(result)


def cmd_status(args: list[str], config: LastroConfig) -> None:
    """Mostra status do sistema."""
    from lastro.engine import status
    s = status(state_db=config.state_db, vault_path=config.vault_path, config=config)
    print("📊 Lastro — Status")
    print(f"   State DB: {s['state_db']} {'✅' if s['state_db_exists'] else '❌'}")
    print(f"   Vault:    {s['vault_path']} {'✅' if s['vault_exists'] else '❌'}")
    print(f"   Coletores: {', '.join(s['collectors'])}")
    if "config" in s:
        paths = s["config"]
        print(f"   Config:   {paths.get('config_file', 'defaults')}")
        print(f"   Timezone: {paths.get('timezone', 'auto')}")


def cmd_list(args: list[str], config: LastroConfig) -> None:
    """Lista coletores disponíveis."""
    from lastro.engine import _make_collectors
    collectors = _make_collectors(config)
    print("📦 Coletores disponíveis:")
    for name, fn in collectors.items():
        doc = fn.__doc__ or "(sem descrição)"
        status = "✅ habilitado" if config.collectors.get(name, False) else "⏸️ desabilitado"
        print(f"   {name:20s} {status:20s} — {doc.strip().split(chr(10))[0][:60]}")


def _print_result(result: CollectorResult) -> None:
    """Exibe resultado de um coletor."""
    icon = "✅" if result.ok else "⚠️"
    print(f"   {icon} {result.collector_name}: {result.events_processed} eventos → "
          f"{len(result.files_written)} arquivos")
    if result.errors:
        for err in result.errors:
            print(f"      ❌ {err}")


def cmd_query(args: list[str], config: LastroConfig) -> None:
    """Executa query SQL no lastro.db."""
    if not os.path.exists(config.db_path):
        print("❌ lastro.db não encontrado. Execute `lastro sync` primeiro.")
        return

    from lastro.db import DatabaseManager
    db = DatabaseManager(config.db_path)

    if not args:
        tables = db.query(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        print("📊 Tabelas disponíveis no lastro.db:")
        for t in tables:
            count = db.query(
                f"SELECT COUNT(*) as cnt FROM [{t['name']}]"
            )[0]['cnt']
            print(f"   {t['name']:20s} ({count} registros)")
        print('\n   Exemplo: lastro query "SELECT * FROM tb_sessao WHERE qtd_erros > 0"')
        return

    sql = " ".join(args)
    try:
        rows = db.query(sql)
    except Exception as e:
        print(f"❌ Erro na query: {e}")
        return

    if not rows:
        print("(sem resultados)")
        return

    cols = list(rows[0].keys())
    widths = {c: len(c) for c in cols}
    for r in rows:
        for c in cols:
            widths[c] = max(widths[c], len(str(r[c])))

    header = " | ".join(c.ljust(widths[c]) for c in cols)
    sep = "-+-".join("-" * widths[c] for c in cols)
    print(header)
    print(sep)
    for r in rows:
        print(" | ".join(str(r[c]).ljust(widths[c]) for c in cols))
    print(f"\n({len(rows)} resultado(s))")


def cmd_stats(args: list[str], config: LastroConfig) -> None:
    """Mostra estatísticas rápidas do lastro.db."""
    if not os.path.exists(config.db_path):
        print("❌ lastro.db não encontrado. Execute `lastro sync` primeiro.")
        return

    from lastro.db import DatabaseManager
    db = DatabaseManager(config.db_path)
    s = db.stats()

    print("📊 Lastro — Estatísticas")
    print(f"   Sessões registradas:  {s['sessoes']}")
    print(f"   Aprovações:           {s['aprovacoes']}")
    print(f"   Syncs executados:     {s['syncs']}")
    print(f"   Sessões com erro:     {s['sessoes_com_erro']}")
    print(f"   Custo total (USD):    ${s['custo_total']:.4f}")
    print(f"   Resumos finais:       {s['resumos']} ({s['resumos_pendentes']} pendentes)")
    print(f"   Não relevantes:       {s['sessoes_nao_relevantes']}")
    print(f"   Último sync ok:       {s['ultimo_sync_ok']}")

    top = db.query(
        "SELECT titulo, qtd_erros FROM tb_sessao "
        "WHERE qtd_erros > 0 ORDER BY qtd_erros DESC LIMIT 5"
    )
    if top:
        print("\n   🔥 Sessões com mais erros:")
        for t in top:
            print(f"      {t['qtd_erros']:3d} erros — {t['titulo'][:70]}")


def cmd_resumos(args: list[str], config: LastroConfig) -> None:
    """Gera os resumos finais pendentes das sessões (IA local + fallback)."""
    limite = 10
    continuo = False
    refazer = False
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--continuo":
            continuo = True
        elif a == "--refazer":
            refazer = True
        elif a == "--limite" and i + 1 < len(args):
            i += 1
            try:
                limite = int(args[i])
            except ValueError:
                pass
        i += 1

    if not os.path.exists(config.db_path):
        print("❌ lastro.db não encontrado. Execute `lastro sync` primeiro.")
        return

    from lastro.db import DatabaseManager
    from lastro.resumo import processar_resumos

    db = DatabaseManager(config.db_path)
    if refazer:
        n = db.limpar_resumos_heuristicos()
        print(f"♻️  {n} resumo(s) heurístico(s) zerado(s) para regeneração.")

    pend = db.contar_pendentes_resumo()
    print(f"🧠 Lastro → resumos finais (pendentes: {pend} · motor: "
          f"{config.resumo.motor} · modelo: {config.resumo.modelo})")
    if pend == 0:
        print("   ✅ Nada pendente.")
    else:
        total: dict[str, int] = {"gerados": 0, "ia": 0, "heuristica": 0, "falhas": 0}
        processados = 0
        while True:
            restante = limite - processados
            if not continuo and restante <= 0:
                break
            passo = 25 if continuo else min(25, restante)
            stats = processar_resumos(config.state_db, config.db_path,
                                      config.resumo, limite=passo)
            for k in total:
                total[k] += stats[k]
            if stats["gerados"] == 0:
                break
            processados += stats["gerados"]
            print(f"   … progresso: {total['gerados']} gerado(s) "
                  f"({total['ia']} IA · {total['heuristica']} heurística)")

        print(f"✅ Resumos: {total['gerados']} gerado(s) — {total['ia']} IA, "
              f"{total['heuristica']} heurística, {total['falhas']} falha(s)")

    # Re-renderiza o diário com os resumos atualizados (sem gerar novos)
    from lastro.engine import run_collector
    limite_sync = config.resumo.limite_por_sync
    config.resumo.limite_por_sync = 0
    try:
        result = run_collector("sessions", state_db=config.state_db,
                               vault_path=config.vault_path, config=config)
        _print_result(result)
    finally:
        config.resumo.limite_por_sync = limite_sync


def main() -> None:
    argv = sys.argv[1:] if len(sys.argv) > 1 else ["sync"]
    cmd, rest, config_path = _parse_args(argv)

    config = load_or_default(config_path)

    if cmd == "sync":
        cmd_sync(rest, config)
    elif cmd == "status":
        cmd_status(rest, config)
    elif cmd == "list":
        cmd_list(rest, config)
    elif cmd == "query":
        cmd_query(rest, config)
    elif cmd == "stats":
        cmd_stats(rest, config)
    elif cmd == "resumos":
        cmd_resumos(rest, config)
    else:
        print(f"❌ Comando desconhecido: {cmd}")
        print("   Disponíveis: sync, status, list, query, stats, resumos")
        sys.exit(1)


if __name__ == "__main__":
    main()
