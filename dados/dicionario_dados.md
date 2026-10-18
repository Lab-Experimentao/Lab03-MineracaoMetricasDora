# Dicionário de dados

Colunas de todos os CSVs gerados pelo pipeline (`python -m pipeline --config config.yaml`).

Convenções válidas para todos os arquivos:

- **Codificação:** UTF-8, separador vírgula, cabeçalho na primeira linha.
- **Datas:** ISO 8601 em UTC (ex.: `2026-03-15T14:02:11+00:00`). A GraphQL devolve o fuso do
  autor do commit, que é convertido para UTC na coleta.
- **Booleanos:** `1` (verdadeiro) ou `0` (falso).
- **Valor ausente:** célula vazia (ex.: métrica sem dados suficientes, campo que a API não devolveu).
- **Janela de observação:** `janela.inicio` a `janela.fim` do `config.yaml` (2025-10-01 a
  2026-09-30, ambas inclusivas). Semanas da janela = dias ÷ 7 ≈ 52,1.
- **`repositorio`:** nome completo `dono/nome` (`full_name` da API). É a chave que liga os arquivos.

Tipos: `texto`, `inteiro`, `real`, `data-hora`, `data`, `booleano`.

## Arquivo principal

### `dados/metricas.csv`

Uma linha por repositório da amostra final. É o dataset usado nas análises. Traz as colunas de
`repositorios.csv` (ver abaixo) seguidas das métricas na definição principal (C1): release
como deploy, lead time (a) e CFR (a). O CFR (b) vem em colunas à parte e não entra nas classes.

| Coluna | Tipo | Unidade | Fórmula / origem |
|---|---|---|---|
| `repositorio`, `url`, `estrelas`, `linguagem`, `criado_em`, `contribuidores`, `branch_padrao`, `faixa` | — | — | Iguais a `brutos/repositorios.csv`. |
| `releases_janela` | inteiro | releases | Releases publicadas na janela com `draft = false` e `prerelease = false` (linhas da cadeia `release` em `compares.csv`). |
| `deploys_por_semana` | real | releases/semana | RQ 01: `releases_janela` ÷ semanas da janela (≈ 52,1). |
| `lead_time_release_horas` | real | horas | RQ 02 (a): para cada release, `published_at` − `commit.author.date` do commit mais antigo do compare com a release anterior; mediana entre as releases. |
| `lead_time_commit_horas` | real | horas | RQ 02 (b): `published_at` da release − `commit.author.date` de cada commit; mediana de todos os commits de todas as releases. |
| `releases_lead_time` | inteiro | releases | Releases que entraram no lead time (com anterior, compare ok e ao menos um commit). |
| `releases_primeira` | inteiro | releases | Releases sem release anterior na história do repositório; ficam fora do lead time. |
| `releases_sem_commits` | inteiro | releases | Releases cujo compare com a anterior não trouxe commits válidos; ficam fora do lead time. |
| `releases_compare_erro` | inteiro | releases | Releases ignoradas no lead time porque o compare falhou (ex.: 404 por tag apagada ou sem ancestral comum). |
| `commits_data_futura` | inteiro | commits | Commits com `commit.author.date` posterior a `published_at` da release (rebase, cherry-pick); ignorados. |
| `cfr_ci` | real | proporção (0–1) | RQ 03 (a): `runs_falha` ÷ (`runs_falha` + `runs_sucesso`). Vazio se não há runs válidos. |
| `runs_falha` | inteiro | runs | Runs com `conclusion` em `failure`, `timed_out` ou `startup_failure`. |
| `runs_sucesso` | inteiro | runs | Runs com `conclusion = success`. |
| `runs_ignorados` | inteiro | runs | Demais runs (`cancelled`, `skipped`, `neutral`, `action_required`, `stale`, vazio); não entram em nenhum cálculo. |
| `cfr_ci_sem_flaky` | real | proporção (0–1) | `cfr_ci` recalculado sem os `falhas_flaky_mesmo_commit`: (`runs_falha` − `falhas_flaky_mesmo_commit`) ÷ (`runs_falha` − `falhas_flaky_mesmo_commit` + `runs_sucesso`). Vazio se não há runs válidos. |
| `falhas_flaky_mesmo_commit` | inteiro | runs | Runs com falha seguidos, no mesmo `workflow_id` e `head_sha`, por um run com `conclusion = success` (`run_started_at` posterior). |
| `runs_reexecutados` | inteiro | runs | Runs com `run_attempt` > 1 (coluna `tentativa` de `runs.csv`). |
| `runs_flaky_reexecucao` | inteiro | runs | Runs com `run_attempt` > 1 e `conclusion = success`: falharam e passaram ao ser reexecutados no mesmo commit. A tentativa com falha não é listada pela API, então eles já contam como sucesso em `cfr_ci`. |
| `cfr_entrega` | real | proporção (0–1) | RQ 03 (b): `releases_falharam` ÷ `releases_avaliadas_cfr`. Vazio se nenhuma release pôde ser avaliada. |
| `releases_falharam` | inteiro | releases | Releases seguidas, em até 7 dias (`metricas.janela_release_corretiva_dias`), por alguma release corretiva. |
| `releases_avaliadas_cfr` | inteiro | releases | Releases da janela publicadas antes dos últimos 7 dias (denominador do CFR (b)). |
| `releases_censuradas_cfr` | inteiro | releases | Releases publicadas nos últimos 7 dias da janela: ainda não se sabe se haverá correção; fora do denominador. |
| `releases_corretivas` | inteiro | releases | Releases que a heurística atual (v3: a própria versão é um patch, X.Y.Z com Z > 0) marcou como corretivas. Base para a rework rate (RQ 08). |
| `recuperacao_horas` | real | horas | RQ 04: mediana dos episódios recuperados de todos os workflows. Episódio: da primeira falha após um sucesso (`run_started_at`, ou `created_at` se ausente) ao próximo sucesso do mesmo `workflow_id` (`updated_at`). Vazio se não há episódio recuperado. |
| `episodios_recuperados` | inteiro | episódios | Episódios de falha encerrados por um sucesso dentro da janela. |
| `episodios_censurados` | inteiro | episódios | Episódios sem sucesso posterior até o fim da janela (censura). |
| `proporcao_censurados` | real | proporção (0–1) | `episodios_censurados` ÷ (`episodios_recuperados` + `episodios_censurados`). Vazio se não há episódios. |
| `classe_frequencia` | texto | Elite/High/Medium/Low | Corte de `deploys_por_semana`: ≥ 7 Elite; ≥ 1 High; ≥ 1/mês Medium; abaixo disso Low. |
| `classe_lead_time` | texto | Elite/High/Medium/Low | Corte de `lead_time_release_horas`: < 1 dia Elite; < 1 semana High; < 30 dias Medium; ≥ 30 dias Low. |
| `classe_cfr` | texto | Elite/High/Medium/Low | Corte de `cfr_ci`: ≤ 15% Elite; ≤ 30% High; ≤ 45% Medium; > 45% Low. |
| `classe_recuperacao` | texto | Elite/High/Medium/Low | Corte de `recuperacao_horas`: < 1 h Elite; < 1 dia High; < 1 semana Medium; ≥ 1 semana Low. |
| `classe_geral` | texto | Elite/High/Medium/Low | Notas Elite = 4 … Low = 1 das classes disponíveis; mediana arredondada para baixo. Sem tempo de recuperação, usa as três restantes. |

### `dados/metricas_combinacoes.csv`

Uma linha por repositório e combinação de definições da RQ 07 (`metricas/combinacoes.py`), gerado
pela etapa de métricas junto com o `metricas.csv`. A linha da C1 repete as classes do
`metricas.csv`.

| Combinação | Unidade de deploy (cadeia de `compares.csv`) | Lead time | CFR |
|---|---|---|---|
| C1 | release (`release`) | (a) por release | (a) CI |
| C2 | release + pré-release (`release_prerelease`) | (b) por commit | (b) entrega |
| C3 | tag (`tag`) | (b) por commit | (a) CI |

| Coluna | Tipo | Unidade | Fórmula / origem |
|---|---|---|---|
| `repositorio`, `combinacao` | texto | — | Repositório e `C1`, `C2` ou `C3`. |
| `unidade_deploy`, `lead_time_variante`, `cfr_variante` | texto | — | Definições da combinação (`a` ou `b`). |
| `itens_janela` | inteiro | itens | Linhas da cadeia da combinação em `compares.csv` (itens publicados na janela). |
| `deploys_por_semana` | real | itens/semana | `itens_janela` ÷ semanas da janela. |
| `lead_time_horas` | real | horas | Lead time (a) ou (b) calculado sobre a cadeia da combinação, como em `metricas.csv`. |
| `cfr` | real | proporção (0–1) | `cfr_ci` do `metricas.csv` (a) ou CFR de entrega (b) calculado sobre a cadeia da combinação (heurística v3, 7 dias). |
| `recuperacao_horas` | real | horas | Igual ao `metricas.csv` em todas as combinações. |
| `classe_frequencia`, `classe_lead_time`, `classe_cfr`, `classe_recuperacao`, `classe_geral` | texto | Elite/High/Medium/Low | Mesmos cortes e mesma regra da classe geral do `metricas.csv`, aplicados aos valores da combinação. |

## Dados brutos da coleta (`dados/brutos/`)

Regenerados a partir do cache da API a cada execução da etapa de coleta.

### `repositorios.csv`

Uma linha por repositório da amostra final.

| Coluna | Tipo | Unidade | Fórmula / origem |
|---|---|---|---|
| `repositorio` | texto | — | `full_name` da busca (`GET /search/repositories`). |
| `url` | texto | — | `html_url` da busca. |
| `estrelas` | inteiro | estrelas | `stargazers_count` no dia da busca (`buscado_em` de `candidatos.csv`). |
| `linguagem` | texto | — | `language` (linguagem principal detectada pelo GitHub); vazio se não houver. |
| `criado_em` | data-hora | — | `created_at` do repositório. |
| `contribuidores` | inteiro | pessoas | Número da última página de `GET /repos/{repo}/contributors?per_page=1&anon=true` (cabeçalho `Link`). Vazio quando a API recusa a lista em repositórios muito grandes. |
| `branch_padrao` | texto | — | `default_branch`. |
| `faixa` | texto | — | Faixa de estrelas do `config.yaml` em que o repositório foi encontrado (ex.: `1000..2000`, `>=50000`). |

### `releases.csv`

Todas as releases de cada repositório da amostra, dentro e fora da janela.
Origem: `GET /repos/{repo}/releases`.

| Coluna | Tipo | Unidade | Fórmula / origem |
|---|---|---|---|
| `repositorio` | texto | — | Repositório. |
| `tag` | texto | — | `tag_name`. |
| `publicada_em` | data-hora | — | `published_at`; vazio em drafts. |
| `draft` | booleano | — | `draft`. |
| `prerelease` | booleano | — | `prerelease`. |
| `url` | texto | — | `html_url` (página da release no GitHub). |
| `notas` | texto | — | `body`: texto das release notes, em Markdown; vazio se a release não tem notas. |

### `tags.csv`

Todas as tags de cada repositório (variante "tag" da RQ 07). Origem: GraphQL
`repository.refs(refPrefix: "refs/tags/")`, com o commit apontado (tags anotadas são seguidas até o commit).

| Coluna | Tipo | Unidade | Fórmula / origem |
|---|---|---|---|
| `repositorio` | texto | — | Repositório. |
| `nome` | texto | — | `name` da ref. |
| `sha` | texto | — | `oid` do commit apontado; vazio se a tag não aponta para um commit. |
| `data_autor` | data-hora | — | `author.date` do commit apontado. É a data usada para situar a tag na janela. |
| `data_committer` | data-hora | — | `committer.date` do commit apontado. |

### `compares.csv`

Uma linha por item publicado na janela, em cada uma das três cadeias de deploy, pareado com o
item imediatamente anterior da mesma cadeia (que pode estar fora da janela).

| Coluna | Tipo | Unidade | Fórmula / origem |
|---|---|---|---|
| `repositorio` | texto | — | Repositório. |
| `cadeia` | texto | — | `release` (definição principal: `draft = false`, sem pré-releases), `release_prerelease` (inclui pré-releases) ou `tag`. |
| `tag` | texto | — | Tag do item. |
| `publicada_em` | data-hora | — | `published_at` (releases) ou `data_autor` (tags). |
| `tag_anterior` | texto | — | Tag do item anterior da cadeia; vazio se é o primeiro da história. |
| `status` | texto | — | `ok`; `primeira` (sem anterior); ou o código HTTP do erro do compare (ex.: `404`). |
| `n_commits` | inteiro | commits | Commits obtidos no compare (linhas em `commits.csv`). |
| `total_commits_api` | inteiro | commits | Total informado pelo GitHub (`aheadBy` na GraphQL, `ahead_by` no REST), para conferir a paginação. |
| `divergencia` | texto | — | `status` do compare no GitHub: `ahead`, `behind`, `diverged` ou `identical`. |

### `commits.csv`

Commits incluídos em cada par de `compares.csv` com `status = ok`. Origem: GraphQL
`ref.compare(headRef).commits`, ou o REST `GET /repos/{repo}/compare/{base}...{head}` paginado
quando o compare passa de 1.000 commits. Pares repetidos entre cadeias aparecem uma vez.

| Coluna | Tipo | Unidade | Fórmula / origem |
|---|---|---|---|
| `repositorio` | texto | — | Repositório. |
| `tag_anterior` | texto | — | Base do compare. |
| `tag` | texto | — | Head do compare (a release que inclui o commit). |
| `sha` | texto | — | `oid` / `sha` do commit. |
| `data_autor` | data-hora | — | `commit.author.date` (`authoredDate` na GraphQL). |
| `titulo` | texto | — | Primeira linha da mensagem. |
| `mensagem` | texto | — | Mensagem completa do commit (usada na heurística de release corretiva). |

### `runs.csv`

Workflow runs do default branch criados na janela, com `event = push`. Origem:
`GET /repos/{repo}/actions/runs?branch={default_branch}&event=push&created=AAAA-MM-DD..AAAA-MM-DD`,
consultado mês a mês.

| Coluna | Tipo | Unidade | Fórmula / origem |
|---|---|---|---|
| `repositorio` | texto | — | Repositório. |
| `id` | inteiro | — | `id` do run. |
| `workflow_id` | inteiro | — | `workflow_id`; agrupa os runs no tempo de recuperação. |
| `workflow_nome` | texto | — | `name` do workflow. |
| `conclusao` | texto | — | `conclusion`; vazio em runs em andamento. |
| `status` | texto | — | `status` (`completed`, `in_progress`...). |
| `criado_em` | data-hora | — | `created_at`. |
| `iniciado_em` | data-hora | — | `run_started_at` (início da última tentativa). |
| `atualizado_em` | data-hora | — | `updated_at`; usado como fim do run de sucesso que encerra um episódio. |
| `head_sha` | texto | — | `head_sha` (commit executado). |
| `tentativa` | inteiro | tentativas | `run_attempt`. A listagem devolve só a última tentativa de cada run; `tentativa > 1` indica que o run foi reexecutado sem novo commit. |

### `runs_intervalos.csv`

Uma linha por consulta de runs feita. Um mês com mais de 1.000 runs (teto da API com filtros) é
dividido ao meio até caber.

| Coluna | Tipo | Unidade | Fórmula / origem |
|---|---|---|---|
| `repositorio` | texto | — | Repositório. |
| `inicio` | data | — | Primeiro dia do intervalo consultado (inclusivo). |
| `fim` | data | — | Último dia do intervalo consultado (inclusivo). |
| `total` | inteiro | runs | `total_count` da consulta. |
| `truncado` | booleano | — | `1` se o intervalo é um único dia com mais de 1.000 runs (dados incompletos). |

## Validação manual (`dados/validacao/`)

### `amostra_ouro.csv`

As releases sorteadas para a amostra-ouro: 60 repositórios da amostra final
(`DataFrame.sample(random_state=42)` sobre a lista ordenada por nome) e 5 releases de cada,
sorteadas da mesma forma entre as da cadeia `release` de `compares.csv`.

| Coluna | Tipo | Unidade | Fórmula / origem |
|---|---|---|---|
| `repositorio` | texto | — | Repositório sorteado. |
| `tag` | texto | — | Tag da release sorteada. |
| `tag_anterior` | texto | — | Release imediatamente anterior na cadeia `release` (por data de publicação); vazio se é a primeira da história. |
| `publicada_em` | data-hora | — | `published_at` da release. |
| `url_release` | texto | — | Página da release no GitHub (`html_url`). |
| `url_commits` | texto | — | `https://github.com/{repo}/compare/{tag_anterior}...{tag}`: commits incluídos na release; vazio sem anterior. |

### `rotulagem_<avaliador>.xlsx`

Planilha preenchida por cada avaliador. A aba `instrucoes` explica os critérios.

Aba `repositorios` (uma linha por repositório da amostra-ouro):

| Coluna | Tipo | Valores | Significado |
|---|---|---|---|
| `repositorio` | texto | — | Repositório. |
| `url_repositorio` | texto | — | Página do repositório no GitHub. |
| `tipo_projeto` | texto | `biblioteca/framework`, `aplicação/serviço`, `ferramenta CLI`, `outro` | Tipo do projeto (RQ 06). |
| `entregas_reais` | texto | `sim`, `não`, `incerto` | As releases representam entregas reais ao usuário? |
| `observacoes` | texto | livre | Dúvidas e justificativas. |

Aba `releases` (uma linha por release de `amostra_ouro.csv`):

| Coluna | Tipo | Valores | Significado |
|---|---|---|---|
| `repositorio`, `tag`, `tag_anterior`, `publicada_em`, `url_release`, `url_commits` | — | — | Iguais a `amostra_ouro.csv`. |
| `corretiva` | texto | `sim`, `não` | O objetivo principal da release é corrigir um defeito recente? (RQ 03 b) |
| `notas_release` | texto | — | Início das release notes (`notas` de `releases.csv`, até 1.000 caracteres, com aviso quando cortado). |
| `titulos_commits` | texto | — | Títulos dos commits do compare com a release anterior (`commits.csv`, até 20, com aviso quando há mais); ou o motivo de não haver lista (primeira release, compare com erro). |
| `observacoes` | texto | livre | Dúvidas e justificativas. |

### `desempates.csv`

Decisões de reunião do grupo, preenchidas à mão: casos sem maioria (1-1-1) e casos de maioria
que o grupo decidiu rediscutir. Prevalecem sobre a votação no consenso.

| Coluna | Tipo | Valores | Significado |
|---|---|---|---|
| `dimensao` | texto | `tipo_projeto`, `entregas_reais`, `corretiva` | Dimensão decidida. |
| `repositorio` | texto | — | Repositório da amostra-ouro. |
| `tag` | texto | — | Tag da release, só para `corretiva`; vazio nas outras dimensões. |
| `rotulo` | texto | os valores da dimensão nas planilhas | Rótulo decidido em reunião. |
| `justificativa` | texto | livre | Por que o grupo decidiu assim. |

### `concordancia.csv`

Concordância entre os avaliadores, uma linha por dimensão, calculada sobre a rotulagem
independente (antes das reuniões).

| Coluna | Tipo | Unidade | Fórmula / origem |
|---|---|---|---|
| `dimensao` | texto | — | `tipo_projeto`, `entregas_reais` ou `corretiva`. |
| `itens` | inteiro | itens | Repositórios (60) ou releases (300) rotulados. |
| `avaliadores` | inteiro | pessoas | `validacao_manual.avaliadores` do `config.yaml`. |
| `kappa` | real | — | Kappa de Fleiss: `fleiss_kappa(aggregate_raters(rotulos)[0])` do statsmodels. NaN se todos usaram uma única categoria. |
| `interpretacao` | texto | — | Faixa de Landis & Koch (1977): pobre (< 0), leve (até 0,20), razoável (até 0,40), moderada (até 0,60), substancial (até 0,80), quase perfeita. |
| `concordancia_observada` | real | proporção | Média, entre os itens, da proporção de pares de avaliadores que deram o mesmo rótulo (o P̄ de Fleiss, sem desconto do acaso). |
| `unanimes` | inteiro | itens | Todos os avaliadores deram o mesmo rótulo. |
| `maioria` | inteiro | itens | Sem unanimidade, mas um rótulo com mais da metade dos votos. |
| `sem_maioria` | inteiro | itens | Nenhum rótulo com mais da metade dos votos (1-1-1). |
| `decididos_em_reuniao` | inteiro | itens | Itens com decisão em `desempates.csv`. |
| `pendentes` | inteiro | itens | Sem maioria e sem decisão de reunião: sem consenso ainda. |

### `consenso_repositorios.csv` e `consenso_releases.csv`

Rótulos de consenso, a referência para validar a classificação automática do tipo de projeto
e a heurística de release corretiva. Uma linha por repositório (60) ou por release (300), na
ordem das planilhas.

| Coluna | Tipo | Valores | Significado |
|---|---|---|---|
| `repositorio`; nas releases também `tag`, `tag_anterior`, `publicada_em` | — | — | Iguais às planilhas de rotulagem. |
| `tipo_projeto`, `entregas_reais` (repositórios); `corretiva` (releases) | texto | os valores das planilhas, ou vazio | Rótulo de consenso; vazio quando pendente. |
| `<dimensao>_regra` | texto | `unanime`, `maioria`, `reuniao`, `pendente` | Regra do protocolo de desempate que definiu o consenso. |
| `<dimensao>_<avaliador>` | texto | os valores das planilhas | Rótulo dado por cada avaliador. |

### `heuristica_versoes.csv`

Uma linha por versão da heurística de release corretiva (`metricas/corretiva.py`), avaliada
contra o `corretiva` de `consenso_releases.csv` com `precision_recall_fscore_support`
(classe positiva: corretiva). Releases sem consenso (`pendente`) ficam de fora.

| Coluna | Tipo | Unidade | Fórmula / origem |
|---|---|---|---|
| `versao`, `descricao` | texto | — | Nome e regra da versão. |
| `releases` | inteiro | releases | Releases avaliadas. |
| `corretivas_consenso`, `corretivas_heuristica` | inteiro | releases | Corretivas segundo o consenso e segundo a heurística. |
| `verdadeiros_positivos`, `falsos_positivos`, `falsos_negativos` | inteiro | releases | Acertos e erros da heurística frente ao consenso. |
| `precisao`, `recall`, `f1` | real | proporção (0–1) | VP ÷ (VP + FP); VP ÷ (VP + FN); 2·P·R ÷ (P + R). |

### `heuristica_erros.csv`

Cada erro de cada versão, para analisar o que motivou o refinamento.

| Coluna | Tipo | Valores | Significado |
|---|---|---|---|
| `versao` | texto | `v1`… | Versão da heurística. |
| `tipo_erro` | texto | `falso positivo`, `falso negativo` | Heurística disse corretiva e o consenso não, ou o contrário. |
| `repositorio`, `tag`, `tag_anterior` | texto | — | Release com erro. |
| `muda_so_patch` | booleano | — | A versão sobe só no último número em relação à `tag_anterior`, no mesmo pacote. |
| `versao_de_patch` | booleano | — | A própria tag é um patch (último número > 0). |
| `commits` | inteiro | commits | Commits do compare com a anterior. |
| `commits_correcao` | inteiro | commits | Commits cujo título tem fix, fixes, fixed, hotfix, bugfix ou revert. |
| `titulos_correcao` | texto | — | Até 5 desses títulos, separados por ` \| `. |

### `tipo_projeto_validacao.csv`

Desempenho de cada versão da heurística de tipo de projeto frente ao `tipo_projeto` de
`consenso_repositorios.csv` (60 repositórios), com `precision_recall_fscore_support`.

| Coluna | Tipo | Unidade | Fórmula / origem |
|---|---|---|---|
| `versao` | texto | — | Versão dos padrões (`metricas/tipo_projeto.py`, `VERSOES`). |
| `classe` | texto | — | Um dos quatro tipos, `macro` (média simples entre os tipos), `ponderada` (média pelo suporte) ou `acuracia`. |
| `suporte` | inteiro | repositórios | Repositórios desse tipo no consenso (nas médias, o total). |
| `previstos` | inteiro | repositórios | Repositórios que a heurística classificou nesse tipo. |
| `precisao`, `recall`, `f1` | real | proporção (0–1) | Por tipo, VP ÷ (VP + FP), VP ÷ (VP + FN) e 2·P·R ÷ (P + R). Na linha `acuracia`, as três colunas trazem a proporção de acertos. |

### `tipo_projeto_erros.csv`

Repositórios da amostra-ouro em que cada versão errou.

| Coluna | Tipo | Valores | Significado |
|---|---|---|---|
| `versao` | texto | `v1`… | Versão da heurística. |
| `repositorio` | texto | — | `owner/repo`. |
| `consenso`, `heuristica` | texto | os quatro tipos | Tipo de consenso e tipo da heurística. |
| `descricao` | texto | — | Até 200 caracteres da descrição do repositório. |
| `topicos` | texto | — | Tópicos separados por `;`. |
| `pontos` | texto | — | Pontos de cada tipo com pelo menos um sinal (ex.: `biblioteca/framework=4, ferramenta CLI=1`). |

## Tipo de projeto

### `dados/perfis_repositorios.csv`

Perfil de cada repositório da amostra, coletado pela etapa `tipo_projeto` e versionado.

| Coluna | Tipo | Unidade | Fórmula / origem |
|---|---|---|---|
| `repositorio` | texto | — | `owner/repo`. |
| `descricao` | texto | — | `description` de `GET /repos/{repo}`; vazio se não houver. |
| `topicos` | texto | — | `topics` de `GET /repos/{repo}`, separados por `;`. |
| `readme` | texto | caracteres | Primeiros 4.000 caracteres do README (`GET /repos/{repo}/readme`, decodificado de base64); vazio se não houver README. |

### `dados/tipo_projeto.csv`

Tipo de projeto dos 300 repositórios, para a RQ 06.

| Coluna | Tipo | Valores | Fórmula / origem |
|---|---|---|---|
| `repositorio` | texto | — | `owner/repo`. |
| `tipo_heuristica` | texto | os quatro tipos | Tipo dado pela versão atual da heurística (v2) para todos os repositórios. |
| `tipo_consenso` | texto | os quatro tipos, ou vazio | Rótulo de consenso, só nos 60 da amostra-ouro. |
| `tipo_projeto` | texto | os quatro tipos | Tipo usado na análise: `tipo_consenso` quando existe; senão, `tipo_heuristica`. |
| `origem` | texto | `consenso`, `heuristica` | De onde veio `tipo_projeto`. |

## Análise (`dados/analise/`)

Gerados pela etapa `analise` a partir de `metricas.csv` (`analise/descritiva.py`). Reais com 4
casas decimais. Os quartis usam `Series.quantile` (interpolação linear), e os valores ausentes
ficam de fora.

### `descritiva_rq01_rq04.csv`

Uma linha por métrica das RQ 01 a RQ 04, resumindo os repositórios.

| Coluna | Tipo | Unidade | Fórmula / origem |
|---|---|---|---|
| `rq` | texto | — | `RQ01`, `RQ02 (a)`, `RQ02 (b)`, `RQ03 (a)`, `RQ03 (b)` ou `RQ04`. |
| `metrica` | texto | — | Coluna de `metricas.csv`: `deploys_por_semana`, `lead_time_release_horas`, `lead_time_commit_horas`, `cfr_ci`, `cfr_ci_sem_flaky`, `cfr_entrega`, `recuperacao_horas`. |
| `descricao`, `unidade` | texto | — | Nome legível e unidade da métrica. |
| `n` | inteiro | repositórios | Repositórios com valor. |
| `ausentes` | inteiro | repositórios | Repositórios com a métrica vazia. |
| `minimo`, `q1`, `mediana`, `q3`, `maximo`, `media` | real | a da métrica | Estatísticas entre os repositórios. |
| `iqr` | real | a da métrica | `q3` − `q1`. |

### `censura.csv`

Uma linha para cada métrica com censura à direita: a RQ 04 (episódios) e a RQ 03 (b) (releases).

| Coluna | Tipo | Unidade | Fórmula / origem |
|---|---|---|---|
| `rq`, `metrica` | texto | — | `RQ04` / `recuperacao_horas` ou `RQ03 (b)` / `cfr_entrega`. |
| `unidade` | texto | — | `episódios` ou `releases`. |
| `observados` | inteiro | a da linha | Soma de `episodios_recuperados` ou de `releases_avaliadas_cfr`. |
| `censurados` | inteiro | a da linha | Soma de `episodios_censurados` ou de `releases_censuradas_cfr`. |
| `proporcao_censurados` | real | proporção (0–1) | `censurados` ÷ (`observados` + `censurados`). |
| `repositorios_com_censura` | inteiro | repositórios | Repositórios com pelo menos um censurado. |
| `repositorios_sem_valor` | inteiro | repositórios | Repositórios com a métrica vazia. |

### `lead_time_divergencia_repositorios.csv`

Uma linha por repositório com as duas variantes do lead time.

| Coluna | Tipo | Unidade | Fórmula / origem |
|---|---|---|---|
| `repositorio`, `lead_time_release_horas`, `lead_time_commit_horas`, `releases_lead_time` | — | — | Iguais a `metricas.csv`. |
| `diferenca_horas` | real | horas | `lead_time_commit_horas` − `lead_time_release_horas` (b − a). |
| `razao` | real | — | `lead_time_commit_horas` ÷ `lead_time_release_horas` (b ÷ a); vazio se (a) = 0. |

### `lead_time_divergencia.csv`

Uma linha com o resumo da divergência entre (a) e (b).

| Coluna | Tipo | Unidade | Fórmula / origem |
|---|---|---|---|
| `repositorios` | inteiro | repositórios | Repositórios com as duas variantes. |
| `mediana_a_horas`, `mediana_b_horas` | real | horas | Medianas de (a) e (b) entre os repositórios. |
| `commit_maior`, `commit_menor`, `iguais` | inteiro | repositórios | Repositórios com (b) > (a), (b) < (a) e (b) = (a). |
| `mediana_diferenca_horas` | real | horas | Mediana de `diferenca_horas`. |
| `mediana_razao`, `q1_razao`, `q3_razao` | real | — | Mediana e quartis de `razao`. |
| `spearman` | real | — | Correlação de Spearman entre (a) e (b). |

### `cfr_flaky.csv`

CFR de CI em três cenários de flakiness, uma linha por cenário.

| Coluna | Tipo | Unidade | Fórmula / origem |
|---|---|---|---|
| `cenario` | texto | — | `sem_flaky`: falhas = `runs_falha` − `falhas_flaky_mesmo_commit`. `atual`: o `cfr_ci`. `com_reexecucoes`: limite superior, com falhas = `runs_falha` + `runs_flaky_reexecucao` e um run a mais no denominador para cada reexecução (a tentativa com falha que a API não lista). |
| `descricao` | texto | — | Explicação do cenário. |
| `falhas`, `runs_validos` | inteiro | runs | Somas de todos os repositórios no cenário. |
| `cfr_agregado` | real | proporção (0–1) | `falhas` ÷ `runs_validos`. |
| `q1`, `mediana`, `q3`, `iqr` | real | proporção (0–1) | Do CFR por repositório no cenário (sem os repositórios sem runs válidos). |
| `diferenca_mediana_pp` | real | pontos percentuais | (`mediana` do cenário − `mediana` de `atual`) × 100. |
| `parcela_flaky_agregada` | real | proporção (0–1) | (`cfr_agregado` − `cfr_agregado` de `sem_flaky`) ÷ `cfr_agregado`: fração da taxa que vem de flakiness. |
| `parcela_flaky_mediana` | real | proporção (0–1) | A mesma fração calculada por repositório; mediana entre os repositórios com CFR > 0. |

### `classificacao_distribuicao.csv`

Distribuição da classificação DORA de referência (C1), em formato longo: uma linha por
dimensão × classe (`analise/classificacao.py`).

| Coluna | Tipo | Unidade | Fórmula / origem |
|---|---|---|---|
| `dimensao` | texto | — | `frequencia`, `lead_time`, `cfr`, `recuperacao` (colunas `classe_*` de `metricas.csv`) ou `geral` (`classe_geral`). |
| `classe` | texto | — | `Elite`, `High`, `Medium`, `Low` ou `sem dados` (classe vazia). |
| `repositorios` | inteiro | repositórios | Repositórios na classe. |
| `proporcao` | real | proporção (0–1) | `repositorios` ÷ total da amostra. |

### `classificacao_metricas_usadas.csv`

Classe geral pelo número de dimensões que entraram na mediana e pelo motivo de faltar o tempo
de recuperação. Só aparecem as combinações com algum repositório.

| Coluna | Tipo | Unidade | Fórmula / origem |
|---|---|---|---|
| `situacao_recuperacao` | texto | — | `com recuperação`; `sem falha de CI` (`runs_falha = 0`); `só episódios censurados` (nenhum episódio recuperado, algum censurado); `falhas só antes do primeiro sucesso` (as falhas não abriram episódio). |
| `metricas_usadas` | inteiro | dimensões | Dimensões com classe (4, ou 3 sem recuperação). |
| `Elite`, `High`, `Medium`, `Low` | inteiro | repositórios | Repositórios em cada classe geral. |
| `repositorios` | inteiro | repositórios | Total da linha. |

### `classificacao_sensibilidade.csv`

Classe geral recalculada (`metricas.classificacao.categoria_geral`) em cenários alternativos.

| Coluna | Tipo | Unidade | Fórmula / origem |
|---|---|---|---|
| `cenario` | texto | — | `referencia` (C1, igual a `classe_geral`); `arredondamento_para_cima` (medianas terminadas em ,5 vão para a classe de cima); `sem_falha_como_elite` (repositórios com `runs_falha = 0` recebem Elite em recuperação). |
| `descricao` | texto | — | Explicação do cenário. |
| `Elite`, `High`, `Medium`, `Low` | inteiro | repositórios | Repositórios em cada classe geral. |
| `sem_dados` | inteiro | repositórios | Repositórios sem nenhuma dimensão com classe. |
| `empates` | inteiro | repositórios | Repositórios cuja mediana das notas termina em ,5: o arredondamento decide a classe. |
| `mudam_de_classe` | inteiro | repositórios | Repositórios com classe geral diferente da `referencia`. |

### `classificacao_limitante.csv`

Uma linha por classe geral, mais `todas`: quantos repositórios têm cada dimensão com classe
abaixo da geral (o que puxa a classificação para baixo).

| Coluna | Tipo | Unidade | Fórmula / origem |
|---|---|---|---|
| `classe_geral` | texto | — | `Elite`, `High`, `Medium`, `Low` ou `todas`. |
| `repositorios` | inteiro | repositórios | Repositórios na classe. |
| `frequencia_abaixo`, `lead_time_abaixo`, `cfr_abaixo`, `recuperacao_abaixo` | inteiro | repositórios | Repositórios em que a dimensão tem nota menor que a classe geral. |

### `rq05_spearman.csv`

Correlação de Spearman entre `deploys_por_semana` e cada variante do CFR (`analise/correlacao.py`),
uma linha por variante.

| Coluna | Tipo | Unidade | Fórmula / origem |
|---|---|---|---|
| `variante` | texto | — | `(a)` ou `(b)`. |
| `metrica_cfr` | texto | — | `cfr_ci` (a) ou `cfr_entrega` (b). |
| `descricao` | texto | — | Nome da variante. |
| `n` | inteiro | repositórios | Repositórios com frequência e CFR preenchidos. |
| `sem_par` | inteiro | repositórios | Repositórios sem o CFR da variante, fora do cálculo. |
| `cfr_zero` | inteiro | repositórios | Repositórios com CFR igual a 0 (no gráfico, ficam na faixa de baixo). |
| `rho` | real | −1 a 1 | `scipy.stats.spearmanr`, com postos médios nos empates. |
| `p_valor` | real | — | Bilateral, de `spearmanr`. |

`rq05_dispersao.png` mostra os mesmos pares, com os dois eixos em escala log.

### `rq06_testes.csv`

Um teste por fator × métrica (`analise/fatores.py`). Fatores: `linguagem` (5 mais frequentes +
`outras`), `estrelas`, `contribuidores` e `idade` (quartis `Q1` a `Q4`, `pd.qcut`; idade em anos
de `criado_em` até o fim da janela) e `tipo_projeto` (de `dados/tipo_projeto.csv`). Métricas:
`deploys_por_semana`, `lead_time_release_horas`, `cfr_ci` e `recuperacao_horas`.

| Coluna | Tipo | Unidade | Fórmula / origem |
|---|---|---|---|
| `fator`, `metrica` | texto | — | Fator e coluna de `metricas.csv`. |
| `teste` | texto | — | `kruskal-wallis` (3 ou mais grupos) ou `mann-whitney` (2 grupos, bilateral). |
| `grupos` | inteiro | — | Grupos com algum valor da métrica. |
| `n` | inteiro | repositórios | Repositórios com a métrica preenchida. |
| `estatistica` | real | — | H (Kruskal-Wallis) ou U (Mann-Whitney), do `scipy.stats`. |
| `p_valor` | real | — | Sem correção. |
| `p_holm` | real | — | Corrigido por Holm sobre os 20 testes (`statsmodels multipletests`). |
| `significativo` | booleano | — | `p_holm` < 0,05. |
| `epsilon2` | real | 0 a 1 | H ÷ (n − 1) (Tomczak e Tomczak, 2014); vazio no Mann-Whitney. |
| `efeito` | texto | — | `desprezível` (< 0,01), `pequeno` (< 0,08), `médio` (< 0,26) ou `grande`. |

### `rq06_grupos.csv`

| Coluna | Tipo | Unidade | Fórmula / origem |
|---|---|---|---|
| `fator`, `grupo`, `metrica` | texto | — | Grupo do fator e métrica. |
| `n` | inteiro | repositórios | Repositórios do grupo com a métrica preenchida. |
| `q1`, `mediana`, `q3` | real | unidade da métrica | `numpy.quantile` (interpolação linear). |

### `rq06_cliff.csv`

Cliff's delta entre grupos: Q4 × Q1 nos fatores em quartis, todos os pares em `linguagem` e
`tipo_projeto`.

| Coluna | Tipo | Unidade | Fórmula / origem |
|---|---|---|---|
| `fator`, `metrica` | texto | — | Fator e métrica. |
| `grupo_a`, `grupo_b` | texto | — | Grupos comparados. |
| `n_a`, `n_b` | inteiro | repositórios | Tamanho de cada grupo. |
| `cliff_delta` | real | −1 a 1 | P(a > b) − P(a < b), sobre todos os pares de repositórios. |
| `magnitude` | texto | — | Romano et al. (2006): `desprezível` (< 0,147), `pequeno` (< 0,33), `médio` (< 0,474) ou `grande`. |
| `grupo_melhor` | texto | — | Grupo com melhor desempenho (mais deploys; menos lead time, CFR e recuperação); vazio se o efeito é desprezível. |

`rq06_<fator>.png`: boxplots das quatro métricas por grupo, só para os fatores com algum teste
significativo (título em negrito nos significativos; escala log, exceto no CFR).

### `rq07_distribuicao.csv`

Classe geral em cada combinação de `metricas_combinacoes.csv` (`analise/combinacoes.py`).

| Coluna | Tipo | Unidade | Fórmula / origem |
|---|---|---|---|
| `combinacao`, `unidade_deploy`, `lead_time_variante`, `cfr_variante` | texto | — | Definições da combinação. |
| `Elite`, `High`, `Medium`, `Low`, `sem_dados` | inteiro | repositórios | Repositórios em cada classe geral. |

### `rq07_concordancia.csv`

Uma linha por par de combinações (C1xC2, C1xC3, C2xC3) e dimensão (`geral`, `frequencia`,
`lead_time`, `cfr`; a recuperação é igual nas três e fica de fora).

| Coluna | Tipo | Unidade | Fórmula / origem |
|---|---|---|---|
| `par`, `combinacao_a`, `combinacao_b`, `dimensao` | texto | — | Par e dimensão comparados. |
| `repositorios` | inteiro | repositórios | Com classe nas duas combinações. |
| `sem_classe` | inteiro | repositórios | Sem classe em alguma das duas (ex.: sem CFR (b)); fora do cálculo. |
| `mudam` | inteiro | repositórios | Classe diferente entre A e B. |
| `proporcao_mudam` | real | proporção (0–1) | `mudam` ÷ `repositorios`. |
| `sobem`, `descem` | inteiro | repositórios | Classe melhor / pior em B do que em A. |
| `mudam_duas_ou_mais` | inteiro | repositórios | Mudam duas classes ou mais (ex.: Elite → Medium). |
| `kappa_linear` | real | −1 a 1 | `sklearn.metrics.cohen_kappa_score(..., weights="linear")`, classes ordenadas de Low a Elite. 1 quando as duas classificações são idênticas. |
| `interpretacao` | texto | — | Escala de Landis e Koch (1977), a mesma de `concordancia.csv`. |

### `rq07_transicoes.csv`

Matriz de transição da classe geral, uma por par (4 linhas cada).

| Coluna | Tipo | Unidade | Fórmula / origem |
|---|---|---|---|
| `par` | texto | — | Par de combinações (A x B). |
| `classe_a` | texto | — | Classe em A. |
| `para_Elite`, `para_High`, `para_Medium`, `para_Low` | inteiro | repositórios | Repositórios com `classe_a` em A e essa classe em B. |
| `repositorios` | inteiro | repositórios | Total da linha. |

## Seleção da amostra

### `dados/candidatos.csv`

Lista congelada de candidatos, gerada uma vez pela busca e reaproveitada nas execuções seguintes.
Origem: `GET /search/repositories?q=stars:{faixa} fork:false archived:false`.

| Coluna | Tipo | Unidade | Fórmula / origem |
|---|---|---|---|
| `repositorio` | texto | — | `full_name`. |
| `faixa` | texto | — | Faixa de estrelas do `config.yaml`. |
| `subintervalo` | texto | — | Pedaço da faixa em que a busca o encontrou (a faixa é dividida até cada consulta ter ≤ 1.000 resultados). |
| `estrelas` | inteiro | estrelas | `stargazers_count` no dia da busca. |
| `linguagem` | texto | — | `language`. |
| `criado_em` | data-hora | — | `created_at`. |
| `branch_padrao` | texto | — | `default_branch`. |
| `url` | texto | — | `html_url`. |
| `buscado_em` | data | — | Data em que a busca foi feita. |

### `dados/candidatos_faixas.csv` e `dados/brutos/faixas_busca.csv`

Uma linha por subintervalo consultado na busca. `candidatos_faixas.csv` traz também `buscado_em`.

| Coluna | Tipo | Unidade | Fórmula / origem |
|---|---|---|---|
| `faixa` | texto | — | Faixa de estrelas do `config.yaml`. |
| `subintervalo` | texto | — | Pedaço da faixa consultado. |
| `consulta` | texto | — | Parâmetro `q` usado na busca. |
| `disponiveis` | inteiro | repositórios | `total_count` da busca. |
| `obtidos` | inteiro | repositórios | Itens efetivamente recebidos. Igual a `disponiveis` quando nada ficou de fora. |
| `buscado_em` | data | — | Data da busca (só em `candidatos_faixas.csv`). |

### `dados/brutos/funil.csv`

Um candidato por linha, na ordem de avaliação (hash SHA-256 de `semente:nome`). Cada candidato
para no primeiro filtro em que reprova.

| Coluna | Tipo | Unidade | Fórmula / origem |
|---|---|---|---|
| `repositorio` | texto | — | Repositório. |
| `faixa` | texto | — | Faixa de estrelas. |
| `estrelas` | inteiro | estrelas | Estrelas no dia da busca. |
| `situacao` | texto | — | `incluido` ou o motivo do descarte: `nao_avaliado` (a amostra encheu antes), `erro_api`, `sem_actions`, `poucas_releases`, `poucos_runs`. |
| `n_workflows` | inteiro | workflows | `total_count` de `GET /repos/{repo}/actions/workflows`; vazio se não chegou a essa etapa. |
| `n_releases_janela` | inteiro | releases | Releases publicadas na janela (`draft = false`, sem pré-releases); vazio se não chegou a essa etapa. |
| `n_runs_validos` | inteiro | runs | Runs `push` do default branch na janela com `conclusion` de sucesso ou falha; vazio se não chegou a essa etapa. |
| `detalhe` | texto | — | Mensagem do erro, quando `situacao = erro_api`. |

### `dados/brutos/funil_resumo.csv`

Quantos repositórios restam após cada etapa do funil (tabela da Metodologia).

| Coluna | Tipo | Unidade | Fórmula / origem |
|---|---|---|---|
| `etapa` | texto | — | `candidatos`, `avaliados`, `acessiveis_pela_api`, `usam_actions`, `com_min_releases`, `com_min_runs_validos`, `amostra_final`. |
| `restantes` | inteiro | repositórios | Repositórios que seguem após a etapa. |
| `descartados` | inteiro | repositórios | Repositórios descartados na etapa. |
| `motivo_descarte` | texto | — | Valor de `situacao` em `funil.csv` correspondente aos descartados. |
