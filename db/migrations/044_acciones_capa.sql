-- =============================================================================
-- Migracion 044: acciones correctivas y preventivas (CAPA) y su medicion
-- Motivo: confirmar una causa no sirve si nadie la corrige ni se comprueba que
--   la correccion funciono. Cada accion CAPA tiene responsable y fecha
--   compromiso, y su eficacia se mide comparando la tasa de devolucion de lo
--   vendido ANTES de implementarla contra lo vendido DESPUES (dominio 11-12 del
--   tercer parcial, pasos 7 y 8 del flujo del profe).
--   - acciones_capa: el plan. implementada exige fecha de implementacion, porque
--     de ella parte la comparacion.
--   - mediciones_eficacia: inmutables. Se guardan ambos periodos, sus unidades y
--     el veredicto; si hay pocas ventas el veredicto es sin_datos y nunca
--     "efectiva". Se puede medir varias veces: la ultima manda.
-- Trazabilidad: RF-24, RF-26, RN-09, RN-12, RF-30
-- Rango de migraciones de Persona 4: 040-049 (docs/PUERTOS.md)
-- =============================================================================

CREATE SEQUENCE IF NOT EXISTS seq_folio_capa START 1;

CREATE OR REPLACE FUNCTION fn_nuevo_folio_capa()
RETURNS VARCHAR AS $$
    SELECT 'CAPA-' || to_char(CURRENT_DATE, 'YYYY') || '-' ||
           lpad(nextval('seq_folio_capa')::text, 4, '0');
$$ LANGUAGE sql;

CREATE TABLE IF NOT EXISTS acciones_capa (
    id                      SERIAL PRIMARY KEY,
    folio                   VARCHAR(30) NOT NULL UNIQUE DEFAULT fn_nuevo_folio_capa(),
    investigacion_id        INTEGER NOT NULL REFERENCES investigaciones(id) ON DELETE RESTRICT,
    tipo                    VARCHAR(20) NOT NULL CHECK (tipo IN ('correctiva', 'preventiva')),
    descripcion             TEXT NOT NULL,
    responsable_id          INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE RESTRICT,
    fecha_compromiso        DATE NOT NULL,
    estado                  VARCHAR(20) NOT NULL DEFAULT 'planificada'
        CHECK (estado IN ('planificada', 'en_curso', 'implementada', 'cancelada')),
    meta_reduccion_pct      NUMERIC(5, 2) NOT NULL DEFAULT 30
        CHECK (meta_reduccion_pct > 0 AND meta_reduccion_pct <= 100),
    fecha_implementacion    DATE,
    comentario_cierre       VARCHAR(500),
    creada_por              INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE RESTRICT,
    fecha_creacion          TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT ck_capa_implementada CHECK (
        (estado = 'implementada' AND fecha_implementacion IS NOT NULL)
     OR (estado <> 'implementada' AND fecha_implementacion IS NULL)),
    CONSTRAINT ck_capa_cancelada CHECK (estado <> 'cancelada' OR comentario_cierre IS NOT NULL)
);
COMMENT ON TABLE acciones_capa IS 'Accion correctiva o preventiva con responsable y fecha compromiso (RF-24).';
CREATE INDEX IF NOT EXISTS idx_capa_investigacion ON acciones_capa (investigacion_id);
CREATE INDEX IF NOT EXISTS idx_capa_responsable ON acciones_capa (responsable_id, estado);

CREATE TABLE IF NOT EXISTS mediciones_eficacia (
    id                      SERIAL PRIMARY KEY,
    accion_id               INTEGER NOT NULL REFERENCES acciones_capa(id) ON DELETE RESTRICT,
    antes_desde             DATE NOT NULL,
    antes_hasta             DATE NOT NULL,
    despues_desde           DATE NOT NULL,
    despues_hasta           DATE NOT NULL,
    antes_vendidas          INTEGER NOT NULL,
    antes_devueltas         INTEGER NOT NULL,
    antes_tasa_pct          NUMERIC(7, 2),
    despues_vendidas        INTEGER NOT NULL,
    despues_devueltas       INTEGER NOT NULL,
    despues_tasa_pct        NUMERIC(7, 2),
    reduccion_pct           NUMERIC(7, 2),
    meta_reduccion_pct      NUMERIC(5, 2) NOT NULL,
    veredicto               VARCHAR(20) NOT NULL CHECK (veredicto IN ('efectiva', 'no_efectiva', 'sin_datos')),
    motivo_sin_datos        VARCHAR(255),
    medido_por              INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE RESTRICT,
    fecha_medicion          TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT ck_medicion_periodos CHECK (antes_desde <= antes_hasta AND despues_desde <= despues_hasta),
    CONSTRAINT ck_medicion_sin_datos CHECK (veredicto <> 'sin_datos' OR motivo_sin_datos IS NOT NULL)
);
COMMENT ON TABLE mediciones_eficacia IS 'Comparacion inmutable de la tasa de devolucion antes y despues de una accion (RF-24, RN-09).';
CREATE INDEX IF NOT EXISTS idx_mediciones_accion ON mediciones_eficacia (accion_id, fecha_medicion DESC);
