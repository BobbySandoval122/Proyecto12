# Evidencia con curl - `analisis-auditoria`

Ejecutada en la VM el 2026-11-22 18:26 UTC con `scripts/evidencias/ejecutar.py auditoria` (commit `e476cf1`).
Casos: **31**, correctos: **31**, con falla: **0**. Los tokens y la contrasena de demo estan ocultos; la IP de la VM se muestra como `$VM_HOST`.

Cada respuesta es la que devolvio el servicio: nada se pego a mano. Un caso que no cumple lo esperado queda marcado como falla, no se omite.

## Preparacion

```bash
export VM_HOST=<IP-DE-LA-VM>      # o 127.0.0.1 si corres los comandos dentro de la VM
export PASSWORD_DEMO=...                 # la de las cuentas de demo; no se versiona
login() { curl -s -X POST "http://$VM_HOST:8001/api/v1/auth/login" -H 'Content-Type: application/json' \
  -d "{\"email\":\"$1\",\"password\":\"$PASSWORD_DEMO\"}" | jq -r .access_token; }
export TOKEN_ADMIN=$(login pablo.admin@demo.mx)
export TOKEN_ANALISTA=$(login josue.analista@demo.mx)
export TOKEN_CLIENTE=$(login ana.cliente@demo.mx)
export TOKEN_SUPERVISOR=$(login jorge.supervisor@demo.mx)
```

El login admite 10 intentos por minuto por IP (RNF-13); el token dura 15 minutos.

## Resumen

| Caso | Resultado | HTTP | Descripcion |
|---|---|---|---|
| [P4-AUD-01](#p4-aud-01) | correcto | 200 | salud 200 con las tres dependencias |
| [P4-AUD-02](#p4-aud-02) | correcto | 200 | Swagger: documentacion de la API |
| [P4-AUD-03](#p4-aud-03) | correcto | 200 | Swagger: especificacion OpenAPI |
| [P4-AUD-04](#p4-aud-04) | correcto | 401 | sin token: 401 |
| [P4-AUD-05](#p4-aud-05) | correcto | 401 | token invalido: 401 |
| [P4-AUD-06](#p4-aud-06) | correcto | 403 | cliente: 403 |
| [P4-AUD-07](#p4-aud-07) | correcto | 403 | supervisor: 403 |
| [P4-AUD-08](#p4-aud-08) | correcto | 200 | bitacora 200: lo mas reciente primero |
| [P4-AUD-09](#p4-aud-09) | correcto | 200 | bitacora 200 XML |
| [P4-AUD-10](#p4-aud-10) | correcto | 200 | bitacora 200 por correlation id |
| [P4-AUD-11](#p4-aud-11) | correcto | 200 | bitacora 200 por usuario |
| [P4-AUD-12](#p4-aud-12) | correcto | 200 | bitacora 200 por entidad y accion |
| [P4-AUD-13](#p4-aud-13) | correcto | 200 | bitacora 200 por periodo |
| [P4-AUD-14](#p4-aud-14) | correcto | 200 | bitacora 200 con intento de inyeccion SQL |
| [P4-AUD-15](#p4-aud-15) | correcto | 400 | bitacora 400 fecha invalida |
| [P4-AUD-16](#p4-aud-16) | correcto | 400 | bitacora 400 hasta antes de desde |
| [P4-AUD-17](#p4-aud-17) | correcto | 400 | bitacora 400 usuario no numerico |
| [P4-AUD-18](#p4-aud-18) | correcto | 400 | bitacora 400 filtro demasiado largo |
| [P4-AUD-19](#p4-aud-19) | correcto | 405 | la bitacora no se escribe por la API: POST |
| [P4-AUD-20](#p4-aud-20) | correcto | 404 | la bitacora no se escribe por la API: PATCH |
| [P4-AUD-21](#p4-aud-21) | correcto | 200 | estado 200: la base protege la bitacora |
| [P4-AUD-22](#p4-aud-22) | correcto | 200 | eventos 200 de MongoDB |
| [P4-AUD-23](#p4-aud-23) | correcto | 200 | eventos 200 por servicio |
| [P4-AUD-24](#p4-aud-24) | correcto | 200 | eventos 200 XML |
| [P4-AUD-25](#p4-aud-25) | correcto | 400 | eventos 400 filtro demasiado largo |
| [P4-AUD-26](#p4-aud-26) | correcto | 200 | obsoleta: alertas de fraude |
| [P4-AUD-27](#p4-aud-27) | correcto | 200 | obsoleta: clasificar motivo |
| [P4-AUD-28](#p4-aud-28) | correcto | 400 | obsoleta: clasificar motivo 400 |
| [P4-AUD-29](#p4-aud-29) | correcto | 200 | obsoleta: alias de eventos |
| [P4-AUD-30](#p4-aud-30) | correcto | 200 | obsoleta: resumen sin sucesor |
| [P4-AUD-31](#p4-aud-31) | correcto | 403 | obsoleta: cliente no ve alertas de fraude |

## P4-AUD-01

**salud 200 con las tres dependencias**

Objetivo: El servicio informa PostgreSQL, Redis y MongoDB, y que el analisis esta obsoleto (RF-32).

Comando:

```bash
curl -sS -i -X GET "http://$VM_HOST:8008/health" \
  -H "Accept: application/json"
```

Respuesta - **200 OK** (19 ms, 208 bytes):

```http
Content-Type: application/json
Content-Length: 208
X-Correlation-ID: f8b7cfd365fc47c0
```

```json
{
  "servicio": "analisis-auditoria",
  "version": "v1",
  "estado": "ok",
  "dependencias": {
    "postgresql": {
      "ok": true,
      "error": null
    },
    "redis": {
      "ok": true,
      "error": null
    },
    "mongodb": {
      "ok": true,
      "error": null
    }
  },
  "analisis": "obsoleto"
}
```

Verificaciones:

- ok: HTTP 200
- ok: estado ok
- ok: MongoDB ok
- ok: analisis obsoleto

## P4-AUD-02

**Swagger: documentacion de la API**

Objetivo: La API publica su documentacion Swagger.

Comando:

```bash
curl -sS -i -X GET "http://$VM_HOST:8008/docs" \
  -H "Accept: text/html"
```

Respuesta - **200 OK** (10 ms, 482 bytes):

```http
Content-Type: text/html; charset=utf-8
Content-Length: 482
X-Correlation-ID: 82cbe43295944f4e
```

```text
<!doctype html>
<html lang="es"><head><meta charset="utf-8"><title>Servicio de auditoria (y analisis obsoleto) - Plataforma de devoluciones</title>
<link rel="stylesheet" href="https://unpkg.com/swagger-ui-dist@5.17.14/swagger-ui.css">
</head><body><div id="swagger"></div>
<script src="https://unpkg.com/swagger-ui-dist@5.17.14/swagger-ui-bundle.js"></script>
<script>SwaggerUIBundle({url: "openapi.json", dom_id: "#swagger",
  persistAuthorization: true});</script>
</body></html>
```

Verificaciones:

- ok: HTTP 200
- ok: HTML de Swagger UI

## P4-AUD-03

**Swagger: especificacion OpenAPI**

Objetivo: La especificacion incluye la auditoria.

Comando:

```bash
curl -sS -i -X GET "http://$VM_HOST:8008/openapi.json" \
  -H "Accept: application/json"
```

Respuesta - **200 OK** (11 ms, 11452 bytes):

```http
Content-Type: application/json
Content-Length: 11452
X-Correlation-ID: 146e90f0dedd4c4e
```

```json
{
  "openapi": "3.0.3",
  "info": {
    "title": "Servicio de auditoria (y analisis obsoleto) - Plataforma de devoluciones",
    "version": "1.0.0",
    "description": "Auditoria: consulta de la bitacora (solo lectura, solo agrega) y eventos por correlation id. RF-30, RN-12, RNF-23. El analisis (clasificar motivo, Pareto, alertas de fraude, sincronizar, resumen) se separo: su sucesor es clasificacion-motivos (8010) y reportes-analitica (8018). Sus rutas siguen disponibles pero obsoletas hasta que los clientes migren. JSON/XML y JWT."
  },
  "servers": [
    {
      "url": "/"
    }
  ],
  "paths": {
    "/health": {
      "get": {
        "summary": "Estado PostgreSQL MongoDB Redis",
        "responses": {
          "200": {
            "description": "Estado PostgreSQL MongoDB Redis",
            "content": {
              "application/json": {
                "schema": {
                  "type": "object"
                }
              },
              "application/xml": {
                "schema": {
                  "type": "object"
                }
              }
            }
          },
          "400": {
            "description": "Parámetros inválidos"
          },
          "401": {
            "description": "Token inválido"
          },
          "403": {
            "description": "Sin permisos"
          },
          "404": {
            "description": "No encontrado"
          },
          "409": {
            "description": "Conflicto de negocio"
          },
          "415": {
            "description": "Formato no permitido"
          },
          "500": {
            "description": "Error interno"
          },
          "503": {
            "description": "Dependencia no disponible"
          }
        }
      }
    },
    "/api/v1/analisis/sincronizar": {
      "post": {
        "summary": "Actualiza MongoDB desde PostgreSQL sin modificar transacciones",
        "responses": {
          "200": {
            "description": "Actualiza MongoDB desde PostgreSQL sin modificar transacciones",
            "content": {
              "application/json": {
                "schema": {
                  "type": "object"
                }
... (recortado: 616 lineas mas)
```

Verificaciones:

- ok: HTTP 200
- ok: incluye la bitacora
- ok: incluye el estado

## P4-AUD-04

**sin token: 401**

Objetivo: La auditoria exige JWT (RNF-09).

Comando:

```bash
curl -sS -i -X GET "http://$VM_HOST:8008/api/v1/auditoria" \
  -H "Accept: application/json"
```

Respuesta - **401 UNAUTHORIZED** (9 ms, 162 bytes):

```http
Content-Type: application/json
Content-Length: 162
X-Correlation-ID: 582504dd067f46a0
```

```json
{
  "error": {
    "codigo": 401,
    "tipo": "no_autenticado",
    "mensaje": "Falta el header 'Authorization: Bearer <token>'.",
    "detalles": null,
    "correlation_id": "582504dd067f46a0"
  }
}
```

Verificaciones:

- ok: HTTP 401
- ok: tipo no_autenticado

## P4-AUD-05

**token invalido: 401**

Objetivo: Un token alterado se rechaza.

Comando:

```bash
curl -sS -i -X GET "http://$VM_HOST:8008/api/v1/auditoria" \
  -H "Accept: application/json" \
  -H "Authorization: Bearer no.es.un.jwt"
```

Respuesta - **401 UNAUTHORIZED** (9 ms, 136 bytes):

```http
Content-Type: application/json
Content-Length: 136
X-Correlation-ID: d3a6f3e165e1429b
```

```json
{
  "error": {
    "codigo": 401,
    "tipo": "token_invalido",
    "mensaje": "El token no es valido.",
    "detalles": null,
    "correlation_id": "d3a6f3e165e1429b"
  }
}
```

Verificaciones:

- ok: HTTP 401
- ok: tipo token_invalido

## P4-AUD-06

**cliente: 403**

Objetivo: La bitacora no la lee un cliente (RN-13).

Comando:

```bash
curl -sS -i -X GET "http://$VM_HOST:8008/api/v1/auditoria" \
  -H "Accept: application/json" \
  -H "Authorization: Bearer $TOKEN_CLIENTE"
```

Respuesta - **403 FORBIDDEN** (12 ms, 232 bytes):

```http
Content-Type: application/json
Content-Length: 232
X-Correlation-ID: 2f8142ba8900475d
```

```json
{
  "error": {
    "codigo": 403,
    "tipo": "sin_permiso",
    "mensaje": "Tu rol no tiene permiso para esta operacion.",
    "detalles": {
      "rol": "Cliente",
      "roles_permitidos": [
        "Administrador",
        "Analista de Devoluciones"
      ]
    },
    "correlation_id": "2f8142ba8900475d"
  }
}
```

Verificaciones:

- ok: HTTP 403
- ok: tipo sin_permiso

## P4-AUD-07

**supervisor: 403**

Objetivo: Auditar es de Administrador y Analista; la separacion de funciones evita que quien opera revise su propio rastro (RN-12).

Comando:

```bash
curl -sS -i -X GET "http://$VM_HOST:8008/api/v1/auditoria/estado" \
  -H "Accept: application/json" \
  -H "Authorization: Bearer $TOKEN_SUPERVISOR"
```

Respuesta - **403 FORBIDDEN** (17 ms, 235 bytes):

```http
Content-Type: application/json
Content-Length: 235
X-Correlation-ID: 773f4f6db4fc438b
```

```json
{
  "error": {
    "codigo": 403,
    "tipo": "sin_permiso",
    "mensaje": "Tu rol no tiene permiso para esta operacion.",
    "detalles": {
      "rol": "Supervisor",
      "roles_permitidos": [
        "Administrador",
        "Analista de Devoluciones"
      ]
    },
    "correlation_id": "773f4f6db4fc438b"
  }
}
```

Verificaciones:

- ok: HTTP 403
- ok: tipo sin_permiso

## P4-AUD-08

**bitacora 200: lo mas reciente primero**

Objetivo: La bitacora registra quien hizo que y cuando (RF-30), ordenada de lo mas reciente a lo mas antiguo.

Comando:

```bash
curl -sS -i -X GET "http://$VM_HOST:8008/api/v1/auditoria?por_pagina=10" \
  -H "Accept: application/json" \
  -H "Authorization: Bearer $TOKEN_ADMIN"
```

Respuesta - **200 OK** (25 ms, 2261 bytes):

```http
Content-Type: application/json
Content-Length: 2261
X-Correlation-ID: 1b6f50b490a84bda
```

```json
{
  "datos": [
    {
      "id": 1119,
      "accion": "login_api",
      "entidad": "usuarios",
      "entidad_id": 18,
      "detalle": "Inicio de sesion por API, JWT emitido",
      "correlation_id": "edabe57a92254690",
      "fecha": "2026-11-22T18:26:43.315534+00:00",
      "usuario": "Pablo Flores"
    },
    {
      "id": 1118,
      "accion": "login_api",
      "entidad": "usuarios",
      "entidad_id": 40,
      "detalle": "Inicio de sesion por API, JWT emitido",
      "correlation_id": "930262e66ae04f5b",
      "fecha": "2026-11-22T18:26:43.171387+00:00",
      "usuario": "Jorge Salinas"
    },
    {
      "id": 1117,
      "accion": "login_api",
      "entidad": "usuarios",
      "entidad_id": 10,
      "detalle": "Inicio de sesion por API, JWT emitido",
      "correlation_id": "33d48afee46840fb",
      "fecha": "2026-11-22T18:26:43.036747+00:00",
      "usuario": "Ana Lopez Garcia"
    },
    {
      "id": 1116,
      "accion": "serie_vendida",
      "entidad": "series_producto",
      "entidad_id": null,
      "detalle": "Serie EVID-P4-003 ligada a la linea 62",
      "correlation_id": "e9782bd3be31418f",
      "fecha": "2026-11-22T18:24:16.722391+00:00",
      "usuario": "Pablo Flores"
    },
    {
      "id": 1115,
      "accion": "serie_vendida",
      "entidad": "series_producto",
      "entidad_id": null,
      "detalle": "Serie EVID-P4-001 ligada a la linea 62",
      "correlation_id": "feac40bef5eb4425",
      "fecha": "2026-11-22T18:24:16.363218+00:00",
      "usuario": "Marta Cantu"
    },
    {
      "id": 1114,
      "accion": "login_api",
      "entidad": "usuarios",
      "entidad_id": 39,
      "detalle": "Inicio de sesion por API, JWT emitido",
      "correlation_id": "dac1181921f54eb3",
      "fecha": "2026-11-22T18:24:16.184514+00:00",
      "usuario": "Marta Cantu"
    },
    {
      "id": 1113,
      "accion": "alta_series",
      "entidad": "lotes",
      "entidad_id": 1,
      "detalle": "Series nuevas: 1",
      "correlation_id": "eb5cccc1f87540f6",
      "fecha": "2026-11-22T18:24:16.076249+00:00",
... (recortado: 40 lineas mas)
```

Verificaciones:

- ok: HTTP 200
- ok: hay registros
- ok: trae usuario, accion y fecha
- ok: orden descendente por id
- ok: sin tokens ni hashes

Efecto en PostgreSQL - registros de la bitacora, para contrastar el total:

```sql
SELECT count(*) AS registros FROM bitacora
```

```text
registros
1119
```

## P4-AUD-09

**bitacora 200 XML**

Objetivo: La bitacora responde XML (RF-31).

Comando:

```bash
curl -sS -i -X GET "http://$VM_HOST:8008/api/v1/auditoria?por_pagina=3" \
  -H "Accept: application/xml" \
  -H "Authorization: Bearer $TOKEN_ANALISTA"
```

Respuesta - **200 OK** (23 ms, 1054 bytes):

```http
Content-Type: application/xml; charset=utf-8
Content-Length: 1054
X-Correlation-ID: e06c7c90b13d445e
```

```xml
<?xml version='1.0' encoding='utf-8'?>
<bitacora><datos><item><id>1120</id><accion>login_api</accion><entidad>usuarios</entidad><entidad_id>16</entidad_id><detalle>Inicio de sesion por API, JWT emitido</detalle><correlation_id>ad9143068ed84c35</correlation_id><fecha>2026-11-22T18:26:43.618112+00:00</fecha><usuario>Josue Berdeal</usuario></item><item><id>1119</id><accion>login_api</accion><entidad>usuarios</entidad><entidad_id>18</entidad_id><detalle>Inicio de sesion por API, JWT emitido</detalle><correlation_id>edabe57a92254690</correlation_id><fecha>2026-11-22T18:26:43.315534+00:00</fecha><usuario>Pablo Flores</usuario></item><item><id>1118</id><accion>login_api</accion><entidad>usuarios</entidad><entidad_id>40</entidad_id><detalle>Inicio de sesion por API, JWT emitido</detalle><correlation_id>930262e66ae04f5b</correlation_id><fecha>2026-11-22T18:26:43.171387+00:00</fecha><usuario>Jorge Salinas</usuario></item></datos><paginacion><pagina>1</pagina><por_pagina>3</por_pagina><total>1120</total><paginas>374</paginas></paginacion></bitacora>
```

Verificaciones:

- ok: HTTP 200
- ok: es XML
- ok: raiz bitacora

## P4-AUD-10

**bitacora 200 por correlation id**

Objetivo: Todo lo que dejo una misma peticion, de punta a punta, se sigue con su correlation id.

Comando:

```bash
curl -sS -i -X GET "http://$VM_HOST:8008/api/v1/auditoria?correlation_id=e9782bd3be31418f" \
  -H "Accept: application/json" \
  -H "Authorization: Bearer $TOKEN_ADMIN"
```

Respuesta - **200 OK** (23 ms, 314 bytes):

```http
Content-Type: application/json
Content-Length: 314
X-Correlation-ID: 49779b11f46f426a
```

```json
{
  "datos": [
    {
      "id": 1116,
      "accion": "serie_vendida",
      "entidad": "series_producto",
      "entidad_id": null,
      "detalle": "Serie EVID-P4-003 ligada a la linea 62",
      "correlation_id": "e9782bd3be31418f",
      "fecha": "2026-11-22T18:24:16.722391+00:00",
      "usuario": "Pablo Flores"
    }
  ],
  "paginacion": {
    "pagina": 1,
    "por_pagina": 20,
    "total": 1,
    "paginas": 1
  }
}
```

Verificaciones:

- ok: HTTP 200
- ok: todas con ese id

## P4-AUD-11

**bitacora 200 por usuario**

Objetivo: Lo que hizo una persona.

Comando:

```bash
curl -sS -i -X GET "http://$VM_HOST:8008/api/v1/auditoria?usuario_id=18&por_pagina=20" \
  -H "Accept: application/json" \
  -H "Authorization: Bearer $TOKEN_ADMIN"
```

Respuesta - **200 OK** (24 ms, 4446 bytes):

```http
Content-Type: application/json
Content-Length: 4446
X-Correlation-ID: 7c9e4894677540e1
```

```json
{
  "datos": [
    {
      "id": 1119,
      "accion": "login_api",
      "entidad": "usuarios",
      "entidad_id": 18,
      "detalle": "Inicio de sesion por API, JWT emitido",
      "correlation_id": "edabe57a92254690",
      "fecha": "2026-11-22T18:26:43.315534+00:00",
      "usuario": "Pablo Flores"
    },
    {
      "id": 1116,
      "accion": "serie_vendida",
      "entidad": "series_producto",
      "entidad_id": null,
      "detalle": "Serie EVID-P4-003 ligada a la linea 62",
      "correlation_id": "e9782bd3be31418f",
      "fecha": "2026-11-22T18:24:16.722391+00:00",
      "usuario": "Pablo Flores"
    },
    {
      "id": 1113,
      "accion": "alta_series",
      "entidad": "lotes",
      "entidad_id": 1,
      "detalle": "Series nuevas: 1",
      "correlation_id": "eb5cccc1f87540f6",
      "fecha": "2026-11-22T18:24:16.076249+00:00",
      "usuario": "Pablo Flores"
    },
    {
      "id": 1112,
      "accion": "alta_series",
      "entidad": "lotes",
      "entidad_id": 15,
      "detalle": "Series nuevas: 1",
      "correlation_id": "06111c8941a442cc",
      "fecha": "2026-11-22T18:24:16.049812+00:00",
      "usuario": "Pablo Flores"
    },
    {
      "id": 1111,
      "accion": "alta_series",
      "entidad": "lotes",
      "entidad_id": 7,
      "detalle": "Series nuevas: 1",
      "correlation_id": "ea7f56f0d3e04427",
      "fecha": "2026-11-22T18:24:15.986938+00:00",
      "usuario": "Pablo Flores"
    },
    {
      "id": 1110,
      "accion": "alta_series",
      "entidad": "lotes",
      "entidad_id": 7,
      "detalle": "Series nuevas: 0",
      "correlation_id": "6fad9b66758e4909",
      "fecha": "2026-11-22T18:24:15.963243+00:00",
      "usuario": "Pablo Flores"
    },
    {
      "id": 1109,
      "accion": "alta_series",
      "entidad": "lotes",
      "entidad_id": 7,
      "detalle": "Series nuevas: 3",
      "correlation_id": "100209b1c0954f83",
      "fecha": "2026-11-22T18:24:15.616706+00:00",
... (recortado: 140 lineas mas)
```

Verificaciones:

- ok: HTTP 200
- ok: hay registros

## P4-AUD-12

**bitacora 200 por entidad y accion**

Objetivo: Filtros por entidad y accion; las reconfirmaciones de contrasena quedan asentadas.

Comando:

```bash
curl -sS -i -X GET "http://$VM_HOST:8008/api/v1/auditoria?entidad=usuarios&accion=autorizacion_operacion" \
  -H "Accept: application/json" \
  -H "Authorization: Bearer $TOKEN_ANALISTA"
```

Respuesta - **200 OK** (26 ms, 1275 bytes):

```http
Content-Type: application/json
Content-Length: 1275
X-Correlation-ID: 8176408a97a042f8
```

```json
{
  "datos": [
    {
      "id": 1050,
      "accion": "autorizacion_operacion",
      "entidad": "usuarios",
      "entidad_id": 40,
      "detalle": "Autorizo cerrar_investigacion sobre 6",
      "correlation_id": "b7548cb0b287428a",
      "fecha": "2026-11-22T18:13:29.521343+00:00",
      "usuario": "Jorge Salinas"
    },
    {
      "id": 1049,
      "accion": "autorizacion_operacion",
      "entidad": "usuarios",
      "entidad_id": 40,
      "detalle": "Autorizo cerrar_investigacion sobre 999999",
      "correlation_id": "5068b1a81c6740ae",
      "fecha": "2026-11-22T18:13:29.384955+00:00",
      "usuario": "Jorge Salinas"
    },
    {
      "id": 1017,
      "accion": "autorizacion_operacion",
      "entidad": "usuarios",
      "entidad_id": 40,
      "detalle": "Autorizo cerrar_investigacion sobre 4",
      "correlation_id": "9040bddad5df4848",
      "fecha": "2026-11-22T18:11:56.392445+00:00",
      "usuario": "Jorge Salinas"
    },
    {
      "id": 1016,
      "accion": "autorizacion_operacion",
      "entidad": "usuarios",
      "entidad_id": 40,
      "detalle": "Autorizo cerrar_investigacion sobre 999999",
      "correlation_id": "e82fc147895846af",
      "fecha": "2026-11-22T18:11:56.255320+00:00",
      "usuario": "Jorge Salinas"
    },
    {
      "id": 846,
      "accion": "autorizacion_operacion",
      "entidad": "usuarios",
      "entidad_id": 40,
      "detalle": "Autorizo cerrar_investigacion sobre 3",
      "correlation_id": "220bd476e8374577",
      "fecha": "2026-11-22T01:17:15.293117+00:00",
      "usuario": "Jorge Salinas"
    }
  ],
  "paginacion": {
    "pagina": 1,
    "por_pagina": 20,
    "total": 5,
    "paginas": 1
  }
}
```

Verificaciones:

- ok: HTTP 200
- ok: todas coinciden

## P4-AUD-13

**bitacora 200 por periodo**

Objetivo: El periodo incluye todo el dia final.

Comando:

```bash
curl -sS -i -X GET "http://$VM_HOST:8008/api/v1/auditoria?desde=2026-01-01&hasta=2026-12-31&por_pagina=5" \
  -H "Accept: application/json" \
  -H "Authorization: Bearer $TOKEN_ADMIN"
```

Respuesta - **200 OK** (24 ms, 1220 bytes):

```http
Content-Type: application/json
Content-Length: 1220
X-Correlation-ID: 2a2693c3c8644659
```

```json
{
  "datos": [
    {
      "id": 1120,
      "accion": "login_api",
      "entidad": "usuarios",
      "entidad_id": 16,
      "detalle": "Inicio de sesion por API, JWT emitido",
      "correlation_id": "ad9143068ed84c35",
      "fecha": "2026-11-22T18:26:43.618112+00:00",
      "usuario": "Josue Berdeal"
    },
    {
      "id": 1119,
      "accion": "login_api",
      "entidad": "usuarios",
      "entidad_id": 18,
      "detalle": "Inicio de sesion por API, JWT emitido",
      "correlation_id": "edabe57a92254690",
      "fecha": "2026-11-22T18:26:43.315534+00:00",
      "usuario": "Pablo Flores"
    },
    {
      "id": 1118,
      "accion": "login_api",
      "entidad": "usuarios",
      "entidad_id": 40,
      "detalle": "Inicio de sesion por API, JWT emitido",
      "correlation_id": "930262e66ae04f5b",
      "fecha": "2026-11-22T18:26:43.171387+00:00",
      "usuario": "Jorge Salinas"
    },
    {
      "id": 1117,
      "accion": "login_api",
      "entidad": "usuarios",
      "entidad_id": 10,
      "detalle": "Inicio de sesion por API, JWT emitido",
      "correlation_id": "33d48afee46840fb",
      "fecha": "2026-11-22T18:26:43.036747+00:00",
      "usuario": "Ana Lopez Garcia"
    },
    {
      "id": 1116,
      "accion": "serie_vendida",
      "entidad": "series_producto",
      "entidad_id": null,
      "detalle": "Serie EVID-P4-003 ligada a la linea 62",
      "correlation_id": "e9782bd3be31418f",
      "fecha": "2026-11-22T18:24:16.722391+00:00",
      "usuario": "Pablo Flores"
    }
  ],
  "paginacion": {
    "pagina": 1,
    "por_pagina": 5,
    "total": 1120,
    "paginas": 224
  }
}
```

Verificaciones:

- ok: HTTP 200
- ok: hay registros

## P4-AUD-14

**bitacora 200 con intento de inyeccion SQL**

Objetivo: Un filtro con SQL se trata como texto (parametros ligados, RNF-11): no devuelve toda la bitacora.

Comando:

```bash
curl -sS -i -X GET "http://$VM_HOST:8008/api/v1/auditoria?accion=x%27%20OR%20%271%27%3D%271" \
  -H "Accept: application/json" \
  -H "Authorization: Bearer $TOKEN_ADMIN"
```

Respuesta - **200 OK** (24 ms, 77 bytes):

```http
Content-Type: application/json
Content-Length: 77
X-Correlation-ID: 4d2e9ad63b544cc0
```

```json
{
  "datos": [],
  "paginacion": {
    "pagina": 1,
    "por_pagina": 20,
    "total": 0,
    "paginas": 0
  }
}
```

Verificaciones:

- ok: HTTP 200
- ok: sin resultados

## P4-AUD-15

**bitacora 400 fecha invalida**

Objetivo: Las fechas son AAAA-MM-DD.

Comando:

```bash
curl -sS -i -X GET "http://$VM_HOST:8008/api/v1/auditoria?desde=ayer" \
  -H "Accept: application/json" \
  -H "Authorization: Bearer $TOKEN_ADMIN"
```

Respuesta - **400 BAD REQUEST** (9 ms, 146 bytes):

```http
Content-Type: application/json
Content-Length: 146
X-Correlation-ID: bd898f812f3e4185
```

```json
{
  "error": {
    "codigo": 400,
    "tipo": "validacion",
    "mensaje": "desde debe tener formato AAAA-MM-DD.",
    "detalles": null,
    "correlation_id": "bd898f812f3e4185"
  }
}
```

Verificaciones:

- ok: HTTP 400
- ok: tipo validacion

## P4-AUD-16

**bitacora 400 hasta antes de desde**

Objetivo: Un periodo al reves se rechaza.

Comando:

```bash
curl -sS -i -X GET "http://$VM_HOST:8008/api/v1/auditoria?desde=2026-06-01&hasta=2026-01-01" \
  -H "Accept: application/json" \
  -H "Authorization: Bearer $TOKEN_ADMIN"
```

Respuesta - **400 BAD REQUEST** (8 ms, 145 bytes):

```http
Content-Type: application/json
Content-Length: 145
X-Correlation-ID: 19ef62dffc4c4eb5
```

```json
{
  "error": {
    "codigo": 400,
    "tipo": "validacion",
    "mensaje": "hasta no puede ser menor que desde.",
    "detalles": null,
    "correlation_id": "19ef62dffc4c4eb5"
  }
}
```

Verificaciones:

- ok: HTTP 400
- ok: tipo validacion

## P4-AUD-17

**bitacora 400 usuario no numerico**

Objetivo: El filtro numerico se valida.

Comando:

```bash
curl -sS -i -X GET "http://$VM_HOST:8008/api/v1/auditoria?usuario_id=abc" \
  -H "Accept: application/json" \
  -H "Authorization: Bearer $TOKEN_ADMIN"
```

Respuesta - **400 BAD REQUEST** (8 ms, 149 bytes):

```http
Content-Type: application/json
Content-Length: 149
X-Correlation-ID: 2f76f0fcab8647c3
```

```json
{
  "error": {
    "codigo": 400,
    "tipo": "validacion",
    "mensaje": "usuario_id debe ser un entero positivo.",
    "detalles": null,
    "correlation_id": "2f76f0fcab8647c3"
  }
}
```

Verificaciones:

- ok: HTTP 400
- ok: tipo validacion

## P4-AUD-18

**bitacora 400 filtro demasiado largo**

Objetivo: Un filtro de texto tiene un maximo de 100 caracteres.

Comando:

```bash
curl -sS -i -X GET "http://$VM_HOST:8008/api/v1/auditoria?accion=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa" \
  -H "Accept: application/json" \
  -H "Authorization: Bearer $TOKEN_ADMIN"
```

Respuesta - **400 BAD REQUEST** (8 ms, 140 bytes):

```http
Content-Type: application/json
Content-Length: 140
X-Correlation-ID: dad414283def4245
```

```json
{
  "error": {
    "codigo": 400,
    "tipo": "validacion",
    "mensaje": "Filtro accion demasiado largo.",
    "detalles": null,
    "correlation_id": "dad414283def4245"
  }
}
```

Verificaciones:

- ok: HTTP 400
- ok: tipo validacion

## P4-AUD-19

**la bitacora no se escribe por la API: POST**

Objetivo: La auditoria solo se consulta: no existe una ruta para agregar o alterar registros (RN-12). Los demas servicios escriben directo en la base.

Comando:

```bash
curl -sS -i -X POST "http://$VM_HOST:8008/api/v1/auditoria" \
  -H "Accept: application/json" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN_ADMIN" \
  -d '{"accion":"falsa","entidad":"x"}'
```

Respuesta - **405 METHOD NOT ALLOWED** (8 ms, 167 bytes):

```http
Content-Type: application/json
Content-Length: 167
X-Correlation-ID: 710e56fd3ead45f3
```

```json
{
  "error": {
    "codigo": 405,
    "tipo": "metodo_no_permitido",
    "mensaje": "The method is not allowed for the requested URL.",
    "detalles": null,
    "correlation_id": "710e56fd3ead45f3"
  }
}
```

Verificaciones:

- ok: HTTP 405
- ok: metodo no permitido

## P4-AUD-20

**la bitacora no se escribe por la API: PATCH**

Objetivo: Tampoco hay ruta para modificar un registro.

Comando:

```bash
curl -sS -i -X PATCH "http://$VM_HOST:8008/api/v1/auditoria/1" \
  -H "Accept: application/json" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN_ADMIN" \
  -d '{"detalle":"alterado"}'
```

Respuesta - **404 NOT FOUND** (9 ms, 233 bytes):

```http
Content-Type: application/json
Content-Length: 233
X-Correlation-ID: be80e9cb44a549c3
```

```json
{
  "error": {
    "codigo": 404,
    "tipo": "no_encontrado",
    "mensaje": "The requested URL was not found on the server. If you entered the URL manually please check your spelling and try again.",
    "detalles": null,
    "correlation_id": "be80e9cb44a549c3"
  }
}
```

Verificaciones:

- ok: HTTP 404
- ok: la ruta no existe

## P4-AUD-21

**estado 200: la base protege la bitacora**

Objetivo: Informa si la base rechaza UPDATE, DELETE y TRUNCATE (migracion 045) y avisa hasta donde llega esa proteccion.

Comando:

```bash
curl -sS -i -X GET "http://$VM_HOST:8008/api/v1/auditoria/estado" \
  -H "Accept: application/json" \
  -H "Authorization: Bearer $TOKEN_ANALISTA"
```

Respuesta - **200 OK** (21 ms, 358 bytes):

```http
Content-Type: application/json
Content-Length: 358
X-Correlation-ID: 897460f9cb394453
```

```json
{
  "registros": 1120,
  "primero": "2026-09-06T23:20:35.290510+00:00",
  "ultimo": "2026-11-22T18:26:43.618112+00:00",
  "proteccion": {
    "actualizar_y_borrar_bloqueados": true,
    "vaciar_bloqueado": true,
    "completa": true
  },
  "aviso": "La bitacora solo admite agregar registros. Esta proteccion es del esquema de la base; no sustituye el control de acceso al servidor de PostgreSQL."
}
```

Verificaciones:

- ok: HTTP 200
- ok: proteccion completa
- ok: hay registros
- ok: no promete mas de lo que hace

Efecto en PostgreSQL - los triggers que la protegen:

```sql
SELECT tgname FROM pg_trigger WHERE tgrelid = 'bitacora'::regclass AND NOT tgisinternal ORDER BY 1
```

```text
tgname
trg_bitacora_inmutable
trg_bitacora_sin_truncate
```

## P4-AUD-22

**eventos 200 de MongoDB**

Objetivo: Traza de eventos entre servicios. Nunca incluye el campo `datos` (puede traer cuerpos de peticiones, RNF-16).

Comando:

```bash
curl -sS -i -X GET "http://$VM_HOST:8008/api/v1/auditoria/eventos?por_pagina=5" \
  -H "Accept: application/json" \
  -H "Authorization: Bearer $TOKEN_ADMIN"
```

Respuesta - **200 OK** (16 ms, 1010 bytes):

```http
Content-Type: application/json
Content-Length: 1010
X-Correlation-ID: dcda6254141d4ebb
```

```json
{
  "datos": [
    {
      "id": "6adad7550194762f256264d5",
      "servicio": "devoluciones",
      "tipo": "devolucion_registrada",
      "usuario_id": 10,
      "correlation_id": "092b43ba39ff4b37",
      "fecha": "2026-10-23T03:41:09.495000+00:00"
    },
    {
      "id": "6adab3ea0194762f256264d4",
      "servicio": "devoluciones",
      "tipo": "devolucion_autorizacion",
      "usuario_id": 16,
      "correlation_id": "1ffadf89fd364d1d",
      "fecha": "2026-10-23T01:10:02.439000+00:00"
    },
    {
      "id": "6adab3c00194762f256264d3",
      "servicio": "devoluciones",
      "tipo": "devolucion_registrada",
      "usuario_id": 10,
      "correlation_id": "41aefe1497d94186",
      "fecha": "2026-10-23T01:09:20.561000+00:00"
    },
    {
      "id": "6ada3a86e8c6892d152d3f08",
      "servicio": "devoluciones",
      "tipo": "devolucion_registrada",
      "usuario_id": 10,
      "correlation_id": "7bb68147efc34694",
      "fecha": "2026-10-22T16:32:06.456000+00:00"
    },
    {
      "id": "6ada1de3e8c6892d152d3f07",
      "servicio": "devoluciones",
      "tipo": "devolucion_autorizacion",
      "usuario_id": 16,
      "correlation_id": "fdd32d64b3b24371",
      "fecha": "2026-10-22T14:29:55.334000+00:00"
    }
  ],
  "paginacion": {
    "pagina": 1,
    "por_pagina": 5,
    "total": 18,
    "paginas": 4
  }
}
```

Verificaciones:

- ok: HTTP 200
- ok: trae paginacion
- ok: ningun evento trae `datos`

## P4-AUD-23

**eventos 200 por servicio**

Objetivo: Filtra los eventos por servicio.

Comando:

```bash
curl -sS -i -X GET "http://$VM_HOST:8008/api/v1/auditoria/eventos?servicio=auth" \
  -H "Accept: application/json" \
  -H "Authorization: Bearer $TOKEN_ANALISTA"
```

Respuesta - **200 OK** (10 ms, 77 bytes):

```http
Content-Type: application/json
Content-Length: 77
X-Correlation-ID: da6c4c134f0d4849
```

```json
{
  "datos": [],
  "paginacion": {
    "pagina": 1,
    "por_pagina": 20,
    "total": 0,
    "paginas": 0
  }
}
```

Verificaciones:

- ok: HTTP 200
- ok: todos del servicio

## P4-AUD-24

**eventos 200 XML**

Objetivo: La traza responde XML (RF-31).

Comando:

```bash
curl -sS -i -X GET "http://$VM_HOST:8008/api/v1/auditoria/eventos?por_pagina=2" \
  -H "Accept: application/xml" \
  -H "Authorization: Bearer $TOKEN_ANALISTA"
```

Respuesta - **200 OK** (14 ms, 653 bytes):

```http
Content-Type: application/xml; charset=utf-8
Content-Length: 653
X-Correlation-ID: 0ad788c8587d450c
```

```xml
<?xml version='1.0' encoding='utf-8'?>
<eventos><datos><item><id>6adad7550194762f256264d5</id><servicio>devoluciones</servicio><tipo>devolucion_registrada</tipo><usuario_id>10</usuario_id><correlation_id>092b43ba39ff4b37</correlation_id><fecha>2026-10-23T03:41:09.495000+00:00</fecha></item><item><id>6adab3ea0194762f256264d4</id><servicio>devoluciones</servicio><tipo>devolucion_autorizacion</tipo><usuario_id>16</usuario_id><correlation_id>1ffadf89fd364d1d</correlation_id><fecha>2026-10-23T01:10:02.439000+00:00</fecha></item></datos><paginacion><pagina>1</pagina><por_pagina>2</por_pagina><total>18</total><paginas>9</paginas></paginacion></eventos>
```

Verificaciones:

- ok: HTTP 200
- ok: es XML

## P4-AUD-25

**eventos 400 filtro demasiado largo**

Objetivo: Un filtro de texto tiene un maximo.

Comando:

```bash
curl -sS -i -X GET "http://$VM_HOST:8008/api/v1/auditoria/eventos?servicio=sssssssssssssssssssssssssssssssssssssssssssssssssssssssssssss" \
  -H "Accept: application/json" \
  -H "Authorization: Bearer $TOKEN_ADMIN"
```

Respuesta - **400 BAD REQUEST** (8 ms, 142 bytes):

```http
Content-Type: application/json
Content-Length: 142
X-Correlation-ID: da88ba988f0b406d
```

```json
{
  "error": {
    "codigo": 400,
    "tipo": "validacion",
    "mensaje": "Filtro servicio demasiado largo.",
    "detalles": null,
    "correlation_id": "da88ba988f0b406d"
  }
}
```

Verificaciones:

- ok: HTTP 400
- ok: tipo validacion

## P4-AUD-26

**obsoleta: alertas de fraude**

Objetivo: Sigue respondiendo como antes, pero avisa que esta obsoleta y donde vive su sucesor (reportes-analitica, 8018).

Comando:

```bash
curl -sS -i -X GET "http://$VM_HOST:8008/api/v1/analisis/alertas-fraude" \
  -H "Accept: application/json" \
  -H "Authorization: Bearer $TOKEN_ANALISTA"
```

Respuesta - **200 OK** (29 ms, 690 bytes):

```http
Content-Type: application/json
Content-Length: 690
X-Correlation-ID: 09cf1c853ab54362
Deprecation: true
Link: <http://reportes-analitica:8000/api/v1/analitica/alertas-fraude>; rel="successor-version"
```

```json
{
  "datos": [
    {
      "cliente_id": 10,
      "cliente": "Ana Lopez Garcia",
      "devoluciones_90_dias": 19,
      "rechazadas": 0,
      "monto_reembolsado": 586.47,
      "razones": [
        "frecuencia alta en 90 dias"
      ],
      "requiere_revision_humana": true
    },
    {
      "cliente_id": 11,
      "cliente": "Miguel Ramos Soto",
      "devoluciones_90_dias": 14,
      "rechazadas": 2,
      "monto_reembolsado": 108.22,
      "razones": [
        "frecuencia alta en 90 dias",
        "multiples solicitudes rechazadas"
      ],
      "requiere_revision_humana": true
    },
    {
      "cliente_id": 12,
      "cliente": "Sofia Herrera",
      "devoluciones_90_dias": 13,
      "rechazadas": 0,
      "monto_reembolsado": 278.42,
      "razones": [
        "frecuencia alta en 90 dias"
      ],
      "requiere_revision_humana": true
    }
  ],
  "total": 3,
  "aviso": "Son indicadores preventivos, no una determinacion de fraude."
}
```

Verificaciones:

- ok: HTTP 200
- ok: Deprecation: true
- ok: Link al sucesor

## P4-AUD-27

**obsoleta: clasificar motivo**

Objetivo: La clasificacion de motivos pasa a clasificacion-motivos (8010); esta ruta avisa su sucesor. Orienta, el usuario confirma.

Comando:

```bash
curl -sS -i -X POST "http://$VM_HOST:8008/api/v1/analisis/clasificar-motivo" \
  -H "Accept: application/json" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN_CLIENTE" \
  -d '{"descripcion":"El producto llego con el empaque roto y derramado"}'
```

Respuesta - **200 OK** (17 ms, 200 bytes):

```http
Content-Type: application/json
Content-Length: 200
X-Correlation-ID: 6bbe36a6a5c043ed
Deprecation: true
Link: <http://clasificacion-motivos:8000/api/v1/motivos/sugerencias>; rel="successor-version"
```

```json
{
  "sugerencias": [
    {
      "motivo": "Producto danado",
      "puntaje": 1,
      "coincidencias": [
        "roto"
      ],
      "motivo_id": 1
    }
  ],
  "requiere_confirmacion": true,
  "explicacion": "La clasificacion orienta; el usuario confirma el motivo."
}
```

Verificaciones:

- ok: HTTP 200
- ok: Deprecation: true
- ok: Link a clasificacion-motivos
- ok: pide confirmacion

## P4-AUD-28

**obsoleta: clasificar motivo 400**

Objetivo: La descripcion tiene entre 10 y 2000 caracteres.

Comando:

```bash
curl -sS -i -X POST "http://$VM_HOST:8008/api/v1/analisis/clasificar-motivo" \
  -H "Accept: application/json" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN_CLIENTE" \
  -d '{"descripcion":"corto"}'
```

Respuesta - **400 BAD REQUEST** (9 ms, 163 bytes):

```http
Content-Type: application/json
Content-Length: 163
X-Correlation-ID: fcc622bd6e814089
Deprecation: true
Link: <http://clasificacion-motivos:8000/api/v1/motivos/sugerencias>; rel="successor-version"
```

```json
{
  "error": {
    "codigo": 400,
    "tipo": "validacion",
    "mensaje": "descripcion debe contener entre 10 y 2000 caracteres.",
    "detalles": null,
    "correlation_id": "fcc622bd6e814089"
  }
}
```

Verificaciones:

- ok: HTTP 400
- ok: tipo validacion
- ok: tambien avisa Deprecation

## P4-AUD-29

**obsoleta: alias de eventos**

Objetivo: La traza por correlation id es auditoria: el alias avisa que el sucesor es /api/v1/auditoria/eventos.

Comando:

```bash
curl -sS -i -X GET "http://$VM_HOST:8008/api/v1/analisis/eventos?por_pagina=2" \
  -H "Accept: application/json" \
  -H "Authorization: Bearer $TOKEN_ADMIN"
```

Respuesta - **200 OK** (10 ms, 450 bytes):

```http
Content-Type: application/json
Content-Length: 450
X-Correlation-ID: 2f154b48aa2b4188
Deprecation: true
Link: </api/v1/auditoria/eventos>; rel="successor-version"
```

```json
{
  "datos": [
    {
      "id": "6adad7550194762f256264d5",
      "servicio": "devoluciones",
      "tipo": "devolucion_registrada",
      "usuario_id": 10,
      "correlation_id": "092b43ba39ff4b37",
      "fecha": "2026-10-23T03:41:09.495000+00:00"
    },
    {
      "id": "6adab3ea0194762f256264d4",
      "servicio": "devoluciones",
      "tipo": "devolucion_autorizacion",
      "usuario_id": 16,
      "correlation_id": "1ffadf89fd364d1d",
      "fecha": "2026-10-23T01:10:02.439000+00:00"
    }
  ],
  "paginacion": {
    "pagina": 1,
    "por_pagina": 2,
    "total": 18,
    "paginas": 9
  }
}
```

Verificaciones:

- ok: HTTP 200
- ok: Deprecation: true
- ok: Link a la auditoria

## P4-AUD-30

**obsoleta: resumen sin sucesor**

Objetivo: Solo contaba snapshots y no tiene sucesor: lleva Deprecation pero no Link.

Comando:

```bash
curl -sS -i -X GET "http://$VM_HOST:8008/api/v1/analisis/resumen" \
  -H "Accept: application/json" \
  -H "Authorization: Bearer $TOKEN_ANALISTA"
```

Respuesta - **200 OK** (12 ms, 91 bytes):

```http
Content-Type: application/json
Content-Length: 91
X-Correlation-ID: 49681a4e7a9e479a
Deprecation: true
```

```json
{
  "casos_sincronizados": 46,
  "reportes_pareto": 16,
  "nota": "No implica causa raiz comprobada."
}
```

Verificaciones:

- ok: HTTP 200
- ok: Deprecation: true
- ok: sin Link

## P4-AUD-31

**obsoleta: cliente no ve alertas de fraude**

Objetivo: Las alertas nombran clientes: solo Administrador y Analista (RN-15).

Comando:

```bash
curl -sS -i -X GET "http://$VM_HOST:8008/api/v1/analisis/alertas-fraude" \
  -H "Accept: application/json" \
  -H "Authorization: Bearer $TOKEN_CLIENTE"
```

Respuesta - **403 FORBIDDEN** (10 ms, 232 bytes):

```http
Content-Type: application/json
Content-Length: 232
X-Correlation-ID: 786899437c4241a1
Deprecation: true
Link: <http://reportes-analitica:8000/api/v1/analitica/alertas-fraude>; rel="successor-version"
```

```json
{
  "error": {
    "codigo": 403,
    "tipo": "sin_permiso",
    "mensaje": "Tu rol no tiene permiso para esta operacion.",
    "detalles": {
      "rol": "Cliente",
      "roles_permitidos": [
        "Administrador",
        "Analista de Devoluciones"
      ]
    },
    "correlation_id": "786899437c4241a1"
  }
}
```

Verificaciones:

- ok: HTTP 403
- ok: tipo sin_permiso

