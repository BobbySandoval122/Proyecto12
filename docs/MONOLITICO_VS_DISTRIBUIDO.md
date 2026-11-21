# Consistencia entre el modo monolitico y el distribuido

Correccion de la retroalimentacion del segundo parcial: demostrar que la web
(monolito) y los microservicios aplican **las mismas reglas** y que la caida de
una API **no duplica** operaciones.

## Los tres caminos

| Camino | Quien lo usa | Como escribe |
|---|---|---|
| Web, modo monolitico (`USE_MICROSERVICES=false`) | Navegador | Directo en PostgreSQL desde `apps/web` |
| Web, modo distribuido (`USE_MICROSERVICES=true`, el de la entrega) | Navegador | La web llama al microservicio (`apps/web/app/api_client.py`) |
| API directa | Apps Android y de escritorio, otros sistemas | El microservicio escribe en PostgreSQL |

Los tres comparten **una sola base** PostgreSQL. Eso da la primera garantia: las
restricciones de la base (llaves unicas, `CHECK`, llaves foraneas, folio
generado por la base) protegen a los tres caminos por igual.

## Donde vive cada regla

| Regla | Monolito (web) | Distribuido (servicio) | Por que no se separan |
|---|---|---|---|
| RN-01 toda devolucion nace de una linea de venta | `devoluciones.nueva` | `devoluciones.registrar` | Llave foranea `venta_detalle_id` NOT NULL |
| RN-02 folio unico | La base | La base | Lo genera PostgreSQL (`folio_devolucion` UNIQUE) |
| RN-16 plazo 30/7 dias | Consulta `politicas_devolucion` | `_exigir_plazo` lee `politicas_devolucion` | El plazo esta en **una tabla**, no en el codigo de cada lado |
| RN-16 una solicitud abierta por linea y motivo | Consulta antes de insertar | `_exigir_no_duplicada` | Misma consulta |
| RF-07 cantidad no mayor a la disponible | Calcula `disponible` | `_exigir_cantidad` | Misma resta sobre `devoluciones` |
| Descripcion de 10 a 2000 caracteres | `MAX_DESCRIPCION = 2000` | `reglas.MAX_DESCRIPCION` | Corregido en esta entrega (ver abajo) |
| Motivo existente y activo | Consulta `motivos` | `_exigir_motivo` | Corregido en esta entrega (ver abajo) |
| RN-13 un cliente solo devuelve sus compras | `abort(403)` | 403 `sin_permiso` | Mismo criterio: `ventas.cliente_id` |
| RN-13 roles de campo | La web no los admite (403) | Solo los endpoints que los nombran | `shared/seguridad.py` y `apps/web/app/security.py` |

## Prueba automatica de paridad

`apps/web/app/tests/test_paridad.py` manda **la misma solicitud por los tres
caminos** contra la base y los servicios reales y exige la misma decision:

| Caso | Web monolitica | Web distribuida | API |
|---|---|---|---|
| Solicitud valida | aceptada | aceptada | aceptada |
| Duplicada (RN-16) | duplicada | duplicada | duplicada |
| Fuera de plazo (RN-16) | fuera de plazo | fuera de plazo | fuera de plazo |
| Cantidad excedida | cantidad | cantidad | cantidad |
| Descripcion corta | descripcion | descripcion | descripcion |
| Descripcion de mas de 2000 | descripcion | descripcion | descripcion |
| Motivo inexistente | motivo | motivo | motivo |
| Compra de otro cliente (RN-13) | 403 | 403 | 403 |

**La prueba encontro dos diferencias reales** en su primera corrida y se
corrigieron en `apps/web/app/blueprints/devoluciones.py`:

1. El monolito **aceptaba** descripciones de mas de 2000 caracteres que la API rechaza.
2. Con un motivo inexistente el monolito respondia **500**; la API, 400.

Salida de las dos corridas: [`pruebas/paridad_2026-11-20.txt`](pruebas/paridad_2026-11-20.txt).
La prueba forma parte de `bash scripts/correr_e2e.sh` (bloque `paridad`).

## Si una API se cae: no se duplica nada

| Situacion | Que pasa | Que evita el duplicado |
|---|---|---|
| La web (modo distribuido) no alcanza al servicio | La web muestra "servicio no disponible" (503) y **no escribe por su cuenta**: no hay "plan B" que inserte directo | Un solo camino de escritura por modo |
| El servicio guardo pero la respuesta se perdio, y el usuario reintenta | El reintento responde 409 `solicitud_duplicada` | RN-16: una solicitud abierta por linea y motivo |
| La app Android reenvia una operacion offline | Responde `repetida: true`, no la aplica otra vez | `id_operacion` como llave primaria (`operaciones_offline`) |
| El POS reenvia un ticket | Responde la venta existente | Llave `(sistema, tipo, id_externo)` en `integraciones_ids` |
| Se cae PostgreSQL | Los servicios responden 503; nada queda a medias | Transaccion por peticion: sin commit no hay cambio |

### Prueba de recuperacion

`scripts/prueba_recuperacion.py` (se corre en la VM) tumba servicios a proposito:

1. **Mata** el servicio de devoluciones despues de confirmar una solicitud. Al volver, la solicitud existe y el reintento responde 409: sigue habiendo una.
2. **Mata** el servicio de sincronizacion. La app reenvia la misma operacion: `repetida`, una sola evidencia.
3. **Detiene PostgreSQL.** Los servicios responden 503, el monitoreo abre la alerta `base_no_disponible`; al volver, los datos confirmados siguen y la alerta se resuelve sola.
4. **Reinicia Redis.** La sesion del usuario sobrevive (Redis con `appendonly`).

Resultado del 2026-11-20: **18 de 18 comprobaciones OK**.
Salida: [`pruebas/recuperacion_2026-11-20.txt`](pruebas/recuperacion_2026-11-20.txt).
