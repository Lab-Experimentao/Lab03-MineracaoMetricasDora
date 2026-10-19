"""RQ 08 (bônus): deployment rework rate e comparação com o CFR (b).

Rework rate = releases corretivas ÷ todas as releases da janela (coluna `rework_rate` de
metricas.csv), com a mesma heurística de release corretiva do CFR (b).

Reexecutável a partir dos CSVs, sem acessar a API:
    python -m analise.rq08_rework --config config.yaml

Saída em `<saida.dir>/analise/`:
- rq08_resumo.csv: mediana e IQR do rework rate e do CFR (b);
- rq08_comparacao.csv: Spearman e Wilcoxon pareado entre as duas métricas e a direção
  da diferença por repositório;
- rq08_amostra_ouro.csv: proporção de corretivas nas 300 releases rotuladas, segundo o
  consenso humano e segundo a heurística (viés do rework rate);
- rq08_rework_vs_cfr.png: dispersão das duas métricas.
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import pandas as pd
from scipy.stats import spearmanr, wilcoxon

from metricas.corretiva import HEURISTICA_ATUAL, ReleaseAvaliada
from pipeline.config import Config, carregar_config

log = logging.getLogger(__name__)

METRICAS = {"rework_rate": "Rework rate", "cfr_entrega": "CFR (b)"}


def resumir(metricas: pd.DataFrame) -> pd.DataFrame:
    """Mediana e IQR de cada métrica, sobre os repositórios com valor."""
    linhas = []
    for coluna, nome in METRICAS.items():
        valores = metricas[coluna].dropna()
        q1, mediana, q3 = valores.quantile([0.25, 0.5, 0.75])
        linhas.append({"metrica": nome, "n": len(valores), "mediana": mediana, "q1": q1, "q3": q3,
                       "iqr": q3 - q1, "minimo": valores.min(), "maximo": valores.max()})
    return pd.DataFrame(linhas)


def comparar(metricas: pd.DataFrame) -> pd.DataFrame:
    """Correlação de Spearman, Wilcoxon pareado e direção da diferença (rework − CFR b)."""
    pares = metricas[["rework_rate", "cfr_entrega"]].dropna()
    rho, p_rho = spearmanr(pares["rework_rate"], pares["cfr_entrega"])
    diferenca = pares["rework_rate"] - pares["cfr_entrega"]
    estatistica, p_w = wilcoxon(pares["rework_rate"], pares["cfr_entrega"])
    return pd.DataFrame([
        {"medida": "n (repositórios com as duas métricas)", "valor": len(pares)},
        {"medida": "Spearman rho", "valor": rho},
        {"medida": "Spearman p-valor", "valor": p_rho},
        {"medida": "Wilcoxon pareado (estatística)", "valor": estatistica},
        {"medida": "Wilcoxon pareado p-valor", "valor": p_w},
        {"medida": "mediana da diferença (rework - CFR b)", "valor": diferenca.median()},
        {"medida": "repositórios com rework > CFR b", "valor": int((diferenca > 0).sum())},
        {"medida": "repositórios com rework = CFR b", "valor": int((diferenca == 0).sum())},
        {"medida": "repositórios com rework < CFR b", "valor": int((diferenca < 0).sum())},
    ])


def comparar_amostra_ouro(consenso: pd.DataFrame) -> pd.DataFrame:
    """Proporção de corretivas nas releases rotuladas: consenso humano × heurística atual.

    A heurística decide pela versão da tag, então os títulos dos commits não são necessários.
    """
    rotuladas = consenso[consenso["corretiva"].isin(["sim", "não"])]
    heuristica = [
        HEURISTICA_ATUAL.funcao(ReleaseAvaliada(r.tag, pd.Timestamp(r.publicada_em).to_pydatetime(),
                                                r.tag_anterior or None, ()))
        for r in rotuladas.itertuples()
    ]
    humano = rotuladas["corretiva"] == "sim"
    return pd.DataFrame([
        {"fonte": "consenso dos avaliadores", "releases": len(rotuladas), "corretivas": int(humano.sum()),
         "proporcao": humano.mean()},
        {"fonte": f"heurística {HEURISTICA_ATUAL.nome}", "releases": len(rotuladas),
         "corretivas": int(sum(heuristica)), "proporcao": sum(heuristica) / len(rotuladas)},
    ])


def grafico(metricas: pd.DataFrame, destino: Path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    pares = metricas[["rework_rate", "cfr_entrega"]].dropna()
    figura, eixo = plt.subplots(figsize=(5, 4.5))
    eixo.scatter(pares["rework_rate"], pares["cfr_entrega"], s=14, alpha=0.6)
    eixo.plot([0, 1], [0, 1], linestyle="--", linewidth=1, color="gray", label="rework = CFR (b)")
    eixo.set_xlabel("Rework rate (corretivas ÷ releases)")
    eixo.set_ylabel("CFR (b) (releases que falharam ÷ avaliadas)")
    eixo.set_xlim(-0.02, 1.02)
    eixo.set_ylim(-0.02, 1.02)
    eixo.legend(loc="upper left")
    figura.tight_layout()
    figura.savefig(destino, dpi=200)
    plt.close(figura)


def executar(config: Config) -> None:
    metricas = pd.read_csv(config.saida_dir / "metricas.csv")
    if "rework_rate" not in metricas.columns:
        raise FileNotFoundError("metricas.csv sem a coluna rework_rate; rode antes a etapa de métricas")
    destino = config.saida_dir / "analise"
    destino.mkdir(parents=True, exist_ok=True)

    resumo = resumir(metricas)
    comparacao = comparar(metricas)
    resumo.to_csv(destino / "rq08_resumo.csv", index=False, encoding="utf-8")
    comparacao.to_csv(destino / "rq08_comparacao.csv", index=False, encoding="utf-8")
    grafico(metricas, destino / "rq08_rework_vs_cfr.png")
    for r in resumo.itertuples():
        log.info("RQ 08, %s: mediana %.3f, IQR [%.3f, %.3f] (n = %d)", r.metrica, r.mediana, r.q1, r.q3, r.n)
    for r in comparacao.itertuples():
        log.info("RQ 08, %s: %s", r.medida, f"{r.valor:.4g}")

    arquivo_consenso = config.saida_dir / "validacao" / "consenso_releases.csv"
    if arquivo_consenso.is_file():
        ouro = comparar_amostra_ouro(pd.read_csv(arquivo_consenso, dtype=str, keep_default_na=False))
        ouro.to_csv(destino / "rq08_amostra_ouro.csv", index=False, encoding="utf-8")
        for r in ouro.itertuples():
            log.info("RQ 08, amostra-ouro, %s: %d de %d releases corretivas (%.3f)",
                     r.fonte, r.corretivas, r.releases, r.proporcao)


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m analise.rq08_rework", description=__doc__.splitlines()[0])
    parser.add_argument("--config", default="config.yaml", help="caminho do config.yaml")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    executar(carregar_config(args.config))


if __name__ == "__main__":
    main()
