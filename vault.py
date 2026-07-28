"""
Lastro — vault.py
==================
Interface com o Obsidian vault. Sabe escrever notas markdown,
gerenciar wikilinks, criar notas de data, e manter a consistência
do vault.
"""

import os
from datetime import datetime, timezone
from typing import Optional


class VaultManager:
    """Gerencia leitura e escrita no vault Obsidian."""

    def __init__(self, vault_path: str):
        self.vault_path = vault_path
        os.makedirs(vault_path, exist_ok=True)

    # ── Path helpers ──────────────────────────────────────────────

    def note_path(self, filename: str) -> str:
        """Caminho absoluto para uma nota."""
        return os.path.join(self.vault_path, filename)

    def date_note_path(self, date_str: str) -> str:
        """Caminho para nota de data (YYYY-MM-DD.md)."""
        return self.note_path(f"{date_str}.md")

    def exists(self, filename: str) -> bool:
        return os.path.exists(self.note_path(filename))

    # ── Read ──────────────────────────────────────────────────────

    def read(self, filename: str) -> Optional[str]:
        """Lê conteúdo completo de uma nota."""
        path = self.note_path(filename)
        if not os.path.exists(path):
            return None
        with open(path, 'r') as f:
            return f.read()

    # ── Write ─────────────────────────────────────────────────────

    def write(self, filename: str, content: str) -> int:
        """Escreve conteúdo em uma nota. Retorna bytes escritos."""
        path = self.note_path(filename)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        content_bytes = content.encode('utf-8')
        with open(path, 'wb') as f:
            f.write(content_bytes)
        return len(content_bytes)

    # ── WikiLink helpers ──────────────────────────────────────────

    @staticmethod
    def wikilink(target: str, alias: Optional[str] = None) -> str:
        """Gera um wikilink Obsidian: [[target]] ou [[target|alias]]."""
        if alias:
            return f"[[{target}|{alias}]]"
        return f"[[{target}]]"

    @staticmethod
    def backlink(target: str, label: str = "← Voltar") -> str:
        """Gera backlink com alias."""
        return f"[[{target}|{label}]]"

    # ── Frontmatter ───────────────────────────────────────────────

    @staticmethod
    def frontmatter(**kwargs) -> str:
        """Gera YAML frontmatter simples."""
        lines = ["---"]
        for k, v in kwargs.items():
            if isinstance(v, datetime):
                v = v.isoformat()
            lines.append(f"{k}: {v}")
        lines.append("---")
        lines.append("")
        return "\n".join(lines)

    # ── Date note management ──────────────────────────────────────

    def ensure_date_note(self, date_str: str) -> str:
        """Garante que a nota de data existe, retorna o path."""
        path = self.date_note_path(date_str)
        if not os.path.exists(path):
            # Cria nota mínima
            content = f"# 📅 {date_str}\n\n"
            self.write(f"{date_str}.md", content)
        return path

    def append_to_date_note(self, date_str: str, section: str, 
                            entry: str) -> int:
        """Adiciona uma entrada a uma seção existente na nota de data."""
        filename = f"{date_str}.md"
        current = self.read(filename) or f"# 📅 {date_str}\n\n"
        
        # Se a seção não existe, cria
        section_header = f"## {section}"
        if section_header not in current:
            current += f"\n{section_header}\n\n"
        
        current += entry + "\n"
        return self.write(filename, current)
