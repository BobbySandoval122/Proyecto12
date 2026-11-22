# Evidencia con curl - `analisis-auditoria`

Ejecutada en la VM el 2026-11-22 18:52 UTC con `scripts/evidencias/ejecutar.py auditoria` (commit `373321c`).
Casos: **32**, correctos: **32**, con falla: **0**. Los tokens y la contrasena de demo estan ocultos; la IP de la VM se muestra como `$VM_HOST`.

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
| [P4-AUD-26](#p4-aud-26) | correcto | 410 | retirada: clasificar motivo |
| [P4-AUD-27](#p4-aud-27) | correcto | 410 | retirada: alertas de fraude |
| [P4-AUD-28](#p4-aud-28) | correcto | 410 | retirada: Pareto |
| [P4-AUD-29](#p4-aud-29) | correcto | 410 | retirada: sincronizar |
| [P4-AUD-30](#p4-aud-30) | correcto | 410 | retirada: resumen |
| [P4-AUD-31](#p4-aud-31) | correcto | 410 | retirada: alias de eventos |
| [P4-AUD-32](#p4-aud-32) | correcto | 200 | la auditoria sigue en pie tras el corte |

## P4-AUD-01

**salud 200 con las tres dependencias**

Objetivo: El servicio informa PostgreSQL, Redis y MongoDB, y que el analisis esta retirado (RF-32).

Comando:

```bash
curl -sS -i -X GET "http://$VM_HOST:8008/health" \
  -H "Accept: application/json"
```

Respuesta - **200 OK** (20 ms, 208 bytes):

```http
Content-Type: application/json
Content-Length: 208
X-Correlation-ID: e097bf5a1a9a49d3
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
  "analisis": "retirado"
}
```

Verificaciones:

- ok: HTTP 200
- ok: estado ok
- ok: MongoDB ok
- ok: analisis retirado

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
X-Correlation-ID: f248d6c6d4a14ad8
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

Respuesta - **200 OK** (10 ms, 11452 bytes):

```http
Content-Type: application/json
Content-Length: 11452
X-Correlation-ID: 3e12b3b458aa4955
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

Respuesta - **401 UNAUTHORIZED** (10 ms, 162 bytes):

```http
Content-Type: application/json
Content-Length: 162
X-Correlation-ID: 62892beda9594b12
```

```json
{
  "error": {
    "codigo": 401,
    "tipo": "no_autenticado",
    "mensaje": "Falta el header 'Authorization: Bearer <token>'.",
    "detalles": null,
    "correlation_id": "62892beda9594b12"
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

Respuesta - **401 UNAUTHORIZED** (10 ms, 136 bytes):

```http
Content-Type: application/json
Content-Length: 136
X-Correlation-ID: 5544d186dd264a2e
```

```json
{
  "error": {
    "codigo": 401,
    "tipo": "token_invalido",
    "mensaje": "El token no es valido.",
    "detalles": null,
    "correlation_id": "5544d186dd264a2e"
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

Respuesta - **403 FORBIDDEN** (10 ms, 232 bytes):

```http
Content-Type: application/json
Content-Length: 232
X-Correlation-ID: 604735c260f345b3
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
    "correlation_id": "604735c260f345b3"
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

Respuesta - **403 FORBIDDEN** (10 ms, 235 bytes):

```http
Content-Type: application/json
Content-Length: 235
X-Correlation-ID: aefb4e72c9764109
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
    "correlation_id": "aefb4e72c9764109"
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

Respuesta - **200 OK** (25 ms, 2436 bytes):

```http
Content-Type: application/json
Content-Length: 2436
X-Correlation-ID: eb56e74e2eea4b56
```

```json
{
  "datos": [
    {
      "id": 1600,
      "accion": "login_api",
      "entidad": "usuarios",
      "entidad_id": 18,
      "detalle": "Inicio de sesion por API, JWT emitido",
      "correlation_id": "55b3e5948f0c407f",
      "fecha": "2026-11-22T18:52:58.541086+00:00",
      "usuario": "Pablo Flores"
    },
    {
      "id": 1599,
      "accion": "login_api",
      "entidad": "usuarios",
      "entidad_id": 40,
      "detalle": "Inicio de sesion por API, JWT emitido",
      "correlation_id": "0e0593c406e248d8",
      "fecha": "2026-11-22T18:52:58.416370+00:00",
      "usuario": "Jorge Salinas"
    },
    {
      "id": 1598,
      "accion": "login_api",
      "entidad": "usuarios",
      "entidad_id": 10,
      "detalle": "Inicio de sesion por API, JWT emitido",
      "correlation_id": "df89b9036840497d",
      "fecha": "2026-11-22T18:52:58.288007+00:00",
      "usuario": "Ana Lopez Garcia"
    },
    {
      "id": 1597,
      "accion": "logout_api",
      "entidad": "usuarios",
      "entidad_id": 10,
      "detalle": "Cierre de sesion por API: token y sesion revocados",
      "correlation_id": "4196f7d2cf41491f",
      "fecha": "2026-11-22T18:51:52.355809+00:00",
      "usuario": "Ana Lopez Garcia"
    },
    {
      "id": 1596,
      "accion": "logout_api",
      "entidad": "usuarios",
      "entidad_id": 18,
      "detalle": "Cierre de sesion por API: token y sesion revocados",
      "correlation_id": "8ea8e8cff5064c09",
      "fecha": "2026-11-22T18:51:52.342050+00:00",
      "usuario": "Pablo Flores"
    },
    {
      "id": 1595,
      "accion": "logout_api",
      "entidad": "usuarios",
      "entidad_id": 17,
      "detalle": "Cierre de sesion por API: token y sesion revocados",
      "correlation_id": "05f4441db07a4db1",
      "fecha": "2026-11-22T18:51:52.328638+00:00",
      "usuario": "Carla Trevino"
    },
    {
      "id": 1594,
      "accion": "logout_api",
      "entidad": "usuarios",
      "entidad_id": 13,
      "detalle": "Cierre de sesion por API: token y sesion revocados",
      "correlation_id": "ee331f8105e0481a",
      "fecha": "2026-11-22T18:51:52.315915+00:00",
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
1600
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

Respuesta - **200 OK** (25 ms, 1054 bytes):

```http
Content-Type: application/xml; charset=utf-8
Content-Length: 1054
X-Correlation-ID: 6ce3a7030d544a2a
```

```xml
<?xml version='1.0' encoding='utf-8'?>
<bitacora><datos><item><id>1601</id><accion>login_api</accion><entidad>usuarios</entidad><entidad_id>16</entidad_id><detalle>Inicio de sesion por API, JWT emitido</detalle><correlation_id>865aac8f85294361</correlation_id><fecha>2026-11-22T18:52:58.878389+00:00</fecha><usuario>Josue Berdeal</usuario></item><item><id>1600</id><accion>login_api</accion><entidad>usuarios</entidad><entidad_id>18</entidad_id><detalle>Inicio de sesion por API, JWT emitido</detalle><correlation_id>55b3e5948f0c407f</correlation_id><fecha>2026-11-22T18:52:58.541086+00:00</fecha><usuario>Pablo Flores</usuario></item><item><id>1599</id><accion>login_api</accion><entidad>usuarios</entidad><entidad_id>40</entidad_id><detalle>Inicio de sesion por API, JWT emitido</detalle><correlation_id>0e0593c406e248d8</correlation_id><fecha>2026-11-22T18:52:58.416370+00:00</fecha><usuario>Jorge Salinas</usuario></item></datos><paginacion><pagina>1</pagina><por_pagina>3</por_pagina><total>1601</total><paginas>534</paginas></paginacion></bitacora>
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
curl -sS -i -X GET "http://$VM_HOST:8008/api/v1/auditoria?correlation_id=4196f7d2cf41491f" \
  -H "Accept: application/json" \
  -H "Authorization: Bearer $TOKEN_ADMIN"
```

Respuesta - **200 OK** (23 ms, 318 bytes):

```http
Content-Type: application/json
Content-Length: 318
X-Correlation-ID: a8ed7d562d844369
```

```json
{
  "datos": [
    {
      "id": 1597,
      "accion": "logout_api",
      "entidad": "usuarios",
      "entidad_id": 10,
      "detalle": "Cierre de sesion por API: token y sesion revocados",
      "correlation_id": "4196f7d2cf41491f",
      "fecha": "2026-11-22T18:51:52.355809+00:00",
      "usuario": "Ana Lopez Garcia"
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
curl -sS -i -X GET "http://$VM_HOST:8008/api/v1/auditoria?usuario_id=10&por_pagina=20" \
  -H "Accept: application/json" \
  -H "Authorization: Bearer $TOKEN_ADMIN"
```

Respuesta - **200 OK** (22 ms, 4796 bytes):

```http
Content-Type: application/json
Content-Length: 4796
X-Correlation-ID: 8436ae522fe247d5
```

```json
{
  "datos": [
    {
      "id": 1598,
      "accion": "login_api",
      "entidad": "usuarios",
      "entidad_id": 10,
      "detalle": "Inicio de sesion por API, JWT emitido",
      "correlation_id": "df89b9036840497d",
      "fecha": "2026-11-22T18:52:58.288007+00:00",
      "usuario": "Ana Lopez Garcia"
    },
    {
      "id": 1597,
      "accion": "logout_api",
      "entidad": "usuarios",
      "entidad_id": 10,
      "detalle": "Cierre de sesion por API: token y sesion revocados",
      "correlation_id": "4196f7d2cf41491f",
      "fecha": "2026-11-22T18:51:52.355809+00:00",
      "usuario": "Ana Lopez Garcia"
    },
    {
      "id": 1560,
      "accion": "acceso_denegado",
      "entidad": "devoluciones",
      "entidad_id": 169,
      "detalle": "Intento de acceder a una devolucion de otro cliente (API)",
      "correlation_id": "9ed763f57291418d",
      "fecha": "2026-11-22T18:51:50.260184+00:00",
      "usuario": "Ana Lopez Garcia"
    },
    {
      "id": 1544,
      "accion": "logout_api",
      "entidad": "usuarios",
      "entidad_id": 10,
      "detalle": "Cierre de sesion por API: token y sesion revocados",
      "correlation_id": "45af126743284288",
      "fecha": "2026-11-22T18:51:49.248146+00:00",
      "usuario": "Ana Lopez Garcia"
    },
    {
      "id": 1539,
      "accion": "login_api",
      "entidad": "usuarios",
      "entidad_id": 10,
      "detalle": "Inicio de sesion por API, JWT emitido",
      "correlation_id": "b791caee16864dba",
      "fecha": "2026-11-22T18:51:48.977993+00:00",
      "usuario": "Ana Lopez Garcia"
    },
    {
      "id": 1531,
      "accion": "login_api",
      "entidad": "usuarios",
      "entidad_id": 10,
      "detalle": "Inicio de sesion por API, JWT emitido",
      "correlation_id": "34bb2d684e484260",
      "fecha": "2026-11-22T18:51:47.735221+00:00",
      "usuario": "Ana Lopez Garcia"
    },
    {
      "id": 1521,
      "accion": "logout_api",
      "entidad": "usuarios",
      "entidad_id": 10,
      "detalle": "Cierre de sesion por API: token y sesion revocados",
      "correlation_id": "add4825222bd4e76",
      "fecha": "2026-11-22T18:51:04.146045+00:00",
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

Respuesta - **200 OK** (24 ms, 1753 bytes):

```http
Content-Type: application/json
Content-Length: 1753
X-Correlation-ID: e8829bc62f91434f
```

```json
{
  "datos": [
    {
      "id": 1313,
      "accion": "autorizacion_operacion",
      "entidad": "usuarios",
      "entidad_id": 40,
      "detalle": "Autorizo cerrar_investigacion sobre 9",
      "correlation_id": "4190a90480a74cc4",
      "fecha": "2026-11-22T18:29:59.283348+00:00",
      "usuario": "Jorge Salinas"
    },
    {
      "id": 1128,
      "accion": "autorizacion_operacion",
      "entidad": "usuarios",
      "entidad_id": 17,
      "detalle": "Autorizo aprobar_reembolso sobre 999999",
      "correlation_id": "516a2ebbe3994372",
      "fecha": "2026-11-22T18:29:02.029354+00:00",
      "usuario": "Carla Trevino"
    },
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
... (recortado: 10 lineas mas)
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

Respuesta - **200 OK** (24 ms, 1224 bytes):

```http
Content-Type: application/json
Content-Length: 1224
X-Correlation-ID: 0783814c635340a5
```

```json
{
  "datos": [
    {
      "id": 1601,
      "accion": "login_api",
      "entidad": "usuarios",
      "entidad_id": 16,
      "detalle": "Inicio de sesion por API, JWT emitido",
      "correlation_id": "865aac8f85294361",
      "fecha": "2026-11-22T18:52:58.878389+00:00",
      "usuario": "Josue Berdeal"
    },
    {
      "id": 1600,
      "accion": "login_api",
      "entidad": "usuarios",
      "entidad_id": 18,
      "detalle": "Inicio de sesion por API, JWT emitido",
      "correlation_id": "55b3e5948f0c407f",
      "fecha": "2026-11-22T18:52:58.541086+00:00",
      "usuario": "Pablo Flores"
    },
    {
      "id": 1599,
      "accion": "login_api",
      "entidad": "usuarios",
      "entidad_id": 40,
      "detalle": "Inicio de sesion por API, JWT emitido",
      "correlation_id": "0e0593c406e248d8",
      "fecha": "2026-11-22T18:52:58.416370+00:00",
      "usuario": "Jorge Salinas"
    },
    {
      "id": 1598,
      "accion": "login_api",
      "entidad": "usuarios",
      "entidad_id": 10,
      "detalle": "Inicio de sesion por API, JWT emitido",
      "correlation_id": "df89b9036840497d",
      "fecha": "2026-11-22T18:52:58.288007+00:00",
      "usuario": "Ana Lopez Garcia"
    },
    {
      "id": 1597,
      "accion": "logout_api",
      "entidad": "usuarios",
      "entidad_id": 10,
      "detalle": "Cierre de sesion por API: token y sesion revocados",
      "correlation_id": "4196f7d2cf41491f",
      "fecha": "2026-11-22T18:51:52.355809+00:00",
      "usuario": "Ana Lopez Garcia"
    }
  ],
  "paginacion": {
    "pagina": 1,
    "por_pagina": 5,
    "total": 1601,
    "paginas": 321
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

Respuesta - **200 OK** (23 ms, 77 bytes):

```http
Content-Type: application/json
Content-Length: 77
X-Correlation-ID: cfaef1d050e54c05
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

Respuesta - **400 BAD REQUEST** (10 ms, 146 bytes):

```http
Content-Type: application/json
Content-Length: 146
X-Correlation-ID: cb8675ae3cbb4773
```

```json
{
  "error": {
    "codigo": 400,
    "tipo": "validacion",
    "mensaje": "desde debe tener formato AAAA-MM-DD.",
    "detalles": null,
    "correlation_id": "cb8675ae3cbb4773"
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
X-Correlation-ID: dcb28d20b0334d0e
```

```json
{
  "error": {
    "codigo": 400,
    "tipo": "validacion",
    "mensaje": "hasta no puede ser menor que desde.",
    "detalles": null,
    "correlation_id": "dcb28d20b0334d0e"
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

Respuesta - **400 BAD REQUEST** (10 ms, 149 bytes):

```http
Content-Type: application/json
Content-Length: 149
X-Correlation-ID: f6412d7cc1f04f56
```

```json
{
  "error": {
    "codigo": 400,
    "tipo": "validacion",
    "mensaje": "usuario_id debe ser un entero positivo.",
    "detalles": null,
    "correlation_id": "f6412d7cc1f04f56"
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

Respuesta - **400 BAD REQUEST** (11 ms, 140 bytes):

```http
Content-Type: application/json
Content-Length: 140
X-Correlation-ID: 4fb954b5315a4550
```

```json
{
  "error": {
    "codigo": 400,
    "tipo": "validacion",
    "mensaje": "Filtro accion demasiado largo.",
    "detalles": null,
    "correlation_id": "4fb954b5315a4550"
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

Respuesta - **405 METHOD NOT ALLOWED** (10 ms, 167 bytes):

```http
Content-Type: application/json
Content-Length: 167
X-Correlation-ID: 37100e7383b3493d
```

```json
{
  "error": {
    "codigo": 405,
    "tipo": "metodo_no_permitido",
    "mensaje": "The method is not allowed for the requested URL.",
    "detalles": null,
    "correlation_id": "37100e7383b3493d"
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
X-Correlation-ID: bb1ef08b233f4b95
```

```json
{
  "error": {
    "codigo": 404,
    "tipo": "no_encontrado",
    "mensaje": "The requested URL was not found on the server. If you entered the URL manually please check your spelling and try again.",
    "detalles": null,
    "correlation_id": "bb1ef08b233f4b95"
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

Respuesta - **200 OK** (23 ms, 358 bytes):

```http
Content-Type: application/json
Content-Length: 358
X-Correlation-ID: 1ee553c918054e87
```

```json
{
  "registros": 1601,
  "primero": "2026-09-06T23:20:35.290510+00:00",
  "ultimo": "2026-11-22T18:52:58.878389+00:00",
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

Respuesta - **200 OK** (13 ms, 1021 bytes):

```http
Content-Type: application/json
Content-Length: 1021
X-Correlation-ID: eea893cbf1984d4e
```

```json
{
  "datos": [
    {
      "id": "6b0337fab29f09f2d6b3b7cc",
      "servicio": "devoluciones",
      "tipo": "devolucion_registrada",
      "usuario_id": 11,
      "correlation_id": "6646b2aace514c2c",
      "fecha": "2026-11-22T18:44:10.938000+00:00"
    },
    {
      "id": "6b0337fa39e349dccf13fbe1",
      "servicio": "devoluciones",
      "tipo": "devolucion_registrada",
      "usuario_id": 11,
      "correlation_id": "25aeb7fa817a4425",
      "fecha": "2026-11-22T18:44:10.888000+00:00"
    },
    {
      "id": "6b03349864e8f88c00ab6b6d",
      "servicio": "integraciones-monitoreo",
      "tipo": "venta_importada",
      "usuario_id": 18,
      "correlation_id": "a9e29d4812964df0",
      "fecha": "2026-11-22T18:29:44.565000+00:00"
    },
    {
      "id": "6b033498a7125e1ee88f2f0b",
      "servicio": "integraciones-monitoreo",
      "tipo": "venta_importada",
      "usuario_id": 18,
      "correlation_id": "2b8829a81e724032",
      "fecha": "2026-11-22T18:29:44.494000+00:00"
    },
    {
      "id": "6b033498a7125e1ee88f2f0a",
      "servicio": "integraciones-monitoreo",
      "tipo": "venta_importada",
      "usuario_id": 18,
      "correlation_id": "448abad358df4dce",
      "fecha": "2026-11-22T18:29:44.405000+00:00"
    }
  ],
  "paginacion": {
    "pagina": 1,
    "por_pagina": 5,
    "total": 32,
    "paginas": 7
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

Respuesta - **200 OK** (12 ms, 77 bytes):

```http
Content-Type: application/json
Content-Length: 77
X-Correlation-ID: ddc681c2c70f4012
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

Respuesta - **200 OK** (12 ms, 652 bytes):

```http
Content-Type: application/xml; charset=utf-8
Content-Length: 652
X-Correlation-ID: 22d9e2518c894a82
```

```xml
<?xml version='1.0' encoding='utf-8'?>
<eventos><datos><item><id>6b0337fab29f09f2d6b3b7cc</id><servicio>devoluciones</servicio><tipo>devolucion_registrada</tipo><usuario_id>11</usuario_id><correlation_id>6646b2aace514c2c</correlation_id><fecha>2026-11-22T18:44:10.938000+00:00</fecha></item><item><id>6b0337fa39e349dccf13fbe1</id><servicio>devoluciones</servicio><tipo>devolucion_registrada</tipo><usuario_id>11</usuario_id><correlation_id>25aeb7fa817a4425</correlation_id><fecha>2026-11-22T18:44:10.888000+00:00</fecha></item></datos><paginacion><pagina>1</pagina><por_pagina>2</por_pagina><total>32</total><paginas>16</paginas></paginacion></eventos>
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

Respuesta - **400 BAD REQUEST** (10 ms, 142 bytes):

```http
Content-Type: application/json
Content-Length: 142
X-Correlation-ID: 63b94c6b5b874dfd
```

```json
{
  "error": {
    "codigo": 400,
    "tipo": "validacion",
    "mensaje": "Filtro servicio demasiado largo.",
    "detalles": null,
    "correlation_id": "63b94c6b5b874dfd"
  }
}
```

Verificaciones:

- ok: HTTP 400
- ok: tipo validacion

## P4-AUD-26

**retirada: clasificar motivo**

Objetivo: La clasificacion de motivos vive ahora en clasificacion-motivos (8010). Esta ruta responde 410 aun sin token y dice donde.

Comando:

```bash
curl -sS -i -X POST "http://$VM_HOST:8008/api/v1/analisis/clasificar-motivo" \
  -H "Accept: application/json" \
  -H "Content-Type: application/json" \
  -d '{"descripcion":"El producto llego con el empaque roto"}'
```

Respuesta - **410 GONE** (9 ms, 455 bytes):

```http
Content-Type: application/json
Content-Length: 455
X-Correlation-ID: 816331a09b2d4f80
Deprecation: true
Link: <http://clasificacion-motivos:8000/api/v1/motivos/sugerencias>; rel="successor-version"
```

```json
{
  "error": {
    "codigo": 410,
    "tipo": "servicio_movido",
    "mensaje": "El analisis ya no se ofrece en analisis-auditoria; solo queda la auditoria.",
    "detalles": {
      "clasificar-motivo": "http://clasificacion-motivos:8000/api/v1/motivos/sugerencias",
      "alertas-fraude": "http://reportes-analitica:8000/api/v1/analitica/alertas-fraude",
      "pareto": "http://reportes-analitica:8000/api/v1/reportes/pareto",
      "eventos": "/api/v1/auditoria/eventos"
    },
    "correlation_id": "816331a09b2d4f80"
  }
}
```

Verificaciones:

- ok: HTTP 410
- ok: 410 servicio_movido
- ok: nombra al sucesor
- ok: lleva Deprecation: true

## P4-AUD-27

**retirada: alertas de fraude**

Objetivo: Las alertas de fraude viven en reportes-analitica (8018). Ni un Analista con token las obtiene aqui.

Comando:

```bash
curl -sS -i -X GET "http://$VM_HOST:8008/api/v1/analisis/alertas-fraude" \
  -H "Accept: application/json" \
  -H "Authorization: Bearer $TOKEN_ANALISTA"
```

Respuesta - **410 GONE** (10 ms, 455 bytes):

```http
Content-Type: application/json
Content-Length: 455
X-Correlation-ID: 56b0d6a4be8e42af
Deprecation: true
Link: <http://reportes-analitica:8000/api/v1/analitica/alertas-fraude>; rel="successor-version"
```

```json
{
  "error": {
    "codigo": 410,
    "tipo": "servicio_movido",
    "mensaje": "El analisis ya no se ofrece en analisis-auditoria; solo queda la auditoria.",
    "detalles": {
      "clasificar-motivo": "http://clasificacion-motivos:8000/api/v1/motivos/sugerencias",
      "alertas-fraude": "http://reportes-analitica:8000/api/v1/analitica/alertas-fraude",
      "pareto": "http://reportes-analitica:8000/api/v1/reportes/pareto",
      "eventos": "/api/v1/auditoria/eventos"
    },
    "correlation_id": "56b0d6a4be8e42af"
  }
}
```

Verificaciones:

- ok: HTTP 410
- ok: 410 servicio_movido
- ok: nombra al sucesor
- ok: lleva Deprecation: true

## P4-AUD-28

**retirada: Pareto**

Objetivo: El Pareto vive en reportes-analitica (8018), calculado directo en PostgreSQL.

Comando:

```bash
curl -sS -i -X GET "http://$VM_HOST:8008/api/v1/analisis/pareto?dimension=motivo" \
  -H "Accept: application/json" \
  -H "Authorization: Bearer $TOKEN_ANALISTA"
```

Respuesta - **410 GONE** (9 ms, 455 bytes):

```http
Content-Type: application/json
Content-Length: 455
X-Correlation-ID: d3fee30e5697496c
Deprecation: true
Link: <http://reportes-analitica:8000/api/v1/reportes/pareto>; rel="successor-version"
```

```json
{
  "error": {
    "codigo": 410,
    "tipo": "servicio_movido",
    "mensaje": "El analisis ya no se ofrece en analisis-auditoria; solo queda la auditoria.",
    "detalles": {
      "clasificar-motivo": "http://clasificacion-motivos:8000/api/v1/motivos/sugerencias",
      "alertas-fraude": "http://reportes-analitica:8000/api/v1/analitica/alertas-fraude",
      "pareto": "http://reportes-analitica:8000/api/v1/reportes/pareto",
      "eventos": "/api/v1/auditoria/eventos"
    },
    "correlation_id": "d3fee30e5697496c"
  }
}
```

Verificaciones:

- ok: HTTP 410
- ok: 410 servicio_movido
- ok: nombra al sucesor
- ok: lleva Deprecation: true

## P4-AUD-29

**retirada: sincronizar**

Objetivo: Sincronizar ya no hace falta: 8018 calcula directo en PostgreSQL y siempre esta al dia. No escribe nada.

Comando:

```bash
curl -sS -i -X POST "http://$VM_HOST:8008/api/v1/analisis/sincronizar" \
  -H "Accept: application/json" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN_ANALISTA" \
  -d '{}'
```

Respuesta - **410 GONE** (10 ms, 455 bytes):

```http
Content-Type: application/json
Content-Length: 455
X-Correlation-ID: 2ccbf572798b4850
Deprecation: true
```

```json
{
  "error": {
    "codigo": 410,
    "tipo": "servicio_movido",
    "mensaje": "El analisis ya no se ofrece en analisis-auditoria; solo queda la auditoria.",
    "detalles": {
      "clasificar-motivo": "http://clasificacion-motivos:8000/api/v1/motivos/sugerencias",
      "alertas-fraude": "http://reportes-analitica:8000/api/v1/analitica/alertas-fraude",
      "pareto": "http://reportes-analitica:8000/api/v1/reportes/pareto",
      "eventos": "/api/v1/auditoria/eventos"
    },
    "correlation_id": "2ccbf572798b4850"
  }
}
```

Verificaciones:

- ok: HTTP 410
- ok: 410 servicio_movido

## P4-AUD-30

**retirada: resumen**

Objetivo: El resumen solo contaba snapshots y no tiene sucesor.

Comando:

```bash
curl -sS -i -X GET "http://$VM_HOST:8008/api/v1/analisis/resumen" \
  -H "Accept: application/json" \
  -H "Authorization: Bearer $TOKEN_ANALISTA"
```

Respuesta - **410 GONE** (9 ms, 455 bytes):

```http
Content-Type: application/json
Content-Length: 455
X-Correlation-ID: d93dcc6c31a14ea3
Deprecation: true
```

```json
{
  "error": {
    "codigo": 410,
    "tipo": "servicio_movido",
    "mensaje": "El analisis ya no se ofrece en analisis-auditoria; solo queda la auditoria.",
    "detalles": {
      "clasificar-motivo": "http://clasificacion-motivos:8000/api/v1/motivos/sugerencias",
      "alertas-fraude": "http://reportes-analitica:8000/api/v1/analitica/alertas-fraude",
      "pareto": "http://reportes-analitica:8000/api/v1/reportes/pareto",
      "eventos": "/api/v1/auditoria/eventos"
    },
    "correlation_id": "d93dcc6c31a14ea3"
  }
}
```

Verificaciones:

- ok: HTTP 410
- ok: 410 servicio_movido

## P4-AUD-31

**retirada: alias de eventos**

Objetivo: La traza por correlation id es auditoria: el sucesor es /api/v1/auditoria/eventos, que sigue en 200 (ver arriba).

Comando:

```bash
curl -sS -i -X GET "http://$VM_HOST:8008/api/v1/analisis/eventos?por_pagina=2" \
  -H "Accept: application/json" \
  -H "Authorization: Bearer $TOKEN_ADMIN"
```

Respuesta - **410 GONE** (9 ms, 455 bytes):

```http
Content-Type: application/json
Content-Length: 455
X-Correlation-ID: 9d3f2e4cd58e4dd3
Deprecation: true
Link: </api/v1/auditoria/eventos>; rel="successor-version"
```

```json
{
  "error": {
    "codigo": 410,
    "tipo": "servicio_movido",
    "mensaje": "El analisis ya no se ofrece en analisis-auditoria; solo queda la auditoria.",
    "detalles": {
      "clasificar-motivo": "http://clasificacion-motivos:8000/api/v1/motivos/sugerencias",
      "alertas-fraude": "http://reportes-analitica:8000/api/v1/analitica/alertas-fraude",
      "pareto": "http://reportes-analitica:8000/api/v1/reportes/pareto",
      "eventos": "/api/v1/auditoria/eventos"
    },
    "correlation_id": "9d3f2e4cd58e4dd3"
  }
}
```

Verificaciones:

- ok: HTTP 410
- ok: 410 servicio_movido
- ok: nombra al sucesor
- ok: lleva Deprecation: true

## P4-AUD-32

**la auditoria sigue en pie tras el corte**

Objetivo: Retirar el analisis no toca la auditoria: la separacion que pidio el profe.

Comando:

```bash
curl -sS -i -X GET "http://$VM_HOST:8008/api/v1/auditoria/estado" \
  -H "Accept: application/json" \
  -H "Authorization: Bearer $TOKEN_ANALISTA"
```

Respuesta - **200 OK** (23 ms, 358 bytes):

```http
Content-Type: application/json
Content-Length: 358
X-Correlation-ID: ce3b69f5278b4a0b
```

```json
{
  "registros": 1601,
  "primero": "2026-09-06T23:20:35.290510+00:00",
  "ultimo": "2026-11-22T18:52:58.878389+00:00",
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

