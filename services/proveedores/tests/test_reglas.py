"""Reglas puras de proveedores y reclamaciones. No necesitan base de datos.

Trazabilidad: RF-24, RF-26, RN-09, RN-12.
"""
from datetime import date
from decimal import Decimal

import pytest

import reglas
from shared.respuestas import ErrorApi

HOY = date(2026, 11, 21)


def test_tasa_sin_ventas_es_none_no_cero():
    assert reglas.tasa(18, 96) == 18.75
    assert reglas.tasa(0, 0) is None


@pytest.mark.parametrize("tasa,promedio,vendidas,esperado", [
    (10.0, 5.0, 100, "critico"),      # exactamente el doble
    (7.0, 5.0, 100, "atencion"),      # 1.4 veces
    (5.5, 5.0, 100, "normal"),
    (1.0, 5.0, 100, "normal"),
    (50.0, 5.0, 19, "sin_datos"),     # muestra insuficiente aunque la tasa sea enorme
    (None, 5.0, 100, "sin_datos"),
    (10.0, None, 100, "sin_datos"),
    (10.0, 0, 100, "sin_datos"),
])
def test_semaforo(tasa, promedio, vendidas, esperado):
    assert reglas.semaforo(tasa, promedio, vendidas) == esperado


def test_semaforo_justo_en_la_muestra_minima():
    assert reglas.semaforo(10.0, 5.0, reglas.MIN_UNIDADES) == "critico"


@pytest.mark.parametrize("valor,esperado", [
    ("1250.50", Decimal("1250.50")), (100, Decimal("100.00")), ("0", Decimal("0.00")),
    (None, None), ("", None),
])
def test_monto_valido(valor, esperado):
    assert reglas.monto(valor, "monto") == esperado


@pytest.mark.parametrize("valor", ["-1", "1.234", "abc", "NaN", "Infinity", True, "10000000.01", "1e3x"])
def test_monto_invalido(valor):
    with pytest.raises(ErrorApi) as err:
        reglas.monto(valor, "monto")
    assert err.value.codigo == 400


def test_monto_requerido():
    with pytest.raises(ErrorApi):
        reglas.monto(None, "monto", requerido=True)


BASE = {"proveedor_id": 1, "asunto": "Leche tibia en lote 52", "descripcion": "Varias devoluciones del mismo lote",
        "lote_id": 5}


def test_reclamacion_valida_con_lote():
    r = reglas.validar_reclamacion(dict(BASE), HOY)
    assert r["lote_id"] == 5 and r["devolucion_ids"] == [] and r["monto_reclamado"] is None


def test_reclamacion_con_devoluciones_deduplica_y_ordena():
    r = reglas.validar_reclamacion({**BASE, "lote_id": None, "devolucion_ids": ["9", 3, 9],
                                    "monto_reclamado": "4800.00",
                                    "fecha_limite_respuesta": "2026-12-01"}, HOY)
    assert r["devolucion_ids"] == [3, 9]
    assert r["monto_reclamado"] == Decimal("4800.00")
    assert r["fecha_limite_respuesta"] == date(2026, 12, 1)


def test_reclamacion_acepta_hoy_como_fecha_limite():
    assert reglas.validar_reclamacion({**BASE, "fecha_limite_respuesta": "2026-11-21"}, HOY)


@pytest.mark.parametrize("cambio", [
    {"proveedor_id": None}, {"proveedor_id": 0}, {"proveedor_id": True},
    {"asunto": "cort"}, {"asunto": "x" * 151}, {"descripcion": "corta"},
    {"lote_id": "abc"}, {"devolucion_ids": "uno"}, {"devolucion_ids": [0]},
    {"devolucion_ids": list(range(1, 102))}, {"monto_reclamado": "-5"},
    {"fecha_limite_respuesta": "2026-11-20"}, {"fecha_limite_respuesta": "2026-02-30"},
    {"creada_por": 1}, {"estado": "cerrada"},
])
def test_reclamacion_invalida(cambio):
    with pytest.raises(ErrorApi) as err:
        reglas.validar_reclamacion({**BASE, **cambio}, HOY)
    assert err.value.codigo == 400


def test_reclamacion_sin_lote_ni_devoluciones_se_rechaza():
    with pytest.raises(ErrorApi):
        reglas.validar_reclamacion({k: v for k, v in BASE.items() if k != "lote_id"}, HOY)
    # Lista vacia llegada de XML tampoco cuenta.
    with pytest.raises(ErrorApi):
        reglas.validar_reclamacion({**{k: v for k, v in BASE.items() if k != "lote_id"},
                                    "devolucion_ids": ""}, HOY)


def rec(estado, reclamado="1000.00"):
    return {"estado": estado, "monto_reclamado": Decimal(reclamado) if reclamado else None}


def test_flujo_normal_hasta_aceptada():
    assert reglas.validar_seguimiento({"estado": "enviada"}, rec("abierta"))[0] == "enviada"
    assert reglas.validar_seguimiento({"estado": "respondida", "comentario": "Respondio por correo"},
                                      rec("enviada"))[0] == "respondida"
    assert reglas.validar_seguimiento(
        {"estado": "cerrada", "resolucion": "aceptada", "monto_recuperado": "800",
         "comentario": "Nota de credito"}, rec("respondida")
    ) == ("cerrada", "Nota de credito", "aceptada", Decimal("800.00"))


@pytest.mark.parametrize("actual,nuevo", [
    ("abierta", "respondida"), ("abierta", "en_analisis"), ("enviada", "abierta"),
    ("cerrada", "enviada"), ("cerrada", "cerrada"), ("respondida", "enviada"),
])
def test_transiciones_invalidas_409(actual, nuevo):
    with pytest.raises(ErrorApi) as err:
        reglas.validar_seguimiento({"estado": nuevo, "comentario": "x" * 10}, rec(actual))
    assert err.value.codigo == 409


def test_reabrir_el_analisis_tras_una_respuesta():
    assert reglas.validar_seguimiento({"estado": "en_analisis"}, rec("respondida"))[0] == "en_analisis"


def test_cerrar_exige_comentario_y_resolucion():
    base = {"estado": "cerrada", "comentario": "Sin respuesta del proveedor"}
    with pytest.raises(ErrorApi):
        reglas.validar_seguimiento({"estado": "cerrada", "resolucion": "retirada"}, rec("enviada"))
    with pytest.raises(ErrorApi):
        reglas.validar_seguimiento(base, rec("enviada"))
    with pytest.raises(ErrorApi):
        reglas.validar_seguimiento({**base, "resolucion": "ganada"}, rec("enviada"))


def test_no_se_acepta_ni_rechaza_lo_que_no_respondieron():
    for resolucion in ("aceptada", "parcial", "rechazada"):
        with pytest.raises(ErrorApi) as err:
            reglas.validar_seguimiento({"estado": "cerrada", "resolucion": resolucion,
                                        "monto_recuperado": "10", "comentario": "Intento"}, rec("enviada"))
        assert err.value.codigo == 409
    # Retirarla si se puede en cualquier estado abierto, y no recupera nada.
    assert reglas.validar_seguimiento({"estado": "cerrada", "resolucion": "retirada",
                                       "comentario": "Ya no procede"}, rec("abierta"))[3] == Decimal("0.00")


def test_rechazada_y_retirada_no_llevan_monto():
    for resolucion in ("rechazada", "retirada"):
        with pytest.raises(ErrorApi):
            reglas.validar_seguimiento({"estado": "cerrada", "resolucion": resolucion,
                                        "monto_recuperado": "5", "comentario": "Con monto"}, rec("respondida"))


def test_no_se_recupera_mas_de_lo_reclamado():
    with pytest.raises(ErrorApi) as err:
        reglas.validar_seguimiento({"estado": "cerrada", "resolucion": "aceptada",
                                    "monto_recuperado": "1000.01", "comentario": "Demasiado"}, rec("respondida"))
    assert err.value.codigo == 409
    # Sin monto reclamado registrado no hay tope que comparar.
    assert reglas.validar_seguimiento({"estado": "cerrada", "resolucion": "aceptada",
                                       "monto_recuperado": "5000", "comentario": "Sin tope"},
                                      rec("respondida", None))[3] == Decimal("5000.00")


def test_aceptada_y_parcial_exigen_monto_y_parcial_no_puede_ser_cero():
    for resolucion in ("aceptada", "parcial"):
        with pytest.raises(ErrorApi):
            reglas.validar_seguimiento({"estado": "cerrada", "resolucion": resolucion,
                                        "comentario": "Sin monto"}, rec("respondida"))
    with pytest.raises(ErrorApi):
        reglas.validar_seguimiento({"estado": "cerrada", "resolucion": "parcial",
                                    "monto_recuperado": "0", "comentario": "Cero"}, rec("respondida"))


def test_resolucion_y_monto_solo_al_cerrar():
    with pytest.raises(ErrorApi):
        reglas.validar_seguimiento({"estado": "enviada", "resolucion": "aceptada"}, rec("abierta"))
    with pytest.raises(ErrorApi):
        reglas.validar_seguimiento({"estado": "enviada", "monto_recuperado": "5"}, rec("abierta"))


def test_seguimiento_rechaza_campos_extra_y_estado_invalido():
    for malo in ({"estado": "enviada", "usuario_id": 1}, {"estado": "ganada"}, {}):
        with pytest.raises(ErrorApi):
            reglas.validar_seguimiento(malo, rec("abierta"))
