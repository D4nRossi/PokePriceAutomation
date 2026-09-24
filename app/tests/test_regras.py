import json
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from monitor import decisao, relatorio
from monitor.fontes import copag
from monitor.telegram import MARCADOR, interpretar_fixada, serializar

FIX = Path(__file__).parent / "fixtures"
TOL = Decimal("1.00")
T0 = datetime(2026, 9, 23, 20, 0, tzinfo=timezone.utc)


def item(fonte="copag", disp=False, preco="69.99", sugerido=None):
    return {"fonte": fonte, "disponivel": disp, "preco": Decimal(preco) if preco else None,
            "preco_sugerido": Decimal(sugerido) if sugerido else None}


class Copag(unittest.TestCase):
    def test_resposta_real_gravada(self):
        resp = json.loads((FIX / "copag-simulation.json").read_text(encoding="utf-8"))
        obs = copag.interpretar(resp, ["2602", "2605"])
        self.assertTrue(obs["2602"]["disponivel"])
        self.assertEqual(obs["2602"]["preco"], Decimal("69.99"))
        self.assertFalse(obs["2605"]["disponivel"])
        self.assertEqual(obs["2605"]["status"], "withoutStock")

    def test_campo_ausente_e_erro_nao_indisponivel(self):
        with self.assertRaises(copag.FormatoInesperado):
            copag.interpretar({"items": [{"id": "2602", "sellingPrice": 1}]}, ["2602"])
        with self.assertRaises(copag.FormatoInesperado):
            copag.interpretar({"outra": "coisa"}, ["2602"])
        with self.assertRaises(copag.FormatoInesperado):
            copag.interpretar([], ["2602"])

    def test_sku_omitido_fica_marcado_como_ausente(self):
        obs = copag.interpretar({"items": []}, ["2602"])
        self.assertEqual(obs["2602"]["status"], "ausente_na_resposta")
        self.assertFalse(obs["2602"]["disponivel"])


class Decisao(unittest.TestCase):
    def rodar(self, sequencia):
        ant, tipos = None, []
        for it in sequencia:
            tipo, ant = decisao.decidir(it, ant, TOL)
            tipos.append(tipo)
        return tipos

    def test_volta_ao_estoque_alerta_uma_vez(self):
        self.assertEqual(self.rodar([item(), item(disp=True), item(disp=True)]),
                         [None, "voltou_estoque", None])

    def test_esgota_e_volta_alerta_de_novo(self):
        self.assertEqual(self.rodar([item(disp=True), item(), item(disp=True)]),
                         ["voltou_estoque", None, "voltou_estoque"])

    def test_primeira_observacao_ja_disponivel_alerta(self):
        self.assertEqual(self.rodar([item(disp=True)]), ["voltou_estoque"])

    def test_preco_caiu_enquanto_disponivel(self):
        self.assertEqual(self.rodar([item(disp=True, preco="99.99"), item(disp=True, preco="89.99"),
                                     item(disp=True, preco="95.00")]),
                         ["voltou_estoque", "preco_caiu", None])

    def test_teto_inclusivo_no_ml(self):
        ml = lambda p: item("mercadolivre", True, p, "100.00")
        self.assertEqual(decisao.decidir(ml("101.00"), None, TOL)[0], "dentro_do_teto")
        self.assertIsNone(decisao.decidir(ml("101.01"), None, TOL)[0])

    def test_ml_sem_sugerido_nunca_alerta(self):
        self.assertIsNone(decisao.decidir(item("mercadolivre", True, "1.00"), None, TOL)[0])

    def test_ml_nao_repete_dentro_do_teto(self):
        ml = lambda p: item("mercadolivre", True, p, "100.00")
        self.assertEqual(self.rodar([ml("90"), ml("95"), ml("150"), ml("99")]),
                         ["dentro_do_teto", None, None, "dentro_do_teto"])

    def test_estado_sobrevive_ao_json_do_telegram(self):
        _, reg = decisao.decidir(item(disp=True), None, TOL)
        reg = json.loads(json.dumps(reg))
        self.assertIsNone(decisao.decidir(item(disp=True), reg, TOL)[0])


class Papel(unittest.TestCase):
    def papel(self, lider=False, maquina="B", estado=None, agora=T0, inicio=T0):
        return decisao.papel(lider, maquina, estado or {}, agora, inicio, 15)[0]

    def hb(self, m, minutos_atras):
        return {"l": {"m": m, "em": (T0 - timedelta(minutes=minutos_atras)).isoformat()}}

    def test_lider_sempre_atua(self):
        self.assertTrue(self.papel(lider=True, estado=self.hb("X", 0)))

    def test_reserva_quieta_com_lider_vivo(self):
        self.assertFalse(self.papel(estado=self.hb("A", 5)))

    def test_reserva_assume_com_lider_morto(self):
        self.assertTrue(self.papel(estado=self.hb("A", 15)))

    def test_reserva_que_assumiu_continua(self):
        self.assertTrue(self.papel(estado=self.hb("B", 1)))

    def test_reserva_devolve_quando_lider_volta(self):
        self.assertFalse(self.papel(estado=self.hb("A", 0)))

    def test_grupo_novo_reserva_espera_antes_de_assumir(self):
        self.assertFalse(self.papel(inicio=T0 - timedelta(minutes=5)))
        self.assertTrue(self.papel(inicio=T0 - timedelta(minutes=15)))


class EstadoTelegram(unittest.TestCase):
    def test_ida_e_volta(self):
        est = {"a": {"copag:2602": {"d": True, "p": "69.99", "t": False}}, "l": {"m": "A", "em": T0.isoformat()}}
        pin = {"message_id": 7, "from": {"id": 42}, "text": serializar(est)}
        self.assertEqual(interpretar_fixada(pin, 42), (7, est))

    def test_fixada_de_outra_pessoa_e_ignorada(self):
        pin = {"message_id": 7, "from": {"id": 1}, "text": serializar({"x": 1})}
        self.assertEqual(interpretar_fixada(pin, 42), (None, {}))

    def test_json_corrompido_recomeca_sem_quebrar(self):
        pin = {"message_id": 7, "from": {"id": 42}, "text": MARCADOR + "\n{quebrado"}
        self.assertEqual(interpretar_fixada(pin, 42), (7, {}))

    def test_estado_cabe_numa_mensagem(self):
        est = {"a": {f"copag:{i}": {"d": True, "p": "399.99", "t": True} for i in range(60)},
               "n": [str(i) for i in range(30)], "l": {"m": "DESKTOP-VPRVBHA", "em": T0.isoformat()}, "hb": "2026-09-23"}
        self.assertLess(len(serializar(est)), 4096)


class Relatorio(unittest.TestCase):
    def test_texto_do_alerta(self):
        it = {**item(disp=True, preco="169.99", sugerido="169.99"), "produto_nome": "Box ex Greninja",
              "fonte_nome": "Copag Loja", "url": "https://www.copagloja.com.br/box-greninja/p"}
        hist = {"preco_anterior": Decimal("179.99"), "ultima_disponivel": None,
                "indisponivel_desde": T0 - timedelta(hours=2, minutes=10),
                "primeira_observacao": T0 - timedelta(days=1), "menor_preco_disponivel": None}
        txt = relatorio.alerta("voltou_estoque", it, hist, TOL, "PC-A", T0)
        print("\n" + txt)
        self.assertIn("🟢 VOLTOU AO ESTOQUE: Box ex Greninja", txt)
        self.assertIn("teto R$ 170,99 · igual · dentro do teto", txt)
        self.assertIn("Preço anterior: R$ 179,99 (-R$ 10,00 (-5,6%))", txt)
        self.assertIn("há 2 h 10 min", txt)
        self.assertIn("nunca visto por esta máquina", txt)

    def test_brl_milhar(self):
        self.assertEqual(relatorio.brl(Decimal("1234.5")), "R$ 1.234,50")


if __name__ == "__main__":
    unittest.main()
