CREATE TABLE IF NOT EXISTS config_ingresos_mensual (
    id          BIGSERIAL PRIMARY KEY,
    user_id     UUID        NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    año         INTEGER     NOT NULL,
    mes         INTEGER     NOT NULL CHECK (mes BETWEEN 1 AND 12),
    sueldo_liquido   NUMERIC DEFAULT 0,
    anticipo         NUMERIC DEFAULT 0,
    amipass          NUMERIC DEFAULT 0,
    arriendo_cobrado NUMERIC DEFAULT 0,
    ingreso_variable NUMERIC DEFAULT 0,
    bono_mensual     NUMERIC DEFAULT 0,
    otros_ingresos   NUMERIC DEFAULT 0,
    nota             TEXT    DEFAULT '',
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    updated_at  TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT uq_config_mensual UNIQUE (user_id, año, mes)
);

ALTER TABLE config_ingresos_mensual ENABLE ROW LEVEL SECURITY;

CREATE POLICY "usuario_propio" ON config_ingresos_mensual
    FOR ALL USING (auth.uid() = user_id)
    WITH CHECK (auth.uid() = user_id);
