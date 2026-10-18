import pandas as pd
import pytest

from analise.classificacao import (
    COLUNAS_DISTRIBUICAO,
    COLUNAS_LIMITANTE,
    COLUNAS_METRICAS_USADAS,
    COLUNAS_SENSIBILIDADE,
    FALHA_ANTES_DO_SUCESSO,
    SEM_FALHA,
    SO_CENSURADOS,
    dimensao_limitante,
    distribuicao,
    perfil_metricas_usadas,
    sensibilidade,
    situacao_recuperacao,
)

NAN = float("nan")


def repo(frequencia, lead, cfr, recuperacao, geral, runs_falha=5, censurados=0):
    return {
        "classe_frequencia": frequencia, "classe_lead_time": lead, "classe_cfr": cfr,
        "classe_recuperacao": recuperacao, "classe_geral": geral,
        "recuperacao_horas": NAN if recuperacao is None else 1.0,
        "runs_falha": runs_falha, "episodios_censurados": censurados,
    }


@pytest.fixture
def amostra():
    return pd.DataFrame([
        repo("Elite", "Elite", "High", "Medium", "High"),    # mediana 3,5: empate
        repo("Low", "Medium", "Elite", "High", "Medium"),    # mediana 2,5: empate
        repo("High", "High", "Elite", "High", "High"),       # mediana 3
        repo("Low", "Low", "Elite", None, "Low", runs_falha=0),  # (1, 1, 4) -> 1; sem falha
        repo("Medium", "High", "Elite", None, "High", runs_falha=3),  # falha só antes do sucesso
    ])


def test_distribuicao_conta_cada_classe_e_sem_dados(amostra):
    tabela = distribuicao(amostra)
    assert list(tabela.columns) == COLUNAS_DISTRIBUICAO
    assert len(tabela) == 5 * 5  # 4 dimensões + geral, 4 classes + sem dados
    geral = tabela[tabela["dimensao"] == "geral"].set_index("classe")["repositorios"]
    assert geral.to_dict() == {"Elite": 0, "High": 3, "Medium": 1, "Low": 1, "sem dados": 0}
    recuperacao = tabela[tabela["dimensao"] == "recuperacao"].set_index("classe")
    assert recuperacao.loc["sem dados", "repositorios"] == 2
    assert recuperacao.loc["sem dados", "proporcao"] == pytest.approx(0.4)
    for _, grupo in tabela.groupby("dimensao"):
        assert grupo["proporcao"].sum() == pytest.approx(1)
    assert list(tabela["classe"][:5]) == ["Elite", "High", "Medium", "Low", "sem dados"]


def test_situacao_recuperacao_distingue_os_motivos():
    assert situacao_recuperacao(pd.Series(repo("Low", "Low", "Elite", None, "Low", runs_falha=0))) == SEM_FALHA
    assert situacao_recuperacao(pd.Series(repo("Low", "Low", "Low", None, "Low", censurados=2))) == SO_CENSURADOS
    assert situacao_recuperacao(pd.Series(repo("Low", "Low", "Low", None, "Low"))) == FALHA_ANTES_DO_SUCESSO


def test_perfil_metricas_usadas(amostra):
    tabela = perfil_metricas_usadas(amostra)
    assert list(tabela.columns) == COLUNAS_METRICAS_USADAS
    linhas = {(l.situacao_recuperacao, l.metricas_usadas): l for l in tabela.itertuples()}
    com = linhas[("com recuperação", 4)]
    assert (com.High, com.Medium, com.repositorios) == (2, 1, 3)
    assert linhas[(SEM_FALHA, 3)].Low == 1
    assert linhas[(FALHA_ANTES_DO_SUCESSO, 3)].High == 1
    assert tabela["repositorios"].sum() == len(amostra)
    assert tabela["situacao_recuperacao"].iloc[0] == "com recuperação"


def test_sensibilidade(amostra):
    tabela = sensibilidade(amostra).set_index("cenario")
    assert list(tabela.reset_index().columns) == COLUNAS_SENSIBILIDADE

    referencia = tabela.loc["referencia"]
    assert (referencia["Elite"], referencia["High"], referencia["Medium"], referencia["Low"]) == (0, 3, 1, 1)
    assert referencia["mudam_de_classe"] == 0
    assert referencia["empates"] == 2

    para_cima = tabela.loc["arredondamento_para_cima"]
    assert (para_cima["Elite"], para_cima["High"], para_cima["Medium"], para_cima["Low"]) == (1, 3, 0, 1)
    assert para_cima["mudam_de_classe"] == 2

    # Repositório sem falha passa de (1, 1, 4) para (1, 1, 4, 4): mediana 2,5 -> Medium.
    sem_falha = tabela.loc["sem_falha_como_elite"]
    assert (sem_falha["Medium"], sem_falha["Low"]) == (2, 0)
    assert sem_falha["mudam_de_classe"] == 1
    assert sem_falha["empates"] == 3


def test_referencia_reproduz_a_classe_geral_da_etapa_de_metricas(amostra):
    from analise.classificacao import CENARIOS, classes_gerais
    assert list(classes_gerais(amostra, CENARIOS[0])) == list(amostra["classe_geral"])


def test_sem_nenhuma_dimensao_fica_sem_dados():
    df = pd.DataFrame([repo(None, None, None, None, None)])
    referencia = sensibilidade(df).set_index("cenario").loc["referencia"]
    assert referencia["sem_dados"] == 1 and referencia["empates"] == 0


def test_dimensao_limitante(amostra):
    tabela = dimensao_limitante(amostra)
    assert list(tabela.columns) == COLUNAS_LIMITANTE
    linhas = tabela.set_index("classe_geral")
    high = linhas.loc["High"]
    # High: (E, E, H, M) -> recuperação abaixo; (H, H, E, H) -> nada; (M, H, E, -) -> frequência abaixo.
    assert (high["repositorios"], high["frequencia_abaixo"], high["recuperacao_abaixo"]) == (3, 1, 1)
    assert high["lead_time_abaixo"] == 0 and high["cfr_abaixo"] == 0
    medium = linhas.loc["Medium"]  # (L, M, E, H)
    assert (medium["frequencia_abaixo"], medium["lead_time_abaixo"]) == (1, 0)
    assert linhas.loc["Elite", "repositorios"] == 0
    assert linhas.loc["todas", "repositorios"] == 5
    assert linhas.loc["todas", "frequencia_abaixo"] == 2
