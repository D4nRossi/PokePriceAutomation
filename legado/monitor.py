"""Monitor de estoque Copag, Pokémon TCG Celebração 30 Anos.

Uso:
  python monitor.py            # uma checagem
  python monitor.py --loop     # checa a cada intervalo_segundos, até Ctrl+C
  python monitor.py --dry-run  # mostra o que alertaria, não envia nem grava estado

Alerta no Telegram se TELEGRAM_BOT_TOKEN e TELEGRAM_CHAT_ID estiverem definidos;
senão, no console com bipe.
"""
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

BASE = "https://www.copagloja.com.br"
UA = "monitor-pessoal-pokemon/0.1 (hobby, uso pessoal)"
DIR = Path(__file__).parent
CONFIG = DIR / "products.json"
STATE = DIR / "state.json"
LOG = DIR / "monitor.log"


def log(msg):
    """Console quando existe (pythonw não tem) e sempre no monitor.log."""
    if sys.stdout:
        print(msg, flush=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(msg + "\n")


def toast(titulo, texto):
    """Notificação nativa do Windows, via PowerShell, sem janela."""
    def esc(t):
        return t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;").replace("'", "''")
    xml = (
        '<toast scenario="reminder"><visual><binding template="ToastGeneric">'
        f"<text>{esc(titulo)}</text><text>{esc(texto)}</text></binding></visual>"
        '<actions><action content="OK" arguments="ok" activationType="system"/></actions></toast>'
    )
    ps = (
        "[Windows.UI.Notifications.ToastNotificationManager,Windows.UI.Notifications,ContentType=WindowsRuntime]>$null;"
        "[Windows.Data.Xml.Dom.XmlDocument,Windows.Data.Xml.Dom.XmlDocument,ContentType=WindowsRuntime]>$null;"
        "$x=New-Object Windows.Data.Xml.Dom.XmlDocument;"
        f"$x.LoadXml('{xml}');"
        "$app='{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\\WindowsPowerShell\\v1.0\\powershell.exe';"
        "[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($app).Show([Windows.UI.Notifications.ToastNotification]::new($x))"
    )
    subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), timeout=30, check=True,
                   capture_output=True)


class FormatoInesperado(Exception):
    """A resposta veio, mas sem o campo esperado. Nunca vira 'sem estoque'."""


def http(method, url, body=None, tentativas=3):
    data = json.dumps(body).encode() if body is not None else None
    headers = {"User-Agent": UA, "Accept": "application/json"}
    if data:
        headers["Content-Type"] = "application/json"
    espera = 5
    for i in range(tentativas):
        try:
            req = urllib.request.Request(url, data=data, headers=headers, method=method)
            with urllib.request.urlopen(req, timeout=20) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code not in (403, 429) and e.code < 500 or i == tentativas - 1:
                raise
        except (urllib.error.URLError, TimeoutError):
            if i == tentativas - 1:
                raise
        time.sleep(espera)
        espera *= 3


# ---------- coleta ----------

def simular(skus):
    body = {"items": [{"id": s, "quantity": 1, "seller": "1"} for s in skus], "country": "BRA"}
    return http("POST", f"{BASE}/api/checkout/pub/orderForms/simulation?sc=1", body)


def interpretar_simulacao(resp, skus):
    """Devolve {sku: {"disponivel": bool, "preco": float}}. Campo faltando => FormatoInesperado."""
    itens = resp.get("items") if isinstance(resp, dict) else None
    if not isinstance(itens, list):
        raise FormatoInesperado("simulação sem 'items'")
    out = {}
    for it in itens:
        if "id" not in it or "availability" not in it or "sellingPrice" not in it:
            raise FormatoInesperado(f"item sem id/availability/sellingPrice: {str(it)[:200]}")
        out[str(it["id"])] = {
            "disponivel": it["availability"] == "available",
            "status": it["availability"],
            "preco": it["sellingPrice"] / 100,
        }
    faltando = set(skus) - set(out)
    # SKU que some da resposta é informação: a VTEX omite item desativado. Reporta, não inventa.
    for s in faltando:
        out[s] = {"disponivel": False, "status": "ausente_na_resposta", "preco": None}
    return out


def catalogo(fq):
    q = urllib.parse.urlencode({"fq": fq, "_from": 0, "_to": 49})
    return http("GET", f"{BASE}/api/catalog_system/pub/products/search?{q}")


def skus_do_catalogo(resp):
    if not isinstance(resp, list):
        raise FormatoInesperado("catálogo não é lista")
    out = {}
    for p in resp:
        for it in p.get("items", []):
            out[str(it["itemId"])] = {"nome": p.get("productName", "?"), "link": p.get("link")}
    return out


# ---------- máquina de estado ----------

def avaliar(state, obs, nomes, links):
    """Compara observação com o último estado. Devolve (alertas, novo_state). Pura."""
    alertas = []
    novo = dict(state)
    ult = dict(state.get("disponivel", {}))
    for sku, o in obs.items():
        antes = ult.get(sku)  # None = nunca visto
        if o["disponivel"] and antes is not True:
            preco = f"R$ {o['preco']:.2f}".replace(".", ",") if o["preco"] is not None else "?"
            alertas.append(f"🟢 DISPONÍVEL na Copag: {nomes.get(sku, sku)} por {preco}\n{links.get(sku) or BASE}")
        ult[sku] = o["disponivel"]
    novo["disponivel"] = ult
    return alertas, novo


def registrar_falha(state, fonte, erro, limite):
    novo = dict(state)
    falhas = dict(state.get("falhas", {}))
    avisado = dict(state.get("cego_avisado", {}))
    falhas[fonte] = falhas.get(fonte, 0) + 1
    alertas = []
    if falhas[fonte] >= limite and not avisado.get(fonte):
        alertas.append(f"🔴 Monitor CEGO para {fonte}: {falhas[fonte]} falhas seguidas. Último erro: {erro}")
        avisado[fonte] = True
    novo["falhas"], novo["cego_avisado"] = falhas, avisado
    return alertas, novo


def registrar_sucesso(state, fonte):
    novo = dict(state)
    alertas = []
    if state.get("cego_avisado", {}).get(fonte):
        alertas.append(f"✅ {fonte} voltou a responder.")
    novo["falhas"] = {**state.get("falhas", {}), fonte: 0}
    novo["cego_avisado"] = {**state.get("cego_avisado", {}), fonte: False}
    return alertas, novo


# ---------- notificação e persistência ----------

def notificar(msgs, dry):
    if not msgs:
        return
    token, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    for m in msgs:
        log(("[DRY-RUN] " if dry else "[ALERTA] ") + m)
        if dry:
            continue
        if token and chat:
            try:
                body = urllib.parse.urlencode({"chat_id": chat, "text": m}).encode()
                urllib.request.urlopen(f"https://api.telegram.org/bot{token}/sendMessage", body, timeout=20)
            except Exception as e:
                log(f"  falha ao enviar Telegram: {e}")
        else:
            try:
                toast("Monitor Pokémon 30 Anos", m)
            except Exception as e:
                log(f"  falha no toast: {e}")


def carregar(p, padrao):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return padrao


def salvar(p, obj):
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(p)


# ---------- ciclo ----------

def ciclo(cfg, state, dry, checar_catalogo):
    prods = [p for p in cfg["produtos"] if p.get("monitorar", True)]
    skus = [p["sku"] for p in prods]
    nomes = {p["sku"]: p["nome"] for p in prods}
    links = state.get("links", {})
    alertas = []

    if checar_catalogo:
        try:
            cat = skus_do_catalogo(catalogo(cfg["categoria_fq"]))
            links = {s: v["link"] for s, v in cat.items()}
            state = {**state, "links": links}
            conhecidos = set(p["sku"] for p in cfg["produtos"]) | set(state.get("skus_novos_avisados", []))
            novos = [s for s in cat if s not in conhecidos]
            for s in novos:
                alertas.append(f"🆕 SKU novo na categoria 30 Anos: {s} {cat[s]['nome']} (adicione em products.json)\n{cat[s]['link']}")
            state["skus_novos_avisados"] = sorted(set(state.get("skus_novos_avisados", [])) | set(novos))
        except Exception as e:
            log(f"  catálogo falhou (só descoberta, não afeta estoque): {e}")

    try:
        obs = interpretar_simulacao(simular(skus), skus)
        a, state = registrar_sucesso(state, "Copag")
        alertas += a
        a, state = avaliar(state, obs, nomes, links)
        alertas += a
        linha = " | ".join(f"{nomes[s][:18]}={'SIM' if obs[s]['disponivel'] else '-'}" for s in skus)
        log(f"{datetime.now():%d/%m %H:%M:%S} {linha}")
    except Exception as e:
        log(f"{datetime.now():%d/%m %H:%M:%S} ERRO Copag: {type(e).__name__}: {e}")
        a, state = registrar_falha(state, "Copag", f"{type(e).__name__}: {e}", cfg["falhas_para_alerta_cego"])
        alertas += a

    hoje = f"{datetime.now():%Y-%m-%d}"
    if datetime.now().hour >= 9 and state.get("heartbeat") != hoje and not dry:
        falhas = state.get("falhas", {}).get("Copag", 0)
        alertas.append(f"💓 Monitor vivo: {len(skus)} produtos, fonte Copag, {falhas} falhas seguidas agora.")
        state = {**state, "heartbeat": hoje}

    notificar(alertas, dry)
    return state


def main():
    if "--teste-alerta" in sys.argv:
        notificar(["🧪 Teste: se você está lendo isto, o alerta chega."], dry=False)
        return
    dry = "--dry-run" in sys.argv
    loop = "--loop" in sys.argv
    cfg = carregar(CONFIG, None)
    state = carregar(STATE, {})
    n = 0
    while True:
        state = ciclo(cfg, state, dry, checar_catalogo=(n % 12 == 0))
        if not dry:
            salvar(STATE, state)
        n += 1
        if not loop:
            break
        time.sleep(max(300, cfg["intervalo_segundos"]))


if __name__ == "__main__":
    main()
