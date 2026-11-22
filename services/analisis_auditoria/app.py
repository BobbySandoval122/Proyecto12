"""Auditoria (bitacora y traza de eventos). Este servicio queda solo con eso.

El analisis (clasificar, Pareto, alertas de fraude) se separo para que cambiarlo
nunca toque la auditoria: vive en analisis.py, marcado obsoleto, y su sucesor son
clasificacion-motivos (8010) y reportes-analitica (8018). Sigue disponible,
igual que antes, hasta que los clientes migren; con ANALISIS_HABILITADO=false
responde 410 y el servicio queda como solo auditoria.

Trazabilidad: RF-30, RN-12, RNF-23. Guia de migracion: docs/MIGRACION_ANALISIS_8008.md.
"""
import os

from flask import Flask

import analisis
import auditoria
from shared import docs, mongo, respuestas
from shared.infra import cerrar_conexion, salud_postgres, salud_redis
from shared.respuestas import responder

# Reexportados para que los usuarios del modulo anterior (y sus pruebas) sigan funcionando.
from analisis import calcular_pareto, clasificar_descripcion  # noqa: F401

NOMBRE = "analisis-auditoria"


def create_app():
    app = Flask(__name__)
    app.json.sort_keys = False
    respuestas.registrar(app, NOMBRE)
    app.teardown_appcontext(cerrar_conexion)
    app.register_blueprint(auditoria.bp)
    app.register_blueprint(analisis.bp)
    docs.registrar(app, os.path.join(os.path.dirname(__file__), "openapi.yaml"))

    @app.get("/health")
    def health():
        deps = {"postgresql": salud_postgres(), "redis": salud_redis(),
                "mongodb": mongo.salud_mongo()}
        ok = all(x["ok"] for x in deps.values())
        return responder({"servicio": NOMBRE, "version": "v1", "estado": "ok" if ok else "degradado",
                          "dependencias": deps,
                          "analisis": "obsoleto" if analisis.habilitado() else "retirado"},
                         200 if ok else 503)
    return app
