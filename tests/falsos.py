"""Cliente falso para testar a coleta sem rede."""

from coleta.cliente import ErroAPI, Resposta


def pagina(dados, links=None):
    return Resposta(200, dados, links or {}, do_cache=False)


class ClienteFalso:
    """`rotas` mapeia caminho -> páginas (lista de Resposta ou de corpos JSON), um
    ErroAPI, ou uma função(params) que devolve um desses. Caminhos ausentes dão 404.
    """

    def __init__(self, rotas):
        self.rotas = rotas
        self.chamadas = []

    def _paginas(self, caminho, params):
        self.chamadas.append((caminho, dict(params or {})))
        rota = self.rotas.get(caminho, ErroAPI("não encontrado", status=404, url=caminho))
        if callable(rota):
            rota = rota(dict(params or {}))
        if isinstance(rota, ErroAPI):
            raise rota
        return [p if isinstance(p, Resposta) else pagina(p) for p in rota]

    def obter(self, caminho, params=None):
        return self._paginas(caminho, params)[0]

    def paginas(self, caminho, params=None, *, max_paginas=None):
        yield from self._paginas(caminho, params)[:max_paginas]

    def paginar(self, caminho, params=None, *, chave_itens=None, max_paginas=None):
        for p in self.paginas(caminho, params, max_paginas=max_paginas):
            if p.dados is None:
                continue
            yield from (p.dados if chave_itens is None else p.dados.get(chave_itens, []))

    def graphql(self, consulta, variaveis=None):
        """Rota "graphql": função(variaveis) que devolve o campo `data`, ou um ErroAPI."""
        self.chamadas.append(("graphql", dict(variaveis or {})))
        rota = self.rotas["graphql"]
        resultado = rota(dict(variaveis or {})) if callable(rota) else rota
        if isinstance(resultado, ErroAPI):
            raise resultado
        return resultado

    def caminhos(self):
        return [c for c, _ in self.chamadas]
