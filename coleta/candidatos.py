"""Lista de candidatos congelada em arquivo.

A busca do GitHub muda com o tempo (estrelas sobem e descem, repositórios surgem),
então a lista é gravada uma vez, com a data da busca, e reaproveitada nas execuções
seguintes e pelo grupo replicador. Para refazer a busca, apague o arquivo.
"""

from __future__ import annotations

import csv
from collections.abc import Iterable
from datetime import date
from pathlib import Path

from coleta.modelos import Candidato, ler_data
from coleta.saida import gravar_csv
from coleta.selecao import ResumoFaixa

COLUNAS_CANDIDATOS = [
    "repositorio", "faixa", "subintervalo", "estrelas", "linguagem", "criado_em", "branch_padrao",
    "url", "buscado_em",
]
COLUNAS_FAIXAS = ["faixa", "subintervalo", "consulta", "disponiveis", "obtidos", "buscado_em"]


def arquivo_faixas(arquivo_candidatos: Path) -> Path:
    return arquivo_candidatos.with_name(f"{arquivo_candidatos.stem}_faixas.csv")


def gravar_candidatos(
    arquivo: Path, candidatos: Iterable[Candidato], faixas: Iterable[ResumoFaixa], buscado_em: date
) -> None:
    gravar_csv(arquivo, (
        {
            "repositorio": c.nome, "faixa": c.faixa, "subintervalo": c.subintervalo,
            "estrelas": c.estrelas, "linguagem": c.linguagem, "criado_em": c.criado_em, "branch_padrao": c.branch_padrao, "url": c.url, "buscado_em": buscado_em,
        }
        for c in candidatos
    ), COLUNAS_CANDIDATOS)
    gravar_csv(arquivo_faixas(arquivo), ({**vars(f), "buscado_em": buscado_em} for f in faixas), COLUNAS_FAIXAS)


def ler_candidatos(arquivo: Path) -> tuple[list[Candidato], list[ResumoFaixa], str]:
    """Candidatos, resumo das faixas e a data da busca gravados por `gravar_candidatos`."""
    with arquivo.open(encoding="utf-8", newline="") as entrada:
        linhas = list(csv.DictReader(entrada))
    candidatos = [
        Candidato(
            nome=l["repositorio"],
            estrelas=int(l["estrelas"]),
            linguagem=l["linguagem"] or None,
            criado_em=ler_data(l["criado_em"]),
            branch_padrao=l["branch_padrao"],
            url=l["url"],
            faixa=l["faixa"],
            subintervalo=l.get("subintervalo", ""),
        )
        for l in linhas
    ]
    faixas = []
    caminho_faixas = arquivo_faixas(arquivo)
    if caminho_faixas.is_file():
        with caminho_faixas.open(encoding="utf-8", newline="") as entrada:
            faixas = [
                ResumoFaixa(l["faixa"], l["consulta"], int(l["disponiveis"]), int(l["obtidos"]),
                            l.get("subintervalo", ""))
                for l in csv.DictReader(entrada)
            ]
    buscado_em = linhas[0]["buscado_em"] if linhas else ""
    return candidatos, faixas, buscado_em
