"""
Lastro — sanitize.py
====================
Funções de sanitização de dados sensíveis (IPs, PII) antes da
renderização em notas do vault Obsidian.

Aplica masking em strings que podem conter endereços IP, URLs com IP
e outros identificadores de infraestrutura que não devem ser expostos
em notas sincronizadas ou repositórios públicos.
"""

import re

# ── Padrões de sanitização ──────────────────────────────────────────

# IPv4: 0.0.0.0 – 255.255.255.255
_IPV4_RE = re.compile(
    r'\b(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)\.'
    r'(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)\.'
    r'(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)\.'
    r'(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)\b'
)

# IPv6 (simplificado — cobre os formatos mais comuns)
_IPV6_RE = re.compile(
    r'(?<!\w)(?:[0-9a-fA-F]{1,4}:){2,7}[0-9a-fA-F]{1,4}(?!\w)|'
    r'(?<!\w)(?:[0-9a-fA-F]{1,4}:){1,6}:[0-9a-fA-F]{1,4}(?!\w)|'
    r'(?<!\w)::1(?!\w)|'
    r'(?<!\w)fe80::[0-9a-fA-F:]*(?!\w)'
)

# URL com IP no host (ex: http://192.168.0.189:8332/path)
_URL_WITH_IP_RE = re.compile(
    r'(https?://)'
    r'(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)\.'
    r'(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)\.'
    r'(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)\.'
    r'(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)'
    r'(:\d+)?(/\S*)?'
)

# Placeholder para substituição
_IPV4_PLACEHOLDER = '[IP]'
_IPV6_PLACEHOLDER = '[IPv6]'


def sanitize(text: str) -> str:
    """Remove IPs e URLs com IP de uma string.

    Preserva a estrutura semântica (portas, paths) mas substitui
    o endereço IP pelo placeholder.

    Args:
        text: String potencialmente contendo IPs.

    Returns:
        String sanitizada.
    """
    if not text:
        return text

    # 1. URLs com IP — preserva scheme, porta e path
    def _mask_url(match: re.Match) -> str:
        scheme = match.group(1)      # 'http://' ou 'https://'
        port = match.group(2) or ''  # ':8332' ou vazio
        path = match.group(3) or ''  # '/path' ou vazio
        return f'{scheme}[IP]{port}{path}'

    text = _URL_WITH_IP_RE.sub(_mask_url, text)

    # 2. IPv6 (antes do IPv4 para evitar falsos positivos)
    text = _IPV6_RE.sub(_IPV6_PLACEHOLDER, text)

    # 3. IPv4 bare
    text = _IPV4_RE.sub(_IPV4_PLACEHOLDER, text)

    return text


# ── Testes rápidos (executáveis com: python3 -m lastro.sanitize) ────

def _test():
    cases = [
        # IPv4 bare
        ("IP 192.168.0.189 no log", "IP [IP] no log"),
        ("acessa 10.0.0.1 e 172.16.0.5", "acessa [IP] e [IP]"),
        # IPv6
        ("local ::1 loopback", "local [IPv6] loopback"),
        ("link fe80::1%eth0", "link [IPv6]%eth0"),
        # URL com IP
        ("http://192.168.0.189:8332/", "http://[IP]:8332/"),
        ("curl https://10.0.0.1/api", "curl https://[IP]/api"),
        # Misturado
        (
            "scan: URL http://192.168.0.189:8332/ + IP 192.168.0.189",
            "scan: URL http://[IP]:8332/ + IP [IP]",
        ),
        # Sem IP
        ("texto normal sem ip", "texto normal sem ip"),
        ("https://github.com/repo", "https://github.com/repo"),
    ]
    failed = 0
    for inp, expected in cases:
        got = sanitize(inp)
        status = "✅" if got == expected else "❌"
        if got != expected:
            failed += 1
            print(f"{status} IN:  {inp}")
            print(f"   EXP: {expected}")
            print(f"   GOT: {got}")
        else:
            print(f"{status} {inp}")
    print(f"\n{len(cases) - failed}/{len(cases)} passaram")


if __name__ == "__main__":
    _test()
