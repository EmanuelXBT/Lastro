"""
Lastro — CLI
============
Interface de linha de comando.

Uso:
    python3 -m lastro sync              # Executa todos os coletores
    python3 -m lastro sync approvals    # Executa só o coletor de aprovações
    python3 -m lastro status            # Status dos coletores
    python3 -m lastro list              # Lista coletores disponíveis
"""

import os
import sys

# Adiciona o diretório pai ao path para suporte a execução direta do script
_parent = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _parent not in sys.path:
    sys.path.insert(0, _parent)

from lastro.schemas import CollectorResult


def cmd_sync(args: list[str]) -> None:
    """Executa coletores."""
    from lastro.engine import run_all, run_collector

    if args:
        collector_name = args[0]
        print(f"🔄 Lastro → executando coletor '{collector_name}'...")
        result = run_collector(collector_name)
        _print_result(result)
    else:
        print("🔄 Lastro → executando todos os coletores...")
        results = run_all()
        for result in results.values():
            _print_result(result)


def cmd_status(args: list[str]) -> None:
    """Mostra status do sistema."""
    from lastro.engine import status
    s = status()
    print("📊 Lastro — Status")
    print(f"   State DB: {s['state_db']} {'✅' if s['state_db_exists'] else '❌'}")
    print(f"   Vault:    {s['vault_path']} {'✅' if s['vault_exists'] else '❌'}")
    print(f"   Coletores: {', '.join(s['collectors'])}")


def cmd_list(args: list[str]) -> None:
    """Lista coletores disponíveis."""
    from lastro.engine import COLLECTORS
    print("📦 Coletores disponíveis:")
    for name in COLLECTORS:
        doc = COLLECTORS[name].__doc__ or "(sem descrição)"
        print(f"   {name:20s} — {doc.strip().split(chr(10))[0][:60]}")


def _print_result(result: CollectorResult) -> None:
    """Exibe resultado de um coletor."""
    icon = "✅" if result.ok else "⚠️"
    print(f"   {icon} {result.collector_name}: {result.events_processed} eventos → "
          f"{len(result.files_written)} arquivos")
    if result.errors:
        for err in result.errors:
            print(f"      ❌ {err}")


COMMANDS = {
    "sync": cmd_sync,
    "status": cmd_status,
    "list": cmd_list,
}


def main() -> None:
    args = sys.argv[1:] if len(sys.argv) > 1 else ["sync"]

    cmd = args[0] if args else "sync"
    rest = args[1:] if len(args) > 1 else []

    if cmd in COMMANDS:
        COMMANDS[cmd](rest)
    else:
        print(f"❌ Comando desconhecido: {cmd}")
        print(f"   Disponíveis: {', '.join(COMMANDS.keys())}")
        sys.exit(1)


if __name__ == "__main__":
    main()
