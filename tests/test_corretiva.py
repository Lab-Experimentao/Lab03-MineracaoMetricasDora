from datetime import datetime, timezone

import pytest

from metricas.corretiva import (
    VERSOES,
    Versao,
    ReleaseAvaliada,
    HEURISTICA_ATUAL,
    cfr_entrega,
    eh_titulo_de_correcao,
    eh_versao_de_patch,
    ler_versao,
    muda_so_patch,
    v1,
    v2,
    v3,
    v4,
)

FIM_JANELA = datetime(2026, 10, 1, tzinfo=timezone.utc)  # exclusivo: janela termina em 30/09


def dia(d, m):
    return datetime(2026, m, d, 12, tzinfo=timezone.utc)


def release(tag, anterior, publicada, *titulos):
    return ReleaseAvaliada(tag, publicada, anterior, tuple(titulos))


@pytest.fixture
def releases_exemplo():
    """Exemplo do enunciado: v2.3.0 falha (v2.3.1 em 2 dias, só patch e com fix); v2.4.0 não."""
    return [
        release("v2.3.0", "v2.2.0", dia(10, 5), "feat: abrir arquivos grandes"),
        release("v2.3.1", "v2.3.0", dia(12, 5), "fix: crash ao abrir arquivo"),
        release("v2.4.0", "v2.3.1", dia(1, 6), "feat: exportar PDF"),
        release("v2.5.0", "v2.4.0", dia(20, 6), "feat: modo escuro"),
    ]


@pytest.mark.parametrize("tag, prefixo, numeros, sufixo", [
    ("v1.2.3", "", (1, 2, 3), ""),
    ("1.2", "", (1, 2), ""),
    ("v4.0.0-beta.10", "", (4, 0, 0), "-beta.10"),
    ("@assistant-ui/react@0.3.14", "@assistant-ui/react@", (0, 3, 14), ""),
    ("async-http-client-project-3.0.4", "async-http-client-project-", (3, 0, 4), ""),
    ("3.1.4.36", "", (3, 1, 4, 36), ""),
])
def test_ler_versao(tag, prefixo, numeros, sufixo):
    assert ler_versao(tag) == Versao(prefixo, numeros, sufixo)


def test_tag_sem_numeros_nao_tem_versao():
    assert ler_versao("skia-a9c42c9f") is None
    assert ler_versao("v7") is None


@pytest.mark.parametrize("tag, anterior, esperado", [
    ("v2.3.1", "v2.3.0", True),
    ("2.3.1", "v2.3.0", True),  # "v" opcional
    ("v1.2.1", "v1.2", True),  # número omitido vale 0
    ("3.1.4.37", "3.1.4.36", True),  # quatro números: o último faz o papel do patch
    ("v2.4.0", "v2.3.1", False),  # minor
    ("v3.0.0", "v2.9.9", False),  # major
    ("v2.3.1", "v2.3.1-rc1", False),  # promoção de pré-release, mesmos números
    ("v3.0.15", "v4.1.1", False),  # anterior de outra linha de versão
    ("pkg-b@1.0.1", "pkg-a@1.0.0", False),  # monorepo: outro pacote
    ("v1.0.0", None, False),  # primeira release
    ("skia-a9c42c9f", "v1.0.8", False),
])
def test_muda_so_patch(tag, anterior, esperado):
    assert muda_so_patch(tag, anterior) is esperado


@pytest.mark.parametrize("titulo, esperado", [
    ("fix: crash ao abrir arquivo", True),
    ("fix(parser): limite de profundidade", True),
    ("Fix SOCKS proxy SSL handler issue", True),
    ("Revert \"feat: novo cache\"", True),
    ("hotfix para o login", True),
    ("Fixed import of models", True),
    ("[fix][sec] Upgrade Jetty", True),
    ("feat: add prefix option", False),  # "prefix" não é "fix"
    ("test: new fixtures", False),
    ("Bump lodash from 4.17.20 to 4.17.21", False),
])
def test_titulo_de_correcao(titulo, esperado):
    assert eh_titulo_de_correcao(titulo) is esperado


def test_v1_patch_ou_commit_de_correcao(releases_exemplo):
    assert [v1(r) for r in releases_exemplo] == [False, True, False, False]
    assert v1(release("v3.0.0", "v2.5.0", dia(1, 7), "fix: typo"))  # só o commit
    assert v1(release("v2.5.1", "v2.5.0", dia(1, 7), "docs: README"))  # só o patch


@pytest.mark.parametrize("tag, esperado", [
    ("v2.3.1", True),
    ("v3.0.15", True),  # backport de outra linha: patch pela própria versão
    ("@scope/pkg@0.3.14", True),
    ("3.1.4.36", True),
    ("v0.3.1-beta.3", True),
    ("v2.4.0", False),
    ("v3.0.0", False),
    ("1.2", False),  # 1.2.0
    ("skia-a9c42c9f", False),
])
def test_eh_versao_de_patch(tag, esperado):
    assert eh_versao_de_patch(tag) is esperado


def test_v2_exige_patch_e_commit_de_correcao():
    assert v2(release("v2.3.1", "v2.3.0", dia(1, 7), "fix: crash"))
    assert not v2(release("v2.3.1", "v2.3.0", dia(1, 7), "docs: README"))
    assert not v2(release("v2.4.0", "v2.3.1", dia(1, 7), "fix: crash"))


def test_v3_olha_so_a_propria_versao():
    assert v3(release("v3.0.15", "v4.1.1", dia(1, 7)))  # anterior de outra linha
    assert not v3(release("v2.4.0", "v2.3.1", dia(1, 7), "fix: crash"))


def test_v4_exige_versao_de_patch_e_commit_de_correcao():
    assert v4(release("v3.0.15", "v4.1.1", dia(1, 7), "Revert \"feat: cache\""))
    assert not v4(release("v3.0.15", "v4.1.1", dia(1, 7), "chore: deps"))


def test_heuristica_atual_e_a_v3():
    assert HEURISTICA_ATUAL.nome == "v3"


def test_versoes_registradas_tem_nomes_unicos():
    nomes = [v.nome for v in VERSOES]
    assert len(nomes) == len(set(nomes))


def test_exemplo_do_enunciado(releases_exemplo):
    resultado = cfr_entrega(releases_exemplo, FIM_JANELA, heuristica=v1)
    # v2.3.0 falhou; v2.3.1, v2.4.0 e v2.5.0 não foram seguidas por corretiva em até 7 dias.
    assert (resultado.falhas, resultado.avaliadas, resultado.censuradas) == (1, 4, 0)
    assert resultado.taxa == pytest.approx(1 / 4)
    assert resultado.corretivas == 1


def test_ordem_de_entrada_nao_importa(releases_exemplo):
    assert cfr_entrega(list(reversed(releases_exemplo)), FIM_JANELA, heuristica=v1).falhas == 1


def test_corretiva_depois_de_7_dias_nao_conta():
    releases = [
        release("v1.0.0", "v0.9.0", dia(1, 5)),
        release("v1.0.1", "v1.0.0", dia(9, 5), "fix: bug"),  # 8 dias depois
    ]
    assert cfr_entrega(releases, FIM_JANELA, heuristica=v1).falhas == 0


def test_corretiva_no_setimo_dia_conta():
    releases = [
        release("v1.0.0", "v0.9.0", dia(1, 5)),
        release("v1.0.1", "v1.0.0", dia(8, 5), "fix: bug"),  # exatamente 7 dias
    ]
    assert cfr_entrega(releases, FIM_JANELA, heuristica=v1).falhas == 1


def test_qualquer_release_corretiva_no_prazo_conta():
    """A corretiva não precisa ser a release imediatamente seguinte."""
    releases = [
        release("v1.0.0", "v0.9.0", dia(1, 5)),
        release("v1.1.0", "v1.0.0", dia(3, 5), "feat: novo recurso"),
        release("v1.1.1", "v1.1.0", dia(5, 5), "fix: regressão"),
    ]
    resultado = cfr_entrega(releases, FIM_JANELA, heuristica=v1)
    assert resultado.falhas == 2  # v1.0.0 e v1.1.0


def test_releases_dos_ultimos_7_dias_sao_censuradas():
    releases = [
        release("v1.0.0", "v0.9.0", dia(20, 9)),
        release("v1.0.1", "v1.0.0", dia(24, 9), "fix: bug"),  # depois do corte (24/09 00h)
        release("v1.0.2", "v1.0.1", dia(29, 9), "fix: bug"),
    ]
    resultado = cfr_entrega(releases, FIM_JANELA, heuristica=v1)
    assert (resultado.avaliadas, resultado.censuradas) == (1, 2)
    assert resultado.taxa == 1.0  # v1.0.0 foi seguida por v1.0.1


def test_repositorio_com_uma_unica_release():
    resultado = cfr_entrega([release("v1.0.0", None, dia(1, 5))], FIM_JANELA, heuristica=v1)
    assert (resultado.taxa, resultado.falhas, resultado.avaliadas) == (0.0, 0, 1)


def test_sem_releases_avaliaveis():
    assert cfr_entrega([], FIM_JANELA).taxa is None
    so_censurada = [release("v1.0.0", None, dia(28, 9))]
    assert cfr_entrega(so_censurada, FIM_JANELA, heuristica=v1).taxa is None


def test_janela_configuravel():
    releases = [
        release("v1.0.0", "v0.9.0", dia(1, 5)),
        release("v1.0.1", "v1.0.0", dia(9, 5), "fix: bug"),
    ]
    assert cfr_entrega(releases, FIM_JANELA, dias=10, heuristica=v1).falhas == 1


# ---------------------------------------------------------------- rework rate (RQ 08)


def test_rework_rate_do_exemplo(releases_exemplo):
    resultado = cfr_entrega(releases_exemplo, FIM_JANELA, heuristica=v1)
    assert resultado.rework_rate == pytest.approx(1 / 4)  # só v2.3.1 é corretiva


def test_rework_conta_a_correcao_e_o_cfr_conta_a_release_que_falhou():
    """Duas corretivas seguidas: o rework conta as duas; o CFR (b), quem veio antes de cada uma."""
    releases = [
        release("v1.0.0", "v0.9.0", dia(1, 5)),
        release("v1.0.1", "v1.0.0", dia(2, 5), "fix: a"),
        release("v1.0.2", "v1.0.1", dia(3, 5), "fix: b"),
        release("v1.1.0", "v1.0.2", dia(1, 6)),
    ]
    resultado = cfr_entrega(releases, FIM_JANELA, heuristica=v1)
    assert resultado.rework_rate == pytest.approx(2 / 4)
    assert resultado.taxa == pytest.approx(2 / 4)  # v1.0.0 e v1.0.1 falharam


def test_corretiva_tardia_entra_no_rework_mas_nao_no_cfr():
    releases = [
        release("v1.0.0", "v0.9.0", dia(1, 5)),
        release("v1.0.1", "v1.0.0", dia(20, 5), "fix: bug antigo"),  # 19 dias depois
    ]
    resultado = cfr_entrega(releases, FIM_JANELA, heuristica=v1)
    assert (resultado.rework_rate, resultado.taxa) == (0.5, 0.0)


def test_rework_inclui_releases_censuradas_no_cfr():
    releases = [release("v1.0.0", "v0.9.0", dia(1, 9)), release("v1.0.1", "v1.0.0", dia(29, 9), "fix: x")]
    resultado = cfr_entrega(releases, FIM_JANELA, heuristica=v1)
    assert (resultado.avaliadas, resultado.censuradas) == (1, 1)
    assert resultado.rework_rate == 0.5  # a v1.0.1 censurada conta no rework


def test_rework_sem_releases():
    assert cfr_entrega([], FIM_JANELA).rework_rate is None
