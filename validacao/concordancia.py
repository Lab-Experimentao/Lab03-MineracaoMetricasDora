"""Concordância entre os avaliadores e rótulos de consenso da amostra-ouro (seção 6, itens 3 e 4).

A concordância é medida com o kappa de Fleiss (`aggregate_raters` + `fleiss_kappa` do
statsmodels), em cada dimensão rotulada. O consenso segue o protocolo do grupo:

1. rótulo unânime: é o consenso;
2. sem unanimidade, mas com maioria simples (2 a 1): vale a maioria;
3. sem maioria (1-1-1): o caso é decidido em reunião e registrado em `desempates.csv`.

Uma decisão registrada em `desempates.csv` prevalece também sobre a maioria, para os
casos 2 a 1 que o grupo decidir rediscutir. Sem decisão, um 1-1-1 fica pendente.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd
from statsmodels.stats.inter_rater import aggregate_raters, fleiss_kappa

from validacao.planilha import CORRETIVA, ENTREGAS_REAIS, TIPOS_PROJETO

# Dimensão rotulada: (aba da planilha, valores aceitos).
DIMENSOES = {
    "tipo_projeto": ("repositorios", TIPOS_PROJETO),
    "entregas_reais": ("repositorios", ENTREGAS_REAIS),
    "corretiva": ("releases", CORRETIVA),
}
# Colunas que identificam cada linha da aba.
CHAVES = {"repositorios": ["repositorio"], "releases": ["repositorio", "tag"]}
# Colunas de contexto copiadas da planilha para o arquivo de consenso.
CONTEXTO = {"repositorios": ["repositorio"], "releases": ["repositorio", "tag", "tag_anterior", "publicada_em"]}

UNANIME = "unanime"
MAIORIA = "maioria"
REUNIAO = "reuniao"
PENDENTE = "pendente"

COLUNAS_DESEMPATES = ["dimensao", "repositorio", "tag", "rotulo", "justificativa"]
COLUNAS_CONCORDANCIA = [
    "dimensao", "itens", "avaliadores", "kappa", "interpretacao", "concordancia_observada",
    "unanimes", "maioria", "sem_maioria", "decididos_em_reuniao", "pendentes",
]

# Landis & Koch (1977): limite superior de cada faixa.
INTERPRETACAO = (
    (0.0, "pobre"), (0.20, "leve"), (0.40, "razoável"), (0.60, "moderada"),
    (0.80, "substancial"), (1.0, "quase perfeita"),
)


class ErroRotulos(ValueError):
    """Planilhas ou desempates que não permitem calcular a concordância."""


def ler_planilha(caminho: Path) -> dict[str, pd.DataFrame]:
    """As abas de rótulos de uma planilha, com todas as células como texto sem espaços nas pontas."""
    abas = pd.read_excel(caminho, sheet_name=list(CHAVES), dtype=str)
    return {nome: aba.fillna("").apply(lambda c: c.str.strip()) for nome, aba in abas.items()}


def problemas(abas: dict[str, pd.DataFrame]) -> list[str]:
    """Células de rótulo vazias ou com valor fora da lista, como 'aba linha N: coluna'."""
    encontrados = []
    for dimensao, (aba, valores) in DIMENSOES.items():
        for indice, valor in abas[aba][dimensao].items():
            linha = indice + 2  # cabeçalho na linha 1 do Excel
            if not valor:
                encontrados.append(f"{aba} linha {linha}: {dimensao} vazio")
            elif valor not in valores:
                encontrados.append(f"{aba} linha {linha}: {dimensao} = {valor!r} fora da lista")
    return encontrados


def tabela_rotulos(planilhas: dict[str, dict[str, pd.DataFrame]], dimensao: str) -> pd.DataFrame:
    """Uma linha por item, com o contexto e uma coluna com o rótulo de cada avaliador."""
    aba = DIMENSOES[dimensao][0]
    chaves = CHAVES[aba]
    avaliadores = list(planilhas)
    base = planilhas[avaliadores[0]][aba]
    tabela = base[CONTEXTO[aba]].copy()
    for avaliador in avaliadores:
        atual = planilhas[avaliador][aba]
        if not atual[chaves].equals(base[chaves]):
            raise ErroRotulos(
                f"a aba '{aba}' de {avaliador} não tem as mesmas linhas, na mesma ordem, "
                f"que a de {avaliadores[0]}; as planilhas devem vir da mesma amostra-ouro"
            )
        tabela[avaliador] = atual[dimensao].to_numpy()
    return tabela


def kappa(rotulos: pd.DataFrame) -> float:
    """Kappa de Fleiss de uma tabela itens x avaliadores (NaN se todos usaram uma única categoria)."""
    contagens, _ = aggregate_raters(rotulos.to_numpy())
    with np.errstate(invalid="ignore", divide="ignore"):
        return float(fleiss_kappa(contagens, method="fleiss"))


def concordancia_observada(rotulos: pd.DataFrame) -> float:
    """Proporção média de pares de avaliadores que concordam em cada item (o P̄ de Fleiss)."""
    n = rotulos.shape[1]
    pares = rotulos.apply(lambda linha: sum(c * (c - 1) for c in Counter(linha).values()), axis=1)
    return float((pares / (n * (n - 1))).mean())


def interpretar(valor: float) -> str:
    if pd.isna(valor):
        return "indefinido"
    if valor < 0:
        return "pobre"
    return next(nome for limite, nome in INTERPRETACAO[1:] if valor <= limite)


def ler_desempates(caminho: Path) -> pd.DataFrame:
    if not caminho.is_file():
        return pd.DataFrame(columns=COLUNAS_DESEMPATES)
    desempates = pd.read_csv(caminho, dtype=str, keep_default_na=False)
    faltando = set(COLUNAS_DESEMPATES) - set(desempates.columns)
    if faltando:
        raise ErroRotulos(f"{caminho.name} sem as colunas {sorted(faltando)}")
    return desempates.apply(lambda c: c.str.strip())


def _decisoes(desempates: pd.DataFrame, dimensao: str, tabela: pd.DataFrame) -> dict[tuple, str]:
    """Decisões de reunião da dimensão, por chave do item, validadas contra a tabela."""
    aba, valores = DIMENSOES[dimensao]
    chaves = CHAVES[aba]
    existentes = set(tabela[chaves].itertuples(index=False, name=None))
    decisoes = {}
    for linha in desempates[desempates["dimensao"] == dimensao].itertuples():
        chave = (linha.repositorio, linha.tag) if aba == "releases" else (linha.repositorio,)
        descricao = f"desempate de {dimensao} para {' '.join(chave)}"
        if chave not in existentes:
            raise ErroRotulos(f"{descricao}: item não está na amostra-ouro")
        if linha.rotulo not in valores:
            raise ErroRotulos(f"{descricao}: rótulo {linha.rotulo!r} fora de {list(valores)}")
        if chave in decisoes:
            raise ErroRotulos(f"{descricao}: registrado mais de uma vez")
        decisoes[chave] = linha.rotulo
    return decisoes


def consenso(rotulos: pd.Series, decisao: str | None) -> tuple[str, str]:
    """Rótulo de consenso de um item e a regra que o definiu."""
    if decisao is not None:
        return decisao, REUNIAO
    rotulo, votos = Counter(rotulos).most_common(1)[0]
    if votos == len(rotulos):
        return rotulo, UNANIME
    if votos > len(rotulos) / 2:
        return rotulo, MAIORIA
    return "", PENDENTE


def calcular(
    planilhas: dict[str, dict[str, pd.DataFrame]], desempates: pd.DataFrame
) -> tuple[pd.DataFrame, dict[str, pd.DataFrame]]:
    """Resumo da concordância por dimensão e uma tabela de consenso por aba."""
    desconhecidas = set(desempates["dimensao"]) - set(DIMENSOES)
    if desconhecidas:
        raise ErroRotulos(f"desempates com dimensão desconhecida: {sorted(desconhecidas)}")
    avaliadores = list(planilhas)
    resumo = []
    consensos: dict[str, pd.DataFrame] = {}
    for dimensao, (aba, _) in DIMENSOES.items():
        tabela = tabela_rotulos(planilhas, dimensao)
        rotulos = tabela[avaliadores]
        decisoes = _decisoes(desempates, dimensao, tabela)
        chaves = list(tabela[CHAVES[aba]].itertuples(index=False, name=None))
        linhas = [linha for _, linha in rotulos.iterrows()]
        # Os votos sozinhos (sem as reuniões) dão as contagens de concordância.
        votacao = Counter(consenso(linha, None)[1] for linha in linhas)
        resultado = [consenso(linha, decisoes.get(chave)) for chave, linha in zip(chaves, linhas)]
        regras = Counter(regra for _, regra in resultado)
        valor = kappa(rotulos)
        resumo.append({
            "dimensao": dimensao,
            "itens": len(tabela),
            "avaliadores": len(avaliadores),
            "kappa": round(valor, 4),
            "interpretacao": interpretar(valor),
            "concordancia_observada": round(concordancia_observada(rotulos), 4),
            "unanimes": votacao[UNANIME],
            "maioria": votacao[MAIORIA],
            "sem_maioria": votacao[PENDENTE],
            "decididos_em_reuniao": regras[REUNIAO],
            "pendentes": regras[PENDENTE],
        })

        atual = consensos.get(aba, tabela[CONTEXTO[aba]].copy())
        atual[dimensao] = [rotulo for rotulo, _ in resultado]
        atual[f"{dimensao}_regra"] = [regra for _, regra in resultado]
        for avaliador in avaliadores:
            atual[f"{dimensao}_{avaliador}"] = tabela[avaliador].to_numpy()
        consensos[aba] = atual
    return pd.DataFrame(resumo, columns=COLUNAS_CONCORDANCIA), consensos
