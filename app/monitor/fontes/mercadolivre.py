"""Mercado Livre: DESLIGADO.

Spike de 23/09/2026: /products, /products/{id}/items, /items e /sites/MLB/search
responderam 401/403 sem token; a página /p/ redireciona para verificação anti-robô.
Os links já estão no banco (catalogo.json). O coletor só será escrito depois de
ver uma resposta real COM token; nenhum campo de JSON aqui é suposto.
"""


class NaoDisponivel(Exception):
    pass


def coletar(ids_catalogo, token):
    raise NaoDisponivel("coletor do Mercado Livre ainda não implementado (falta testar com token)")
