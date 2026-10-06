"""Seleção de repositórios: busca fatiada por estrelas e funil com o motivo de cada descarte."""

from __future__ import annotations

import hashlib
import logging
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from coleta import releases as rel
from coleta import workflow_runs as wr
from coleta.cliente import ErroAPI
from coleta.modelos import Candidato
from pipeline.config import Config

log = logging.getLogger(__name__)

# A busca devolve no máximo 1.000 resultados (10 páginas de 100) por consulta.
MAX_PAGINAS_BUSCA = 10

INCLUIDO = "incluido"
NAO_AVALIADO = "nao_avaliado"  # a amostra encheu antes de chegar a ele
ERRO_API = "erro_api"
SEM_ACTIONS = "sem_actions"
POUCAS_RELEASES = "poucas_releases"
POUCOS_RUNS = "poucos_runs"

# Ordem das etapas do funil e o motivo de descarte de cada uma.
ETAPAS_FUNIL = (
    ("avaliados", NAO_AVALIADO),
    ("acessiveis_pela_api", ERRO_API),
    ("usam_actions", SEM_ACTIONS),
    ("com_min_releases", POUCAS_RELEASES),
    ("com_min_runs_validos", POUCOS_RUNS),
)


def rotulo_faixa(minimo: int, maximo: int | None) -> str:
    return f">={minimo}" if maximo is None else f"{minimo}..{maximo}"


def consulta_faixa(minimo: int, maximo: int | None, filtros: str = "") -> str:
    return f"stars:{rotulo_faixa(minimo, maximo)} {filtros}".strip()


@dataclass(frozen=True)
class ResumoFaixa:
    faixa: str
    consulta: str
    disponiveis: int  # total_count da busca
    obtidos: int  # limitado a 1.000 pela API


def buscar_candidatos(
    cliente, faixas: Iterable[tuple[int, int | None]], filtros: str = ""
) -> tuple[list[Candidato], list[ResumoFaixa]]:
    """Candidatos de todas as faixas, sem repetição (faixas vizinhas compartilham o limite)."""
    candidatos: dict[str, Candidato] = {}
    resumos = []
    for minimo, maximo in faixas:
        faixa = rotulo_faixa(minimo, maximo)
        consulta = consulta_faixa(minimo, maximo, filtros)
        params = {"q": consulta, "sort": "stars", "order": "desc", "per_page": 100}
        disponiveis = obtidos = 0
        for numero, pagina in enumerate(
            cliente.paginas("/search/repositories", params, max_paginas=MAX_PAGINAS_BUSCA)
        ):
            dados = pagina.dados or {}
            if numero == 0:
                disponiveis = dados.get("total_count", 0)
            if dados.get("incomplete_results"):
                log.warning("busca '%s' devolveu resultados incompletos", consulta)
            for item in dados.get("items", []):
                obtidos += 1
                candidatos.setdefault(item["full_name"], Candidato.da_api(item, faixa))
        resumos.append(ResumoFaixa(faixa, consulta, disponiveis, obtidos))
        log.info("faixa %s: %d disponíveis, %d obtidos", faixa, disponiveis, obtidos)
    return list(candidatos.values()), resumos


def _posicao_sorteada(nome: str, semente: int) -> str:
    return hashlib.sha256(f"{semente}:{nome.lower()}".encode()).hexdigest()


def embaralhar(candidatos: Iterable[Candidato], semente: int) -> list[Candidato]:
    """Ordem de avaliação aleatória e reproduzível.

    A posição de cada repositório depende só da semente e do próprio nome (hash),
    não do conjunto todo: se a busca for refeita em outra data e alguns candidatos
    entrarem ou saírem, os demais mantêm a mesma ordem relativa.
    """
    return sorted(candidatos, key=lambda c: _posicao_sorteada(c.nome, semente))


@dataclass(frozen=True)
class Avaliacao:
    candidato: Candidato
    motivo: str
    n_workflows: int | None = None
    n_releases_janela: int | None = None
    n_runs_validos: int | None = None
    detalhe: str = ""

    @property
    def incluido(self) -> bool:
        return self.motivo == INCLUIDO


def avaliar(cliente, candidato: Candidato, config: Config) -> Avaliacao:
    """Aplica os filtros do mais barato para o mais caro e para no primeiro que reprovar."""
    repo = candidato.nome
    try:
        workflows = cliente.obter(f"/repos/{repo}/actions/workflows", {"per_page": 1}).dados or {}
        n_workflows = workflows.get("total_count", 0)
        if n_workflows == 0:
            return Avaliacao(candidato, SEM_ACTIONS, n_workflows)

        n_releases = rel.contar_releases_janela(rel.listar_releases(cliente, repo), config.janela)
        if n_releases < config.criterios_inclusao.min_releases:
            return Avaliacao(candidato, POUCAS_RELEASES, n_workflows, n_releases)

        # Contagem exata a partir dos runs coletados: o total_count com filtro `status`
        # não é confiável (subconta em repositórios ativos). Os runs de quem passa
        # ficam no cache e são reaproveitados na coleta completa.
        runs_cfg = config.workflow_runs
        runs, _ = wr.coletar_runs(cliente, repo, candidato.branch_padrao, runs_cfg.evento, config.janela)
        n_runs = wr.contar_validos(runs, runs_cfg.conclusoes_sucesso, runs_cfg.conclusoes_falha)
        if n_runs < config.criterios_inclusao.min_workflow_runs:
            return Avaliacao(candidato, POUCOS_RUNS, n_workflows, n_releases, n_runs)
    except ErroAPI as erro:
        if erro.status is None or erro.status >= 500:
            raise
        log.warning("%s descartado: %s", repo, erro)
        return Avaliacao(candidato, ERRO_API, detalhe=str(erro))

    return Avaliacao(candidato, INCLUIDO, n_workflows, n_releases, n_runs)


def selecionar(
    cliente, candidatos: Sequence[Candidato], config: Config
) -> list[Avaliacao]:
    """Avalia os candidatos na ordem dada até a amostra atingir `tamanho_amostra`."""
    meta = config.selecao.tamanho_amostra
    avaliacoes = []
    incluidos = 0
    for indice, candidato in enumerate(candidatos, start=1):
        if incluidos >= meta:
            avaliacoes.append(Avaliacao(candidato, NAO_AVALIADO))
            continue
        avaliacao = avaliar(cliente, candidato, config)
        avaliacoes.append(avaliacao)
        incluidos += avaliacao.incluido
        log.info("[%d/%d] %s: %s (amostra: %d/%d)",
                 indice, len(candidatos), candidato.nome, avaliacao.motivo, incluidos, meta)
    if incluidos < meta:
        log.warning("só %d repositórios passaram nos critérios (meta: %d)", incluidos, meta)
    return avaliacoes


@dataclass(frozen=True)
class EtapaFunil:
    etapa: str
    restantes: int
    descartados: int
    motivo_descarte: str


def resumir_funil(avaliacoes: Iterable[Avaliacao]) -> list[EtapaFunil]:
    """Quantos restam após cada etapa, na ordem de ETAPAS_FUNIL."""
    avaliacoes = list(avaliacoes)
    motivos = Counter(a.motivo for a in avaliacoes)
    restantes = len(avaliacoes)
    etapas = [EtapaFunil("candidatos", restantes, 0, "")]
    for etapa, motivo in ETAPAS_FUNIL:
        restantes -= motivos[motivo]
        etapas.append(EtapaFunil(etapa, restantes, motivos[motivo], motivo))
    etapas.append(EtapaFunil("amostra_final", motivos[INCLUIDO], 0, ""))
    return etapas
