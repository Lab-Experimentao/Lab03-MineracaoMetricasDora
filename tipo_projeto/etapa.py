"""Etapa tipo_projeto: classifica todos os repositórios da amostra pelo tipo de projeto.

1. Coleta o perfil (descrição, tópicos e README) dos repositórios de `metricas.csv` que ainda
   não estão em `perfis_repositorios.csv`; só nesse caso precisa do token.
2. Classifica cada um com a heurística de `metricas/tipo_projeto.py` (versão atual).
3. Compara cada versão da heurística com o consenso da amostra-ouro (precisão, recall e F1 por tipo).
4. Grava `tipo_projeto.csv`, com o tipo de cada repositório para a RQ 06.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

import pandas as pd

from coleta.cliente import ClienteGitHub
from coleta.perfil import coletar_perfil
from metricas.tipo_projeto import VERSAO_ATUAL, VERSOES, classificar
from pipeline.config import Config
from validacao.concordancia import PENDENTE
from validacao.tipo_projeto import COLUNAS_ERROS, COLUNAS_METRICAS, avaliar

log = logging.getLogger(__name__)

ARQUIVO_PERFIS = "perfis_repositorios.csv"
ARQUIVO_TIPOS = "tipo_projeto.csv"
ARQUIVO_VALIDACAO = "validacao/tipo_projeto_validacao.csv"
ARQUIVO_ERROS = "validacao/tipo_projeto_erros.csv"
ARQUIVO_CONSENSO = "validacao/consenso_repositorios.csv"

COLUNAS_PERFIS = ["repositorio", "descricao", "topicos", "readme"]
COLUNAS_TIPOS = ["repositorio", "tipo_heuristica", "tipo_consenso", "tipo_projeto", "origem"]


def _ler(caminho: Path) -> pd.DataFrame:
    return pd.read_csv(caminho, dtype=str, keep_default_na=False)


def _repositorios(config: Config) -> list[str]:
    arquivo = config.saida_dir / "metricas.csv"
    if not arquivo.is_file():
        raise FileNotFoundError(f"{arquivo} não encontrado; rode antes a etapa de métricas")
    return sorted(_ler(arquivo)["repositorio"])


def atualizar_perfis(config: Config, repositorios: list[str], obter_token: Callable[[], str]) -> pd.DataFrame:
    """Perfis de todos os repositórios, coletando só os que faltam no arquivo."""
    arquivo = config.saida_dir / ARQUIVO_PERFIS
    perfis = _ler(arquivo) if arquivo.is_file() else pd.DataFrame(columns=COLUNAS_PERFIS)
    faltando = [r for r in repositorios if r not in set(perfis["repositorio"])]
    if faltando:
        log.info("coletando o perfil de %d repositórios", len(faltando))
        with ClienteGitHub.de_config(config, obter_token()) as cliente:
            novos = []
            for indice, repo in enumerate(faltando, start=1):
                perfil = coletar_perfil(cliente, repo)
                novos.append({"repositorio": repo, "descricao": perfil.descricao,
                              "topicos": ";".join(perfil.topicos), "readme": perfil.readme})
                if indice % 50 == 0:
                    log.info("perfis: %d/%d", indice, len(faltando))
        perfis = pd.concat([perfis, pd.DataFrame(novos, columns=COLUNAS_PERFIS)], ignore_index=True)
        perfis.sort_values("repositorio").to_csv(arquivo, index=False, encoding="utf-8")
    return perfis[perfis["repositorio"].isin(repositorios)].sort_values("repositorio", ignore_index=True)


def classificar_perfis(perfis: pd.DataFrame, versao: str = VERSAO_ATUAL) -> pd.DataFrame:
    linhas = []
    for p in perfis.itertuples():
        resultado = classificar(p.descricao, [t for t in p.topicos.split(";") if t], p.readme, versao)
        pontos = ", ".join(f"{tipo}={n}" for tipo, n in resultado.pontos.items() if n)
        linhas.append({"repositorio": p.repositorio, "tipo_heuristica": resultado.tipo, "pontos": pontos})
    return pd.DataFrame(linhas)


def executar(config: Config, obter_token: Callable[[], str]) -> None:
    repositorios = _repositorios(config)
    perfis = atualizar_perfis(config, repositorios, obter_token)
    tipos = classificar_perfis(perfis)

    arquivo_consenso = config.saida_dir / ARQUIVO_CONSENSO
    consenso = _ler(arquivo_consenso) if arquivo_consenso.is_file() else pd.DataFrame(
        columns=["repositorio", "tipo_projeto", "tipo_projeto_regra"])
    consenso = consenso[consenso["tipo_projeto_regra"] != PENDENTE].set_index("repositorio")["tipo_projeto"]
    tipos["tipo_consenso"] = tipos["repositorio"].map(consenso).fillna("")
    # Na amostra-ouro vale o rótulo humano; nos demais, o da heurística.
    rotulado = tipos["tipo_consenso"] != ""
    tipos["tipo_projeto"] = tipos["tipo_consenso"].where(rotulado, tipos["tipo_heuristica"])
    tipos["origem"] = rotulado.map({True: "consenso", False: "heuristica"})
    tipos[COLUNAS_TIPOS].to_csv(config.saida_dir / ARQUIVO_TIPOS, index=False, encoding="utf-8")
    log.info("tipo de projeto de %d repositórios gravado em %s: %s", len(tipos),
             config.saida_dir / ARQUIVO_TIPOS, tipos["tipo_projeto"].value_counts().to_dict())

    if not rotulado.any():
        log.warning("%s sem rótulos de consenso; heurística não validada", arquivo_consenso)
        return
    consenso_ouro = tipos.loc[rotulado, ["repositorio", "tipo_consenso"]]
    tabelas, erros = [], []
    for versao in VERSOES:
        ouro = consenso_ouro.merge(classificar_perfis(perfis, versao), on="repositorio").merge(perfis, on="repositorio")
        tabelas.append(avaliar(ouro["tipo_consenso"], ouro["tipo_heuristica"]).assign(versao=versao))
        errados = ouro[ouro["tipo_consenso"] != ouro["tipo_heuristica"]].rename(
            columns={"tipo_consenso": "consenso", "tipo_heuristica": "heuristica"})
        erros.append(errados.assign(versao=versao, descricao=errados["descricao"].str.slice(0, 200)))
    metricas = pd.concat(tabelas, ignore_index=True)
    metricas[["versao", *COLUNAS_METRICAS]].to_csv(config.saida_dir / ARQUIVO_VALIDACAO, index=False, encoding="utf-8")
    pd.concat(erros, ignore_index=True)[["versao", *COLUNAS_ERROS]].to_csv(
        config.saida_dir / ARQUIVO_ERROS, index=False, encoding="utf-8")
    for m in metricas[metricas["classe"].isin(["macro", "acuracia"])].itertuples():
        log.info("tipo de projeto %s, %s: precisão %.3f, recall %.3f, F1 %.3f",
                 m.versao, m.classe, m.precisao, m.recall, m.f1)
