"""Textos das mensagens. Texto puro (sem parse_mode) para nome de produto não quebrar o envio."""
from decimal import Decimal
from zoneinfo import ZoneInfo

from .decisao import teto

SP = ZoneInfo("America/Sao_Paulo")

TITULOS = {
    "voltou_estoque": "🟢 VOLTOU AO ESTOQUE",
    "preco_caiu": "📉 PREÇO CAIU",
    "dentro_do_teto": "💰 DENTRO DO TETO",
}


def brl(v):
    if v is None:
        return "?"
    s = f"{Decimal(v):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {s}"


def diferenca(atual, referencia):
    """'+R$ 5,00 (+3,1%)' ou 'igual'."""
    if atual is None or referencia is None:
        return None
    d = Decimal(atual) - Decimal(referencia)
    if d == 0:
        return "igual"
    pct = (d / Decimal(referencia) * 100) if referencia else Decimal(0)
    sinal = "+" if d > 0 else "-"
    pct_txt = f"{abs(pct):.1f}".replace(".", ",")
    return f"{sinal}{brl(abs(d))} ({sinal}{pct_txt}%)"


def duracao(delta):
    m = int(delta.total_seconds() // 60)
    if m < 60:
        return f"{m} min"
    h, m = divmod(m, 60)
    if h < 24:
        return f"{h} h {m:02d} min"
    d, h = divmod(h, 24)
    return f"{d} d {h} h"


def quando(dt, agora):
    if dt is None:
        return None
    return f"{dt.astimezone(SP):%d/%m %H:%M} (há {duracao(agora - dt)})"


def alerta(tipo, item, hist, tolerancia, maquina, agora):
    preco = item.get("preco")
    sug = item.get("preco_sugerido")
    linhas = [f"{TITULOS.get(tipo, tipo)}: {item['produto_nome']}", f"Fonte: {item['fonte_nome']}", f"Preço: {brl(preco)}"]

    if sug is None:
        linhas.append("Sugerido: não cadastrado (sem teto)")
    else:
        t = teto(sug, tolerancia)
        situacao = "dentro do teto" if preco is not None and Decimal(preco) <= t else "ACIMA do teto"
        linhas.append(f"Sugerido: {brl(sug)} · teto {brl(t)} · {diferenca(preco, sug)} · {situacao}")

    if hist:
        if hist.get("preco_anterior") is not None and preco is not None:
            linhas.append(f"Preço anterior: {brl(hist['preco_anterior'])} ({diferenca(preco, hist['preco_anterior'])})")
        if hist.get("menor_preco_disponivel") is not None:
            linhas.append(f"Menor preço já visto disponível: {brl(hist['menor_preco_disponivel'])}")
        if tipo == "voltou_estoque":
            desde = quando(hist.get("indisponivel_desde"), agora)
            ultima = quando(hist.get("ultima_disponivel"), agora)
            if desde:
                linhas.append(f"Estava indisponível desde: {desde}")
            linhas.append(f"Última vez disponível: {ultima or 'nunca visto por esta máquina'}")
        if hist.get("primeira_observacao") is None:
            linhas.append("Primeira observação desta máquina (sem histórico).")

    linhas.append(f"🔗 {item['url']}")
    linhas.append(f"🖥️ {maquina} · {agora.astimezone(SP):%d/%m %H:%M}")
    return "\n".join(linhas)


def monitor_cego(fonte, n, erro, maquina):
    return f"🔴 MONITOR CEGO: {fonte} falhou {n} vezes seguidas.\nÚltimo erro: {erro[:300]}\n🖥️ {maquina}"


def fonte_voltou(fonte, maquina):
    return f"✅ {fonte} voltou a responder.\n🖥️ {maquina}"


def sku_novo(sku, nome, url, maquina):
    return (f"🆕 Produto novo na categoria 30 Anos da Copag: {nome} (SKU {sku}).\n"
            f"Adicione em catalogo.json para monitorar.\n🔗 {url}\n🖥️ {maquina}")


def assumiu(motivo, maquina):
    return f"🔁 {maquina} assumiu os envios: {motivo}."


def heartbeat(n_links, fontes, falhas, maquina, papel):
    return (f"💓 Monitor vivo: {n_links} links em {fontes}. Falhas seguidas agora: {falhas}.\n"
            f"🖥️ {maquina} ({papel})")
