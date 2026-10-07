"""Cache em SQLite das respostas da API, com commit a cada gravação para permitir retomada.

O corpo é gravado em JSON comprimido com zlib: as páginas de workflow runs têm ~1,4 MB
de JSON e comprimem cerca de 10 vezes. Corpos gravados como texto (versões anteriores
do cache) continuam sendo lidos.
"""

from __future__ import annotations

import json
import sqlite3
import zlib
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
    """Chave do cache: URL com os parâmetros da query ordenados."""
    partes = urlsplit(url)
    query = urlencode(sorted(parse_qsl(partes.query, keep_blank_values=True)))
    return urlunsplit((partes.scheme, partes.netloc.lower(), partes.path, query, ""))


def _ler_corpo(corpo: bytes | str | None) -> Any:
    if corpo is None:
        return None
    if isinstance(corpo, bytes):
        corpo = zlib.decompress(corpo).decode()
    return json.loads(corpo)


@dataclass(frozen=True)
class RespostaCacheada:
    status: int
    dados: Any
    links: dict[str, str]


class CacheRespostas:
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
            dados=_ler_corpo(corpo),
            links=json.loads(links),
        )

    def gravar(self, url: str, status: int, dados: Any, links: dict[str, str]) -> None:
        self._conexao.execute(
            "INSERT OR REPLACE INTO respostas (chave, status, corpo, links, obtido_em) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                url_canonica(url),
                status,
                zlib.compress(json.dumps(dados, ensure_ascii=False).encode()) if dados is not None else None,
                json.dumps(links),
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        self._conexao.commit()

    def __len__(self) -> int:
        return self._conexao.execute("SELECT COUNT(*) FROM respostas").fetchone()[0]

    def fechar(self) -> None:
        self._conexao.close()
