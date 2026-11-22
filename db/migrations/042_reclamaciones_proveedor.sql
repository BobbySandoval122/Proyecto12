-- =============================================================================
-- Migracion 042: reclamaciones a proveedores y su seguimiento
-- Motivo: cuando varias devoluciones apuntan a un mismo proveedor o lote, la
--   empresa debe poder reclamarle, dar seguimiento hasta que responda y saber
--   cuanto se recupero. Hasta ahora el proveedor solo existia como catalogo
--   (001) sin ningun registro de lo que se le reclama (dominio 13 del tercer
--   parcial).
--   - reclamaciones_proveedor: la reclamacion, con folio generado por la base
--     (como en devoluciones, 007) para que dos personas no repitan folio.
--   - reclamacion_devoluciones: que casos respaldan la reclamacion. Una
--     devolucion no puede estar en dos reclamaciones abiertas; eso cruza dos
--     tablas, asi que lo valida el servicio bloqueando las devoluciones.
--   - seguimiento_reclamacion: bitacora propia e inmutable de cada cambio de
--     estado, con comentario y responsable; de ahi salen los tiempos de
--     respuesta del proveedor.
--   Los montos son informativos: el reembolso al cliente sigue en reembolsos.
-- Trazabilidad: RF-23, RF-24, RF-26, RF-27, RN-09, RN-12, RF-30
-- Rango de migraciones de Persona 4: 040-049 (docs/PUERTOS.md)
-- =============================================================================

CREATE SEQUENCE IF NOT EXISTS seq_folio_reclamacion START 1;

CREATE OR REPLACE FUNCTION fn_nuevo_folio_reclamacion()
RETURNS VARCHAR AS $$
    SELECT 'RCL-' || to_char(CURRENT_DATE, 'YYYY') || '-' ||
           lpad(nextval('seq_folio_reclamacion')::text, 4, '0');
$$ LANGUAGE sql;

CREATE TABLE IF NOT EXISTS reclamaciones_proveedor (
    id                      SERIAL PRIMARY KEY,
    folio                   VARCHAR(30) NOT NULL UNIQUE DEFAULT fn_nuevo_folio_reclamacion(),
    proveedor_id            INTEGER NOT NULL REFERENCES proveedores(id) ON DELETE RESTRICT,
    lote_id                 INTEGER REFERENCES lotes(id) ON DELETE RESTRICT,
    asunto                  VARCHAR(150) NOT NULL,
    descripcion             TEXT NOT NULL,
    estado                  VARCHAR(20) NOT NULL DEFAULT 'abierta'
        CHECK (estado IN ('abierta', 'enviada', 'en_analisis', 'respondida', 'cerrada')),
    resolucion              VARCHAR(20)
        CHECK (resolucion IN ('aceptada', 'parcial', 'rechazada', 'retirada')),
    monto_reclamado         NUMERIC(12, 2) CHECK (monto_reclamado IS NULL OR monto_reclamado >= 0),
    monto_recuperado        NUMERIC(12, 2) CHECK (monto_recuperado IS NULL OR monto_recuperado >= 0),
    fecha_limite_respuesta  DATE,
    creada_por              INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE RESTRICT,
    fecha_creacion          TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    fecha_cierre            TIMESTAMPTZ,
    -- Una reclamacion cerrada siempre dice como termino, y una abierta no (RN-12).
    CONSTRAINT ck_reclamacion_cierre CHECK (
        (estado = 'cerrada' AND resolucion IS NOT NULL AND fecha_cierre IS NOT NULL)
     OR (estado <> 'cerrada' AND resolucion IS NULL AND fecha_cierre IS NULL)),
    CONSTRAINT ck_reclamacion_recuperado CHECK (
        monto_recuperado IS NULL OR monto_reclamado IS NULL OR monto_recuperado <= monto_reclamado)
);
COMMENT ON TABLE reclamaciones_proveedor IS 'Reclamacion formal a un proveedor por devoluciones de sus lotes (RF-24). Los montos son informativos.';

CREATE TABLE IF NOT EXISTS reclamacion_devoluciones (
    reclamacion_id  INTEGER NOT NULL REFERENCES reclamaciones_proveedor(id) ON DELETE RESTRICT,
    devolucion_id   INTEGER NOT NULL REFERENCES devoluciones(id) ON DELETE RESTRICT,
    PRIMARY KEY (reclamacion_id, devolucion_id)
);
COMMENT ON TABLE reclamacion_devoluciones IS 'Devoluciones que respaldan una reclamacion.';
CREATE INDEX IF NOT EXISTS idx_reclamacion_dev_devolucion ON reclamacion_devoluciones (devolucion_id);

CREATE TABLE IF NOT EXISTS seguimiento_reclamacion (
    id               SERIAL PRIMARY KEY,
    reclamacion_id   INTEGER NOT NULL REFERENCES reclamaciones_proveedor(id) ON DELETE RESTRICT,
    estado_anterior  VARCHAR(20),
    estado_nuevo     VARCHAR(20) NOT NULL,
    comentario       VARCHAR(500),
    usuario_id       INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE RESTRICT,
    fecha            TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
COMMENT ON TABLE seguimiento_reclamacion IS 'Linea de tiempo inmutable de cada reclamacion; de aqui salen los tiempos de respuesta del proveedor.';
CREATE INDEX IF NOT EXISTS idx_seguimiento_reclamacion ON seguimiento_reclamacion (reclamacion_id, fecha);

CREATE INDEX IF NOT EXISTS idx_reclamaciones_proveedor ON reclamaciones_proveedor (proveedor_id, estado);
CREATE INDEX IF NOT EXISTS idx_reclamaciones_lote ON reclamaciones_proveedor (lote_id) WHERE lote_id IS NOT NULL;
