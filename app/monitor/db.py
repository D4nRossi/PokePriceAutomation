import json
import logging
import time
from pathlib import Path

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

log = logging.getLogger("monitor.db")
SQL = Path(__file__).resolve().parent.parent / "sql"


def conectar(url, tentativas=30):
    for i in range(tentativas):
        try:
            return psycopg.connect(url, autocommit=True, row_factory=dict_row)
        except psycopg.OperationalError as e:
            if i == tentativas - 1:
                raise
            log.warning("banco indisponível (%s), nova tentativa em 2 s", str(e).strip()[:120])
            time.sleep(2)


def aplicar_schema(conn):
    for f in sorted(SQL.glob("*.sql")):
        conn.execute(f.read_text(encoding="utf-8"))


def sincronizar_catalogo(conn, caminho):
    """catalogo.json manda: upsert de fontes, produtos e links; o que saiu do arquivo fica inativo."""
    cat = json.loads(Path(caminho).read_text(encoding="utf-8"))
    with conn.transaction():
        for f in cat["fontes"]:
            conn.execute(
                "INSERT INTO fonte (codigo, nome) VALUES (%s, %s) "
                "ON CONFLICT (codigo) DO UPDATE SET nome = EXCLUDED.nome",
                (f["codigo"], f["nome"]))
        conn.execute("UPDATE produto SET ativo = false")
        conn.execute("UPDATE link SET ativo = false")
        for p in cat["produtos"]:
            pid = conn.execute(
                "INSERT INTO produto (codigo, nome, ean, preco_sugerido, ativo, atualizado_em) "
                "VALUES (%s, %s, %s, %s, true, now()) "
                "ON CONFLICT (codigo) DO UPDATE SET nome = EXCLUDED.nome, ean = EXCLUDED.ean, "
                "preco_sugerido = EXCLUDED.preco_sugerido, ativo = true, atualizado_em = now() "
                "RETURNING id",
                (p["codigo"], p["nome"], p.get("ean"), p.get("preco_sugerido"))).fetchone()["id"]
            for l in p.get("links", []):
                conn.execute(
                    "INSERT INTO link (produto_id, fonte, id_externo, url, ativo) VALUES (%s, %s, %s, %s, true) "
                    "ON CONFLICT (fonte, id_externo) DO UPDATE SET produto_id = EXCLUDED.produto_id, "
                    "url = EXCLUDED.url, ativo = true",
                    (pid, l["fonte"], l["id_externo"], l["url"]))
    n = conn.execute("SELECT count(*) AS n FROM link WHERE ativo").fetchone()["n"]
    log.info("catálogo sincronizado: %d produtos, %d links ativos", len(cat["produtos"]), n)


def links(conn, fonte):
    return conn.execute(
        "SELECT l.id AS link_id, l.fonte, l.id_externo, l.url, p.codigo AS produto_codigo, "
        "p.nome AS produto_nome, p.preco_sugerido, f.nome AS fonte_nome "
        "FROM link l JOIN produto p ON p.id = l.produto_id JOIN fonte f ON f.codigo = l.fonte "
        "WHERE l.ativo AND p.ativo AND l.fonte = %s ORDER BY p.id",
        (fonte,)).fetchall()


def ids_externos(conn, fonte):
    return {r["id_externo"] for r in conn.execute("SELECT id_externo FROM link WHERE fonte = %s", (fonte,))}


def gravar_observacao(conn, link_id, obs, maquina):
    return conn.execute(
        "INSERT INTO observacao (link_id, disponivel, status, preco, frete, vendedor, maquina) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id",
        (link_id, obs["disponivel"], obs["status"], obs.get("preco"), obs.get("frete"),
         obs.get("vendedor"), maquina)).fetchone()["id"]


def historico(conn, link_id, obs_id):
    """Contexto para o report: tudo ANTES da observação atual."""
    return conn.execute(
        """
        WITH antes AS (SELECT * FROM observacao WHERE link_id = %(l)s AND id < %(id)s),
             ult_disp AS (SELECT max(observado_em) AS em FROM antes WHERE disponivel)
        SELECT
          (SELECT preco FROM antes ORDER BY id DESC LIMIT 1)                    AS preco_anterior,
          (SELECT disponivel FROM antes ORDER BY id DESC LIMIT 1)               AS disponivel_anterior,
          (SELECT em FROM ult_disp)                                             AS ultima_disponivel,
          (SELECT min(observado_em) FROM antes
             WHERE NOT disponivel
               AND observado_em > coalesce((SELECT em FROM ult_disp), '-infinity')) AS indisponivel_desde,
          (SELECT min(observado_em) FROM antes)                                 AS primeira_observacao,
          (SELECT min(preco) FROM antes WHERE disponivel)                       AS menor_preco_disponivel
        """, {"l": link_id, "id": obs_id}).fetchone()


def gravar_alerta(conn, link_id, tipo, mensagem, enviado, erro, maquina):
    conn.execute(
        "INSERT INTO alerta_enviado (link_id, tipo, mensagem, enviado, erro, maquina) "
        "VALUES (%s, %s, %s, %s, %s, %s)",
        (link_id, tipo, mensagem, enviado, erro, maquina))


def falha_registrar(conn, fonte, erro):
    return conn.execute(
        "INSERT INTO falha_fonte (fonte, consecutivas, ultimo_erro, atualizado_em) VALUES (%s, 1, %s, now()) "
        "ON CONFLICT (fonte) DO UPDATE SET consecutivas = falha_fonte.consecutivas + 1, "
        "ultimo_erro = EXCLUDED.ultimo_erro, atualizado_em = now() "
        "RETURNING consecutivas, cego_avisado",
        (fonte, erro)).fetchone()


def falha_marcar_avisado(conn, fonte):
    conn.execute("UPDATE falha_fonte SET cego_avisado = true WHERE fonte = %s", (fonte,))


def falha_zerar(conn, fonte):
    """Devolve True se a fonte estava marcada como cega (para avisar que voltou)."""
    r = conn.execute(
        "UPDATE falha_fonte f SET consecutivas = 0, cego_avisado = false, atualizado_em = now() "
        "FROM (SELECT cego_avisado FROM falha_fonte WHERE fonte = %s) antes "
        "WHERE f.fonte = %s RETURNING antes.cego_avisado",
        (fonte, fonte)).fetchone()
    return bool(r and r["cego_avisado"])


def estado_local_ler(conn):
    r = conn.execute("SELECT dados FROM estado_local WHERE id = 1").fetchone()
    return r["dados"] if r else {}


def estado_local_gravar(conn, dados):
    conn.execute(
        "INSERT INTO estado_local (id, dados) VALUES (1, %s) ON CONFLICT (id) DO UPDATE SET dados = EXCLUDED.dados",
        (Jsonb(dados),))
