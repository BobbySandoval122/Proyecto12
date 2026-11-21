"""Paridad entre el modo monolitico y el distribuido (correccion del segundo parcial).

La misma solicitud de devolucion se manda por TRES caminos y la decision debe
ser la misma en los tres:

1. Web en modo monolitico (USE_MICROSERVICES=false): la web escribe directo en
   PostgreSQL.
2. Web en modo distribuido (USE_MICROSERVICES=true): la web llama al servicio de
   devoluciones.
3. API directa: lo que usan las apps Android y de escritorio.

Contra la base y los servicios reales; lo que crea se borra al terminar. Solo en
la VM, dentro del contenedor de la web:

    docker compose exec -e INTEGRACION=1 app sh -c \
      "cd apps/web && python -m pytest -v -s -p no:cacheprovider app/tests/test_paridad.py"

Trazabilidad: RNF-28, RF-07, RN-01, RN-16, RN-13.
"""
import json
import os
import re
import unittest
import urllib.error
import urllib.request
from datetime import datetime, timezone
from html import unescape

import psycopg2
import psycopg2.extras

AUTH_URL = os.environ.get("AUTH_URL", "http://auth:8000")
DEVOLUCIONES_URL = os.environ.get("DEVOLUCIONES_URL", "http://devoluciones:8000")
CAMINOS = ("web monolitica", "web distribuida", "api directa")
DESCRIPCION = "Prueba de paridad entre monolito y microservicios."


def _sql(sentencia, params=(), uno=False):
    conn = psycopg2.connect(
        host=os.environ.get("POSTGRES_HOST", "postgres"),
        dbname=os.environ.get("POSTGRES_DB", "devoluciones"),
        user=os.environ.get("POSTGRES_USER", "devoluciones_app"),
        password=os.environ.get("POSTGRES_PASSWORD", ""),
        cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        with conn, conn.cursor() as cur:
            cur.execute(sentencia, params)
            if cur.description is None:
                return None
            return cur.fetchone() if uno else cur.fetchall()
    finally:
        conn.close()


def _http(metodo, url, cuerpo=None, token=None):
    cabeceras = {"Content-Type": "application/json", "Accept": "application/json"}
    if token:
        cabeceras["Authorization"] = f"Bearer {token}"
    peticion = urllib.request.Request(url, method=metodo, headers=cabeceras,
                                      data=json.dumps(cuerpo).encode() if cuerpo is not None else None)
    try:
        with urllib.request.urlopen(peticion, timeout=20) as resp:
            return resp.status, json.loads(resp.read() or b"null")
    except urllib.error.HTTPError as exc:
        try:
            return exc.code, json.loads(exc.read())
        except ValueError:
            return exc.code, None


# --------------------------------------------------------------------------- #
# Traduccion de cada respuesta a una decision comparable
# --------------------------------------------------------------------------- #
def _avisos(html):
    """Solo los mensajes flash; el resto de la pagina tambien dice 'cantidad'."""
    return [unescape(m).lower() for m in re.findall(r'<div class="aviso-msg [a-z]+">(.*?)</div>', html, re.S)]


def decision_web(respuesta):
    if respuesta.status_code == 302 and re.search(r"/devoluciones/\d+$", respuesta.location or ""):
        return "aceptada"
    if respuesta.status_code == 403:
        return "ajena"
    if respuesta.status_code >= 500:
        return f"error_{respuesta.status_code}"
    texto = " ".join(_avisos(respuesta.get_data(as_text=True)))
    for clave, decision in (("plazo", "fuera_de_plazo"), ("ya tienes la solicitud", "duplicada"),
                            ("abierta", "duplicada"), ("cantidad", "cantidad"),
                            ("caracteres", "descripcion"), ("motivo", "motivo")):
        if clave in texto:
            return decision
    return f"otro_{respuesta.status_code}:{texto[:60]}"


def decision_api(codigo, cuerpo):
    if codigo == 201:
        return "aceptada"
    if codigo == 403:
        return "ajena"
    error = (cuerpo or {}).get("error") or {}
    tipo = error.get("tipo")
    if tipo == "fuera_de_plazo":
        return "fuera_de_plazo"
    if tipo == "solicitud_duplicada":
        return "duplicada"
    if tipo in ("sin_disponible", "cantidad_excedida"):
        return "cantidad"
    campos = " ".join(str(d.get("campo")) for d in (error.get("detalles") or []) if isinstance(d, dict))
    if "descripcion" in campos:
        return "descripcion"
    if "motivo" in campos or "motivo" in str(error.get("mensaje", "")).lower():
        return "motivo"
    return f"otro_{codigo}:{tipo}"


SKIP = unittest.skipUnless(os.environ.get("INTEGRACION") == "1",
                           "Solo en la VM: INTEGRACION=1 y el entorno levantado")


@SKIP
class ParidadMonolitoDistribuido(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.inicio = datetime.now(timezone.utc)
        cls.password = os.environ["PASSWORD_DEMO"]
        # Un cliente demo con al menos 3 lineas sin devoluciones dentro del plazo
        # (una por camino) y una fuera del plazo.
        libres = """
            SELECT vd.id, v.cliente_id,
                   (v.fecha_venta + pol.dias_plazo) >= CURRENT_DATE AS en_plazo
              FROM venta_detalle vd
              JOIN ventas v ON v.id = vd.venta_id
              JOIN usuarios u ON u.id = v.cliente_id
              JOIN lotes l ON l.id = vd.lote_id JOIN productos p ON p.id = l.producto_id
              JOIN politicas_devolucion pol ON pol.clasificacion_temperatura = p.clasificacion_temperatura
             WHERE v.eliminado_en IS NULL AND vd.cantidad >= 2 AND RIGHT(u.email, 8) = '@demo.mx'
               AND NOT EXISTS (SELECT 1 FROM devoluciones d WHERE d.venta_detalle_id = vd.id
                                  AND d.eliminado_en IS NULL)"""
        filas = _sql(libres + " ORDER BY vd.id")
        por_cliente = {}
        for f in filas:
            por_cliente.setdefault(f["cliente_id"], {"en": [], "fuera": []})["en" if f["en_plazo"] else "fuera"].append(f["id"])
        candidato = next((c for c, d in por_cliente.items() if len(d["en"]) >= 3 and d["fuera"]), None)
        if candidato is None:
            raise unittest.SkipTest("Faltan lineas libres dentro y fuera del plazo (corre seed_demo hoy)")
        cls.lineas = dict(zip(CAMINOS, por_cliente[candidato]["en"][:3]))
        cls.fuera = por_cliente[candidato]["fuera"][0]
        cls.ajena = next((d["en"][0] for c, d in por_cliente.items() if c != candidato and d["en"]), None)
        cls.email = _sql("SELECT email FROM usuarios WHERE id = %s", (candidato,), uno=True)["email"]
        motivos = _sql("SELECT id FROM motivos WHERE activo ORDER BY id LIMIT 2")
        cls.m1, cls.m2 = motivos[0]["id"], motivos[1]["id"]
        cls.motivo_inexistente = _sql("SELECT COALESCE(MAX(id), 0) + 1000 AS id FROM motivos", uno=True)["id"]

        from app import create_app
        cls.webs = {}
        for camino, distribuido in (("web monolitica", False), ("web distribuida", True)):
            app = create_app()
            app.config.update(USE_MICROSERVICES=distribuido, TESTING=True, PROPAGATE_EXCEPTIONS=False)
            cliente = app.test_client()
            r = cliente.post("/login", data={"email": cls.email, "password": cls.password})
            assert r.status_code == 302, f"login web ({camino}) respondio {r.status_code}"
            cls.webs[camino] = cliente
        codigo, cuerpo = _http("POST", AUTH_URL + "/api/v1/auth/login",
                               {"email": cls.email, "password": cls.password})
        assert codigo == 200, f"login API respondio {codigo}"
        cls.token = cuerpo["access_token"]
        cls.tabla = []

    @classmethod
    def tearDownClass(cls):
        lineas = tuple(list(cls.lineas.values()) + [cls.fuera] + ([cls.ajena] if cls.ajena else []))
        creadas = _sql("""SELECT id FROM devoluciones WHERE venta_detalle_id IN %s AND fecha_solicitud >= %s""",
                       (lineas, cls.inicio))
        if creadas:
            ids = tuple(f["id"] for f in creadas)
            for paso in ("DELETE FROM notificaciones WHERE devolucion_id IN %s",
                         "DELETE FROM devoluciones WHERE id IN %s"):
                _sql(paso, (ids,))
        _http("POST", AUTH_URL + "/api/v1/auth/logout", token=cls.token)
        print("\n\nParidad monolito / distribuido / API")
        print(f"{'Caso':32} " + " ".join(f"{c:18}" for c in CAMINOS))
        for caso, decisiones in cls.tabla:
            print(f"{caso:32} " + " ".join(f"{decisiones[c]:18}" for c in CAMINOS))

    # ------------------------------------------------------------------ #
    def _mandar(self, camino, linea, motivo, cantidad=1, descripcion=DESCRIPCION):
        if camino == "api directa":
            codigo, cuerpo = _http("POST", DEVOLUCIONES_URL + "/api/v1/devoluciones",
                                   {"venta_detalle_id": linea, "motivo_id": motivo,
                                    "cantidad_devuelta": cantidad, "descripcion_problema": descripcion},
                                   token=self.token)
            return decision_api(codigo, cuerpo)
        r = self.webs[camino].post("/devoluciones/nueva", data={
            "venta_detalle_id": linea, "motivo_id": motivo,
            "cantidad_devuelta": cantidad, "descripcion_problema": descripcion})
        return decision_web(r)

    def _caso(self, nombre, esperado, **por_camino):
        decisiones = {c: self._mandar(c, **por_camino[c]) if c in por_camino else self._mandar(c, **por_camino["todos"])
                      for c in CAMINOS}
        self.tabla.append((nombre, decisiones))
        self.assertEqual(decisiones, {c: esperado for c in CAMINOS}, nombre)

    def _cada_uno(self, **datos):
        return {c: dict(datos, linea=self.lineas[c]) for c in CAMINOS}

    def test_01_solicitud_valida(self):
        self._caso("valida", "aceptada", **self._cada_uno(motivo=self.m1))

    def test_02_duplicada_misma_linea_y_motivo(self):
        self._caso("duplicada (RN-16)", "duplicada", **self._cada_uno(motivo=self.m1))

    def test_03_fuera_de_plazo(self):
        self._caso("fuera de plazo (RN-16)", "fuera_de_plazo", todos={"linea": self.fuera, "motivo": self.m1})

    def test_04_cantidad_mayor_a_la_disponible(self):
        self._caso("cantidad excedida (RF-07)", "cantidad", **self._cada_uno(motivo=self.m2, cantidad=99))

    def test_05_descripcion_corta(self):
        self._caso("descripcion corta", "descripcion", **self._cada_uno(motivo=self.m2, descripcion="corta"))

    def test_06_descripcion_larga(self):
        self._caso("descripcion > 2000", "descripcion", **self._cada_uno(motivo=self.m2, descripcion="x" * 2001))

    def test_07_motivo_inexistente(self):
        self._caso("motivo inexistente", "motivo", **self._cada_uno(motivo=self.motivo_inexistente))

    def test_08_compra_de_otro_cliente(self):
        if not self.ajena:
            self.skipTest("No hay linea libre de otro cliente")
        self._caso("compra ajena (RN-13)", "ajena", todos={"linea": self.ajena, "motivo": self.m1})


if __name__ == "__main__":
    unittest.main()
