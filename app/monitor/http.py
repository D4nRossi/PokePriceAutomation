import json
import time
import urllib.error
import urllib.request

UA = "monitor-pessoal-pokemon/0.2 (hobby, uso pessoal)"


def json_request(method, url, body=None, tentativas=3, timeout=20, headers=None):
    """JSON in/out com backoff em 403/429/5xx e erro de rede. Outros 4xx sobem direto."""
    data = json.dumps(body).encode() if body is not None else None
    h = {"User-Agent": UA, "Accept": "application/json"}
    if data is not None:
        h["Content-Type"] = "application/json"
    h.update(headers or {})
    espera = 5
    for i in range(tentativas):
        try:
            req = urllib.request.Request(url, data=data, headers=h, method=method)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            reintentavel = e.code in (403, 429) or e.code >= 500
            if not reintentavel or i == tentativas - 1:
                raise
        except (urllib.error.URLError, TimeoutError):
            if i == tentativas - 1:
                raise
        time.sleep(espera)
        espera *= 3
