"""Distribuição da classificação DORA de referência (C1) sobre o `metricas.csv`.

As classes por dimensão e a geral já vêm calculadas da etapa de métricas
(`metricas/classificacao.py`); aqui elas são contadas e cruzadas, e a classe geral é
recalculada só nos cenários de sensibilidade. Nenhuma função faz I/O.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from statistics import median

import pandas as pd

from metricas.classificacao import Categoria, categoria_geral

CLASSES = [c.rotulo for c in sorted(Categoria, reverse=True)]  # Elite, High, Medium, Low
SEM_DADOS = "sem dados"
POR_ROTULO = {c.rotulo: c for c in Categoria}

# Dimensões da classe geral, na ordem da tabela de referência: (nome, coluna de metricas.csv).
DIMENSOES = (
    ("frequencia", "classe_frequencia"),
    ("lead_time", "classe_lead_time"),
    ("cfr", "classe_cfr"),
    ("recuperacao", "classe_recuperacao"),
)
GERAL = ("geral", "classe_geral")

COLUNAS_DISTRIBUICAO = ["dimensao", "classe", "repositorios", "proporcao"]


def distribuicao(df: pd.DataFrame) -> pd.DataFrame:
    """Repositórios por classe em cada dimensão e na geral, de Elite a Low, mais "sem dados"."""
    linhas = []
    for dimensao, coluna in (*DIMENSOES, GERAL):
        contagem = df[coluna].fillna(SEM_DADOS).value_counts()
        for classe in (*CLASSES, SEM_DADOS):
            repositorios = int(contagem.get(classe, 0))
            linhas.append({
                "dimensao": dimensao,
                "classe": classe,
                "repositorios": repositorios,
                "proporcao": repositorios / len(df) if len(df) else float("nan"),
            })
    return pd.DataFrame(linhas, columns=COLUNAS_DISTRIBUICAO)


COM_RECUPERACAO = "com recuperação"
SEM_FALHA = "sem falha de CI"
SO_CENSURADOS = "só episódios censurados"
FALHA_ANTES_DO_SUCESSO = "falhas só antes do primeiro sucesso"


def situacao_recuperacao(linha: pd.Series) -> str:
    """Por que o repositório tem ou não tempo de recuperação."""
    if pd.notna(linha["recuperacao_horas"]):
        return COM_RECUPERACAO
    if linha["runs_falha"] == 0:
        return SEM_FALHA
    if linha["episodios_censurados"] > 0:
        return SO_CENSURADOS
    # Falhas antes do primeiro sucesso de cada workflow não abrem episódio.
    return FALHA_ANTES_DO_SUCESSO


COLUNAS_METRICAS_USADAS = ["situacao_recuperacao", "metricas_usadas", *CLASSES, "repositorios"]


def perfil_metricas_usadas(df: pd.DataFrame) -> pd.DataFrame:
    """Classe geral pelo número de dimensões usadas e pelo motivo de faltar a recuperação."""
    ordem = [COM_RECUPERACAO, SEM_FALHA, SO_CENSURADOS, FALHA_ANTES_DO_SUCESSO]
    perfil = pd.DataFrame({
        "situacao_recuperacao": pd.Categorical(df.apply(situacao_recuperacao, axis=1), categories=ordem),
        "metricas_usadas": df[[c for _, c in DIMENSOES]].notna().sum(axis=1),
        "classe_geral": df["classe_geral"],
    })
    tabela = (
        pd.crosstab([perfil["situacao_recuperacao"], perfil["metricas_usadas"]], perfil["classe_geral"])
        .reindex(columns=CLASSES, fill_value=0)
    )
    tabela["repositorios"] = tabela.sum(axis=1)
    tabela = tabela.reset_index().sort_values(["situacao_recuperacao", "metricas_usadas"], ascending=[True, False])
    tabela["situacao_recuperacao"] = tabela["situacao_recuperacao"].astype(str)
    return tabela.reset_index(drop=True)[COLUNAS_METRICAS_USADAS]


def _notas(df: pd.DataFrame) -> dict[str, list[Categoria | None]]:
    """Categoria de cada dimensão (None quando falta), uma lista por dimensão.

    Listas, e não colunas de DataFrame: o pandas trocaria o None por NaN.
    """
    return {
        dimensao: [POR_ROTULO.get(v) if isinstance(v, str) else None for v in df[coluna]]
        for dimensao, coluna in DIMENSOES
    }


def _mediana_empatada(notas: list[Categoria | None]) -> bool:
    """A mediana das notas termina em ,5: o arredondamento decide a classe."""
    validas = [int(n) for n in notas if n is not None]
    return bool(validas) and median(validas) % 1 == 0.5


@dataclass(frozen=True)
class Cenario:
    nome: str
    descricao: str
    arredondar: Callable[[float], int] = math.floor
    sem_falha_como_elite: bool = False


CENARIOS = (
    Cenario("referencia", "C1: mediana das notas arredondada para baixo; sem recuperação, usa as demais"),
    Cenario("arredondamento_para_cima", "medianas terminadas em ,5 arredondadas para cima", arredondar=math.ceil),
    Cenario("sem_falha_como_elite",
            "repositórios sem nenhuma falha de CI recebem Elite em recuperação", sem_falha_como_elite=True),
)
COLUNAS_SENSIBILIDADE = ["cenario", "descricao", *CLASSES, "sem_dados", "empates", "mudam_de_classe"]


def _notas_cenario(df: pd.DataFrame, cenario: Cenario) -> list[list[Categoria | None]]:
    notas = _notas(df)
    if cenario.sem_falha_como_elite:
        notas["recuperacao"] = [
            Categoria.ELITE if nota is None and falhas == 0 else nota
            for nota, falhas in zip(notas["recuperacao"], df["runs_falha"])
        ]
    return [list(linha) for linha in zip(*notas.values())]


def classes_gerais(df: pd.DataFrame, cenario: Cenario) -> pd.Series:
    """Classe geral (rótulo, ou None) de cada repositório no cenário."""
    gerais = [categoria_geral(notas, cenario.arredondar) for notas in _notas_cenario(df, cenario)]
    return pd.Series([None if g is None else g.rotulo for g in gerais], index=df.index, dtype=object)


def sensibilidade(df: pd.DataFrame) -> pd.DataFrame:
    """Distribuição da classe geral na referência e em cada cenário alternativo.

    `empates`: repositórios cuja mediana das notas cai entre duas classes (termina em ,5), em
    que o critério de arredondamento decide a classe. `mudam_de_classe`: repositórios com classe
    diferente da referência.
    """
    referencia = classes_gerais(df, CENARIOS[0])
    linhas = []
    for cenario in CENARIOS:
        gerais = classes_gerais(df, cenario)
        contagem = gerais.value_counts()
        linhas.append({
            "cenario": cenario.nome,
            "descricao": cenario.descricao,
            **{classe: int(contagem.get(classe, 0)) for classe in CLASSES},
            "sem_dados": int(gerais.isna().sum()),
            "empates": sum(_mediana_empatada(notas) for notas in _notas_cenario(df, cenario)),
            "mudam_de_classe": int((gerais.fillna(SEM_DADOS) != referencia.fillna(SEM_DADOS)).sum()),
        })
    return pd.DataFrame(linhas, columns=COLUNAS_SENSIBILIDADE)


COLUNAS_LIMITANTE = ["classe_geral", "repositorios", *(f"{d}_abaixo" for d, _ in DIMENSOES)]


def dimensao_limitante(df: pd.DataFrame) -> pd.DataFrame:
    """Para cada classe geral, quantos repositórios têm cada dimensão abaixo dela.

    Mostra o que puxa a classe geral para baixo. A última linha (`todas`) soma as classes.
    """
    notas = _notas(df)
    geral = [POR_ROTULO.get(v) if isinstance(v, str) else None for v in df["classe_geral"]]
    abaixo = pd.DataFrame({
        f"{d}_abaixo": [n is not None and g is not None and n < g for n, g in zip(notas[d], geral)]
        for d, _ in DIMENSOES
    }, index=df.index)
    linhas = []
    for classe in (*CLASSES, "todas"):
        filtro = df["classe_geral"].notna() if classe == "todas" else df["classe_geral"] == classe
        linhas.append({
            "classe_geral": classe,
            "repositorios": int(filtro.sum()),
            **{coluna: int(abaixo.loc[filtro, coluna].sum()) for coluna in abaixo},
        })
    return pd.DataFrame(linhas, columns=COLUNAS_LIMITANTE)
