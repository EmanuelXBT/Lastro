# Lastro

> **Organização para a era da IA.**
> Do `state.db` ao Obsidian — transforme dados brutos de agentes em notas markdown linkadas.

[![Python](https://img.shields.io/badge/Python-3.9%2B-blue)](https://python.org)
[![Versão](https://img.shields.io/badge/Versão-0.1.0-purple)](https://github.com/EmanuelXBT/Lastro/releases)
[![Licença](https://img.shields.io/badge/Licença-MIT-green)](LICENSE)

---

## O que é?

O **Lastro** é um sistema de coletores que extrai dados dos bastidores do [Hermes Agent](https://github.com/NousResearch/hermes-agent) e os transforma em notas organizadas no [Obsidian](https://obsidian.md).

Cada interação com seu agente de IA gera decisões, aprovações, descobertas e erros. Mas isso tudo fica preso num `state.db` ilegível. O Lastro transforma esse ruído em **notas markdown com wikilinks** — navegáveis, buscáveis, conectadas ao resto do seu conhecimento.

```
state.db ──→ lastro sync ──→ vault Obsidian
  (SQLite)      (Python)       (markdown + wikilinks)
```

---

## Observações

Caso ainda não possua Hermes no UmbrelOS, visite este guia: https://github.com/EmanuelXBT/hermes-agent-umbrel

## Instalação

```bash
git clone https://github.com/EmanuelXBT/lastro.git
cd lastro
```

Zero dependências externas. Só precisa de **Python 3.9+** e acesso ao `state.db` do Hermes.

### Timezone

O Lastro converte automaticamente timestamps UTC para o horário local do seu UmbrelOS. A detecção segue esta prioridade:

1. Variável de ambiente `$TZ`
2. Arquivo `/etc/timezone` (Debian/Ubuntu)
3. Symlink `/etc/localtime` (se diferente de UTC)
4. Arquivo `.tz` na raiz do projeto (crie com o nome do timezone, ex: `America/Sao_Paulo`)
5. Fallback: UTC

Para configurar manualmente:

```bash
echo "America/Sao_Paulo" > .tz
```

O arquivo `.tz` está no `.gitignore` — cada instalação tem o seu.

---

## Uso

```bash
# Sincronizar tudo
python3 -m lastro sync

# Só um coletor específico
python3 -m lastro sync approvals

# Ver status
python3 -m lastro status

# Listar coletores disponíveis
python3 -m lastro list
```

### Configuração padrão

| Parâmetro | Valor |
|---|---|
| State DB | `/opt/data/state.db` |
| Vault | `/opt/data/obsidian-vault/` |

Para customizar paths, edite `engine.py` ou passe argumentos via API Python.

---

## Coletores

### ✅ `approvals` — Histórico de Aprovações

Extrai todas as aprovações de comandos do Hermes (terminal + clarify).

**Entrada:** `state.db` → tabelas `messages` + `sessions`

**Saída no vault:**
- `Historico_Aprovacoes.md` — índice consolidado com tabelas por projeto (data + **hora local**)
- `YYYY-MM-DD.md` — notas diárias com detalhes de cada aprovação (risco, comando, sessão, horário)
- Detecção de sessões YOLO (autorização em lote)
- Backlinks navegáveis entre notas
- Timestamps convertidos de UTC para o timezone do UmbrelOS

### 🛰️ `hub` — Nó central do grafo

Gera e mantém `Lastro.md`, o MOC (Map of Content) que conecta tudo que o pipeline produz.

**Entrada:** o próprio vault (vault-driven — não lê o `state.db`)

**Saída no vault:**
- `Lastro.md` — hub com links para o histórico de aprovações, últimas notas diárias e âncoras de seção da nota mestra do harness (SOUL · Skills · Runtime)
- Tabela de status do pipeline (coletores ativos, timezone, último sync)
- Alertas de links quebrados (notas mestras ausentes)

> O hub roda **por último** no engine, para indexar os arquivos gerados pelos coletores de dados no mesmo sync. A nota é regenerada a cada sync — edições manuais são perdidas.

---

## Arquitetura

```
lastro/
├── __init__.py              # "Organização para a era da IA"
├── __main__.py              # python3 -m lastro
├── cli.py                   # CLI: sync, status, list
├── engine.py                # Orquestrador de coletores
├── schemas.py               # Modelos: ApprovalEvent, SessionInfo, CollectorResult
├── tz.py                    # Detecção automática de timezone (5 níveis)
├── vault.py                 # Interface Obsidian: wikilinks, frontmatter, notas
├── collectors/
│   ├── __init__.py          # Registro de coletores
│   ├── hermes_approvals.py  # Coletor de aprovações (com hora local)
│   └── hub.py               # Hub central Lastro.md (MOC do grafo)
```

### Interface de um coletor

Todo coletor implementa uma única função:

```python
def run(state_db: str, vault_path: str) -> CollectorResult:
    """Extrai dados e renderiza markdown no vault."""
    ...
```

Para adicionar um coletor novo:
1. Crie `collectors/seu_coletor.py`
2. Implemente `run(state_db, vault_path)`
3. Registre no `engine.py` → dict `COLLECTORS`

---

## Roadmap

- [x] `approvals` — Histórico de aprovações
- [x] `timezone` — Detecção automática de timezone do UmbrelOS
- [x] `hub` — Nó central Lastro.md (MOC) conectando o grafo do vault
- [ ] `sessions` — Diário automático de sessões (resumo + decisões)
- [ ] `cron` — Log de cron jobs executados
- [ ] `skills` — Catálogo de skills instaladas
- [ ] `sistema` — Métricas do Umbrel (disco, RAM, uptime)
- [ ] Templates Jinja2 customizáveis
- [ ] `config.yaml` para paths e preferências

---

## Por que "Lastro"?

**Lastro** (substantivo masculino, PT-BR):
1. *Náutica* — peso que dá estabilidade à embarcação
2. *Figurado* — base sólida, fundamento, aquilo que dá firmeza

O Lastro dá peso e estrutura ao conhecimento gerado pelos seus agentes de IA. Transforma logs efêmeros em conhecimento durável.

---

## Licença

MIT © 2026 Emanuel Filipe ([@EmanuelXBT](https://github.com/EmanuelXBT))
