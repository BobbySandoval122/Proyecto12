-- =============================================================================
-- Migracion 018: conciliacion de identificadores con sistemas externos
-- Motivo: el tercer parcial agrega el dominio 21 (integraciones con POS, ERP,
--   WMS, transportistas y sistemas financieros). Cada sistema tiene sus propios
--   identificadores: la tienda "T-001" del POS es la tienda 3 de esta base, la
--   venta "TK-88123" del POS es la venta 512. Esta tabla guarda esa equivalencia.
--   La llave (sistema, tipo_entidad, id_externo) hace la importacion idempotente:
--   si el POS manda dos veces el mismo ticket, la segunda vez se responde la venta
--   ya creada en lugar de duplicarla.
--   Un id interno puede tener un solo id externo por sistema y tipo (indice
--   unico), para que la exportacion no reporte dos folios para el mismo registro.
-- Trazabilidad: RF-05, RF-06, RNF-11, RNF-28, dominio 21 del tercer parcial
-- =============================================================================

CREATE TABLE IF NOT EXISTS integraciones_ids (
    sistema         VARCHAR(20) NOT NULL
        CHECK (sistema IN ('pos', 'erp', 'wms', 'transportista', 'financiero')),
    tipo_entidad    VARCHAR(20) NOT NULL
        CHECK (tipo_entidad IN ('tienda', 'venta', 'producto', 'devolucion', 'recoleccion')),
    id_externo      VARCHAR(64) NOT NULL,
    id_interno      INTEGER NOT NULL,
    creado_por      INTEGER REFERENCES usuarios(id) ON DELETE RESTRICT,
    creado_en       TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (sistema, tipo_entidad, id_externo)
);
COMMENT ON TABLE integraciones_ids IS
    'Equivalencia entre identificadores de sistemas externos y los de esta base (dominio 21).';

CREATE UNIQUE INDEX IF NOT EXISTS idx_integraciones_ids_interno
    ON integraciones_ids (sistema, tipo_entidad, id_interno);
