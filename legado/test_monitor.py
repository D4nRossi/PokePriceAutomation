import json
import unittest
from pathlib import Path

import monitor as m

EV = Path(__file__).parent / "docs" / "evidencias"
NOMES = {"2602": "Duplo", "2605": "ETB"}


def sim(avail_2602="withoutStock"):
    return {"items": [
        {"id": "2602", "availability": avail_2602, "sellingPrice": 6999},
        {"id": "2605", "availability": "withoutStock", "sellingPrice": 39999},
    ]}


class T(unittest.TestCase):
    def test_fixture_real_parseia(self):
        d = json.loads((EV / "copag-simulation-sem-cep-2026-09-23.json").read_text(encoding="utf-8"))
        obs = m.interpretar_simulacao(d, ["2602", "2605"])
        self.assertTrue(obs["2602"]["disponivel"])
        self.assertFalse(obs["2605"]["disponivel"])

    def test_indisponivel_para_disponivel_alerta_uma_vez(self):
        st = {}
        a, st = m.avaliar(st, m.interpretar_simulacao(sim(), ["2602", "2605"]), NOMES, {})
        self.assertEqual(a, [])
        a, st = m.avaliar(st, m.interpretar_simulacao(sim("available"), ["2602", "2605"]), NOMES, {})
        self.assertEqual(len(a), 1)
        self.assertIn("69,99", a[0])
        a, st = m.avaliar(st, m.interpretar_simulacao(sim("available"), ["2602", "2605"]), NOMES, {})
        self.assertEqual(a, [], "não pode duplicar")

    def test_volta_a_alertar_depois_de_esgotar(self):
        st = {}
        for av, esperado in [("available", 1), ("withoutStock", 0), ("available", 1)]:
            a, st = m.avaliar(st, m.interpretar_simulacao(sim(av), ["2602"]), NOMES, {})
            self.assertEqual(len(a), esperado)

    def test_campo_ausente_e_erro_nao_indisponivel(self):
        with self.assertRaises(m.FormatoInesperado):
            m.interpretar_simulacao({"items": [{"id": "2602", "sellingPrice": 1}]}, ["2602"])
        with self.assertRaises(m.FormatoInesperado):
            m.interpretar_simulacao({"erro": "x"}, ["2602"])

    def test_monitor_cego_avisa_uma_vez_e_avisa_volta(self):
        st, total = {}, []
        for _ in range(5):
            a, st = m.registrar_falha(st, "Copag", "403", 3)
            total += a
        self.assertEqual(len(total), 1)
        a, st = m.registrar_sucesso(st, "Copag")
        self.assertEqual(len(a), 1)
        a, st = m.registrar_sucesso(st, "Copag")
        self.assertEqual(a, [])


if __name__ == "__main__":
    unittest.main()
