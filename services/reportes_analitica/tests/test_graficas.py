"""Opciones de Highcharts. No necesitan base de datos (RF-26)."""
import json

import estadistica as e
import graficas as g


def test_pareto_tiene_columnas_y_linea_acumulada_en_segundo_eje():
    p = e.pareto([("a", 50, 5), ("b", 30, 3), ("c", 20, 2)])
    o = g.pareto_opciones("Pareto", p, "costo")
    assert o["xAxis"]["categories"] == ["a", "b", "c"]
    columna, linea = o["series"]
    assert columna["type"] == "column" and columna["data"] == [50.0, 30.0, 20.0]
    assert linea["type"] == "line" and linea["yAxis"] == 1 and linea["data"] == [50.0, 80.0, 100.0]
    assert o["yAxis"][1]["max"] == 100 and o["yAxis"][0]["title"]["text"] == "Costo ($)"


def test_tasas_omite_objetos_sin_tasa_y_limita():
    filas = [{"etiqueta": f"P{i}", "tasa_pct": float(i)} for i in range(20)] + [{"etiqueta": "sin", "tasa_pct": None}]
    o = g.tasas_opciones("T", filas, limite=5)
    assert len(o["series"][0]["data"]) == 5 and "sin" not in o["xAxis"]["categories"]


def puntos():
    return [{"mes": f"2026-0{m}", "valor": v} for m, v in zip(range(1, 8), [1.0, 3.0, 5.0, None, 9.0, 11.0, 13.0])]


def test_tendencia_alinea_historia_pronostico_y_huecos():
    pts = puntos()
    ajuste = e.ajustar([(i, p["valor"]) for i, p in enumerate(pts) if p["valor"] is not None])
    pron = e.pronosticar([(i, p["valor"]) for i, p in enumerate(pts) if p["valor"] is not None], 2, 6)["puntos"]
    o = g.tendencia_opciones("T", "tasa", pts, ajuste, pron, ["2026-08", "2026-09"])
    assert o["xAxis"]["categories"][-2:] == ["2026-08", "2026-09"] and len(o["xAxis"]["categories"]) == 9
    nombres = [s["name"] for s in o["series"]]
    assert nombres == ["Observado", "Tendencia", "Pronostico", "Limite inferior", "Limite superior"]
    assert all(len(s["data"]) == 9 for s in o["series"])           # todas alineadas con las categorias
    assert o["series"][0]["data"][3] is None                       # mes sin dato: hueco, no cero
    assert o["series"][2]["data"][6] == 13.0                       # el pronostico arranca del ultimo dato real
    assert o["series"][2]["data"][7:] == [p["valor"] for p in pron]
    json.dumps(o)                                                  # serializable tal cual


def test_tendencia_sin_pronostico_ni_ajuste_solo_dibuja_lo_observado():
    o = g.tendencia_opciones("T", "devoluciones", puntos()[:3], None, [], [])
    assert [s["name"] for s in o["series"]] == ["Observado"]
