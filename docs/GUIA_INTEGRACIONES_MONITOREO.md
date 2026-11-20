# Guia de integraciones y monitoreo (servicio 8021)

Servicio `integraciones-monitoreo`, puerto **8021**. Swagger: `http://<IP-VM>:8021/docs`.
Dominios 21 (integraciones) y 22 (monitoreo) de la retroalimentacion.

## Integraciones

Todo acepta JSON o XML (validado con XSD en `services/integraciones_monitoreo/contratos/`).

### Conciliacion de identificadores

Cada sistema externo usa sus propios ids. Antes de integrar, el Administrador
registra la equivalencia:

```json
POST /api/v1/integraciones/conciliaciones
{"sistema": "pos", "tipo_entidad": "tienda", "id_externo": "T-001", "id_interno": 3}
```

- `sistema`: pos, erp, wms, transportista, financiero.
- `tipo_entidad`: tienda, venta, producto, devolucion, recoleccion.
- Si un id externo llega sin equivalencia, la respuesta es `422 sin_conciliar`
  y dice exactamente que falta.
- Traducir: `GET /api/v1/integraciones/conciliaciones/pos/tienda/T-001`.

### POS: importar ventas

```json
POST /api/v1/integraciones/ventas
{"id_externo": "TK-88123", "tienda_externa": "T-001", "cliente_email": "cliente@demo.mx",
 "fecha_venta": "2026-11-20",
 "lineas": [{"sku": "LEC-001", "numero_lote": "L-2026-11", "cantidad": 2, "precio_unitario": 32.50}]}
```

**Idempotente:** el mismo ticket dos veces devuelve la misma venta con
`repetida: true` (200), nunca una segunda venta. La venta queda con folio
`POS-<ticket>` y conciliada como `pos/venta/<ticket>`.

### ERP y sistemas financieros: exportar devoluciones

`GET /api/v1/integraciones/exportaciones/devoluciones?desde=2026-11-01&hasta=2026-11-30`

Con `Accept: application/xml` sale en XML. Cada fila trae folio, estado, producto,
lote, reembolso, costo total y los ids del POS (`venta_id_pos`) y del ERP
(`devolucion_id_erp`) para que el otro sistema concilie.

### Transportistas

```json
POST /api/v1/integraciones/transportistas/eventos
{"guia": "DHL-9981", "estado": "en_transito"}
```

La guia se concilia antes como `transportista/recoleccion`. Reenviar el mismo
evento responde `cambio: false`: no se aplica dos veces.

## Monitoreo (Administrador y Supervisor)

| Endpoint | Que muestra |
|---|---|
| `GET /api/v1/monitoreo/estado` | Chequeo ahora: cada servicio (estado y ms), PostgreSQL, Redis, MongoDB y la cola de sincronizacion |
| `GET /api/v1/monitoreo/disponibilidad?horas=24` | Por servicio: % disponible, tiempo promedio, p95 y fallas |
| `GET /api/v1/monitoreo/alertas?estado=activa` | Alertas operativas |
| `GET /api/v1/monitoreo/traza/<correlation_id>` | Todo lo que paso en todos los servicios con ese `X-Correlation-ID` |

- El servicio se revisa solo **cada 60 segundos** (`MONITOREO_INTERVALO_SEG`).
  Un candado en Redis evita que los dos workers revisen a la vez.
- **Alertas:** servicio caido (alta), servicio degradado, respuesta mayor a
  1500 ms, base no disponible (alta) y mas de 10 conflictos de sincronizacion
  en 24 h. Hay una sola alerta activa por problema (cuenta las veces) y **se
  resuelve sola** cuando el recurso vuelve a estar bien.
- El historial de chequeos se borra solo a los 7 dias (indice TTL en MongoDB).

### Para agregar el servicio de un compañero al monitoreo

Agregar `nombre=http://<servicio-compose>:8000` a la variable
`MONITOREO_SERVICIOS` (o a `SERVICIOS_DEFECTO` en `monitor.py`). Solo necesita
un `GET /health` que responda `{"estado": "ok", "dependencias": {...}}`, como
los demas.
