"""Bot API do Telegram: envio e estado compartilhado entre máquinas.

O estado compartilhado é uma mensagem do próprio bot, FIXADA no grupo, com um
JSON. Toda máquina lê pelo getChat (pinned_message); só quem está atuando edita.
Por isso o bot precisa ser administrador com permissão de fixar mensagens.
"""
import json
import urllib.error
import urllib.request

MARCADOR = "🤖 Estado do monitor (não apague nem desafixe)"


class TelegramErro(Exception):
    pass


class Telegram:
    def __init__(self, token, chat_id):
        self.base = f"https://api.telegram.org/bot{token}/"
        self.chat_id = chat_id
        self._bot_id = None

    def api(self, metodo, **params):
        req = urllib.request.Request(
            self.base + metodo, data=json.dumps(params).encode(),
            headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                resp = json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            try:
                resp = json.loads(e.read().decode("utf-8"))
            except Exception:
                raise TelegramErro(f"HTTP {e.code} em {metodo}") from None
        except urllib.error.URLError as e:
            raise TelegramErro(f"rede em {metodo}: {e.reason}") from None
        if not resp.get("ok"):
            raise TelegramErro(f"{metodo}: {resp.get('error_code')} {resp.get('description')}")
        return resp["result"]

    @property
    def bot_id(self):
        if self._bot_id is None:
            self._bot_id = self.api("getMe")["id"]
        return self._bot_id

    def enviar(self, texto):
        return self.api("sendMessage", chat_id=self.chat_id, text=texto[:4000])["message_id"]

    # ----- estado compartilhado -----

    def ler_estado(self):
        """(message_id | None, dict). Mensagem fixada que não é nossa = sem estado."""
        pin = self.api("getChat", chat_id=self.chat_id).get("pinned_message")
        return interpretar_fixada(pin, self.bot_id)

    def gravar_estado(self, message_id, estado):
        texto = serializar(estado)
        if message_id:
            try:
                self.api("editMessageText", chat_id=self.chat_id, message_id=message_id, text=texto)
                return message_id
            except TelegramErro as e:
                if "message is not modified" in str(e):
                    return message_id
                if "message to edit not found" not in str(e):
                    raise
        novo = self.api("sendMessage", chat_id=self.chat_id, text=texto, disable_notification=True)["message_id"]
        self.api("pinChatMessage", chat_id=self.chat_id, message_id=novo, disable_notification=True)
        return novo


def serializar(estado):
    return MARCADOR + "\n" + json.dumps(estado, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def interpretar_fixada(pin, bot_id):
    if not pin or pin.get("from", {}).get("id") != bot_id:
        return None, {}
    texto = pin.get("text") or ""
    if not texto.startswith(MARCADOR):
        return None, {}
    try:
        return pin["message_id"], json.loads(texto[len(MARCADOR):].strip())
    except json.JSONDecodeError:
        # Alguém editou à mão ou corrompeu: recomeça. Custa no máximo um alerta repetido.
        return pin["message_id"], {}
