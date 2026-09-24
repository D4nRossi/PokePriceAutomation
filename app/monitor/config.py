import os
import socket
from dataclasses import dataclass
from decimal import Decimal


def _bool(v):
    return str(v).strip().lower() in ("1", "true", "sim", "yes")


@dataclass(frozen=True)
class Config:
    database_url: str
    catalogo: str
    maquina: str
    lider: bool
    failover_minutos: int
    intervalo_segundos: int
    falhas_para_alerta_cego: int
    tolerancia: Decimal
    hora_heartbeat: int
    telegram_token: str
    telegram_chat_id: str
    ml_token: str

    @property
    def tem_telegram(self):
        return bool(self.telegram_token and self.telegram_chat_id)


def carregar():
    e = os.environ.get
    return Config(
        database_url=e("DATABASE_URL", "postgresql://pokemon:pokemon-local@localhost:5433/pokemon"),
        catalogo=e("CATALOGO", "catalogo.json"),
        maquina=(e("MAQUINA") or socket.gethostname()).strip(),
        lider=_bool(e("LIDER", "false")),
        failover_minutos=int(e("FAILOVER_MINUTOS", "15")),
        # Regra de cliente educado: nunca menos de 5 min por fonte.
        intervalo_segundos=max(300, int(e("INTERVALO_SEGUNDOS", "300"))),
        falhas_para_alerta_cego=int(e("FALHAS_PARA_ALERTA_CEGO", "3")),
        tolerancia=Decimal(e("TOLERANCIA_REAIS", "1.00")),
        hora_heartbeat=int(e("HORA_HEARTBEAT", "9")),
        telegram_token=(e("TELEGRAM_BOT_TOKEN") or "").strip(),
        telegram_chat_id=(e("TELEGRAM_CHAT_ID") or "").strip(),
        ml_token=(e("ML_ACCESS_TOKEN") or "").strip(),
    )
