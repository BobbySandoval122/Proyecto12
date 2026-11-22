"""Reglas puras de causa raiz y CAPA. No necesitan base de datos.

Trazabilidad: RF-23, RF-24, RN-09, RN-11, RN-12.
"""
from datetime import date, timedelta
from decimal import Decimal

import pytest

import reglas
from shared.respuestas import ErrorApi

HOY = date(2026, 11, 21)


def falla(codigo, funcion, *args, **kwargs):
    with pytest.raises(ErrorApi) as err:
        funcion(*args, **kwargs)
    assert err.value.codigo == codigo, err.value.mensaje
    return err.value


# --------------------------------------------------------------------------- alertas
def test_alerta_con_patron_claro():
    assert reglas.evaluar_alerta(100, 12, 6, 5.0) == 2.4


def test_alerta_justo_en_el_doble_del_promedio():
    assert reglas.evaluar_alerta(100, 10, 5, 5.0) == 2.0


@pytest.mark.parametrize("vendidas,devueltas,casos,promedio", [
    (19, 10, 5, 5.0),     # muestra insuficiente aunque la tasa sea enorme
    (100, 12, 2, 5.0),    # menos de 3 casos
    (100, 9, 5, 5.0),     # menos del doble del promedio
    (0, 0, 0, 5.0),       # sin ventas
    (100, 12, 6, None),   # sin promedio contra el cual comparar
    (100, 12, 6, 0),
])
def test_sin_alerta(vendidas, devueltas, casos, promedio):
    assert reglas.evaluar_alerta(vendidas, devueltas, casos, promedio) is None


def test_descartar_exige_comentario():
    assert reglas.validar_descartar({"comentario": "Fue un lote de prueba interna"})
    for malo in ({}, {"comentario": "corto"}, {"comentario": "x" * 501}, {"comentario": "ok ok ok ok", "x": 1}):
        falla(400, reglas.validar_descartar, malo)


# --------------------------------------------------------------------------- investigaciones
def test_investigacion_manual_valida():
    r = reglas.validar_investigacion({"dimension": "lote", "referencia_id": "7",
                                      "titulo": "Lote 52 tibio", "descripcion": "Varias devoluciones"})
    assert r["referencia_id"] == 7


@pytest.mark.parametrize("cambio", [
    {"dimension": "ruta"}, {"dimension": None}, {"referencia_id": 0}, {"referencia_id": True},
    {"titulo": "cort"}, {"titulo": "x" * 151}, {"descripcion": "corta"}, {"estado": "cerrada"},
])
def test_investigacion_invalida(cambio):
    base = {"dimension": "lote", "referencia_id": 7, "titulo": "Lote 52 tibio", "descripcion": "Varias devoluciones"}
    falla(400, reglas.validar_investigacion, {**base, **cambio})


def test_investigacion_desde_alerta_no_acepta_objeto():
    ok = {"titulo": "Investigar el lote", "descripcion": "Propuesta por la alerta"}
    assert reglas.validar_investigacion(ok, desde_alerta=True)
    falla(400, reglas.validar_investigacion, {**ok, "dimension": "lote"}, desde_alerta=True)


# --------------------------------------------------------------------------- hipotesis
def hip(**k):
    return {"tipo": "cinco_porques", "descripcion": "El camion llego con la caja caliente", **k}


def test_primer_porque_es_nivel_uno():
    r = reglas.validar_hipotesis(hip(), [])
    assert (r["nivel"], r["padre_id"]) == (1, None)


def test_porque_siguiente_calcula_su_nivel():
    existentes = [{"id": 10, "tipo": "cinco_porques", "nivel": 2, "padre_id": 9}]
    r = reglas.validar_hipotesis(hip(padre_id="10"), existentes)
    assert (r["nivel"], r["padre_id"]) == (3, 10)


def test_cadena_no_pasa_de_cinco_ni_se_ramifica():
    quinto = [{"id": 5, "tipo": "cinco_porques", "nivel": 5, "padre_id": 4}]
    assert falla(409, reglas.validar_hipotesis, hip(padre_id=5), quinto).tipo == "cadena_completa"
    con_hijo = [{"id": 1, "tipo": "cinco_porques", "nivel": 1, "padre_id": None},
                {"id": 2, "tipo": "cinco_porques", "nivel": 2, "padre_id": 1}]
    assert falla(409, reglas.validar_hipotesis, hip(padre_id=1), con_hijo).tipo == "porque_con_continuacion"


def test_porque_con_padre_de_otra_investigacion_o_otro_tipo():
    assert falla(409, reglas.validar_hipotesis, hip(padre_id=99), []).tipo == "padre_invalido"
    libre = [{"id": 3, "tipo": "libre", "nivel": None, "padre_id": None}]
    assert falla(409, reglas.validar_hipotesis, hip(padre_id=3), libre).tipo == "padre_invalido"


def test_ishikawa_exige_categoria_valida():
    d = {"tipo": "ishikawa", "descripcion": "El proveedor cambio de material de empaque"}
    assert reglas.validar_hipotesis({**d, "categoria_ishikawa": "material"}, [])["categoria_ishikawa"] == "material"
    falla(400, reglas.validar_hipotesis, d, [])
    falla(400, reglas.validar_hipotesis, {**d, "categoria_ishikawa": "clima"}, [])


@pytest.mark.parametrize("datos", [
    {"tipo": "libre", "descripcion": "Una idea suelta sobre el caso", "categoria_ishikawa": "material"},
    {"tipo": "libre", "descripcion": "Una idea suelta sobre el caso", "padre_id": 1},
    {"tipo": "ishikawa", "descripcion": "Rama de metodo", "categoria_ishikawa": "metodo", "padre_id": 1},
    {"tipo": "otro", "descripcion": "Un tipo que no existe"},
    {"tipo": "libre", "descripcion": "corta"},
    {"tipo": "libre", "descripcion": "Con campo extra permitido", "nivel": 3},
])
def test_hipotesis_invalida(datos):
    falla(400, reglas.validar_hipotesis, datos, [])


def test_verificacion_de_hipotesis():
    assert reglas.validar_verificacion({"resultado": "verificada",
                                        "resultado_verificacion": "El registro de temperatura lo confirma"})[0] == "verificada"
    for malo in ({"resultado": "quiza", "resultado_verificacion": "Texto suficiente aqui"},
                 {"resultado": "verificada"}, {"resultado": "verificada", "resultado_verificacion": "corto"}):
        falla(400, reglas.validar_verificacion, malo)


# --------------------------------------------------------------------------- evidencia
def test_evidencia_de_devolucion_exige_el_caso():
    ok = reglas.validar_evidencia({"tipo": "devolucion", "devolucion_id": "12", "descripcion": "Caso con producto tibio"})
    assert ok["devolucion_id"] == 12
    falla(400, reglas.validar_evidencia, {"tipo": "devolucion", "descripcion": "Caso con producto tibio"})
    falla(400, reglas.validar_evidencia, {"tipo": "inspeccion", "descripcion": "Inspeccion sin caso"})
    assert reglas.validar_evidencia({"tipo": "nota", "descripcion": "Llamada con el proveedor"})["devolucion_id"] is None


@pytest.mark.parametrize("cambio", [{"tipo": "video"}, {"descripcion": "x"}, {"devolucion_id": 0},
                                    {"hipotesis_id": "abc"}, {"referencia_externa": "x" * 256}, {"usuario": 1}])
def test_evidencia_invalida(cambio):
    falla(400, reglas.validar_evidencia, {"tipo": "nota", "descripcion": "Llamada con el proveedor", **cambio})


# --------------------------------------------------------------------------- conclusion
CONF = {"conclusion": "causa_confirmada", "causa_raiz": "Falla de refrigeracion del camion 4",
        "justificacion": "Los registros de temperatura lo demuestran"}


def test_confirmar_causa_exige_evidencia_e_hipotesis_verificada():
    assert reglas.validar_conclusion(CONF, 1, 1)[0] == "causa_confirmada"
    assert falla(409, reglas.validar_conclusion, CONF, 1, 0).tipo == "sin_evidencia"
    assert falla(409, reglas.validar_conclusion, CONF, 0, 3).tipo == "sin_hipotesis_verificada"


def test_confirmar_exige_causa_y_justificacion():
    falla(400, reglas.validar_conclusion, {k: v for k, v in CONF.items() if k != "causa_raiz"}, 1, 1)
    falla(400, reglas.validar_conclusion, {k: v for k, v in CONF.items() if k != "justificacion"}, 1, 1)


def test_inconclusa_no_exige_evidencia_pero_si_justificacion_y_no_declara_causa():
    ok = reglas.validar_conclusion({"conclusion": "inconclusa", "justificacion": "No hay datos suficientes"}, 0, 0)
    assert ok == ("inconclusa", None, "No hay datos suficientes")
    falla(400, reglas.validar_conclusion, {"conclusion": "inconclusa"}, 0, 0)
    falla(400, reglas.validar_conclusion, {"conclusion": "inconclusa", "causa_raiz": "Una causa cualquiera",
                                           "justificacion": "No hay datos suficientes"}, 0, 0)
    falla(400, reglas.validar_conclusion, {"conclusion": "tal vez", "justificacion": "Texto suficiente"}, 1, 1)


# --------------------------------------------------------------------------- estados
def test_flujo_feliz_de_estados():
    for a, b in [("abierta", "en_verificacion"), ("en_verificacion", "concluida"), ("concluida", "en_accion"),
                 ("en_accion", "en_medicion"), ("en_medicion", "cerrada")]:
        reglas.exigir_transicion(a, b)


@pytest.mark.parametrize("a,b", [
    ("abierta", "concluida"), ("abierta", "cerrada"), ("en_verificacion", "cerrada"),
    ("en_verificacion", "en_accion"), ("concluida", "en_medicion"), ("cerrada", "abierta"),
    ("cerrada", "cerrada"), ("en_medicion", "en_accion"), ("en_accion", "concluida"),
])
def test_saltarse_pasos_es_409(a, b):
    assert falla(409, reglas.exigir_transicion, a, b).tipo == "transicion_invalida"


def test_se_puede_medir_varias_veces_y_cerrar_inconclusa_desde_concluida():
    reglas.exigir_transicion("en_medicion", "en_medicion")
    reglas.exigir_transicion("concluida", "cerrada")
    reglas.exigir_transicion("concluida", "en_verificacion")


def test_cierre_valida_comentario():
    assert reglas.validar_cierre({"comentario": "Las acciones funcionaron"})
    falla(400, reglas.validar_cierre, {"comentario": "ok"})


# --------------------------------------------------------------------------- CAPA
CAPA = {"tipo": "correctiva", "descripcion": "Cambiar el contrato de transporte refrigerado",
        "responsable_id": 5, "fecha_compromiso": "2026-12-15"}


def test_capa_valida_con_meta_predeterminada():
    r = reglas.validar_capa(dict(CAPA), HOY)
    assert r["meta_reduccion_pct"] == Decimal("30") and r["fecha_compromiso"] == date(2026, 12, 15)


def test_capa_con_meta_propia_y_fecha_de_hoy():
    r = reglas.validar_capa({**CAPA, "meta_reduccion_pct": "45.5", "fecha_compromiso": "2026-11-21"}, HOY)
    assert r["meta_reduccion_pct"] == Decimal("45.50")


@pytest.mark.parametrize("cambio", [
    {"tipo": "otra"}, {"descripcion": "corta"}, {"responsable_id": 0}, {"responsable_id": None},
    {"fecha_compromiso": "2026-11-20"}, {"fecha_compromiso": "manana"}, {"fecha_compromiso": None},
    {"meta_reduccion_pct": "0"}, {"meta_reduccion_pct": "101"}, {"meta_reduccion_pct": "12.345"},
    {"meta_reduccion_pct": "NaN"}, {"estado": "implementada"},
])
def test_capa_invalida(cambio):
    falla(400, reglas.validar_capa, {**CAPA, **cambio}, HOY)


def test_estado_de_capa_flujo_normal():
    assert reglas.validar_estado_capa({"estado": "en_curso"}, "planificada", HOY) == ("en_curso", None, None)
    assert reglas.validar_estado_capa({"estado": "implementada"}, "en_curso", HOY)[1] == HOY
    assert reglas.validar_estado_capa({"estado": "implementada", "fecha_implementacion": "2026-10-01"},
                                      "en_curso", HOY)[1] == date(2026, 10, 1)


@pytest.mark.parametrize("actual,nuevo", [
    ("planificada", "implementada"), ("implementada", "en_curso"), ("implementada", "cancelada"),
    ("cancelada", "en_curso"), ("en_curso", "en_curso"),
])
def test_estado_de_capa_transicion_invalida(actual, nuevo):
    falla(409, reglas.validar_estado_capa, {"estado": nuevo, "comentario": "Motivo suficiente"}, actual, HOY)


def test_implementar_no_acepta_fechas_futuras_ni_muy_viejas_ni_fuera_de_lugar():
    for fecha in ("2026-11-22", "2025-11-20", "ayer"):
        falla(400, reglas.validar_estado_capa, {"estado": "implementada", "fecha_implementacion": fecha}, "en_curso", HOY)
    falla(400, reglas.validar_estado_capa, {"estado": "en_curso", "fecha_implementacion": "2026-11-01"}, "planificada", HOY)


def test_cancelar_exige_comentario():
    falla(400, reglas.validar_estado_capa, {"estado": "cancelada"}, "planificada", HOY)
    assert reglas.validar_estado_capa({"estado": "cancelada", "comentario": "Ya no aplica"},
                                      "planificada", HOY)[2] == "Ya no aplica"


# --------------------------------------------------------------------------- periodos de medicion
def test_periodos_cortan_despues_en_el_plazo_de_devolucion():
    impl = date(2026, 10, 1)
    p = reglas.periodos_medicion(impl, HOY, 30, 90)
    assert p["antes_hasta"] == date(2026, 9, 30) and p["antes_desde"] == date(2026, 7, 3)
    assert p["despues_desde"] == impl
    assert p["despues_hasta"] == date(2026, 10, 22)  # hoy menos 30 dias, no hoy
    assert not p["inmaduro"]


def test_ventas_recientes_no_cuentan_si_aun_pueden_devolverse():
    impl = HOY - timedelta(days=10)
    p = reglas.periodos_medicion(impl, HOY, 30, 90)
    assert p["inmaduro"] and p["despues_hasta"] == impl


def test_hasta_pedido_se_respeta_si_es_anterior_al_tope_y_se_recorta_si_no():
    impl = date(2026, 9, 1)
    assert reglas.periodos_medicion(impl, HOY, 30, 90, date(2026, 10, 10))["despues_hasta"] == date(2026, 10, 10)
    assert reglas.periodos_medicion(impl, HOY, 30, 90, HOY)["despues_hasta"] == date(2026, 10, 22)


def test_validar_medicion():
    assert reglas.validar_medicion({}, HOY) == (90, None)
    assert reglas.validar_medicion({"ventana_antes_dias": "30", "hasta": "2026-11-01"}, HOY) == (30, date(2026, 11, 1))
    for malo in ({"ventana_antes_dias": 6}, {"ventana_antes_dias": 366}, {"ventana_antes_dias": True},
                 {"hasta": "2026-11-22"}, {"hasta": "ayer"}, {"otro": 1}):
        falla(400, reglas.validar_medicion, malo, HOY)


# --------------------------------------------------------------------------- veredicto
def test_efectiva_si_la_reduccion_alcanza_la_meta():
    r = reglas.calcular_medicion(100, 20, 100, 10, 30)
    assert (r["antes_tasa_pct"], r["despues_tasa_pct"], r["reduccion_pct"], r["veredicto"]) == (20.0, 10.0, 50.0, "efectiva")


def test_justo_en_la_meta_cuenta_como_efectiva():
    assert reglas.calcular_medicion(100, 20, 100, 14, 30)["veredicto"] == "efectiva"


def test_no_efectiva_si_no_llega_a_la_meta_o_empeora():
    assert reglas.calcular_medicion(100, 20, 100, 15, 30)["veredicto"] == "no_efectiva"
    peor = reglas.calcular_medicion(100, 20, 100, 30, 30)
    assert peor["veredicto"] == "no_efectiva" and peor["reduccion_pct"] == -50.0


@pytest.mark.parametrize("args", [
    (19, 5, 100, 1),    # poca muestra antes
    (100, 20, 19, 0),   # poca muestra despues: 0 devoluciones con 19 ventas no prueba nada
    (100, 0, 100, 0),   # antes no hubo problema que reducir
])
def test_sin_datos_nunca_es_efectiva(args):
    r = reglas.calcular_medicion(*args, 30)
    assert r["veredicto"] == "sin_datos" and r["reduccion_pct"] is None and r["motivo_sin_datos"]


def test_inmaduro_es_sin_datos_aunque_parezca_perfecto():
    r = reglas.calcular_medicion(100, 20, 0, 0, 30, inmaduro=True, madurez_hasta=date(2026, 10, 22))
    assert r["veredicto"] == "sin_datos" and "2026-10-22" in r["motivo_sin_datos"]


def test_veredicto_global_no_esconde_lo_que_no_funciono():
    assert reglas.veredicto_global([]) == "sin_acciones"
    assert reglas.veredicto_global(["efectiva", "efectiva"]) == "efectiva"
    assert reglas.veredicto_global(["efectiva", "no_efectiva"]) == "no_efectiva"
    assert reglas.veredicto_global(["efectiva", "sin_datos"]) == "sin_datos"
    assert reglas.veredicto_global(["efectiva", None]) == "sin_datos"
    assert reglas.veredicto_global(["no_efectiva", "sin_datos"]) == "no_efectiva"
