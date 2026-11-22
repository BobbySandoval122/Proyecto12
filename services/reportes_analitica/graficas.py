"""Opciones de Highcharts listas para pintar (sin base de datos).

La web ya carga Highcharts por CDN (seccion 5.2 del documento); estas funciones
devuelven el objeto `options` completo para que cualquier cliente haga
`Highcharts.chart(contenedor, opciones)` sin armar series por su cuenta.
Los puntos sin dato van como null: Highcharts deja el hueco en lugar de dibujar
un cero que no existe.

Trazabilidad: RF-26, RF-28.
"""

UNIDADES = {"tasa": "Tasa de devolucion (%)", "devoluciones": "Devoluciones", "costo": "Costo ($)"}


def pareto_opciones(titulo, pareto, medida):
    cats = pareto["categorias"]
    return {
        "chart": {"zoomType": "xy"}, "title": {"text": titulo}, "credits": {"enabled": False},
        "xAxis": {"categories": [c["etiqueta"] for c in cats], "crosshair": True},
        "yAxis": [{"title": {"text": {"frecuencia": "Devoluciones", "cantidad": "Unidades", "costo": "Costo ($)"}[medida]}},
                  {"title": {"text": "% acumulado"}, "min": 0, "max": 100, "opposite": True}],
        "tooltip": {"shared": True},
        "series": [{"type": "column", "name": "Total", "data": [c["total"] for c in cats]},
                   {"type": "line", "name": "% acumulado", "yAxis": 1,
                    "data": [c["porcentaje_acumulado"] for c in cats], "tooltip": {"valueSuffix": " %"}}],
    }


def tasas_opciones(titulo, filas, limite=15):
    top = [f for f in filas if f["tasa_pct"] is not None][:limite]
    return {
        "chart": {"type": "bar"}, "title": {"text": titulo}, "credits": {"enabled": False},
        "xAxis": {"categories": [f["etiqueta"] for f in top]},
        "yAxis": {"min": 0, "title": {"text": "Tasa de devolucion (%)"}},
        "tooltip": {"valueSuffix": " %"}, "legend": {"enabled": False},
        "series": [{"name": "Tasa", "data": [f["tasa_pct"] for f in top]}],
    }


def tendencia_opciones(titulo, medida, puntos, ajuste, pronostico, meses_futuros):
    """puntos: serie mensual; ajuste: dict de estadistica.ajustar o None; pronostico: puntos del pronostico."""
    historia = [p["mes"] for p in puntos]
    categorias = historia + meses_futuros[:len(pronostico)]
    n, m = len(historia), len(pronostico)
    observado = [p["valor"] for p in puntos] + [None] * m
    series = [{"name": "Observado", "data": observado, "zIndex": 3}]
    if ajuste:
        series.append({"name": "Tendencia", "dashStyle": "ShortDash", "marker": {"enabled": False},
                       "data": [round(ajuste["intercepto"] + ajuste["pendiente"] * i, 2) for i in range(n)] + [None] * m})
    if pronostico:
        ultimo = next((p["valor"] for p in reversed(puntos) if p["valor"] is not None), None)
        enlace = [None] * (n - 1) + [ultimo] if ultimo is not None else [None] * n
        series.append({"name": "Pronostico", "dashStyle": "Dot", "data": enlace + [p["valor"] for p in pronostico]})
        for nombre, clave in (("Limite inferior", "limite_inferior"), ("Limite superior", "limite_superior")):
            series.append({"name": nombre, "dashStyle": "Dash", "marker": {"enabled": False}, "color": "#999999",
                           "data": [None] * n + [p[clave] for p in pronostico]})
    return {"chart": {"type": "line"}, "title": {"text": titulo}, "credits": {"enabled": False},
            "xAxis": {"categories": categorias}, "yAxis": {"min": 0, "title": {"text": UNIDADES[medida]}},
            "tooltip": {"shared": True}, "series": series}
