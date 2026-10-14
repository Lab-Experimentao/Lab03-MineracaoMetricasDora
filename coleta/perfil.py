"""Perfil do repositório (descrição, tópicos e README) para classificar o tipo de projeto."""

from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass

from coleta.cliente import ErroAPI

# O começo do README basta para dizer o que o projeto é e como se instala.
MAX_CARACTERES_README = 4000


@dataclass(frozen=True)
class Perfil:
    repositorio: str
    descricao: str
    topicos: tuple[str, ...]
    readme: str


def decodificar_readme(dados: dict | None) -> str:
    """Texto do README a partir da resposta de `GET /repos/{repo}/readme` (base64)."""
    if not dados or dados.get("encoding") != "base64":
        return ""
    try:
        return base64.b64decode(dados.get("content") or "").decode("utf-8", errors="replace")
    except (binascii.Error, ValueError):
        return ""


def coletar_perfil(cliente, repo: str) -> Perfil:
    """Duas chamadas: os metadados do repositório e o README (vazio se não houver)."""
    dados = cliente.obter(f"/repos/{repo}").dados or {}
    try:
        readme = decodificar_readme(cliente.obter(f"/repos/{repo}/readme").dados)
    except ErroAPI as erro:
        if erro.status != 404:
            raise
        readme = ""
    return Perfil(
        repositorio=repo,
        descricao=dados.get("description") or "",
        topicos=tuple(dados.get("topics") or ()),
        readme=readme[:MAX_CARACTERES_README],
    )
