"""Reglas puras de lotes y trazabilidad (sin base de datos, probables en cualquier maquina).

Trazabilidad: RF-23, RF-24, RN-09, RN-10.
"""
import re

from shared.respuestas import ErrorApi

MAX_SERIES = 500
PATRON_SERIE = re.compile(r"^[A-Za-z0-9._-]{1,60}$")
DIMENSIONES_TASA = ("proveedor", "tienda", "producto", "lote", "ruta")


def tasa(devueltas, vendidas):
    """Porcentaje de lo vendido que regreso. None si no hay denominador.

    None y no 0: un lote sin ventas no tiene tasa baja, no tiene tasa.
    """
    vendidas = float(vendidas or 0)
    if vendidas <= 0:
        return None
    return round(float(devueltas or 0) * 100.0 / vendidas, 2)


def validar_series(datos):
    """Lista de series a dar de alta en un lote; sin duplicados y con formato fijo."""
    if not isinstance(datos, dict) or not isinstance(datos.get("series"), list):
        raise ErrorApi(400, "validacion", "Se requiere series como lista.")
    series = datos["series"]
    if not 1 <= len(series) <= MAX_SERIES:
        raise ErrorApi(400, "validacion", f"Envia entre 1 y {MAX_SERIES} series.")
    limpias, errores = [], []
    for i, valor in enumerate(series):
        if not isinstance(valor, str) or not PATRON_SERIE.match(valor.strip()):
            errores.append({"campo": f"series[{i}]",
                            "problema": "1 a 60 caracteres: letras, numeros, punto, guion"})
        else:
            limpias.append(valor.strip())
    if errores:
        raise ErrorApi(400, "validacion", "Series invalidas.", errores[:20])
    if len(set(limpias)) != len(limpias):
        raise ErrorApi(400, "validacion", "La lista trae series repetidas.")
    return limpias


def validar_dimension(valor):
    if valor not in DIMENSIONES_TASA:
        raise ErrorApi(400, "validacion",
                       "por debe ser una de: " + ", ".join(DIMENSIONES_TASA) + ".")
    return valor
