import sys
from pathlib import Path

# Permite importar os pacotes do projeto (pipeline, coleta, metricas, analise) nos testes.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
