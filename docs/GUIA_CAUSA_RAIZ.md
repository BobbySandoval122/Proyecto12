# Guia de causa raiz y acciones correctivas (para la web y la app de escritorio)

Servicio `causa-raiz`, puerto **8011**. Swagger: `http://<IP-VM>:8011/docs`.
Responde JSON o XML segun `Accept`; las peticiones en XML se validan con los XSD
de `http://<IP-VM>:8011/contratos/<archivo>.xsd`.

La app de escritorio solo muestra la pantalla de investigaciones y acciones
correctivas: los datos y las reglas viven aqui. **El analisis apoya; cada paso
lo decide una persona** (RN-09, RN-11).

## Quien puede que

| Operacion | Roles |
|---|---|
| Alertas, investigaciones, hipotesis, evidencias, conclusion, crear acciones y medir | Administrador, Analista, Supervisor |
| Cerrar una investigacion | **Solo Supervisor**, distinto del analista, con reconfirmacion de contrasena |
| Ver y mover **sus** acciones CAPA | Cualquier rol interno que sea el responsable |

Una accion ajena responde 404 (no revela que existe).

## Los 9 pasos y el endpoint de cada uno

| Paso | Que pasa | Endpoint (bajo `/api/v1/causa-raiz`) |
|---|---|---|
| 1 | El sistema detecta un patron raro | `POST /alertas/detectar` |
| 2 | Genera una alerta que propone investigar | `GET /alertas` |
| 3 | Una persona abre la investigacion y junta evidencia | `POST /alertas/{id}/investigar` o `POST /investigaciones`; `POST /investigaciones/{id}/evidencias` |
| 4 | Se escriben hipotesis | `POST /investigaciones/{id}/hipotesis` |
| 5 | Se verifican con mas informacion | `POST /investigaciones/{id}/verificacion`; `POST /investigaciones/{id}/hipotesis/{hid}/verificacion` |
| 6 | Causa confirmada o inconclusa | `POST /investigaciones/{id}/conclusion` |
| 7 | Plan CAPA con responsable y fecha | `POST /investigaciones/{id}/acciones`; `POST /acciones/{id}/estado` |
| 8 | Se mide si funciono | `POST /acciones/{id}/mediciones` |
| 9 | Un supervisor cierra | `POST /investigaciones/{id}/cierre` |

`GET /investigaciones/{id}` devuelve todo el expediente: hipotesis, evidencias,
acciones con su ultimo veredicto y la linea de tiempo. `GET /investigaciones` y
`GET /acciones` (con `vencidas=true`) alimentan el panel de trabajo.

## Estados de una investigacion

```
abierta -> en_verificacion -> concluida -> en_accion -> en_medicion -> cerrada
                                  |                                       ^
                                  +--- (inconclusa) ----------------------+
```

- No se salta ningun paso: pedirlo responde **409** `transicion_invalida`.
- Una investigacion **inconclusa** se cierra directo desde `concluida`, o se
  reabre con `POST /reabrir` si aparece mas informacion.
- Un lote, proveedor, tienda o producto no puede tener **dos investigaciones sin
  cerrar** (409 `investigacion_activa`).

## Reglas que la pantalla debe anticipar

- **Alertas.** Exigen una tasa de al menos 2 veces el promedio, 20 unidades
  vendidas y 3 casos. Detectar de nuevo actualiza las abiertas, no las duplica.
  Una alerta se **descarta con comentario** o se convierte en investigacion; nunca
  se abre una investigacion sola.
- **Evidencia.** Es inmutable: no se edita ni se borra. Una devolucion citada
  debe pertenecer al objeto investigado (409 `devolucion_ajena`). Solo se agrega
  mientras la investigacion esta `abierta` o `en_verificacion`.
- **Cinco porques.** No se manda el nivel: sin `padre_id` es el nivel 1; con
  `padre_id`, el siguiente. Maximo 5 y sin ramificar (cada porque tiene una sola
  continuacion). **Ishikawa** exige `categoria_ishikawa`: material, metodo,
  maquina, mano_de_obra, medicion o medio_ambiente.
- **Confirmar una causa** exige `causa_raiz`, al menos una evidencia y una
  hipotesis verificada. Una conclusion inconclusa no declara causa.
- **Acciones CAPA.** Solo con causa confirmada. El responsable debe ser personal
  interno activo y la fecha compromiso no puede ser pasada. `meta_reduccion_pct`
  por omision es 30. Implementar fija la fecha desde la que se mide.
- **Cierre.** No hay acciones pendientes (`planificada` o `en_curso`) ni
  implementadas sin medir. El `veredicto_final` no esconde lo que fallo: una sola
  accion `no_efectiva` hace no efectiva toda la investigacion.

## Como se mide si funciono (paso 8)

Se compara la **tasa de devolucion de lo vendido** en los `ventana_antes_dias`
(90 por omision) previos a la implementacion contra lo vendido desde la
implementacion. Se cuenta por **cohorte de venta**: una devolucion que llega
semanas despues se suma a su venta.

- **"Despues" se corta en hoy menos el plazo maximo de devolucion** (30 dias,
  RN-16). Lo vendido en los ultimos dias aun puede devolverse y contarlo haria ver
  mejor de lo que es. Si la implementacion es tan reciente que no queda nada
  maduro, el veredicto es `sin_datos`.
- **Menos de 20 unidades vendidas** en alguno de los periodos, o ninguna
  devolucion antes: `sin_datos`. **Nunca `efectiva`.**
- `efectiva` si la reduccion alcanza la meta; si no, `no_efectiva` (una tasa que
  empeora da reduccion negativa).
- Se puede medir varias veces; **la ultima manda**. Cada medicion queda guardada
  con sus periodos y unidades.
- Un buen resultado orienta, no prueba causalidad.

## Cerrar una investigacion (operacion critica)

El cierre exige reconfirmar la contrasena del supervisor. La pantalla debe:

1. Pedir la contrasena y llamar a `POST http://<IP-VM>:8001/api/v1/auth/autorizar-operacion`
   con `{"operacion": "cerrar_investigacion", "recurso_id": "<id de la investigacion>", "password": "..."}`.
2. Mandar el `token_operacion` recibido en el header `X-Autorizacion-Operacion`
   al llamar a `POST /investigaciones/{id}/cierre`.

El permiso vale **una sola vez**, para esa investigacion, durante 5 minutos. Sin
el header: 403 `autorizacion_operacion_requerida`. Si quien cierra es el analista
de la investigacion: 409 `cierre_independiente`. El servicio valida las reglas de
negocio antes de consumir el permiso, asi que un 409 no obliga a reconfirmar.

## Ejemplo (JSON)

```json
POST /api/v1/causa-raiz/investigaciones/12/hipotesis
{"tipo": "cinco_porques", "descripcion": "El camion llego con la caja a 14 grados"}

POST /api/v1/causa-raiz/investigaciones/12/hipotesis
{"tipo": "cinco_porques", "padre_id": 31, "descripcion": "El refrigerador del camion 4 estaba averiado"}

POST /api/v1/causa-raiz/investigaciones/12/acciones
{"tipo": "correctiva", "descripcion": "Reemplazar el contrato de transporte",
 "responsable_id": 8, "fecha_compromiso": "2026-12-15", "meta_reduccion_pct": "40"}
```

El mismo cuerpo en XML (`Content-Type: application/xml`):

```xml
<accion>
  <tipo>correctiva</tipo>
  <descripcion>Reemplazar el contrato de transporte</descripcion>
  <responsable_id>8</responsable_id>
  <fecha_compromiso>2026-12-15</fecha_compromiso>
  <meta_reduccion_pct>40</meta_reduccion_pct>
</accion>
```

## Lo que este servicio no hace todavia

- **No notifica.** Avisar al responsable de una accion o al supervisor de un
  cierre pendiente le tocara al servicio de notificaciones (8017). Mientras tanto,
  los responsables consultan `GET /acciones`.
- **No hay un reloj propio.** La deteccion de patrones se dispara con
  `POST /alertas/detectar`; programarla periodicamente es trabajo del monitoreo.
- Las investigaciones por **ruta** no estan soportadas: una ruta no tiene unidades
  vendidas contra las cuales medir una tasa (ver `ventas-catalogos`, `/trazabilidad/tasas`).
