# Lab03 - Mineração de Métricas DORA

Pipeline que coleta dados públicos de repositórios open-source no GitHub (releases,
commits e workflow runs do GitHub Actions) e calcula aproximações das métricas DORA.

## Requisitos

- Python 3.11
- Um token pessoal do GitHub em um arquivo .env

## Instalação

```bash
python -m venv .venv
# Linux/macOS: source .venv/bin/activate
# Windows (PowerShell): .venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## Execução

O token é lido da variável de ambiente `GITHUB_TOKEN` e nunca deve ser commitado
(`.env`, `cache/` e arquivos de token estão no `.gitignore`). A forma mais simples é
criar um arquivo `.env` ao lado do `config.yaml`, que o pipeline carrega sozinho:

```bash
cp .env.example .env   # e edite o valor de GITHUB_TOKEN
python -m pipeline --config config.yaml
```

Também é possível exportar a variável no shell; ela tem prioridade sobre o `.env`:

```bash
# Linux/macOS
export GITHUB_TOKEN=ghp_...
# Windows (PowerShell)
$env:GITHUB_TOKEN = "ghp_..."
```

Opções:

| Opção | Descrição |
|---|---|
| `--config CAMINHO` | Arquivo de configuração (obrigatório). |
| `--etapas ...` | Executa só algumas etapas, entre `coleta`, `metricas`, `validacao`, `tipo_projeto` e `analise` (padrão: todas). A `coleta` exige o token; a `tipo_projeto`, só se faltar coletar algum perfil. |
| `-v`, `--verbose` | Log detalhado. |

O comando roda as etapas em sequência: a **coleta** grava os dados brutos em
`dados/brutos/`, a etapa de **métricas** calcula, a partir deles, `dados/metricas.csv`, e
a de **validação** sorteia a amostra-ouro, gera as planilhas de rotulagem e, com elas
preenchidas, calcula a concordância e o consenso (`dados/validacao/`). A de **tipo de projeto**
classifica os 300 repositórios em biblioteca/framework, aplicação/serviço, ferramenta CLI ou
outro (`dados/tipo_projeto.csv`). A de **análise** lê `dados/metricas.csv` e grava as tabelas
das RQs em `dados/analise/` (por enquanto, a estatística descritiva das RQ 01 a RQ 04 e a
distribuição da classificação DORA de referência).

Se a execução for interrompida (rate limit, queda de rede, `Ctrl+C`), basta rodar o
mesmo comando de novo: as respostas da API ficam em cache em `cache/api.sqlite`.

A coleta da amostra de 300 repositórios, sem cache, fez cerca de 24 mil chamadas à API
e levou em torno de 11 horas de execução (avaliação de 2.160 candidatos no funil e coleta
completa dos 300). A cota de 5.000 chamadas/hora quase não chegou a ser atingida: o que
mais pesa é o tempo de resposta da API. Para rodá-la em segundo plano no macOS ou Linux,
gravando o log em arquivo e sem o computador dormir (macOS):

```bash
caffeinate -i nohup python -m pipeline --config config.yaml > coleta.log 2>&1 &
tail -f coleta.log
```

No Windows (PowerShell), o processo segue rodando mesmo se o terminal for fechado
(desative a suspensão do computador enquanto isso):

```powershell
Start-Process cmd -ArgumentList '/c python -m pipeline --config config.yaml > coleta.log 2>&1' -WindowStyle Hidden
Get-Content coleta.log -Wait -Tail 5
```

### Cliente HTTP (`coleta/cliente.py`)

Todo acesso à API passa por `ClienteGitHub`, implementado só com `requests`:

- **Cache e retomada:** cada página de resposta é gravada no SQLite assim que chega,
  com a URL (parâmetros ordenados) como chave. Erros definitivos (404, 409, 410, 451)
  também ficam em cache, para não serem repetidos. O corpo é gravado em JSON
  comprimido (zlib), o que reduz o cache cerca de 10 vezes. Para forçar uma nova
  coleta, apague `cache/api.sqlite`.
- **Rate limit:** lê `X-RateLimit-Remaining`/`X-RateLimit-Reset` de cada resposta e,
  quando a cota de um recurso (`core`, `search`...) chega a zero, pausa até a
  renovação. Respostas 403/429 de limite secundário respeitam `Retry-After` (ou
  esperam 60 s).
- **Erros temporários:** respostas 5xx e falhas de rede são repetidas com backoff
  exponencial (1 s, 2 s, 4 s, ...), até `coleta.max_tentativas`.
- **Paginação:** `paginar()` segue o cabeçalho `Link` (`rel="next"`) até a última página.
- **GraphQL:** `graphql(consulta, variaveis)` faz o POST em `/graphql` com o mesmo
  controle de cota e backoff; a chave do cache é o hash da consulta com as variáveis.
  É usado em dois pontos:
  - tags: 100 por consulta já com a data do commit (no REST seria uma chamada por tag);
  - commits entre releases (`ref.compare`): 5 compares por consulta, paginados de 100
    em 100, só com SHA, `authoredDate` (= `commit.author.date`) e mensagem. O compare
    do REST traz também o diff dos arquivos (~1 MB por chamada), que nenhuma RQ usa.
    Os dois devolvem os mesmos commits e datas; uma tag inexistente vira status `404`.

```python
from coleta.cliente import ClienteGitHub

with ClienteGitHub.de_config(config, token) as cliente:
    releases = list(cliente.paginar(f"/repos/{dono}/{repo}/releases", {"per_page": 100}))
    runs = cliente.paginar(f"/repos/{dono}/{repo}/actions/runs",
                           {"branch": "main", "event": "push", "per_page": 100},
                           chave_itens="workflow_runs")
```

## Configuração (`config.yaml`)

| Seção | Conteúdo |
|---|---|
| `janela` | Início e fim da janela de observação de 12 meses (UTC, datas inclusivas). |
| `selecao` | Faixas de estrelas e filtros da busca, arquivo onde a lista de candidatos fica salva (`arquivo_candidatos`), semente da ordem de avaliação e tamanho da amostra final. |
| `criterios_inclusao` | Mínimo de releases (5) e de workflow runs válidos (50) na janela. |
| `workflow_runs` | Evento considerado (`push`) e quais `conclusion` contam como sucesso/falha; as demais são ignoradas. |
| `metricas` | Parâmetros das métricas (ex.: janela de 7 dias da release corretiva). |
| `coleta` | Pasta de cache, tentativas e backoff para erros temporários. |
| `validacao_manual` | Semente e tamanhos da amostra-ouro, e os avaliadores (uma planilha de rotulagem para cada). |
| `saida` | Pasta dos CSVs gerados. |

Caminhos relativos são resolvidos a partir da pasta do `config.yaml`.

## Coleta e funil de seleção

### 1. Lista de candidatos (salva e reaproveitada)

Os **candidatos** são todos os repositórios que podem ser sorteados para a amostra.
Eles vêm da busca do GitHub, feita por faixa de estrelas (`selecao.faixas_estrelas`),
sem forks nem repositórios arquivados (`selecao.filtros_busca`).

**O problema do teto de 1.000.** A busca do GitHub devolve no máximo 1.000 resultados
por consulta, sempre os de mais estrelas. A faixa "1.000 a 2.000 estrelas" tem cerca de
29 mil repositórios, então uma única consulta traria só os 1.000 maiores (de ~1.940 a
2.000 estrelas). Um repositório com 1.100 estrelas nunca entraria na lista.

**A solução: dividir a faixa em pedaços menores.** Quando uma consulta passa de 1.000
resultados, a faixa é dividida ao meio, e cada metade é consultada de novo. Isso se
repete até cada pedaço (chamado de *subintervalo*) ter no máximo 1.000 repositórios.
Exemplo:

```
1000..2000  → 29.000 resultados, passa de 1.000 → divide
├── 1000..1500 → 20.000, passa de 1.000 → divide
│   ├── 1000..1250 → ...
│   └── ...
└── 1501..2000 → ...
    └── ... até cada pedaço ter no máximo 1.000
```

Assim vêm **todos** os repositórios de cada faixa, e qualquer um deles pode ser sorteado.

A busca atual trouxe **60.043 candidatos** (todos os repositórios com 1.000 estrelas ou
mais, sem forks nem arquivados). Esses repositórios são apenas **listados**: de cada um
vêm só os dados que a própria busca devolve (nome, estrelas, linguagem, criação, branch
principal). Releases, commits e workflow runs só são coletados dos candidatos avaliados
no funil e da amostra.

**Por que listar todos.** O enunciado pede para fatiar a busca para obter mais
candidatos, mas não exige todos. Listar todos foi decisão do grupo: com só os 1.000
maiores de cada faixa, faixas inteiras de popularidade ficariam sem candidatos (por
exemplo, nenhum repositório entre 1.000 e 1.940 estrelas), o que distorceria a amostra
e a comparação por popularidade da RQ 06. Pegar uma parte de cada subintervalo também
resolveria; a lista completa foi escolhida por ser mais simples de justificar e porque
a busca é feita uma única vez.

**A busca é feita uma única vez** e fica salva em dois arquivos, que vão para o git:

| Arquivo | O que tem |
|---|---|
| `dados/candidatos.csv` | A lista de candidatos: uma linha por repositório, com nome, faixa, subintervalo, estrelas, linguagem, data de criação, branch principal, link e data da busca. |
| `dados/candidatos_faixas.csv` | Uma linha por subintervalo consultado: a faixa, a consulta usada, quantos repositórios existiam (`disponiveis`) e quantos vieram (`obtidos`). Se `obtidos` for igual a `disponiveis` em todas as linhas, nenhum repositório ficou de fora. |

Nas próximas execuções, o pipeline usa esses arquivos e **não busca de novo**. Por isso
a amostra não muda com o tempo (mesmo que os repositórios ganhem ou percam estrelas) e
todos usam a mesma lista, inclusive o grupo que for replicar o trabalho. As estrelas
registradas são as do dia da busca.

- **Para refazer a busca**, apague `dados/candidatos.csv` e `dados/candidatos_faixas.csv`.
- Se as faixas ou os filtros do `config.yaml` mudarem sem apagar os arquivos, o log avisa.

### 2. Ordem de avaliação e amostra

A ordem de avaliação é aleatória e reproduzível: os candidatos são ordenados pelo
hash SHA-256 de `selecao.semente` + nome do repositório. Com a mesma lista e a mesma
semente, a ordem (e portanto a amostra) é sempre a mesma. Como a posição de cada
repositório depende só do próprio nome, se a busca for refeita e alguns candidatos
entrarem ou saírem, os demais mantêm a ordem relativa.

**Por que sortear.** O enunciado deixa a definição da amostra com o grupo. Milhares
de candidatos passam nos critérios de inclusão, e só queremos 100 (depois 300). Sem
uma ordem aleatória, a escolha cairia sempre nos primeiros da lista (que vem ordenada
por estrelas) e a amostra teria só os mais populares. Avaliar numa ordem aleatória e
parar nos primeiros N aprovados equivale a sortear N entre todos os que passam nos
critérios, sem precisar avaliar os 60 mil.

Os candidatos são avaliados nessa ordem até a amostra atingir `selecao.tamanho_amostra`
(100 na S01, ≥ 300 na S02). Aumentar o tamanho não troca quem já entrou: a avaliação
continua do ponto seguinte da mesma ordem. Os candidatos que sobram entram no funil
como `nao_avaliado`. Para outra amostra, mude a semente (decisão do grupo, registrada
na Metodologia).

### 3. Funil de seleção

Cada candidato passa pelos filtros do mais barato ao mais caro e para no primeiro
em que reprovar; o motivo fica em `funil.csv`:

| Etapa | Critério | Motivo do descarte |
|---|---|---|
| Acesso | O repositório responde na API (não foi apagado ou bloqueado). Token inválido (401), erros 5xx e falhas de rede interrompem a coleta em vez de descartar o candidato. | `erro_api` |
| Usa Actions | `/actions/workflows` com `total_count > 0`. | `sem_actions` |
| Releases | ≥ 5 releases publicadas na janela (`draft = false`, sem pré-releases). | `poucas_releases` |
| Workflow runs | ≥ 50 runs válidos na janela: `event = push` no default branch, `conclusion` de sucesso ou falha. A contagem é exata, feita sobre os runs coletados (o `total_count` com filtro `status` da API subconta). | `poucos_runs` |

### 4. Coleta de cada repositório da amostra

- **Metadados:** estrelas, linguagem, data de criação e default branch vêm da busca; o
  nº de contribuidores vem de `/contributors?per_page=1&anon=true` (número da última
  página do cabeçalho `Link`). Em repositórios muito grandes a API se recusa a listar
  os contribuidores; nesse caso o campo fica vazio.
- **Releases:** todas, com `draft`, `prerelease`, `published_at`, `tag_name` e link.
- **Tags** (variante da RQ 07): pela GraphQL, 100 por consulta, já com as datas do commit
  apontado (no REST seria uma chamada por tag). A data usada para ordenar e situar a tag
  na janela é a data de autor do commit, coerente com a regra `commit.author.date`.
- **Commits entre releases:** para cada item publicado na janela, o compare com o item
  anterior (que pode estar fora da janela), em três cadeias: `release` (definição
  principal), `release_prerelease` e `tag` (variantes da RQ 07). Pares repetidos entre
  cadeias são consultados uma vez. É feito pela GraphQL (`ref.compare`), 5 compares por
  consulta e todos os commits paginados de 100 em 100, com SHA, `commit.author.date` e a
  mensagem completa. Tag apagada ou renomeada vira status `404` e é contada.
  A GraphQL para em 1.000 commits por compare; quando o total informado é maior, o par
  é refeito pelo compare do REST, paginado. Se o REST recusar o par (por exemplo, 404
  "No common ancestor", quando o projeto mantém linhas de versão com históricos
  separados), ele recebe esse status e fica fora do lead time, como os demais 404.
- **Workflow runs:** `event = push` no default branch, janela dividida em meses. Um mês
  com mais de 1.000 runs (teto da API com filtros) é dividido ao meio até caber; se nem
  um dia couber, ele fica marcado como truncado em `runs_intervalos.csv`.

Todas as datas são gravadas em UTC (a GraphQL devolve o fuso do autor do commit, que é
convertido).

### Desempenho

Medido em execuções de teste com 3 repositórios, sobre o cache da API:

| Ponto | Antes | Depois |
|---|---|---|
| Tags (`astral-sh/ruff`, 431 tags) | REST: ~440 chamadas, ~170 s | GraphQL: 5 chamadas, ~3 s |
| Commits entre releases (3 repositórios) | REST: 132 chamadas, ~230 s, ~150 MB (o REST traz o diff dos arquivos) | GraphQL: 35 chamadas, ~60 s, 16 MB, com os mesmos commits, datas e mensagens |
| Reexecução | — | 0 chamadas, ~2 s (tudo do cache) |
| Busca | Refeita a cada execução sem cache | Feita uma vez (~37 min para os 60.043 candidatos, em 90 consultas, por causa do limite de 30 buscas por minuto) e salva em `dados/candidatos.csv` |

O que mais pesa agora são os workflow runs: só existem no REST, cada página traz no
máximo 100 runs e leva ~3 s para o GitHub gerar. O tempo de uma coleta depende de
quantos repositórios muito ativos forem sorteados.

### Arquivos gerados em `dados/brutos/`

Regenerados a cada execução a partir do cache. Só os três arquivos do funil
(`faixas_busca.csv`, `funil.csv` e `funil_resumo.csv`, ~3 MB no total) vão para o git,
porque entram na Metodologia; os demais são grandes e não são versionados.

| Arquivo | Conteúdo |
|---|---|
| `faixas_busca.csv` | Uma linha por subintervalo da busca: faixa, consulta, total disponível e quantos foram obtidos. |
| `funil.csv` | Um candidato por linha, com a situação (`incluido` ou o motivo do descarte). |
| `funil_resumo.csv` | Quantos repositórios restaram após cada etapa do funil. |
| `repositorios.csv` | Metadados da amostra: estrelas, linguagem, criação, contribuidores, default branch. |
| `releases.csv` | Todas as releases, com `draft`, `prerelease`, `publicada_em`, link e o texto das release notes (`body`). |
| `tags.csv` | Tags com as datas de autor e de committer do commit apontado. |
| `compares.csv` | Item de cada cadeia publicado na janela, o anterior, o status do compare (`ok`, `primeira` ou o HTTP do erro, ex.: `404`), a divergência (`ahead`, `behind`...) e o total de commits informado pelo GitHub, para conferir a paginação. |
| `commits.csv` | Commits de cada compare: SHA, `commit.author.date`, título e mensagem completa (usada na heurística de release corretiva). |
| `runs.csv` | Workflow runs com workflow, `conclusion`, `run_started_at`, `updated_at` e `run_attempt` (coluna `tentativa`: > 1 indica run reexecutado sem novo commit). |
| `runs_intervalos.csv` | Consultas de runs feitas, com o `total_count` e se o intervalo ficou truncado. |

### Baixar os dados brutos sem refazer a coleta

Os CSVs da amostra final (300 repositórios, coleta concluída em 2026-10-13) estão no
release [`dados-s02`](https://github.com/Lab-Experimentao/Lab03-MineracaoMetricasDora/releases/tag/dados-s02),
no arquivo `dados_brutos_s02.zip` (~157 MB). Com eles não é preciso token nem acessar a API.

1. Baixe o `.zip` pela página do release ou pelo terminal:
   - com o GitHub CLI: `gh release download dados-s02 --repo Lab-Experimentao/Lab03-MineracaoMetricasDora`
   - sem o GitHub CLI: `curl -LO https://github.com/Lab-Experimentao/Lab03-MineracaoMetricasDora/releases/download/dados-s02/dados_brutos_s02.zip` (no PowerShell, use `curl.exe`)
2. Descompacte em `dados/brutos/`:

   ```powershell
   # Windows (PowerShell)
   Expand-Archive dados_brutos_s02.zip dados/brutos -Force
   ```

   ```bash
   # Linux / macOS
   unzip -o dados_brutos_s02.zip -d dados/brutos
   ```

3. (Opcional) Recalcule `dados/metricas.csv` a partir deles:
   `python -m pipeline --config config.yaml --etapas metricas`.

Atenção: a etapa de coleta regrava `dados/brutos/` a partir do cache. Sem o
`cache/api.sqlite`, rode só `--etapas metricas` para não refazer a coleta.

## Métricas (`dados/metricas.csv`)

A etapa de métricas lê `dados/brutos/` e grava `dados/metricas.csv`, versionado no git,
com uma linha por repositório da amostra: os metadados de `repositorios.csv` mais as
métricas abaixo, na definição principal (release como deploy, lead time (a), CFR (a)).
As funções de cálculo ficam em `metricas/` e têm testes com os exemplos do enunciado.

| Coluna | Unidade | Como é calculada |
|---|---|---|
| `releases_janela` | releases | Releases publicadas na janela (`draft = false`, sem pré-releases). |
| `deploys_por_semana` | releases/semana | `releases_janela` ÷ semanas da janela (≈ 52,1). |
| `lead_time_release_horas` | horas | (a) Mediana, entre as releases, de publicação − commit mais antigo incluído. |
| `lead_time_commit_horas` | horas | (b) Mediana de publicação − data de cada commit, de todas as releases. |
| `releases_lead_time` | releases | Releases usadas no lead time. |
| `releases_primeira` | releases | Primeira release da história (sem anterior): fora do lead time. |
| `releases_sem_commits` | releases | Releases sem commits novos em relação à anterior. |
| `releases_compare_erro` | releases | Releases ignoradas no lead time porque o compare falhou (ex.: 404). |
| `commits_data_futura` | commits | Commits com data de autor posterior à release, ignorados (rebase, cherry-pick). |
| `cfr_ci` | proporção (0–1) | (a) Runs com falha ÷ (falhas + sucessos); `cancelled`, `skipped` etc. não entram. |
| `runs_falha`, `runs_sucesso`, `runs_ignorados` | runs | Contagens usadas no CFR. |
| `cfr_ci_sem_flaky` | proporção (0–1) | `cfr_ci` sem as falhas seguidas de sucesso no mesmo workflow e commit (`falhas_flaky_mesmo_commit`), para comparar com o original. |
| `falhas_flaky_mesmo_commit` | runs | Runs com falha que têm um run com sucesso depois, no mesmo workflow e `head_sha`. |
| `runs_reexecutados` | runs | Runs com `run_attempt` > 1. |
| `runs_flaky_reexecucao` | runs | Runs reexecutados que terminaram em sucesso. |
| `cfr_entrega` | proporção (0–1) | (b) Releases seguidas por uma release corretiva em até 7 dias ÷ releases avaliadas. Não entra na classificação C1. |
| `releases_falharam`, `releases_avaliadas_cfr`, `releases_censuradas_cfr` | releases | Contagens do CFR (b). As releases dos últimos 7 dias da janela são censuradas: ficam fora do denominador. |
| `releases_corretivas` | releases | Releases marcadas como corretivas pela heurística (base da rework rate, RQ 08). |
| `recuperacao_horas` | horas | Mediana dos episódios de falha de todos os workflows: da primeira falha após um sucesso (`run_started_at`) ao próximo sucesso do mesmo workflow (`updated_at`). |
| `episodios_recuperados`, `episodios_censurados` | episódios | Episódios encerrados e não encerrados até o fim da janela. |
| `proporcao_censurados` | proporção (0–1) | Censurados ÷ total de episódios. |
| `classe_frequencia`, `classe_lead_time`, `classe_cfr`, `classe_recuperacao` | Elite/High/Medium/Low | Cortes da tabela de referência do enunciado. |
| `classe_geral` | Elite/High/Medium/Low | Mediana das notas (Elite = 4 … Low = 1), arredondada para baixo. |

Decisões adotadas onde o enunciado não define:

- Falhas antes do primeiro sucesso de um workflow não abrem episódio de recuperação,
  pois o início real da falha é desconhecido.
- Um repositório sem nenhuma falha de CI não tem tempo de recuperação; nesse caso a
  classe geral é a mediana das métricas disponíveis (três em vez de quatro).
- Runs sem `run_started_at` usam o `created_at` como início.
- Falha intermitente (flaky) é a que passou no mesmo commit sem mudança de código. Um run
  reexecutado que passou (`run_attempt` > 1) é o caso mais comum, mas a listagem de runs
  da API traz só a última tentativa: a falha anterior não está nos dados, e o run já entra
  no `cfr_ci` como sucesso. Por isso ele só é contado (`runs_flaky_reexecucao`), e o
  `cfr_ci_sem_flaky` tira apenas as falhas que estão nos dados (`falhas_flaky_mesmo_commit`).
  Para ver as falhas escondidas pelas reexecuções seria preciso buscar cada tentativa
  anterior em `GET /repos/{repo}/actions/runs/{id}/attempts/{n}`.

O log da etapa mostra quantas releases foram ignoradas por erro no compare e a
distribuição da classificação geral. Para recalcular só as métricas, sem acessar a API:

```bash
python -m pipeline --config config.yaml --etapas metricas
```

## Validação manual (`dados/validacao/`)

A etapa de validação sorteia a amostra-ouro (seção 6 do enunciado) e gera uma planilha de
rotulagem em branco por avaliador. Não acessa a API; lê `dados/metricas.csv` e
`dados/brutos/` (baixe-os do release `dados-s02` se não tiver feito a coleta):

```bash
python -m pipeline --config config.yaml --etapas validacao
```

- **Repositórios:** 60 da amostra final, sorteados com `DataFrame.sample(n=60, random_state=42)`
  sobre a lista ordenada por nome (`validacao_manual.n_repositorios` e `semente`).
- **Releases:** 5 por repositório, sorteadas da mesma forma entre as releases da definição
  principal publicadas na janela (cadeia `release` de `compares.csv`), as mesmas que a
  heurística de release corretiva classifica.

| Arquivo | Conteúdo |
|---|---|
| `amostra_ouro.csv` | As 300 releases sorteadas: repositório, tag, release anterior, data, link da release e link dos commits desde a anterior. Referência para cruzar com os rótulos. |
| `rotulagem_<avaliador>.xlsx` | Planilha de cada avaliador (`validacao_manual.avaliadores`), com as abas `instrucoes`, `repositorios` (tipo do projeto e se as releases são entregas reais) e `releases` (se a release é corretiva). Os rótulos são escolhidos em listas suspensas. Para cada release, a planilha já traz o início das release notes (até 1.000 caracteres, de `releases.csv`) e os títulos dos commits desde a anterior (até 20, de `commits.csv`), para julgar sem abrir os links na maioria dos casos. |

A planilha não mostra nenhuma saída da heurística. Cada avaliador preenche a sua sozinho,
sem consultar os demais, e a commita. Reexecutar a etapa não sobrescreve planilhas que já
existem; para gerar uma de novo em branco, apague-a antes.

### Concordância e consenso

Quando as planilhas de todos os avaliadores estão completas (nenhum rótulo vazio ou fora
da lista), a mesma etapa calcula o kappa de Fleiss em cada dimensão, com `aggregate_raters`
e `fleiss_kappa` do statsmodels, e monta o rótulo de consenso. Enquanto alguma estiver
incompleta, ela só avisa no log o que falta. O código fica em `validacao/concordancia.py`.
Com as planilhas de todos os avaliadores já criadas, a etapa não refaz o sorteio e não lê
`dados/brutos/`: para calcular a concordância bastam as planilhas.

**Protocolo de desempate:**

1. Os três concordam: é o consenso (`unanime`).
2. Dois concordam e um diverge: vale a maioria simples (`maioria`).
3. Os três divergem (1-1-1, possível em `tipo_projeto` e `entregas_reais`): o caso é decidido
   em reunião do grupo e registrado em `desempates.csv` (`reuniao`). Até lá, fica `pendente`
   e a etapa avisa no log.

Se o grupo rediscutir em reunião um caso de maioria, a decisão também vai em
`desempates.csv` e prevalece sobre a maioria. O kappa e as contagens de concordância são
sempre os da rotulagem independente, antes de qualquer reunião.

| Arquivo | Conteúdo |
|---|---|
| `desempates.csv` | Preenchido pelo grupo: `dimensao` (`tipo_projeto`, `entregas_reais` ou `corretiva`), `repositorio`, `tag` (só para `corretiva`), `rotulo` decidido e `justificativa`. A etapa cria o arquivo em branco e recusa decisões com item ou rótulo inexistente. |
| `concordancia.csv` | Uma linha por dimensão: itens, avaliadores, kappa de Fleiss, interpretação (Landis & Koch, 1977), concordância observada (proporção média de pares de avaliadores que concordam), e quantos itens foram unânimes, decididos por maioria, sem maioria, decididos em reunião e ainda pendentes. |
| `consenso_repositorios.csv` | Os 60 repositórios: `tipo_projeto` e `entregas_reais` de consenso, a regra que definiu cada um (`*_regra`) e o rótulo de cada avaliador (`*_<avaliador>`). Referência para a classificação automática do tipo de projeto e para a RQ 06. |
| `consenso_releases.csv` | As 300 releases: `corretiva` de consenso, a regra e o rótulo de cada avaliador. Referência para a precisão, o recall e o F1 da heurística de release corretiva. |

Um kappa baixo com concordância observada alta indica que quase todos os itens caíram na
mesma categoria: o kappa desconta a concordância esperada por acaso, que nesse caso já é
alta. É o que acontece em `entregas_reais`, em que a resposta é `sim` para quase todos os
repositórios.

### Heurística de release corretiva (CFR b)

O CFR (b) considera que uma release falhou quando ela é seguida, em até 7 dias
(`metricas.janela_release_corretiva_dias`), por uma release corretiva. Basta qualquer release
corretiva nesse prazo, não só a imediatamente seguinte. As releases publicadas nos últimos 7
dias da janela ficam fora do denominador (censura). O código está em `metricas/corretiva.py`.

A heurística que decide se uma release é corretiva foi validada contra o consenso das 300
releases da amostra-ouro (126 corretivas), com `precision_recall_fscore_support` do
scikit-learn. A mesma etapa de validação recalcula tudo e grava `heuristica_versoes.csv` e
`heuristica_erros.csv` (precisa de `dados/brutos/commits.csv`). Cada versão testada:

| Versão | Regra | Precisão | Recall | F1 |
|---|---|---|---|---|
| v1 | Muda só o patch em relação à anterior **ou** algum commit com fix/hotfix/revert (sugestão do enunciado) | 0,471 | 0,960 | 0,632 |
| v2 | Muda só o patch em relação à anterior **e** algum commit com fix/hotfix/revert | 0,681 | 0,611 | 0,644 |
| v3 | A própria versão é um patch (X.Y.Z com Z > 0) | 0,578 | 0,936 | **0,715** |
| v4 | A própria versão é um patch **e** algum commit com fix/hotfix/revert | 0,671 | 0,762 | 0,714 |

Erros que motivaram cada refinamento:

- **v1 → v2:** dos 136 falsos positivos da v1, 84 eram releases minor ou major com algum
  commit de correção. Releases com recursos novos quase sempre trazem também alguns `fix`,
  então o commit sozinho não indica release corretiva. A v2 passou a exigir os dois sinais.
- **v2 → v3:** a precisão subiu, mas o recall caiu para 0,61 (49 falsos negativos). 24 deles
  eram releases patch pela própria versão (ex.: `v3.0.15`), cuja "anterior" na ordem de
  publicação é de outra linha de versão (backport, ex.: `v4.1.1`) ou de outro pacote do
  monorepo. Outros 17 eram patches sem nenhum commit com fix/hotfix/revert no título: a
  correção é descrita com outras palavras (ex.: "Properly reset the breakpoint skip…",
  "Add workaround for Apple GPU hardware bug", "Don't evaluate if() values…") ou o compare
  só tem commits de versão (ex.: "Changes for 8.6.1"). A v3 olha só o número da própria tag.
- **v3 → v4:** a v3 passou do limiar de 0,70. Restam 86 falsos positivos, quase todos versões
  patch que trazem recursos novos (comum em projetos 0.x) ou só atualizam dependências, e 17
  deles sem commits no compare. A v4 tentou recuperar a precisão exigindo também um commit de
  correção, mas perdeu recall na mesma proporção (F1 0,714) e não foi adotada.

O CFR (b) usa a **v3**, a de maior F1. Dos 8 falsos negativos que restam, 7 são releases minor
cujo conteúdo é só de correções (ex.: `remeda v2.44.0`, `itch v26.18.0`) e 1 é uma beta
(`ustcthesis v4.0.0-beta.10`): casos que nenhuma regra baseada na versão consegue separar.

## Tipo de projeto (`dados/tipo_projeto.csv`)

A RQ 06 usa o tipo de projeto como fator. A amostra-ouro tem esse rótulo só para 60
repositórios, então a etapa `tipo_projeto` estende a classificação aos 300 com uma heurística
validada contra o consenso:

```bash
python -m pipeline --config config.yaml --etapas tipo_projeto
```

1. **Perfil:** para cada repositório de `metricas.csv`, coleta a descrição e os tópicos
   (`GET /repos/{repo}`) e os primeiros 4.000 caracteres do README
   (`GET /repos/{repo}/readme`). O resultado vai para `dados/perfis_repositorios.csv`, que é
   versionado: com ele, a etapa roda sem token. O token só é pedido para os repositórios que
   faltam no arquivo; a coleta dos 300 fez 600 chamadas e levou cerca de 4 minutos.
2. **Heurística** (`metricas/tipo_projeto.py`): cada tipo tem padrões de texto procurados na
   descrição (peso 3), nos tópicos (peso 2) e no README (peso 1). Vence o tipo com mais
   pontos. Em caso de empate, ou sem nenhum sinal, a ordem é aplicação, biblioteca, CLI e
   outro, do tipo mais comum para o menos comum na amostra-ouro.
3. **Validação** contra o `tipo_projeto` de `consenso_repositorios.csv`, com
   `precision_recall_fscore_support` por tipo, mais as médias macro e ponderada e a acurácia.
4. **Tipo final:** nos 60 repositórios da amostra-ouro vale o rótulo de consenso; nos demais,
   o da heurística. A coluna `origem` diz qual dos dois foi usado.

| Versão | Acurácia | Precisão (macro) | Recall (macro) | F1 (macro) |
|---|---|---|---|---|
| v1 | 0,733 | 0,783 | 0,617 | 0,662 |
| v2 | 0,950 | 0,971 | 0,902 | 0,932 |

F1 da v2 por tipo: biblioteca/framework 0,952 (21 repositórios), aplicação/serviço 0,964 (27),
ferramenta CLI 0,923 (7) e outro 0,889 (5).

**Erros da v1 que motivaram a v2** (16 dos 60):

- 6 bibliotecas sem nenhuma palavra-chave caíam no tipo padrão, aplicação ("simple HTTP
  client in Erlang", "The Scala HTTP client you always wanted!", "modeling tool for DynamoDB").
  A v2 reconhece "HTTP/API client", "for/in <linguagem>", ORM e os badges e links de pacote
  publicado no README (npm, PyPI, crates.io, Maven Central, NuGet, Hex, Packagist).
- 2 bibliotecas viravam aplicação por palavras genéricas: "database" (EF Core) e "desktop"
  (notificações de desktop em PHP). A v2 exige "desktop app".
- 5 ferramentas CLI eram classificadas como biblioteca ou aplicação: "plugin" do Cargo e do
  Composer contavam como biblioteca, e um profiler, um binário estático e uma ferramenta
  instalada por Homebrew/Chocolatey não tinham sinal de CLI. A v2 tira "plugin" e reconhece
  linters, formatadores, profilers, análise estática, "subcommand", instalação por
  Homebrew/Chocolatey/Scoop/winget e "single/static binary".
- 2 do tipo outro: uma GitHub Action identificada só pelo README e um plugin do Obsidian.
- 1 servidor MCP virou CLI por causa do `npx` no README. A v2 reconhece "MCP server".

Erros que restam na v2: uma GitHub Action com um sinal de aplicação e um de outro no README
(o empate favorece aplicação), o Microsoft Quantum
Development Kit (sem sinal de biblioteca) e o dart-sass, que é ao mesmo tempo biblioteca e
CLI e cuja descrição diz "implementation of".

**Limitação:** as regras da v2 foram escritas a partir dos erros da v1 nos mesmos 60
repositórios em que são avaliadas, então o F1 de 0,932 é otimista. Numa checagem informal de
30 repositórios sorteados fora da amostra-ouro, apareceram erros claros que a validação não
captura: `django-debug-toolbar` e `react-native-firebase` saem como aplicação, mas são
bibliotecas. Também há casos ambíguos, como motores de jogo e módulos PowerShell. Para uma
estimativa sem esse viés, o grupo pode rotular uma amostra nova, fora dos 60, e compará-la
com `tipo_heuristica`.

## Estatística descritiva das RQ 01 a RQ 04 (`dados/analise/`)

A etapa `analise` lê só `dados/metricas.csv` (não precisa de token nem de `dados/brutos/`):

```bash
python -m pipeline --config config.yaml --etapas analise
```

Resultado com os 300 repositórios (mediana e IQR entre os repositórios):

| RQ | Métrica | n | Mediana | Q1 – Q3 | IQR |
|---|---|---|---|---|---|
| 01 | Deploys por semana | 300 | 0,35 | 0,19 – 0,85 | 0,66 |
| 02 (a) | Lead time por release (h) | 300 | 174,7 | 24,6 – 595,7 | 571,1 |
| 02 (b) | Lead time por commit (h) | 300 | 137,9 | 21,3 – 618,0 | 596,7 |
| 03 (a) | CFR de CI | 300 | 5,98% | 2,55% – 12,84% | 10,30 p.p. |
| 03 (a) | CFR de CI sem flaky | 300 | 5,98% | 2,55% – 12,84% | 10,30 p.p. |
| 03 (b) | CFR de entrega | 299 | 37,5% | 16,7% – 69,6% | 52,96 p.p. |
| 04 | Tempo de recuperação (h) | 283 | 1,97 | 0,55 – 12,21 | 11,66 |

**Censura.** 106 de 13.017 episódios de falha (0,8%, em 60 repositórios) não têm sucesso
posterior até o fim da janela e ficam fora da mediana da RQ 04. Outros 17 repositórios não têm
nenhum episódio recuperado, então não têm tempo de recuperação. No CFR (b), 429 de 15.550
releases (2,8%, em 121 repositórios) saíram nos últimos 7 dias e ficam fora do denominador.
Como os episódios censurados são os que ainda não terminaram, a mediana da RQ 04 tende a
subestimar o tempo real, mas com 0,8% de censura o efeito é pequeno.

**Divergência entre as variantes do lead time.** A mediana de (b) é menor que a de (a)
(137,9 h contra 174,7 h), e (b) fica abaixo de (a) em 193 repositórios. Era o esperado: (a)
mede cada release a partir do commit **mais antigo**, então em cada release ela é o teto de
(b). Mesmo assim, (b) passa de (a) em 105 repositórios. Isso acontece porque (b) junta os
commits de todas as releases e dá a cada uma um peso proporcional ao número de commits, enquanto
(a) dá o mesmo peso a cada release. Assim, poucas releases grandes e demoradas puxam a mediana
de (b) para cima. As duas variantes ordenam os repositórios de forma parecida (Spearman 0,72),
e a razão b/a tem mediana 0,72 (IQR 0,43 – 1,64).

**Flakiness no CFR de CI.** Tirar as falhas seguidas de sucesso no mesmo commit
(`cfr_ci_sem_flaky`) quase não muda nada: são só 13 de 44.545 falhas, em 10 repositórios, e
a mediana continua em 5,98%. A maior parte da flakiness não aparece nessa conta. A API lista só
a última tentativa de cada run, então os 2.021 runs reexecutados que passaram já contam como
sucesso, e a falha anterior deles não está nos dados. Contando uma falha a mais para cada um, o
que é um limite inferior da quantidade de tentativas escondidas, a mediana sobe para 6,61%
(+0,63 p.p.) e a taxa agregada vai de 9,31% para 9,69%. Nesse cenário, cerca de 4% da taxa
agregada (1,9% na mediana por repositório) vem de flakiness. A definição principal fica com o
`cfr_ci`; o cenário com reexecuções é uma análise de sensibilidade.

## Classificação DORA de referência (`dados/analise/classificacao_*.csv`)

A combinação de referência (C1) usa release como deploy, lead time (a), CFR (a) e tempo de
recuperação, com os cortes da tabela do enunciado (`metricas/classificacao.py`). A classe
geral é a mediana das notas (Elite = 4 … Low = 1), arredondada para baixo. As classes são
calculadas na etapa de métricas, e a etapa `analise` faz as contagens e os cruzamentos.

| Dimensão | Elite | High | Medium | Low | Sem dados |
|---|---|---|---|---|---|
| Frequência de deploy | 5 (1,7%) | 57 (19,0%) | 140 (46,7%) | 98 (32,7%) | 0 |
| Lead time (a) | 73 (24,3%) | 76 (25,3%) | 87 (29,0%) | 64 (21,3%) | 0 |
| CFR (a) | 239 (79,7%) | 32 (10,7%) | 13 (4,3%) | 16 (5,3%) | 0 |
| Tempo de recuperação | 102 (34,0%) | 135 (45,0%) | 38 (12,7%) | 8 (2,7%) | 17 |
| **Geral** | **34 (11,3%)** | **130 (43,3%)** | **113 (37,7%)** | **23 (7,7%)** | 0 |

**O que limita a classe geral.** A frequência de deploy é a dimensão mais fraca: em 166
repositórios ela fica abaixo da classe geral (32 dos 34 Elite e 84 dos 130 High). O lead time
vem em seguida (70). CFR e recuperação quase nunca puxam a classe para baixo (13 e 11), pois o
CFR de CI é Elite em 80% dos repositórios.

**Repositórios sem tempo de recuperação (17).** São classificados com as outras três
dimensões. Desses, 11 não tiveram nenhuma falha de CI na janela. Os outros 6 falharam só antes
do primeiro sucesso de cada workflow, então não abriram nenhum episódio.

**Sensibilidade** (`classificacao_sensibilidade.csv`):

| Cenário | Elite | High | Medium | Low | Mudam de classe |
|---|---|---|---|---|---|
| Referência (arredondamento para baixo) | 34 | 130 | 113 | 23 | — |
| Arredondamento para cima | 89 | 145 | 60 | 6 | 142 |
| Sem falha de CI = Elite em recuperação | 34 | 135 | 109 | 22 | 6 |

Em 142 repositórios (47%), a mediana das quatro notas termina em ,5 (ex.: Elite, Elite, High,
Medium), e só o critério de arredondamento decide a classe. Arredondar para cima quase triplica
os Elite. A referência fica com o arredondamento para baixo, o mais conservador, e essa
escolha entra nas ameaças à validade. Dar Elite em recuperação aos 11 repositórios sem falha
muda pouco: 6 repositórios sobem uma classe.

## RQ 05: velocidade x estabilidade (`dados/analise/rq05_*`)

Correlação de Spearman entre `deploys_por_semana` e o CFR, separada por variante
(`analise/correlacao.py`). Entram só os repositórios com os dois valores. O gráfico
`rq05_dispersao.png` usa escala log nos dois eixos, e os repositórios com CFR igual a 0 ficam
numa faixa abaixo do menor valor positivo.

| Variante | n | CFR = 0 | ρ | p-valor |
|---|---|---|---|---|
| (a) CFR de CI | 300 | 11 | 0,10 | 0,072 |
| (b) CFR de entrega | 299 | 38 | 0,63 | < 0,001 |

Com o CFR de CI, não há relação: ρ fica perto de zero e não é significativo a 5%. Fazer
deploy com mais frequência não vem acompanhado de mais falhas no CI. Com o CFR de entrega, a
correlação é forte e positiva, mas parte dela vem da própria definição: uma release só falha se
outra, corretiva, sair em até 7 dias, e quem publica várias releases por semana tem muito mais
chance de ter uma release logo depois da anterior. Por isso o resultado de (b) não deve ser lido
como "quem entrega mais rápido quebra mais", e essa limitação entra nas ameaças à validade.

## RQ 06: características associadas ao desempenho (`dados/analise/rq06_*`)

Cinco fatores (`analise/fatores.py`), comparados nas quatro métricas da C1 (frequência de
deploy, lead time (a), CFR de CI e tempo de recuperação):

| Fator | Grupos |
|---|---|
| Linguagem | as 5 mais frequentes (TypeScript, Go, Rust, Python, C++) e `outras` (94) |
| Estrelas | quartis (cortes em 1.620, 3.310 e 7.660) |
| Contribuidores | quartis (cortes em 27, 76 e 178) |
| Idade no fim da janela | quartis (cortes em 1,5, 6,1 e 10,3 anos) |
| Tipo de projeto | os 4 tipos de `dados/tipo_projeto.csv` (`outro` tem só 10 repositórios) |

Para cada par fator × métrica, o teste é o de Kruskal-Wallis (com 2 grupos seria o de
Mann-Whitney), e os 20 p-valores são corrigidos juntos pelo método de Holm. O tamanho de efeito
é o ε² = H ÷ (n − 1), e o Cliff's delta compara Q4 com Q1 nos fatores em quartis e todos os pares
nos demais. As medianas de cada grupo estão em `rq06_grupos.csv`, e há um boxplot
(`rq06_<fator>.png`) para cada fator com algum resultado significativo.

Só 3 dos 20 testes ficam significativos depois da correção:

| Fator | Métrica | p (Holm) | ε² | Mediana Q1 → Q4 | Cliff Q4 × Q1 |
|---|---|---|---|---|---|
| Idade | Lead time (a) | < 0,001 | 0,120 (médio) | 36 h → 264 h | 0,47 (médio) |
| Idade | Deploys por semana | 0,002 | 0,071 (pequeno) | 0,61 → 0,27 | −0,45 (médio) |
| Contribuidores | Lead time (a) | 0,017 | 0,055 (pequeno) | 75 h → 340 h | 0,37 (médio) |

Os repositórios mais novos (até 1,5 ano) publicam releases com mais frequência e com lead time
bem menor. Nos repositórios com mais contribuidores o lead time também é maior. Os dois fatores
andam juntos (Spearman 0,57 entre idade e contribuidores), então não dá para separar o efeito de
cada um só com esses testes. O CFR de CI e o tempo de recuperação não variam com nenhum fator, e
estrelas e tipo de projeto não aparecem em nenhum resultado significativo. Linguagem chega perto
no lead time e na recuperação (p sem correção de 0,004 e 0,005), mas não passa pela correção de
Holm. Mesmo nos resultados significativos o ε² fica entre pequeno e médio: os fatores explicam
pouco da variação entre os repositórios.

## Dicionário de dados

Todas as colunas dos CSVs gerados (`metricas.csv`, `brutos/`, candidatos, funil, amostra-ouro e análise), com nome,
tipo, unidade e fórmula ou origem na API, estão em
[`dados/dicionario_dados.md`](dados/dicionario_dados.md).

## Estrutura

```
pipeline/   ponto de entrada (python -m pipeline) e leitura do config/token
coleta/     acesso à API do GitHub, cache, rate limit e funil de seleção
metricas/   funções puras de cálculo das métricas DORA
validacao/  sorteio da amostra-ouro, planilhas de rotulagem, concordância, consenso e
            validação das heurísticas (release corretiva e tipo de projeto)
tipo_projeto/ etapa que classifica o tipo de projeto dos 300 repositórios
analise/    análise estatística das RQs
tests/      testes com pytest
```

## Testes

```bash
pytest --cov=metricas --cov-report=term-missing
```

O workflow [`.github/workflows/testes.yml`](.github/workflows/testes.yml) roda os testes no
GitHub Actions a cada push e pull request, e falha se a cobertura do módulo `metricas`
ficar abaixo de 80% (`--cov-fail-under=80`).
