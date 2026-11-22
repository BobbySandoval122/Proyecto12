-- =============================================================================
-- Migracion 045: la bitacora solo admite agregar registros
-- Motivo: la pantalla de auditoria promete "ver el historial sin poder
--   modificarlo" (dominio 8 del tercer parcial) y hasta ahora eso solo era
--   cierto porque el servicio de auditoria no tiene rutas de escritura. Pero
--   todos los servicios escriben en `bitacora` con la misma cuenta de base de
--   datos, asi que un descuido o una inyeccion SQL en cualquiera de ellos podia
--   borrar o reescribir el rastro. Esta migracion lo impide en la base:
--   - UPDATE y DELETE sobre una fila fallan.
--   - TRUNCATE falla.
--   - Unica excepcion: que `usuarios` borre a una persona y la llave foranea
--     `ON DELETE SET NULL` anonimice `usuario_id`. Se permite solo si ese es el
--     UNICO cambio de la fila; cualquier otra modificacion falla.
--   Se verifico que ningun codigo del repositorio actualiza ni borra la
--   bitacora (solo INSERT y SELECT), por lo que ningun flujo existente se rompe.
--   Alcance honesto: es una proteccion del esquema. Frena a la aplicacion, a un
--   error o a una inyeccion; no a quien administre PostgreSQL y desactive el
--   trigger a proposito (eso exige ser dueno de la tabla). Para depurar
--   registros antiguos hay que desactivarlo de forma explicita y deliberada.
-- Trazabilidad: RF-30, RN-12, RNF-16
-- Rango de migraciones de Persona 4: 040-049 (docs/PUERTOS.md)
-- =============================================================================

CREATE OR REPLACE FUNCTION fn_bitacora_solo_agregar()
RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'UPDATE'
       AND OLD.usuario_id IS NOT NULL AND NEW.usuario_id IS NULL
       AND ROW(NEW.id, NEW.accion, NEW.entidad, NEW.entidad_id, NEW.detalle,
               NEW.correlation_id, NEW.fecha, NEW.ip_origen)
           IS NOT DISTINCT FROM
           ROW(OLD.id, OLD.accion, OLD.entidad, OLD.entidad_id, OLD.detalle,
               OLD.correlation_id, OLD.fecha, OLD.ip_origen)
    THEN
        RETURN NEW;  -- anonimizacion por ON DELETE SET NULL de usuarios
    END IF;
    RAISE EXCEPTION 'La bitacora es de solo agregar: no admite % (RF-30, RN-12)', TG_OP
        USING ERRCODE = 'integrity_constraint_violation';
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE TRIGGER trg_bitacora_inmutable
    BEFORE UPDATE OR DELETE ON bitacora
    FOR EACH ROW EXECUTE FUNCTION fn_bitacora_solo_agregar();

CREATE OR REPLACE TRIGGER trg_bitacora_sin_truncate
    BEFORE TRUNCATE ON bitacora
    FOR EACH STATEMENT EXECUTE FUNCTION fn_bitacora_solo_agregar();

COMMENT ON TRIGGER trg_bitacora_inmutable ON bitacora IS
    'Bloquea UPDATE y DELETE salvo la anonimizacion de usuario_id por ON DELETE SET NULL (RF-30, RN-12).';
