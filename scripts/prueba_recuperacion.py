"""Prueba de recuperacion: se tumban servicios a proposito y se comprueba que
lo confirmado sigue ahi y que reintentar no duplica nada.

Pruebas de la retroalimentacion que cubre:
- "Se reinicia un microservicio y se recuperan las operaciones confirmadas."
- Monolitico vs distribuido: "si una API se cae, no se duplica nada".

Escenarios:
1. Se mata el servicio de devoluciones (kill, sin apagado ordenado) despues de
   confirmar una solicitud. Al volver, la solicitud existe y el reintento del
   cliente responde 409 solicitud_duplicada: sigue habiendo una sola.
2. Se mata el servicio de sincronizacion. La app reenvia la misma operacion
   offline: responde repetida y la evidencia sigue siendo una.
3. Se detiene PostgreSQL. Los servicios responden 503 (no aceptan nada a
   medias), el monitoreo abre la alerta base_no_disponible; al volver, los datos
   confirmados siguen ahi y la alerta se resuelve sola.
4. Se reinicia Redis. La sesion del usuario sobrevive (Redis con appendonly).

Se corre EN LA VM, desde la raiz del repositorio, con el entorno levantado y
seed_demo.py del mismo dia (solo usa la biblioteca estandar de Python):

    python3 scripts/prueba_recuperacion.py

Guarda la salida en docs/pruebas/recuperacion_<fecha>.txt y borra lo que crea.
Trazabilidad: RNF-28, RNF-21, RNF-22, RN-16, dominio 20.
"""
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
PUERTOS = {"auth": 8001, "devoluciones": 8002, "sincronizacion": 8020, "integraciones-monitoreo": 8021}
FECHA = datetime.now(timezone.utc).strftime("%Y-%m-%d")
SALIDA = RAIZ / "docs" / "pruebas" / f"recuperacion_{FECHA}.txt"
lineas_salida, fallos = [], []


def decir(texto=""):
    print(texto, flush=True)
    lineas_salida.append(texto)


def comprobar(condicion, descripcion, detalle=""):
    marca = "OK   " if condicion else "FALLA"
    decir(f"  [{marca}] {descripcion}" + (f"  ({detalle})" if detalle else ""))
    if not condicion:
        fallos.append(descripcion)
    return condicion


# --------------------------------------------------------------------------- #
# Utilidades
# --------------------------------------------------------------------------- #
def leer_env():
    valores = {}
    for linea in (RAIZ / ".env").read_text().splitlines():
        if "=" in linea and not linea.lstrip().startswith("#"):
            clave, valor = linea.split("=", 1)
            if valor.strip():  # el ultimo valor no vacio gana
                valores[clave.strip()] = valor.strip()
    return valores


def compose(*args):
    return subprocess.run(["docker", "compose", *args], cwd=RAIZ, capture_output=True, text=True)


def sql(consulta, *params):
    """psql dentro del contenedor; los valores van como variables de psql
    (:'p1', :'p2'...), nunca pegados a la consulta."""
    args = ["exec", "-T", "postgres", "psql", "-v", "ON_ERROR_STOP=1", "-qtA",
            "-U", ENV.get("POSTGRES_USER", "devoluciones_app"), "-d", ENV.get("POSTGRES_DB", "devoluciones")]
    for i, p in enumerate(params, 1):
        args += ["-v", f"p{i}={p}"]
    r = subprocess.run(["docker", "compose", *args], cwd=RAIZ, input=consulta, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip())
    return r.stdout.strip()


def http(servicio, metodo, ruta, cuerpo=None, token=None, timeout=10):
    """(codigo, cuerpo) o (None, motivo) si no hubo respuesta."""
    cabeceras = {"Content-Type": "application/json", "Accept": "application/json"}
    if token:
        cabeceras["Authorization"] = f"Bearer {token}"
    peticion = urllib.request.Request(f"http://localhost:{PUERTOS[servicio]}{ruta}", method=metodo,
                                      headers=cabeceras,
                                      data=json.dumps(cuerpo).encode() if cuerpo is not None else None)
    try:
        with urllib.request.urlopen(peticion, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read() or b"null")
    except urllib.error.HTTPError as exc:
        try:
            return exc.code, json.loads(exc.read())
        except ValueError:
            return exc.code, None
    except Exception as exc:  # noqa: BLE001 - servicio caido
        return None, type(exc).__name__


def esperar(condicion, segundos=90):
    limite = time.time() + segundos
    while time.time() < limite:
        if condicion():
            return True
        time.sleep(2)
    return False


def sano(servicio):
    return http(servicio, "GET", "/health", timeout=3)[0] == 200


def login(email):
    codigo, cuerpo = http("auth", "POST", "/api/v1/auth/login", {"email": email, "password": ENV["PASSWORD_DEMO"]})
    if codigo != 200:
        raise SystemExit(f"No se pudo iniciar sesion con {email} ({codigo}). Corre seed_demo.py.")
    return cuerpo["access_token"]


def liberar_limite_login():
    claves = compose("exec", "-T", "redis", "redis-cli", "--scan", "--pattern", "devoluciones:limite:*").stdout.split()
    for clave in claves:
        compose("exec", "-T", "redis", "redis-cli", "DEL", clave)


# --------------------------------------------------------------------------- #
# Escenarios
# --------------------------------------------------------------------------- #
creadas = {"devoluciones": [], "operaciones": []}


def escenario_devoluciones():
    decir("\n1. Se mata el servicio de devoluciones despues de confirmar una solicitud")
    fila = sql("""
        SELECT vd.id || '|' || u.email FROM venta_detalle vd
          JOIN ventas v ON v.id = vd.venta_id JOIN usuarios u ON u.id = v.cliente_id
          JOIN lotes l ON l.id = vd.lote_id JOIN productos p ON p.id = l.producto_id
          JOIN politicas_devolucion pol ON pol.clasificacion_temperatura = p.clasificacion_temperatura
         WHERE v.eliminado_en IS NULL AND RIGHT(u.email, 8) = '@demo.mx'
           AND v.fecha_venta + pol.dias_plazo >= CURRENT_DATE
           AND NOT EXISTS (SELECT 1 FROM devoluciones d WHERE d.venta_detalle_id = vd.id AND d.eliminado_en IS NULL)
         ORDER BY vd.id DESC LIMIT 1""")
    if not fila:
        raise SystemExit("No hay una linea libre dentro del plazo. Corre seed_demo.py hoy.")
    linea, email = fila.split("|")
    motivo = int(sql("SELECT id FROM motivos WHERE activo ORDER BY id LIMIT 1"))
    token = login(email)
    solicitud = {"venta_detalle_id": int(linea), "motivo_id": motivo, "cantidad_devuelta": 1,
                 "descripcion_problema": "Prueba de recuperacion: el servicio se cae despues de confirmar."}
    codigo, cuerpo = http("devoluciones", "POST", "/api/v1/devoluciones", solicitud, token)
    if not comprobar(codigo == 201, "La solicitud se confirma (201)", f"respondio {codigo}"):
        return None, token
    dev_id = cuerpo["id"]
    creadas["devoluciones"].append(dev_id)
    decir(f"     folio {cuerpo.get('folio_devolucion')}, id {dev_id}")

    compose("kill", "devoluciones")
    codigo, motivo_falla = http("devoluciones", "POST", "/api/v1/devoluciones", solicitud, token, timeout=5)
    comprobar(codigo is None, "Con el servicio muerto, el reintento del cliente no recibe respuesta", str(motivo_falla))

    compose("start", "devoluciones")
    comprobar(esperar(lambda: sano("devoluciones")), "El servicio vuelve y su /health responde 200")
    codigo, cuerpo = http("devoluciones", "GET", f"/api/v1/devoluciones/{dev_id}", token=token)
    comprobar(codigo == 200, "La solicitud confirmada sigue ahi", f"estado {cuerpo.get('estado') if codigo == 200 else codigo}")
    codigo, cuerpo = http("devoluciones", "POST", "/api/v1/devoluciones", solicitud, token)
    tipo = ((cuerpo or {}).get("error") or {}).get("tipo")
    comprobar(codigo == 409 and tipo == "solicitud_duplicada",
              "El cliente reintenta al volver: 409 solicitud_duplicada", f"{codigo} {tipo}")
    total = int(sql("""SELECT count(*) FROM devoluciones WHERE venta_detalle_id = :'p1' AND motivo_id = :'p2'
                        AND eliminado_en IS NULL""", linea, solicitud["motivo_id"]))
    comprobar(total == 1, "En PostgreSQL hay exactamente una solicitud", f"{total}")
    return dev_id, token


def escenario_sincronizacion():
    decir("\n2. Se mata el servicio de sincronizacion y la app reenvia la misma operacion")
    email = "luis.recolector@demo.mx"
    tienda = sql("SELECT tienda_id FROM usuarios WHERE email = :'p1'", email)
    if not tienda:
        comprobar(False, "luis.recolector tiene sucursal (corre seed_demo.py)")
        return
    linea = sql("""SELECT vd.id FROM venta_detalle vd JOIN ventas v ON v.id = vd.venta_id
                    WHERE v.tienda_id = :'p1' AND v.eliminado_en IS NULL ORDER BY vd.id LIMIT 1""", tienda)
    motivo = sql("SELECT id FROM motivos WHERE activo ORDER BY id LIMIT 1")
    dev = sql("""INSERT INTO devoluciones (venta_detalle_id, motivo_id, descripcion_problema, cantidad_devuelta, estado)
                 VALUES (:'p1', :'p2', 'Prueba de recuperacion de sincronizacion.', 1, 'en_recoleccion')
                 RETURNING id""", linea, motivo).splitlines()[0]
    creadas["devoluciones"].append(int(dev))
    sql("""INSERT INTO recolecciones (devolucion_id, fecha_programada, lugar, estado)
           VALUES (:'p1', CURRENT_DATE, 'Prueba de recuperacion', 'asignada')""", dev)
    token = login(email)
    operacion = {"id_operacion": str(uuid.uuid4()), "tipo": "evidencia",
                 "capturado_en": datetime.now(timezone.utc).isoformat(),
                 "datos": {"devolucion_id": int(dev), "comentario": "Capturado sin red antes de la caida."}}
    creadas["operaciones"].append(operacion["id_operacion"])
    lote = {"dispositivo_id": "android-recuperacion", "operaciones": [operacion]}
    codigo, cuerpo = http("sincronizacion", "POST", "/api/v1/sincronizacion/operaciones", lote, token)
    estado = cuerpo["resultados"][0]["estado"] if codigo == 200 else codigo
    comprobar(estado == "aceptada", "La operacion offline se acepta", str(estado))

    compose("kill", "sincronizacion")
    compose("start", "sincronizacion")
    comprobar(esperar(lambda: sano("sincronizacion")), "El servicio vuelve y su /health responde 200")
    codigo, cuerpo = http("sincronizacion", "POST", "/api/v1/sincronizacion/operaciones", lote, token)
    r = cuerpo["resultados"][0] if codigo == 200 else {}
    comprobar(r.get("estado") == "aceptada" and r.get("repetida") is True,
              "La app reenvia la misma operacion: repetida, no se aplica otra vez",
              f"{r.get('estado')}, repetida={r.get('repetida')}")
    total = int(sql("SELECT count(*) FROM evidencias WHERE devolucion_id = :'p1'", dev))
    envios = sql("SELECT envios FROM operaciones_offline WHERE id_operacion = :'p1'", operacion["id_operacion"])
    comprobar(total == 1 and envios == "2", "Una sola evidencia en PostgreSQL; la operacion registra 2 envios",
              f"evidencias={total}, envios={envios}")


def alerta_base_activa(token):
    codigo, cuerpo = http("integraciones-monitoreo", "GET", "/api/v1/monitoreo/alertas?estado=activa&por_pagina=100",
                          token=token)
    return codigo == 200 and any(a["tipo"] == "base_no_disponible" and a["recurso"] == "postgresql"
                                 for a in cuerpo["datos"])


def escenario_postgres(dev_id, token_cliente):
    decir("\n3. Se detiene PostgreSQL")
    admin = login("pablo.admin@demo.mx")
    compose("stop", "postgres")
    codigo, cuerpo = http("devoluciones", "GET", "/health")
    comprobar(codigo == 503, "devoluciones /health responde 503 (degradado), no 200", str(codigo))
    codigo, _ = http("devoluciones", "GET", f"/api/v1/devoluciones/{dev_id}", token=token_cliente)
    comprobar(codigo is not None and codigo >= 500, "Una consulta responde error controlado, no datos a medias",
              str(codigo))
    codigo, cuerpo = http("integraciones-monitoreo", "GET", "/api/v1/monitoreo/estado", token=admin, timeout=30)
    comprobar(codigo == 200 and not cuerpo["bases"]["postgresql"]["ok"],
              "El monitoreo detecta PostgreSQL caido", str(codigo))
    comprobar(alerta_base_activa(admin), "Se abre la alerta base_no_disponible")

    compose("start", "postgres")
    listo = esperar(lambda: compose("exec", "-T", "postgres", "pg_isready").returncode == 0)
    comprobar(listo and esperar(lambda: sano("devoluciones")), "PostgreSQL vuelve y devoluciones responde 200")
    codigo, cuerpo = http("devoluciones", "GET", f"/api/v1/devoluciones/{dev_id}", token=token_cliente)
    comprobar(codigo == 200, "La solicitud confirmada antes de la caida sigue ahi", str(codigo))
    http("integraciones-monitoreo", "GET", "/api/v1/monitoreo/estado", token=admin, timeout=30)
    comprobar(not alerta_base_activa(admin), "La alerta se resuelve sola")
    return admin


def escenario_redis(dev_id, token_cliente):
    decir("\n4. Se reinicia Redis")
    compose("restart", "redis")
    esperar(lambda: compose("exec", "-T", "redis", "redis-cli", "ping").stdout.strip() == "PONG")
    codigo, _ = http("devoluciones", "GET", f"/api/v1/devoluciones/{dev_id}", token=token_cliente)
    comprobar(codigo == 200, "La sesion del usuario sobrevive al reinicio (appendonly)", str(codigo))


def limpiar():
    ids = ",".join(str(i) for i in creadas["devoluciones"])
    if creadas["operaciones"]:
        sql("DELETE FROM operaciones_offline WHERE id_operacion::text = ANY(string_to_array(:'p1', ','))",
            ",".join(creadas["operaciones"]))
    if ids:
        for tabla in ("notificaciones", "evidencias", "recolecciones"):
            sql(f"DELETE FROM {tabla} WHERE devolucion_id = ANY(string_to_array(:'p1', ',')::int[])", ids)
        sql("DELETE FROM devoluciones WHERE id = ANY(string_to_array(:'p1', ',')::int[])", ids)
    decir("\nLimpieza: se borraron las filas creadas por la prueba.")


ENV = leer_env()

if __name__ == "__main__":
    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=RAIZ, capture_output=True, text=True).stdout.strip()
    decir(f"Prueba de recuperacion - {datetime.now(timezone.utc):%Y-%m-%d %H:%M:%S} UTC - commit {commit}")
    liberar_limite_login()
    try:
        dev_id, token = escenario_devoluciones()
        escenario_sincronizacion()
        if dev_id:
            escenario_postgres(dev_id, token)
            escenario_redis(dev_id, token)
    finally:
        # Si algo fallo a la mitad, deja todo arriba otra vez.
        compose("start", "postgres", "redis", "devoluciones", "sincronizacion")
        esperar(lambda: compose("exec", "-T", "postgres", "pg_isready").returncode == 0)
        limpiar()
    decir(f"\nResultado: {'TODO OK' if not fallos else f'{len(fallos)} comprobacion(es) fallaron'}")
    SALIDA.write_text("\n".join(lineas_salida) + "\n")
    print(f"Salida guardada en {SALIDA.relative_to(RAIZ)}")
    sys.exit(1 if fallos else 0)
