"""La auditoria esta separada del analisis y es de solo lectura. No necesita base de datos.

Correccion del profe: "separarla del analisis, para que cambiar el analisis nunca
toque la auditoria". Estas pruebas hacen cumplir esa regla: si alguien la rompe,
fallan.
Trazabilidad: RF-30, RN-12, RN-13, RNF-16, RNF-23.
"""
import ast
import os

import pytest

import analisis
import app as servicio
import auditoria
import shared.seguridad as seguridad

DIRECTORIO = os.path.dirname(os.path.dirname(__file__))
RUTAS_ANALISIS = [("get", "/api/v1/analisis/alertas-fraude"), ("post", "/api/v1/analisis/clasificar-motivo"),
                  ("get", "/api/v1/analisis/pareto"), ("get", "/api/v1/analisis/resumen"),
                  ("post", "/api/v1/analisis/sincronizar"), ("get", "/api/v1/analisis/eventos")]
RUTAS_AUDITORIA = ["/api/v1/auditoria", "/api/v1/auditoria/eventos", "/api/v1/auditoria/estado"]


def importaciones(archivo):
    arbol = ast.parse(open(os.path.join(DIRECTORIO, archivo), encoding="utf-8").read())
    nombres = set()
    for nodo in ast.walk(arbol):
        if isinstance(nodo, ast.Import):
            nombres |= {a.name.split(".")[0] for a in nodo.names}
        elif isinstance(nodo, ast.ImportFrom):
            nombres.add((nodo.module or "").split(".")[0])
    return nombres


# --------------------------------------------------------------------------- independencia
def test_auditoria_no_importa_el_analisis():
    """La dependencia va en un solo sentido: analisis puede usar auditoria, nunca al reves."""
    usados = importaciones("auditoria.py")
    assert "analisis" not in usados
    assert not usados & {"pymongo", "hashlib", "uuid", "unicodedata"}   # nada del calculo de analisis


def test_auditoria_no_comparte_estado_con_el_analisis():
    simbolos = set(dir(auditoria))
    assert not simbolos & {"calcular_pareto", "clasificar_descripcion", "PALABRAS_MOTIVO", "SQL_SNAPSHOTS", "TTL"}


def test_el_analisis_si_depende_de_la_auditoria_para_su_alias():
    assert "auditoria" in importaciones("analisis.py")


def test_la_auditoria_es_de_solo_lectura():
    """No hay ninguna ruta que escriba: la auditoria se consulta, no se modifica (RN-12)."""
    reglas = [r for r in servicio.create_app().url_map.iter_rules() if r.endpoint.startswith("auditoria.")]
    assert {str(r) for r in reglas} == set(RUTAS_AUDITORIA)
    for r in reglas:
        assert r.methods - {"HEAD", "OPTIONS"} == {"GET"}, r


def test_los_nombres_de_ruta_del_analisis_no_cambiaron():
    """Postman, la suite E2E y la web siguen usando estas rutas mientras migran."""
    reales = {(m.lower(), str(r)) for r in servicio.create_app().url_map.iter_rules()
              if r.endpoint.startswith("analisis.") for m in r.methods if m in ("GET", "POST")}
    assert reales == set(RUTAS_ANALISIS)


# --------------------------------------------------------------------------- interruptor de corte
@pytest.fixture
def cliente(monkeypatch):
    monkeypatch.delenv("ANALISIS_HABILITADO", raising=False)
    return servicio.create_app().test_client()


def test_con_el_analisis_habilitado_exige_token_y_avisa_que_es_obsoleto(cliente):
    r = cliente.get("/api/v1/analisis/pareto")
    assert r.status_code == 401 and r.headers["Deprecation"] == "true"
    assert 'rel="successor-version"' in r.headers["Link"] and "reportes-analitica" in r.headers["Link"]
    assert "clasificacion-motivos" in cliente.post("/api/v1/analisis/clasificar-motivo").headers["Link"]
    assert cliente.get("/api/v1/analisis/eventos").headers["Link"] == '</api/v1/auditoria/eventos>; rel="successor-version"'


def test_las_rutas_sin_sucesor_solo_llevan_deprecation(cliente):
    for ruta in ("/api/v1/analisis/resumen",):
        r = cliente.get(ruta)
        assert r.headers["Deprecation"] == "true" and "Link" not in r.headers


def test_la_auditoria_nunca_se_marca_obsoleta(cliente):
    for ruta in RUTAS_AUDITORIA:
        r = cliente.get(ruta)
        assert r.status_code == 401 and "Deprecation" not in r.headers and "Link" not in r.headers


@pytest.mark.parametrize("valor", ["false", "False", "0", "no", " FALSE "])
def test_con_el_analisis_apagado_responde_410_sin_pedir_token(monkeypatch, valor):
    monkeypatch.setenv("ANALISIS_HABILITADO", valor)
    c = servicio.create_app().test_client()
    for metodo, ruta in RUTAS_ANALISIS:
        r = getattr(c, metodo)(ruta)
        assert r.status_code == 410, ruta
        assert r.json["error"]["tipo"] == "servicio_movido"
        assert "reportes-analitica" in r.json["error"]["detalles"]["pareto"]


def test_con_el_analisis_apagado_la_auditoria_sigue_en_pie(monkeypatch):
    monkeypatch.setenv("ANALISIS_HABILITADO", "false")
    c = servicio.create_app().test_client()
    for ruta in RUTAS_AUDITORIA:
        assert c.get(ruta).status_code == 401          # sigue exigiendo token, no 410


@pytest.mark.parametrize("valor", ["true", "1", "", "cualquier cosa"])
def test_solo_se_apaga_con_un_valor_explicito(monkeypatch, valor):
    monkeypatch.setenv("ANALISIS_HABILITADO", valor)
    assert analisis.habilitado() is True


# --------------------------------------------------------------------------- auditoria con la base simulada
@pytest.fixture
def api(monkeypatch):
    estado = {"rol": "Analista de Devoluciones", "consultas": [], "triggers": ["trg_bitacora_inmutable", "trg_bitacora_sin_truncate"]}
    monkeypatch.delenv("ANALISIS_HABILITADO", raising=False)
    monkeypatch.setattr(seguridad, "decodificar", lambda token, tipo="access": {
        "sub": "7", "rol": estado["rol"], "nombre": "P", "sid": "s", "jti": "j"})
    monkeypatch.setattr(seguridad, "comprobar_en_redis", lambda claims: None)

    def consultar(sql, params=None, uno=False):
        estado["consultas"].append((" ".join(sql.split()), tuple(params or ())))
        if "COUNT(*) AS n" in sql:
            return {"n": 0} if uno else [{"n": 0}]
        if "pg_trigger" in sql:
            return [{"tgname": t} for t in estado["triggers"]]
        if "AS registros" in sql:
            return {"registros": 120, "primero": "2026-09-01", "ultimo": "2026-11-21"}
        return []
    monkeypatch.setattr(auditoria, "consultar", consultar)
    cliente = servicio.create_app().test_client()
    cliente.estado = estado
    cliente.pedir = lambda ruta, rol=None: (estado.update(rol=rol or estado["rol"]) or
                                            cliente.get(ruta, headers={"Authorization": "Bearer x"}))
    return cliente


def test_filtros_de_bitacora_se_ligan_como_parametros(api):
    r = api.pedir("/api/v1/auditoria?accion=alta_devolucion&entidad=devoluciones&entidad_id=5"
                  "&usuario_id=7&correlation_id=abc&desde=2026-10-01&hasta=2026-10-31")
    assert r.status_code == 200
    sql, params = api.estado["consultas"][-1]
    assert params[:7] == ("alta_devolucion", "devoluciones", "abc", 5, 7, __import__("datetime").date(2026, 10, 1),
                          __import__("datetime").date(2026, 10, 31))
    assert "b.accion=%s" in sql and "b.fecha < (%s::date + INTERVAL '1 day')" in sql
    assert "alta_devolucion" not in sql and "devoluciones" not in sql        # nada del usuario dentro del SQL


@pytest.mark.parametrize("consulta", [
    "accion=" + "a" * 101, "entidad=" + "a" * 101, "correlation_id=" + "a" * 101,
    "entidad_id=abc", "entidad_id=0", "entidad_id=-1", "usuario_id=1.5", "usuario_id=99999999999",
    "desde=ayer", "hasta=2026-13-01", "desde=2026-11-02&hasta=2026-11-01", "pagina=0", "por_pagina=101",
])
def test_filtros_invalidos_400(api, consulta):
    assert api.pedir("/api/v1/auditoria?" + consulta).status_code == 400


def test_inyeccion_en_un_filtro_viaja_como_dato(api):
    api.pedir("/api/v1/auditoria?accion=x'%3B DROP TABLE bitacora--")
    sql, params = api.estado["consultas"][-1]
    assert "DROP" not in sql and params[0] == "x'; DROP TABLE bitacora--"


@pytest.mark.parametrize("rol", ["Cliente", "Inspector", "Supervisor", "Encargado de Reembolsos"])
def test_solo_administrador_y_analista_leen_la_auditoria(api, rol):
    for ruta in RUTAS_AUDITORIA:
        assert api.pedir(ruta, rol=rol).status_code == 403, (rol, ruta)
    for rol_ok in ("Administrador", "Analista de Devoluciones"):
        assert api.pedir("/api/v1/auditoria", rol=rol_ok).status_code == 200


def test_estado_informa_la_proteccion_de_la_base(api):
    j = api.pedir("/api/v1/auditoria/estado").json
    assert j["registros"] == 120
    assert j["proteccion"] == {"actualizar_y_borrar_bloqueados": True, "vaciar_bloqueado": True, "completa": True}
    assert "no sustituye" in j["aviso"]


def test_estado_avisa_si_la_migracion_no_esta_puesta_o_esta_incompleta(api):
    api.estado["triggers"] = []
    assert api.pedir("/api/v1/auditoria/estado").json["proteccion"]["completa"] is False
    api.estado["triggers"] = ["trg_bitacora_inmutable"]
    p = api.pedir("/api/v1/auditoria/estado").json["proteccion"]
    assert (p["actualizar_y_borrar_bloqueados"], p["vaciar_bloqueado"], p["completa"]) == (True, False, False)


def test_eventos_nunca_devuelven_el_campo_datos(api, monkeypatch):
    llamadas = {}

    class Cursor(list):
        def sort(self, *a): return self
        def skip(self, n): llamadas["skip"] = n; return self
        def limit(self, n): llamadas["limit"] = n; return self

    class Eventos:
        def count_documents(self, filtro): llamadas["filtro"] = filtro; return 1
        def find(self, filtro, proyeccion): llamadas["proyeccion"] = proyeccion; return Cursor([{"servicio": "devoluciones"}])

    monkeypatch.setattr(auditoria.mongo, "get_mongo", lambda: type("M", (), {"eventos": Eventos()})())
    r = api.pedir("/api/v1/auditoria/eventos?correlation_id=abc&servicio=devoluciones&pagina=2&por_pagina=5")
    assert r.status_code == 200 and llamadas["proyeccion"] == {"datos": 0}          # RNF-16
    assert llamadas["filtro"] == {"correlation_id": "abc", "servicio": "devoluciones"}
    assert (llamadas["skip"], llamadas["limit"]) == (5, 5)
    assert api.pedir("/api/v1/auditoria/eventos?servicio=" + "s" * 61).status_code == 400
