"""Etapa de validação: sorteia a amostra-ouro, gera uma planilha de rotulagem por avaliador
e, quando todas estão preenchidas, calcula a concordância e o consenso. Com o consenso
pronto, avalia as versões da heurística de release corretiva (precisão, recall e F1).

Saída em `<saida.dir>/validacao/`. Não acessa a API: lê `metricas.csv` e os CSVs brutos.
Planilhas já existentes não são sobrescritas, para não apagar rótulos preenchidos.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from pipeline.config import Config
from validacao import concordancia as co
from validacao import heuristica as he
from validacao.amostra import com_textos, sortear_releases, sortear_repositorios
from validacao.planilha import gerar_planilha

log = logging.getLogger(__name__)

ARQUIVO_AMOSTRA = "amostra_ouro.csv"
ARQUIVO_DESEMPATES = "desempates.csv"
ARQUIVO_CONCORDANCIA = "concordancia.csv"
ARQUIVOS_CONSENSO = {"repositorios": "consenso_repositorios.csv", "releases": "consenso_releases.csv"}
ARQUIVO_HEURISTICA = "heuristica_versoes.csv"
ARQUIVO_ERROS_HEURISTICA = "heuristica_erros.csv"


def _ler(caminho: Path) -> pd.DataFrame:
    if not caminho.is_file():
        raise FileNotFoundError(f"{caminho} não encontrado; rode antes as etapas de coleta e métricas")
    return pd.read_csv(caminho, dtype=str, keep_default_na=False)


def _titulos_commits(caminho: Path, repositorios: list[str]) -> pd.DataFrame:
    """Títulos dos commits só dos repositórios sorteados (o commits.csv tem ~500 MB)."""
    if not caminho.is_file():
        raise FileNotFoundError(f"{caminho} não encontrado; rode antes as etapas de coleta e métricas")
    colunas = ["repositorio", "tag_anterior", "tag", "titulo"]
    blocos = pd.read_csv(caminho, dtype=str, keep_default_na=False, usecols=colunas, chunksize=200_000)
    return pd.concat([b[b["repositorio"].isin(repositorios)] for b in blocos], ignore_index=True)


def arquivo_rotulagem(destino: Path, avaliador: str) -> Path:
    return destino / f"rotulagem_{avaliador}.xlsx"


def executar(config: Config) -> None:
    cfg = config.validacao_manual
    destino = config.saida_dir / "validacao"

    # O sorteio só serve para gerar planilhas; com todas já existentes, não lê os brutos.
    if all(arquivo_rotulagem(destino, a).exists() for a in cfg.avaliadores):
        log.info("planilhas de todos os avaliadores já existem em %s; sorteio não refeito", destino)
    else:
        gerar_planilhas(config, destino)
    calcular_concordancia(config, destino)
    avaliar_heuristica(config, destino)


def gerar_planilhas(config: Config, destino: Path) -> None:
    """Sorteia a amostra-ouro e grava as planilhas que ainda não existem."""
    cfg = config.validacao_manual
    brutos = config.saida_dir / "brutos"

    repositorios = sortear_repositorios(_ler(config.saida_dir / "metricas.csv"), cfg.n_repositorios, cfg.semente)
    compares, releases = _ler(brutos / "compares.csv"), _ler(brutos / "releases.csv")
    if "notas" not in releases.columns:
        raise FileNotFoundError(f"{brutos / 'releases.csv'} sem a coluna 'notas'; rode de novo a etapa de coleta")
    amostra = sortear_releases(compares, releases, repositorios, cfg.releases_por_repositorio, cfg.semente)
    para_rotular = com_textos(amostra, compares, releases, _titulos_commits(brutos / "commits.csv", repositorios))

    destino.mkdir(parents=True, exist_ok=True)
    amostra.to_csv(destino / ARQUIVO_AMOSTRA, index=False, encoding="utf-8")
    log.info("amostra-ouro: %d repositórios, %d releases (semente %d), gravada em %s",
             len(repositorios), len(amostra), cfg.semente, destino / ARQUIVO_AMOSTRA)

    for avaliador in cfg.avaliadores:
        planilha = arquivo_rotulagem(destino, avaliador)
        if planilha.exists():
            log.info("%s já existe; mantida (apague-a para gerar de novo em branco)", planilha)
            continue
        gerar_planilha(planilha, para_rotular)
        log.info("planilha de rotulagem gravada em %s", planilha)


def calcular_concordancia(config: Config, destino: Path) -> None:
    """Kappa e consenso, se todas as planilhas estiverem completas; senão, só avisa o que falta."""
    planilhas = {}
    for avaliador in config.validacao_manual.avaliadores:
        abas = co.ler_planilha(arquivo_rotulagem(destino, avaliador))
        faltando = co.problemas(abas)
        if faltando:
            log.warning("rotulagem de %s incompleta (%d problema(s), ex.: %s); concordância não calculada",
                        avaliador, len(faltando), "; ".join(faltando[:3]))
            return
        planilhas[avaliador] = abas

    arquivo_desempates = destino / ARQUIVO_DESEMPATES
    if not arquivo_desempates.exists():
        pd.DataFrame(columns=co.COLUNAS_DESEMPATES).to_csv(arquivo_desempates, index=False, encoding="utf-8")
        log.info("%s criado em branco, para registrar as decisões de reunião", arquivo_desempates)
    resumo, consensos = co.calcular(planilhas, co.ler_desempates(arquivo_desempates))

    resumo.to_csv(destino / ARQUIVO_CONCORDANCIA, index=False, encoding="utf-8")
    for aba, tabela in consensos.items():
        tabela.to_csv(destino / ARQUIVOS_CONSENSO[aba], index=False, encoding="utf-8")
    for r in resumo.itertuples():
        log.info("%s: kappa de Fleiss %.3f (%s); %d unânimes, %d por maioria, %d sem maioria, %d pendentes",
                 r.dimensao, r.kappa, r.interpretacao, r.unanimes, r.maioria, r.sem_maioria, r.pendentes)
    for aba, tabela in consensos.items():
        regras = tabela.filter(like="_regra")
        for coluna in regras:
            for _, linha in tabela[regras[coluna] == co.PENDENTE].iterrows():
                item = " ".join(linha[c] for c in co.CHAVES[aba])
                log.warning("sem maioria em %s de %s: decida em reunião e registre em %s",
                            coluna.removesuffix("_regra"), item, arquivo_desempates)


def avaliar_heuristica(config: Config, destino: Path) -> None:
    """Precisão, recall e F1 de cada versão da heurística frente ao consenso das releases."""
    arquivo_consenso = destino / ARQUIVOS_CONSENSO["releases"]
    if not arquivo_consenso.is_file():
        log.warning("%s não encontrado; heurística de release corretiva não avaliada", arquivo_consenso)
        return
    consenso = _ler(arquivo_consenso)
    pendentes = consenso["corretiva_regra"] == co.PENDENTE
    if pendentes.any():
        log.warning("%d releases sem consenso ficaram fora da avaliação da heurística", pendentes.sum())
        consenso = consenso[~pendentes].reset_index(drop=True)
    arquivo_commits = config.saida_dir / "brutos" / "commits.csv"
    if not arquivo_commits.is_file():
        log.warning("%s não encontrado; heurística de release corretiva não avaliada", arquivo_commits)
        return
    commits = _titulos_commits(arquivo_commits, sorted(consenso["repositorio"].unique()))

    resumo, erros = he.avaliar_versoes(consenso, commits)
    resumo.to_csv(destino / ARQUIVO_HEURISTICA, index=False, encoding="utf-8")
    erros.to_csv(destino / ARQUIVO_ERROS_HEURISTICA, index=False, encoding="utf-8")
    for r in resumo.itertuples():
        log.info("heurística %s: precisão %.3f, recall %.3f, F1 %.3f%s", r.versao, r.precisao, r.recall, r.f1,
                 "" if r.f1 >= he.F1_MINIMO else f" (abaixo de {he.F1_MINIMO})")
