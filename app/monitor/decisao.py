"""Regras de alerta. Puras: sem rede, sem banco, sem relógio.

O "anterior" é o que o GRUPO já recebeu (estado compartilhado), não o que esta
máquina viu. É isso que evita alerta duplicado entre máquinas.
"""
from datetime import datetime, timedelta
from decimal import Decimal

# Copag vende a preço de tabela: o evento é voltar ao estoque.
# Mercado Livre: o evento é aparecer oferta dentro do teto.
MODO_POR_FONTE = {"copag": "estoque", "mercadolivre": "teto"}


def teto(sugerido, tolerancia):
    return None if sugerido is None else Decimal(sugerido) + tolerancia


def dentro_do_teto(preco, sugerido, tolerancia):
    t = teto(sugerido, tolerancia)
    return t is not None and preco is not None and Decimal(preco) <= t


def decidir(item, anterior, tolerancia):
    """item: {fonte, disponivel, preco, preco_sugerido}. anterior: registro do estado ou None.

    Devolve (tipo_do_alerta | None, registro_novo)."""
    disp = bool(item["disponivel"])
    preco = item.get("preco")
    no_teto = disp and dentro_do_teto(preco, item.get("preco_sugerido"), tolerancia)
    novo = {"d": disp, "p": None if preco is None else str(preco), "t": no_teto}

    ant = anterior or {}
    modo = MODO_POR_FONTE.get(item["fonte"], "estoque")
    tipo = None
    if modo == "estoque":
        if disp and ant.get("d") is not True:
            tipo = "voltou_estoque"
        elif disp and preco is not None and ant.get("p") is not None and Decimal(preco) < Decimal(ant["p"]):
            tipo = "preco_caiu"
    else:
        if no_teto and not ant.get("t"):
            tipo = "dentro_do_teto"
    return tipo, novo


def papel(lider, maquina, estado, agora, inicio, failover_minutos):
    """Esta máquina envia neste ciclo? Devolve (atua: bool, motivo: str).

    Líder sempre envia. Reserva envia se o sinal de vida do grupo está velho,
    ou se ela mesma foi a última a assumir (continua até alguém a substituir)."""
    if lider:
        return True, "líder"
    limite = timedelta(minutes=failover_minutos)
    ultimo = estado.get("l")
    if not ultimo:
        if agora - inicio >= limite:
            return True, f"nenhum líder visto em {failover_minutos} min, assumindo"
        return False, "aguardando o líder dar o primeiro sinal"
    visto = datetime.fromisoformat(ultimo["em"])
    idade = agora - visto
    if ultimo.get("m") == maquina:
        return True, "reserva que já tinha assumido"
    if idade >= limite:
        return True, f"líder {ultimo.get('m')} sem sinal há {int(idade.total_seconds() // 60)} min, assumindo"
    return False, f"reserva: {ultimo.get('m')} ativo há {int(idade.total_seconds() // 60)} min"
