"""Metadados do repositório que não vêm no item da busca."""

from __future__ import annotations

import logging
from urllib.parse import parse_qs, urlsplit

from coleta.cliente import ErroAPI

log = logging.getLogger(__name__)


def numero_ultima_pagina(links: dict[str, str]) -> int | None:
    """Número da página em rel="last" do cabeçalho Link; None se não houver."""
    url = links.get("last")
    if url is None:
        return None
    pagina = parse_qs(urlsplit(url).query).get("page")
    return int(pagina[0]) if pagina else None


def contar_contribuidores(cliente, repo: str) -> int | None:
    """Nº de contribuidores (incluindo anônimos) com per_page=1: a última página é o total.

    None quando a API se recusa a listar (histórico grande demais, HTTP 403).
    """
    try:
        resposta = cliente.obter(f"/repos/{repo}/contributors", {"per_page": 1, "anon": "true"})
    except ErroAPI as erro:
        if erro.status != 403:
            raise
        log.warning("%s: a API não lista os contribuidores (%s)", repo, erro)
        return None
    ultima = numero_ultima_pagina(resposta.links)
    if ultima is not None:
        return ultima
    # Sem Link: tudo coube em uma página. Repositório vazio responde 204, sem corpo.
    return len(resposta.dados or [])
