"""Integracion real de lotes, series y tasas contra la VM (requiere seed_demo con el lote problematico).

    docker compose run --rm -e INTEGRACION=1 ventas-catalogos \
        python -m pytest -v tests/test_integracion_trazabilidad.py

El token sale del servicio auth real; los datos de L-2026-PROB-01 vienen de
scripts/seed_demo.py. La prueba de series crea un lote propio y lo borra al
terminar. Trazabilidad: RF-05, RF-23, RF-24, RN-09, RN-13, RNF-09, RNF-28.
"""
import unittest

from test_integracion import (SERVICIO_URL, SKIP, PREFIJO, _http, _login, _logout, _sql)

BASE = PREFIJO + "/trazabilidad"


@SKIP
class IntegracionTrazabilidad(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.admin = _login("Administrador")
        cls.analista = _login("Analista de Devoluciones")
        cls.cliente = _login("Cliente")
        lote = _sql("SELECT id FROM lotes WHERE numero_lote='L-2026-PROB-01'", uno=True)
        if not lote:
            raise unittest.SkipTest("Falta el lote problematico (corre scripts/seed_demo.py)")
        cls.lote_id = lote["id"]

    @classmethod
    def tearDownClass(cls):
        for t in (cls.admin, cls.analista, cls.cliente):
            _logout(t)

    def get(self, ruta, token=None):
        return _http(SERVICIO_URL, "GET", BASE + ruta, token=token or self.analista)

    def test_cliente_no_consulta_trazabilidad_403(self):
        for ruta in (f"/lotes/{self.lote_id}", "/tasas", "/series/PROB01-0001"):
            self.assertEqual(self.get(ruta, self.cliente)[0], 403, ruta)

    def test_sin_token_401(self):
        self.assertEqual(_http(SERVICIO_URL, "GET", BASE + "/tasas")[0], 401)

    def test_trazabilidad_del_lote_problematico(self):
        codigo, lote = self.get(f"/lotes/{self.lote_id}")
        self.assertEqual(codigo, 200)
        self.assertEqual(lote["resumen"]["unidades_vendidas"], 24)
        self.assertEqual(lote["resumen"]["unidades_devueltas"], 16)
        self.assertEqual(lote["resumen"]["tasa_pct"], 66.67)
        self.assertGreater(lote["resumen"]["veces_promedio"], 1)
        tiendas = {t["tienda"]: t for t in lote["tiendas"]}
        self.assertEqual(tiendas["Tienda Centro"]["unidades_devueltas"], 12)
        self.assertEqual(lote["series"]["total"], 24)
        self.assertEqual(len(lote["devoluciones"]), 4)
        # Las cerradas traen el recorrido completo hasta la disposicion.
        cerradas = [d for d in lote["devoluciones"] if d["estado"] == "cerrada"]
        self.assertEqual({d["recorrido"]["destino_disposicion"] for d in cerradas}, {"desecho"})

    def test_trazabilidad_por_serie(self):
        codigo, serie = self.get("/series/PROB01-0001")
        self.assertEqual(codigo, 200)
        self.assertEqual(serie["numero_lote"], "L-2026-PROB-01")
        self.assertEqual(serie["venta"]["tienda"], "Tienda Centro")
        self.assertEqual(serie["estado"], "devuelta")
        self.assertEqual(self.get("/series/NO-EXISTE-1")[0], 404)

    def test_tasas_senalan_el_lote_y_la_tienda_problematicos(self):
        # Se compara contra el promedio y no contra el primer lugar: los datos
        # aleatorios del seed pueden dar tasas altas a lotes con pocas ventas.
        _, lotes = self.get("/tasas?por=lote")
        fila = next(f for f in lotes["datos"] if "L-2026-PROB-01" in f["etiqueta"])
        self.assertEqual(fila["tasa_pct"], 66.67)
        self.assertGreater(fila["veces_promedio"], 1)
        _, tiendas = self.get("/tasas?por=tienda")
        centro = next(f for f in tiendas["datos"] if f["etiqueta"] == "Tienda Centro")
        self.assertGreater(centro["veces_promedio"], 1)
        for dim in ("proveedor", "producto", "ruta"):
            self.assertEqual(self.get(f"/tasas?por={dim}")[0], 200, dim)

    def test_dimension_y_fecha_invalidas_400(self):
        self.assertEqual(self.get("/tasas?por=usuarios;--")[0], 400)
        self.assertEqual(self.get("/tasas?desde=2026-13-01")[0], 400)
        self.assertEqual(self.get("/tasas?desde=2026-11-02&hasta=2026-11-01")[0], 400)

    def test_listado_de_lotes_con_devoluciones(self):
        codigo, pagina = self.get("/lotes?solo_con_devoluciones=true")
        self.assertEqual(codigo, 200)
        self.assertIn("L-2026-PROB-01", [l["numero_lote"] for l in pagina["datos"]])

    def test_alta_de_series_idempotente_y_sin_duplicar_entre_lotes(self):
        producto = _sql("SELECT id, proveedor_id FROM productos ORDER BY id LIMIT 1", uno=True)
        lote = _sql("INSERT INTO lotes (producto_id, proveedor_id, numero_lote) "
                    "VALUES (%s,%s,'L-TEST-SERIES') RETURNING id",
                    (producto["id"], producto["proveedor_id"]), uno=True)["id"]
        try:
            ruta = f"/lotes/{lote}/series"
            cuerpo = {"series": ["TST-0001", "TST-0002"]}
            codigo, r1 = _http(SERVICIO_URL, "POST", BASE + ruta, cuerpo, self.admin)
            self.assertEqual((codigo, r1["registradas"]), (201, 2))
            codigo, r2 = _http(SERVICIO_URL, "POST", BASE + ruta, cuerpo, self.admin)
            self.assertEqual((codigo, r2["registradas"], r2["ya_existian"]), (201, 0, 2))
            # La misma serie en otro lote es un conflicto.
            codigo, _ = _http(SERVICIO_URL, "POST", BASE + f"/lotes/{self.lote_id}/series",
                              cuerpo, self.admin)
            self.assertEqual(codigo, 409)
            # Solo el administrador da de alta series.
            codigo, _ = _http(SERVICIO_URL, "POST", BASE + ruta, cuerpo, self.analista)
            self.assertEqual(codigo, 403)
        finally:
            _sql("DELETE FROM series_producto WHERE lote_id=%s", (lote,))
            _sql("DELETE FROM lotes WHERE id=%s", (lote,))


if __name__ == "__main__":
    unittest.main()
