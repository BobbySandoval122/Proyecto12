"""Reglas puras de lotes, series y tasas. No necesitan base de datos.

Trazabilidad: RF-23, RF-24, RN-09, RNF-11.
"""
import pytest

import reglas
from shared.respuestas import ErrorApi


def test_tasa_es_porcentaje_de_lo_vendido():
    assert reglas.tasa(18, 96) == 18.75


def test_tasa_sin_ventas_es_none_no_cero():
    assert reglas.tasa(0, 0) is None
    assert reglas.tasa(3, None) is None


def test_series_validas_se_limpian():
    assert reglas.validar_series({"series": [" A-001 ", "A.002"]}) == ["A-001", "A.002"]


@pytest.mark.parametrize("datos", [
    {}, {"series": "A-001"}, {"series": []},
    {"series": ["con espacio"]}, {"series": ["x" * 61]}, {"series": [123]},
    {"series": ["A-1", "A-1"]},
    {"series": ["'; DROP TABLE lotes;--"]},
    {"series": [f"S{i}" for i in range(reglas.MAX_SERIES + 1)]},
])
def test_series_invalidas(datos):
    with pytest.raises(ErrorApi) as err:
        reglas.validar_series(datos)
    assert err.value.codigo == 400


@pytest.mark.parametrize("valor", ["proveedor", "tienda", "producto", "lote", "ruta"])
def test_dimensiones_validas(valor):
    assert reglas.validar_dimension(valor) == valor


@pytest.mark.parametrize("valor", ["", "usuario", "1; DROP TABLE x", "PROVEEDOR"])
def test_dimension_invalida(valor):
    with pytest.raises(ErrorApi):
        reglas.validar_dimension(valor)


def test_dimensiones_sql_coinciden_con_las_permitidas():
    """Toda dimension validada, salvo ruta, tiene su SQL en la lista blanca."""
    from trazabilidad import DIMENSIONES_VENTA
    assert set(DIMENSIONES_VENTA) | {"ruta"} == set(reglas.DIMENSIONES_TASA)
