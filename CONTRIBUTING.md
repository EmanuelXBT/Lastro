# 🤝 Contribuindo com o Lastro

Obrigado pelo interesse em contribuir! O Lastro é um sistema de coletores Python que transforma dados do Hermes Agent em notas markdown no Obsidian.

---

## 🚀 Como Contribuir

### 1. Fork e Clone

```bash
git clone https://github.com/SEU_USER/Lastro.git
cd Lastro
```

### 2. Ambiente

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

### 3. Desenvolva

- **Zero dependências externas** — apenas stdlib Python
- Todo coletor implementa `run(state_db: str, vault_path: str) -> CollectorResult`
- Registre novos coletores no dict `COLLECTORS` em `engine.py`
- Mantenha type hints consistentes

### 4. Commits

Use [Conventional Commits](https://www.conventionalcommits.org/):

```
feat: adiciona coletor de sessões
fix: corrige parse de timestamp no hermes_approvals
refactor: extrai timezone para módulo dedicado
docs: atualiza README com novo coletor
chore: atualiza .gitignore
```

### 5. Pull Request

- Descreva **o quê** e **por quê**
- Referencie a issue (`Closes #N`)
- Teste localmente: `python3 -m lastro sync`

---

## 🧱 Arquitetura

```
lastro/
├── collectors/       # Coletores: cada um gera notas no vault
├── engine.py         # Orquestrador
├── schemas.py        # Modelos de dados (dataclasses)
├── tz.py             # Detecção automática de timezone
├── vault.py          # Interface com Obsidian vault
└── cli.py            # CLI: sync, status, list
```

---

## ❓ Dúvidas

Abra uma [issue](https://github.com/EmanuelXBT/Lastro/issues) ou entre em contato: **contato.emanuel2002@gmail.com**
