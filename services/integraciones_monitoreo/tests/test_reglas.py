"""Pruebas unitarias de las reglas de integraciones y monitoreo."""
import unittest
from datetime import date

import reglas

HOY = date(2026, 11, 20)


def venta(**cambios):
    base = {"id_externo": "TK-1", "tienda_externa": "T-001", "cliente_email": "a@b.mx",
            "fecha_venta": "2026-11-19",
            "lineas": [{"sku": "LEC-001", "numero_lote": "L1", "cantidad": 2, "precio_unitario": 30.5}]}
    base.update(cambios)
    return base


class PruebaVentaPos(unittest.TestCase):
    def test_venta_valida(self):
        self.assertEqual(reglas.problemas_de_venta(venta(), HOY), [])

    def test_valores_de_xml_como_texto(self):
        linea = {"sku": "LEC-001", "numero_lote": "L1", "cantidad": "2", "precio_unitario": "30.50"}
        self.assertEqual(reglas.problemas_de_venta(venta(lineas=[linea]), HOY), [])

    def test_fecha_futura_y_mal_formada(self):
        campos = [p["campo"] for p in reglas.problemas_de_venta(venta(fecha_venta="2026-11-21"), HOY)]
        self.assertEqual(campos, ["fecha_venta"])
        self.assertTrue(reglas.problemas_de_venta(venta(fecha_venta="19/11/2026"), HOY))

    def test_lineas_invalidas(self):
        malas = [{"sku": "", "numero_lote": "L1", "cantidad": 0, "precio_unitario": -1}]
        campos = {p["campo"] for p in reglas.problemas_de_venta(venta(lineas=malas), HOY)}
        self.assertEqual(campos, {"lineas[0]", "lineas[0].cantidad", "lineas[0].precio_unitario"})
        self.assertTrue(reglas.problemas_de_venta(venta(lineas=[]), HOY))

    def test_id_externo_con_caracteres_peligrosos(self):
        self.assertIsNone(reglas.id_externo_valido("TK 1; DROP"))
        self.assertIsNone(reglas.id_externo_valido("x" * 65))
        self.assertEqual(reglas.id_externo_valido(" TK-1/A "), "TK-1/A")

    def test_folio_cabe_en_la_columna(self):
        self.assertEqual(reglas.folio_de_pos("TK-1"), "POS-TK-1")
        self.assertEqual(len(reglas.folio_de_pos("x" * 64)), 50)


class PruebaMonitoreo(unittest.TestCase):
    def test_estado_de_un_servicio(self):
        self.assertEqual(reglas.estado_servicio(200, {"estado": "ok"}), "ok")
        self.assertEqual(reglas.estado_servicio(503, {"estado": "degradado"}), "degradado")
        self.assertEqual(reglas.estado_servicio(None, None), "caido")
        self.assertEqual(reglas.estado_servicio(500, None), "caido")

    def chequeo(self):
        return {"servicios": [
                    {"servicio": "auth", "estado": "ok", "ms": 40, "dependencias": {}},
                    {"servicio": "logistica", "estado": "caido", "ms": None, "codigo": None,
                     "error": "URLError", "dependencias": {}},
                    {"servicio": "evidencias", "estado": "degradado", "ms": 2000,
                     "dependencias": {"postgresql": True, "mongodb": False}}],
                "bases": {"postgresql": {"ok": True}, "redis": {"ok": False}},
                "colas": {"operaciones_offline": {"conflicto_24h": 11}}}

    def test_alertas(self):
        claves = {(a["tipo"], a["recurso"]) for a in reglas.alertas_detectadas(self.chequeo())}
        self.assertEqual(claves, {("servicio_caido", "logistica"), ("servicio_degradado", "evidencias"),
                                  ("respuesta_lenta", "evidencias"), ("base_no_disponible", "redis"),
                                  ("conflictos_sincronizacion", "operaciones_offline")})

    def test_todo_bien_sin_alertas(self):
        chequeo = {"servicios": [{"servicio": "auth", "estado": "ok", "ms": 30}],
                   "bases": {"postgresql": {"ok": True}}, "colas": {"operaciones_offline": {"conflicto_24h": 0}}}
        self.assertEqual(reglas.alertas_detectadas(chequeo), [])

    def test_recursos_revisados(self):
        self.assertEqual(reglas.recursos_revisados(self.chequeo()),
                         {"auth", "logistica", "evidencias", "postgresql", "redis", "operaciones_offline"})

    def test_percentil(self):
        self.assertIsNone(reglas.percentil([], 95))
        self.assertEqual(reglas.percentil(list(range(1, 101)), 95), 95)
        self.assertEqual(reglas.percentil([7], 95), 7)

    def test_disponibilidad(self):
        chequeos = [{"servicios": [{"servicio": "auth", "estado": "ok", "ms": 10}]},
                    {"servicios": [{"servicio": "auth", "estado": "ok", "ms": 30}]},
                    {"servicios": [{"servicio": "auth", "estado": "caido", "ms": None}]}]
        auth = reglas.disponibilidad(chequeos)[0]
        self.assertEqual((auth["chequeos"], auth["ok"], auth["caido"]), (3, 2, 1))
        self.assertEqual(auth["disponibilidad_pct"], 66.67)
        self.assertEqual((auth["ms_promedio"], auth["ms_p95"]), (20, 30))


if __name__ == "__main__":
    unittest.main()
