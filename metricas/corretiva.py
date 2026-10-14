"""Change failure rate (RQ 03), variante (b): proxy de entrega por releases corretivas.

Uma release R falha se for seguida, em até 7 dias, por uma release corretiva. A heurística
que decide se uma release é corretiva olha a versão (SemVer) e as mensagens dos commits
desde a release anterior. Cada versão da heurística fica registrada em `VERSOES`, com o F1
obtido na validação contra a amostra-ouro (validacao/heuristica.py).
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

_NUMEROS = re.compile(r"\d+(?:\.\d+)+")
_PALAVRAS_CORRECAO = re.compile(r"\b(fix|fixes|fixed|hotfix|bugfix|revert)\b", re.IGNORECASE)


@dataclass(frozen=True)
class Versao:
    """Números da tag; `prefixo` separa pacotes de um monorepo (ex.: "@scope/pkg@")."""

    prefixo: str
    numeros: tuple[int, ...]
    sufixo: str  # ex.: "-beta.1", "-rc1"; vazio numa versão final


def ler_versao(tag: str) -> Versao | None:
    """Primeiro grupo de números separados por ponto na tag; None se não houver."""
    encontrado = _NUMEROS.search(tag)
    if encontrado is None:
        return None
    prefixo = tag[: encontrado.start()].lower()
    if prefixo.endswith("v"):
        prefixo = prefixo[:-1]
    numeros = tuple(int(n) for n in encontrado.group().split("."))
    return Versao(prefixo, numeros, tag[encontrado.end():].lower())


def muda_so_patch(tag: str, tag_anterior: str | None) -> bool:
    """A versão sobe só no último número (2.3.0 → 2.3.1), no mesmo pacote."""
    if not tag_anterior:
        return False
    atual, anterior = ler_versao(tag), ler_versao(tag_anterior)
    if atual is None or anterior is None or atual.prefixo != anterior.prefixo:
        return False
    tamanho = max(len(atual.numeros), len(anterior.numeros), 3)
    a = atual.numeros + (0,) * (tamanho - len(atual.numeros))
    b = anterior.numeros + (0,) * (tamanho - len(anterior.numeros))
    return a[:-1] == b[:-1] and a[-1] > b[-1]


def eh_versao_de_patch(tag: str) -> bool:
    """A própria versão é um patch: o último número é maior que zero (2.3.1, 3.0.15, 1.2.0.4).

    Não depende da release anterior, que pode ser de outra linha de versão (backport) ou de
    outro pacote do monorepo.
    """
    versao = ler_versao(tag)
    if versao is None:
        return False
    numeros = versao.numeros + (0,) * (3 - len(versao.numeros))
    return numeros[-1] > 0


def eh_titulo_de_correcao(titulo: str) -> bool:
    return bool(_PALAVRAS_CORRECAO.search(titulo))


@dataclass(frozen=True)
class ReleaseAvaliada:
    """Release com o que a heurística precisa: a tag anterior e os títulos dos commits."""

    tag: str
    publicada_em: datetime
    tag_anterior: str | None
    titulos_commits: tuple[str, ...]


Heuristica = Callable[[ReleaseAvaliada], bool]


def _tem_commit_de_correcao(release: ReleaseAvaliada) -> bool:
    return any(eh_titulo_de_correcao(t) for t in release.titulos_commits)


def v1(release: ReleaseAvaliada) -> bool:
    """Sugestão do enunciado: muda só o patch OU algum commit com fix/hotfix/revert."""
    return muda_so_patch(release.tag, release.tag_anterior) or _tem_commit_de_correcao(release)


def v2(release: ReleaseAvaliada) -> bool:
    """Muda só o patch E algum commit com fix/hotfix/revert."""
    return muda_so_patch(release.tag, release.tag_anterior) and _tem_commit_de_correcao(release)


def v3(release: ReleaseAvaliada) -> bool:
    """A própria versão é um patch (X.Y.Z com Z > 0), sem olhar a anterior nem os commits."""
    return eh_versao_de_patch(release.tag)


def v4(release: ReleaseAvaliada) -> bool:
    """A própria versão é um patch E algum commit com fix/hotfix/revert."""
    return eh_versao_de_patch(release.tag) and _tem_commit_de_correcao(release)


@dataclass(frozen=True)
class VersaoHeuristica:
    nome: str
    descricao: str
    funcao: Heuristica


# Versões avaliadas na amostra-ouro, na ordem em que foram testadas. O F1 de cada uma e os
# erros que motivaram a seguinte estão em dados/validacao/heuristica_versoes.csv e no README.
VERSOES: tuple[VersaoHeuristica, ...] = (
    VersaoHeuristica("v1", "muda só o patch em relação à anterior OU algum commit com fix/hotfix/revert", v1),
    VersaoHeuristica("v2", "muda só o patch em relação à anterior E algum commit com fix/hotfix/revert", v2),
    VersaoHeuristica("v3", "a própria versão é um patch (X.Y.Z com Z > 0)", v3),
    VersaoHeuristica("v4", "a própria versão é um patch E algum commit com fix/hotfix/revert", v4),
)
# Versão usada no cálculo do CFR (b): a de maior F1 na validação (0,715).
HEURISTICA_ATUAL = next(v for v in VERSOES if v.nome == "v3")


@dataclass(frozen=True)
class CFREntrega:
    taxa: float | None
    falhas: int
    avaliadas: int
    censuradas: int
    corretivas: int  # releases que a heurística marcou como corretivas (base da RQ 08)


def cfr_entrega(
    releases: Sequence[ReleaseAvaliada],
    fim_janela: datetime,
    dias: int = 7,
    heuristica: Heuristica = HEURISTICA_ATUAL.funcao,
) -> CFREntrega:
    """Releases que falharam ÷ releases avaliadas.

    R falha se alguma release publicada depois dela, em até `dias` dias, é corretiva.
    Releases publicadas nos últimos `dias` dias antes de `fim_janela` (exclusivo) ficam
    fora do denominador: ainda não se sabe se haverá correção (censura).
    """
    ordenadas = sorted(releases, key=lambda r: r.publicada_em)
    corretivas = [heuristica(r) for r in ordenadas]
    prazo = timedelta(days=dias)
    falhas = avaliadas = censuradas = 0
    for i, release in enumerate(ordenadas):
        if release.publicada_em > fim_janela - prazo:
            censuradas += 1
            continue
        avaliadas += 1
        limite = release.publicada_em + prazo
        if any(
            corretivas[j] for j in range(i + 1, len(ordenadas))
            if release.publicada_em < ordenadas[j].publicada_em <= limite
        ):
            falhas += 1
    return CFREntrega(falhas / avaliadas if avaliadas else None, falhas, avaliadas, censuradas, sum(corretivas))
