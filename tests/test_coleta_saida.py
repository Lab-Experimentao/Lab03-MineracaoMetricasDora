import csv
from datetime import datetime, timezone

from coleta import releases as rel
from coleta import saida
from coleta.modelos import Candidato, CommitInfo
from coleta.repositorio import ColetaRepositorio

QUANDO = datetime(2025, 11, 1, 12, tzinfo=timezone.utc)


def coleta(pares, compares):
    candidato = Candidato("dono/repo", 1500, None, QUANDO, "main", "https://github.com/dono/repo", "1000..2000")
    return ColetaRepositorio(candidato, None, [], [], pares, compares, [], [])


def test_status_dos_compares_por_cadeia():
    commit = CommitInfo("abc", QUANDO, "fix: x\n\ncorpo")
    c = coleta(
        pares=[
            rel.Par(rel.CADEIA_RELEASE, "v1", QUANDO, None),
            rel.Par(rel.CADEIA_RELEASE, "v2", QUANDO, "v1"),
            rel.Par(rel.CADEIA_TAG, "v3", QUANDO, "v2"),
        ],
        compares={
            ("v1", "v2"): rel.ResultadoCompare("v1", "v2", rel.COMPARE_OK, (commit,)),
            ("v2", "v3"): rel.ResultadoCompare("v2", "v3", "404", ()),
        },
    )
    linhas = saida.linhas_compares([c])
    assert [(l["tag"], l["status"], l["n_commits"]) for l in linhas] == [
        ("v1", "primeira", None), ("v2", "ok", 1), ("v3", "404", 0),
    ]
    [linha_commit] = saida.linhas_commits([c])
    assert (linha_commit["tag"], linha_commit["sha"]) == ("v2", "abc")


def test_gravar_csv_formata_datas_vazios_e_booleanos(tmp_path):
    caminho = tmp_path / "sub" / "x.csv"
    total = saida.gravar_csv(caminho, [{"a": QUANDO, "b": None, "c": True}], ["a", "b", "c"])
    with caminho.open(encoding="utf-8") as arquivo:
        linhas = list(csv.DictReader(arquivo))
    assert total == 1
    assert linhas == [{"a": "2025-11-01T12:00:00+00:00", "b": "", "c": "1"}]


def test_candidatos_gravados_e_lidos_sao_iguais(tmp_path):
    from datetime import date
    from coleta.candidatos import gravar_candidatos, ler_candidatos
    from coleta.selecao import ResumoFaixa

    candidatos = [
        Candidato("dono/a", 1500, "Python", QUANDO, "main", "https://github.com/dono/a", "1000..2000"),
        Candidato("dono/b", 60000, None, QUANDO, "master", "https://github.com/dono/b", ">=50000"),
    ]
    faixas = [ResumoFaixa("1000..2000", "stars:1000..2000", 29075, 1000)]
    arquivo = tmp_path / "dados" / "candidatos.csv"

    gravar_candidatos(arquivo, candidatos, faixas, date(2026, 10, 6))
    lidos, faixas_lidas, buscado_em = ler_candidatos(arquivo)

    assert lidos == candidatos
    assert faixas_lidas == faixas
    assert buscado_em == "2026-10-06"
