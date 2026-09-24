"""Copag Loja (VTEX). Evidência em docs/00-spike-acesso.md.

Estoque vem da simulação de checkout (no-store). O catálogo tem cache de 300 s e
divergiu da simulação no spike; serve só para descobrir SKU novo.
"""
import urllib.parse
from decimal import Decimal

from ..http import json_request

BASE = "https://www.copagloja.com.br"
CATEGORIA_30_ANOS = "C:/35741/106254/"


class FormatoInesperado(Exception):
    """Resposta veio sem o campo esperado. Nunca pode virar 'sem estoque'."""


def simular(skus):
    body = {"items": [{"id": s, "quantity": 1, "seller": "1"} for s in skus], "country": "BRA"}
    return json_request("POST", f"{BASE}/api/checkout/pub/orderForms/simulation?sc=1", body)


def interpretar(resp, skus):
    """{sku: {disponivel, status, preco}}. Campo faltando => FormatoInesperado."""
    itens = resp.get("items") if isinstance(resp, dict) else None
    if not isinstance(itens, list):
        raise FormatoInesperado("simulação sem 'items'")
    out = {}
    for it in itens:
        if not all(k in it for k in ("id", "availability", "sellingPrice")):
            raise FormatoInesperado(f"item sem id/availability/sellingPrice: {str(it)[:200]}")
        out[str(it["id"])] = {
            "disponivel": it["availability"] == "available",
            "status": str(it["availability"]),
            "preco": Decimal(it["sellingPrice"]) / 100,
        }
    # A VTEX omite item desativado. É informação, não estoque: registra como ausente.
    for s in set(skus) - set(out):
        out[s] = {"disponivel": False, "status": "ausente_na_resposta", "preco": None}
    return out


def coletar(skus):
    return interpretar(simular(skus), skus)


def descobrir(fq=CATEGORIA_30_ANOS):
    """{sku: {nome, url}} de tudo que a categoria lista hoje."""
    q = urllib.parse.urlencode({"fq": fq, "_from": 0, "_to": 49})
    resp = json_request("GET", f"{BASE}/api/catalog_system/pub/products/search?{q}")
    if not isinstance(resp, list):
        raise FormatoInesperado("catálogo não é lista")
    out = {}
    for p in resp:
        for it in p.get("items", []):
            out[str(it["itemId"])] = {"nome": p.get("productName", "?"), "url": p.get("link")}
    return out
