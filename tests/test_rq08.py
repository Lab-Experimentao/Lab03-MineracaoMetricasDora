import math

import pandas as pd
import pytest

from analise import rq08_rework as rq08


@pytest.fixture
def metricas():
    """Quatro repositórios: dois com rework maior que o CFR (b), um igual e um sem CFR (b)."""
    return pd.DataFrame({
        "repositorio": ["a", "b", "c", "d"],
        "rework_rate": [0.8, 0.5, 0.2, 0.6],
        "cfr_entrega": [0.4, 0.5, 0.1, None],
    })


def test_resumo_com_mediana_e_iqr(metricas):
    resumo = rq08.resumir(metricas).set_index("metrica")
    assert resumo.loc["Rework rate", "n"] == 4
    assert resumo.loc["Rework rate", "mediana"] == pytest.approx(0.55)
    assert resumo.loc["CFR (b)", "n"] == 3  # repositório sem CFR (b) fica de fora
    assert resumo.loc["CFR (b)", "iqr"] == pytest.approx(0.45 - 0.25)


def test_comparacao_pareada(metricas):
    comparacao = rq08.comparar(metricas).set_index("medida")["valor"]
    assert comparacao["n (repositórios com as duas métricas)"] == 3
    assert comparacao["Spearman rho"] == pytest.approx(0.5)
    assert comparacao["repositórios com rework > CFR b"] == 2
    assert comparacao["repositórios com rework = CFR b"] == 1
    assert comparacao["mediana da diferença (rework - CFR b)"] == pytest.approx(0.1)
    assert not math.isnan(comparacao["Wilcoxon pareado p-valor"])


def test_amostra_ouro_compara_consenso_e_heuristica():
    consenso = pd.DataFrame({
        "repositorio": ["a", "a", "a", "b"],
        "tag": ["v1.0.1", "v1.1.0", "v1.1.1", "v2.0.0"],
        "tag_anterior": ["v1.0.0", "v1.0.1", "v1.1.0", ""],
        "publicada_em": ["2026-01-01T00:00:00+00:00"] * 4,
        "corretiva": ["sim", "não", "não", "sim"],
    })
    ouro = rq08.comparar_amostra_ouro(consenso).set_index("fonte")
    assert ouro.loc["consenso dos avaliadores", ["corretivas", "proporcao"]].tolist() == [2, 0.5]
    # A heurística atual (v3) marca as versões patch: v1.0.1 e v1.1.1.
    assert ouro.filter(like="heurística", axis=0)["corretivas"].item() == 2


def test_executar_grava_tabelas_e_grafico(tmp_path, metricas, monkeypatch):
    from pathlib import Path

    import yaml

    from pipeline.config import carregar_config

    projeto = Path(__file__).resolve().parent.parent / "config.yaml"
    caminho = tmp_path / "config.yaml"
    caminho.write_text(yaml.safe_dump(yaml.safe_load(projeto.read_text(encoding="utf-8"))), encoding="utf-8")
    config = carregar_config(caminho)
    config.saida_dir.mkdir()
    metricas.to_csv(config.saida_dir / "metricas.csv", index=False)

    rq08.executar(config)
    destino = config.saida_dir / "analise"
    for arquivo in ("rq08_resumo.csv", "rq08_comparacao.csv", "rq08_rework_vs_cfr.png"):
        assert (destino / arquivo).is_file()
    assert not (destino / "rq08_amostra_ouro.csv").exists()  # sem consenso, não compara


def test_metricas_sem_rework_rate_falha_com_mensagem(tmp_path):
    from types import SimpleNamespace

    (tmp_path / "metricas.csv").write_text("repositorio\na\n", encoding="utf-8")
    with pytest.raises(FileNotFoundError, match="rework_rate"):
        rq08.executar(SimpleNamespace(saida_dir=tmp_path))
