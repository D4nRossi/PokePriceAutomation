"""Loop do monitor.

  python -m monitor.main --loop            # produção (CMD do container)
  python -m monitor.main --uma-vez         # um ciclo
  python -m monitor.main --dry-run         # um ciclo, não envia nem grava estado compartilhado
  python -m monitor.main --verificar       # checa banco, bot, grupo e permissão de fixar
  python -m monitor.main --descobrir-chat  # lista grupos que o bot viu (para achar o TELEGRAM_CHAT_ID)
  python -m monitor.main --teste-telegram  # manda uma mensagem de teste
"""
import argparse
import logging
import sys
import time
from datetime import datetime, timezone

from . import config, db, decisao, relatorio
from .fontes import copag
from .relatorio import SP
from .telegram import Telegram, TelegramErro

log = logging.getLogger("monitor")
DESCOBERTA_A_CADA = 12  # ciclos (1 h com intervalo de 5 min)


def agora():
    return datetime.now(timezone.utc)


class Monitor:
    def __init__(self, cfg, dry=False):
        self.cfg = cfg
        self.dry = dry
        self.inicio = agora()
        self.n = 0
        self.conn = db.conectar(cfg.database_url)
        db.aplicar_schema(self.conn)
        db.sincronizar_catalogo(self.conn, cfg.catalogo)
        self.tg = Telegram(cfg.telegram_token, cfg.telegram_chat_id) if cfg.tem_telegram else None
        self.atuando_antes = None
        if not self.tg:
            log.warning("sem TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID: alertas só no log, estado no banco local")
        if cfg.ml_token:
            log.warning("ML_ACCESS_TOKEN definido, mas o coletor do Mercado Livre ainda não existe; ignorado")

    # ----- estado compartilhado (Telegram) ou local (banco) -----

    def ler_estado(self):
        if self.tg:
            return self.tg.ler_estado()
        return None, db.estado_local_ler(self.conn)

    def gravar_estado(self, msg_id, estado):
        if self.dry:
            return
        if self.tg:
            self.tg.gravar_estado(msg_id, estado)
        else:
            db.estado_local_gravar(self.conn, estado)

    def enviar(self, texto, tipo, link_id=None):
        """True se o grupo recebeu (ou se não há grupo). Tudo fica em alerta_enviado."""
        if self.dry:
            log.info("[DRY-RUN] %s", texto.replace("\n", " | "))
            return True
        ok, erro = True, None
        if self.tg:
            try:
                self.tg.enviar(texto)
            except TelegramErro as e:
                ok, erro = False, str(e)
                log.error("falha ao enviar ao Telegram: %s", e)
        log.info("[ALERTA%s] %s", "" if self.tg else " sem Telegram", texto.replace("\n", " | "))
        db.gravar_alerta(self.conn, link_id, tipo, texto, ok, erro, self.cfg.maquina)
        return ok

    # ----- coleta -----

    def coletar_copag(self):
        links = db.links(self.conn, "copag")
        obs = copag.coletar([l["id_externo"] for l in links])
        itens = []
        for l in links:
            o = obs[l["id_externo"]]
            obs_id = db.gravar_observacao(self.conn, l["link_id"], o, self.cfg.maquina)
            itens.append({**l, **o, "obs_id": obs_id})
        return itens

    def coletar(self):
        """Devolve (itens, eventos_de_sistema). Falha de fonte nunca vira 'indisponível'."""
        itens, sistema = [], []
        for fonte, fn in (("copag", self.coletar_copag),):
            try:
                itens += fn()
                if db.falha_zerar(self.conn, fonte):
                    sistema.append(("fonte_voltou", fonte, relatorio.fonte_voltou(fonte, self.cfg.maquina)))
            except Exception as e:
                erro = f"{type(e).__name__}: {e}"
                r = db.falha_registrar(self.conn, fonte, erro)
                log.error("%s falhou (%d seguidas): %s", fonte, r["consecutivas"], erro)
                if r["consecutivas"] >= self.cfg.falhas_para_alerta_cego and not r["cego_avisado"]:
                    sistema.append(("monitor_cego", fonte,
                                    relatorio.monitor_cego(fonte, r["consecutivas"], erro, self.cfg.maquina)))
        return itens, sistema

    def descobrir(self):
        if self.n % DESCOBERTA_A_CADA:
            return {}
        try:
            conhecidos = db.ids_externos(self.conn, "copag")
            return {s: v for s, v in copag.descobrir().items() if s not in conhecidos}
        except Exception as e:
            log.warning("descoberta de SKU novo falhou (não afeta estoque): %s", e)
            return {}

    # ----- ciclo -----

    def ciclo(self):
        t = agora()
        itens, sistema = self.coletar()
        novos = self.descobrir()
        if itens:
            log.info("%s", " | ".join(
                f"{i['produto_nome'][:16]}={'SIM ' + relatorio.brl(i['preco']) if i['disponivel'] else '-'}"
                for i in itens))

        try:
            msg_id, estado = self.ler_estado()
        except TelegramErro as e:
            log.error("não consegui ler o estado do grupo, nada será enviado neste ciclo: %s", e)
            return

        if self.tg:
            atua, motivo = decisao.papel(self.cfg.lider, self.cfg.maquina, estado, t, self.inicio,
                                         self.cfg.failover_minutos)
        else:
            atua, motivo = True, "sem Telegram (só log)"
        if not atua:
            log.info("%s; não envio", motivo)
            self.atuando_antes = False
            return
        if self.tg and not self.cfg.lider and self.atuando_antes is not True:
            self.enviar(relatorio.assumiu(motivo, self.cfg.maquina), "assumiu")
        self.atuando_antes = True

        alertas = estado.setdefault("a", {})
        for it in itens:
            chave = f"{it['fonte']}:{it['id_externo']}"
            tipo, novo = decisao.decidir(it, alertas.get(chave), self.cfg.tolerancia)
            if tipo:
                hist = db.historico(self.conn, it["link_id"], it["obs_id"])
                texto = relatorio.alerta(tipo, it, hist, self.cfg.tolerancia, self.cfg.maquina, t)
                if not self.enviar(texto, tipo, it["link_id"]):
                    continue  # não marca: tenta de novo no próximo ciclo
            alertas[chave] = novo

        for tipo, fonte, texto in sistema:
            if self.enviar(texto, tipo) and tipo == "monitor_cego":
                db.falha_marcar_avisado(self.conn, fonte)

        vistos = set(estado.setdefault("n", []))
        for sku, v in novos.items():
            if sku not in vistos and self.enviar(relatorio.sku_novo(sku, v["nome"], v["url"], self.cfg.maquina), "sku_novo"):
                vistos.add(sku)
        estado["n"] = sorted(vistos)

        local = t.astimezone(SP)
        hoje = f"{local:%Y-%m-%d}"
        if local.hour >= self.cfg.hora_heartbeat and estado.get("hb") != hoje:
            falhas = self.conn.execute("SELECT coalesce(sum(consecutivas), 0) AS n FROM falha_fonte").fetchone()["n"]
            fontes = ", ".join(sorted({i["fonte"] for i in itens})) or "nenhuma fonte respondendo"
            if self.enviar(relatorio.heartbeat(len(itens), fontes, falhas, self.cfg.maquina, motivo), "heartbeat"):
                estado["hb"] = hoje

        estado["l"] = {"m": self.cfg.maquina, "em": t.isoformat(timespec="seconds")}
        try:
            self.gravar_estado(msg_id, estado)
        except TelegramErro as e:
            log.error("não consegui gravar o estado no grupo (o bot é admin com permissão de fixar?): %s", e)

    def rodar(self, loop):
        while True:
            try:
                self.ciclo()
            except Exception:
                log.exception("ciclo quebrou; segue no próximo")
            self.n += 1
            if not loop:
                return
            time.sleep(self.cfg.intervalo_segundos)


# ----- utilitários de configuração -----

def verificar(cfg):
    ok = True
    conn = db.conectar(cfg.database_url, tentativas=3)
    db.aplicar_schema(conn)
    db.sincronizar_catalogo(conn, cfg.catalogo)
    n = conn.execute("SELECT count(*) AS n FROM observacao").fetchone()["n"]
    print(f"[ok] banco: {n} observações gravadas")
    print(f"[..] máquina: {cfg.maquina} · líder: {cfg.lider} · failover: {cfg.failover_minutos} min")
    if not cfg.tem_telegram:
        print("[--] Telegram não configurado (TELEGRAM_BOT_TOKEN e TELEGRAM_CHAT_ID)")
        return True
    tg = Telegram(cfg.telegram_token, cfg.telegram_chat_id)
    try:
        me = tg.api("getMe")
        print(f"[ok] bot: @{me['username']}")
        chat = tg.api("getChat", chat_id=cfg.telegram_chat_id)
        print(f"[ok] grupo: {chat.get('title')} ({chat['type']})")
        membro = tg.api("getChatMember", chat_id=cfg.telegram_chat_id, user_id=me["id"])
        pode_fixar = membro["status"] == "administrator" and membro.get("can_pin_messages", False)
        print(f"[{'ok' if pode_fixar else 'ERRO'}] bot é {membro['status']}, pode fixar: {pode_fixar}")
        if not pode_fixar:
            print("      Torne o bot administrador do grupo com 'Fixar mensagens'. Sem isso as máquinas não se enxergam.")
            ok = False
        msg_id, estado = tg.ler_estado()
        l = estado.get("l")
        print(f"[..] estado compartilhado: {'mensagem ' + str(msg_id) if msg_id else 'ainda não existe'}"
              + (f", último ativo {l['m']} em {l['em']}" if l else ""))
    except TelegramErro as e:
        print(f"[ERRO] {e}")
        ok = False
    return ok


def descobrir_chat(cfg):
    if not cfg.telegram_token:
        print("Defina TELEGRAM_BOT_TOKEN no .env primeiro.")
        return
    tg = Telegram(cfg.telegram_token, "")
    chats = {}
    for u in tg.api("getUpdates"):
        for k in ("message", "my_chat_member", "channel_post"):
            c = (u.get(k) or {}).get("chat")
            if c:
                chats[c["id"]] = f"{c.get('title') or c.get('username') or c.get('first_name')} ({c['type']})"
    if not chats:
        print("Nenhum chat ainda. Adicione o bot ao grupo, mande uma mensagem lá e rode de novo.")
    for cid, nome in chats.items():
        print(f"TELEGRAM_CHAT_ID={cid}    # {nome}")


def main():
    logging.Formatter.converter = staticmethod(lambda s: datetime.fromtimestamp(s, SP).timetuple())
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        datefmt="%d/%m %H:%M:%S", stream=sys.stdout)
    p = argparse.ArgumentParser()
    g = p.add_mutually_exclusive_group()
    for f in ("--loop", "--uma-vez", "--dry-run", "--verificar", "--descobrir-chat", "--teste-telegram"):
        g.add_argument(f, action="store_true")
    a = p.parse_args()
    cfg = config.carregar()

    if a.verificar:
        sys.exit(0 if verificar(cfg) else 1)
    if a.descobrir_chat:
        return descobrir_chat(cfg)
    if a.teste_telegram:
        if not cfg.tem_telegram:
            sys.exit("Telegram não configurado.")
        Telegram(cfg.telegram_token, cfg.telegram_chat_id).enviar(
            f"🧪 Teste do monitor Pokémon 30 Anos. 🖥️ {cfg.maquina}")
        print("enviado")
        return
    log.info("iniciando · máquina %s · líder %s · intervalo %d s", cfg.maquina, cfg.lider, cfg.intervalo_segundos)
    Monitor(cfg, dry=a.dry_run).rodar(loop=a.loop)


if __name__ == "__main__":
    main()
