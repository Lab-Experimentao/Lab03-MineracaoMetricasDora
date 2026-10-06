"""Cache em disco (SQLite) das respostas da API do GitHub.

Cada resposta fica numa linha, identificada pela URL canônica da requisição
(com os parâmetros da query ordenados). Cada gravação é confirmada na hora, então
uma interrupção (rate limit, queda de rede, Ctrl+C) nunca perde o que já foi baixado
e, ao rodar de novo, as chamadas já feitas são lidas daqui em vez da API.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

ESQUEMA = """
CREATE TABLE IF NOT EXISTS respostas (
    chave     TEXT PRIMARY KEY,
    status    INTEGER NOT NULL,
    corpo     TEXT,
    links     TEXT NOT NULL,
    obtido_em TEXT NOT NULL
)
"""


def url_canonica(url: str) -> str:
    """Normaliza a URL para servir de chave: parâmetros da query em ordem alfabética."""
    partes = urlsplit(url)
    query = urlencode(sorted(parse_qsl(partes.query, keep_blank_values=True)))
    return urlunsplit((partes.scheme, partes.netloc.lower(), partes.path, query, ""))


@dataclass(frozen=True)
class RespostaCacheada:
    status: int
    dados: Any
    links: dict[str, str]


class CacheRespostas:
    """Guarda respostas da API num banco SQLite em `caminho`."""

    def __init__(self, caminho: str | Path) -> None:
        caminho = Path(caminho)
        caminho.parent.mkdir(parents=True, exist_ok=True)
        self._conexao = sqlite3.connect(caminho)
        self._conexao.execute(ESQUEMA)
        self._conexao.commit()

    def obter(self, url: str) -> RespostaCacheada | None:
        linha = self._conexao.execute(
            "SELECT status, corpo, links FROM respostas WHERE chave = ?", (url_canonica(url),)
        ).fetchone()
        if linha is None:
            return None
        status, corpo, links = linha
        return RespostaCacheada(
            status=status,
            dados=json.loads(corpo) if corpo is not None else None,
            links=json.loads(links),
        )

    def gravar(self, url: str, status: int, dados: Any, links: dict[str, str]) -> None:
        self._conexao.execute(
            "INSERT OR REPLACE INTO respostas (chave, status, corpo, links, obtido_em) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                url_canonica(url),
                status,
                json.dumps(dados, ensure_ascii=False) if dados is not None else None,
                json.dumps(links),
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        self._conexao.commit()

    def __len__(self) -> int:
        return self._conexao.execute("SELECT COUNT(*) FROM respostas").fetchone()[0]

    def fechar(self) -> None:
        self._conexao.close()
