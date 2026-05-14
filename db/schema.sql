-- ══════════════════════════════════════════════════════════════════
-- finanzas_personales — Esquema Supabase
-- Sprint 5 — Multi-usuario familiar con Row Level Security
--
-- Ejecutar en: Supabase Dashboard → SQL Editor → New query → Run
-- Proyecto: dedicado a finanzas (separado de crypto_bot)
-- ══════════════════════════════════════════════════════════════════

-- ── transacciones ───────────────────────────────────────────────────
-- Una fila por movimiento. importe siempre positivo; tipo_tx define el signo.
create table if not exists public.transacciones (
    id          bigint generated always as identity primary key,
    user_id     uuid not null references auth.users(id) on delete cascade default auth.uid(),
    fecha       date not null,
    tipo_tx     text not null default 'Gasto',          -- Gasto|Ingreso|Transferencia|Ahorro|Inversión
    grupo       text not null default 'Varios y Otros',
    concepto    text default '',
    detalle     text default '',
    importe     numeric(14,2) not null check (importe >= 0),
    cuenta      text default '',
    fuente      text default 'manual',                  -- manual|excel|banco_import
    created_at  timestamptz not null default now(),
    updated_at  timestamptz not null default now()
);
create index if not exists idx_tx_user_fecha on public.transacciones(user_id, fecha);
create index if not exists idx_tx_user_grupo on public.transacciones(user_id, grupo);

-- ── patrimonio ──────────────────────────────────────────────────────
-- Snapshots mensuales: una fila por (user, mes, categoría, item).
-- categoria = 'activo' | 'pasivo'. El patrimonio neto se calcula sumando.
create table if not exists public.patrimonio (
    id          bigint generated always as identity primary key,
    user_id     uuid not null references auth.users(id) on delete cascade default auth.uid(),
    fecha       date not null,                          -- primer día del mes del snapshot
    categoria   text not null check (categoria in ('activo', 'pasivo')),
    item        text not null,                          -- 'Cuenta Corriente', 'Dpto 505', 'Hipoteca'...
    valor       numeric(14,2) not null default 0,
    created_at  timestamptz not null default now(),
    unique (user_id, fecha, categoria, item)
);
create index if not exists idx_patrimonio_user_fecha on public.patrimonio(user_id, fecha);

-- ── categorias ──────────────────────────────────────────────────────
-- Taxonomía del usuario: grupo → concepto, con tipo de gasto.
-- Alimenta los desplegables en cascada del importador bancario.
create table if not exists public.categorias (
    id          bigint generated always as identity primary key,
    user_id     uuid not null references auth.users(id) on delete cascade default auth.uid(),
    grupo       text not null,
    concepto    text not null,
    tipo        text default 'Variable',                -- Fijo|Variable
    created_at  timestamptz not null default now(),
    unique (user_id, grupo, concepto)
);
create index if not exists idx_categorias_user on public.categorias(user_id);

-- ── config_usuario ──────────────────────────────────────────────────
-- Key-value de configuración. valor es jsonb para soportar números,
-- strings y objetos (ej. presupuesto por grupo).
create table if not exists public.config_usuario (
    id          bigint generated always as identity primary key,
    user_id     uuid not null references auth.users(id) on delete cascade default auth.uid(),
    clave       text not null,
    valor       jsonb not null,
    updated_at  timestamptz not null default now(),
    unique (user_id, clave)
);
create index if not exists idx_config_user on public.config_usuario(user_id);

-- ══════════════════════════════════════════════════════════════════
-- Row Level Security — cada cuenta familiar ve SOLO sus propias filas
-- ══════════════════════════════════════════════════════════════════
alter table public.transacciones   enable row level security;
alter table public.patrimonio      enable row level security;
alter table public.categorias      enable row level security;
alter table public.config_usuario  enable row level security;

-- Política uniforme: el usuario autenticado solo accede a filas con su user_id.
-- DROP previo para que el script sea idempotente (re-ejecutable sin error).
drop policy if exists "own_rows" on public.transacciones;
create policy "own_rows" on public.transacciones
    for all using (auth.uid() = user_id) with check (auth.uid() = user_id);

drop policy if exists "own_rows" on public.patrimonio;
create policy "own_rows" on public.patrimonio
    for all using (auth.uid() = user_id) with check (auth.uid() = user_id);

drop policy if exists "own_rows" on public.categorias;
create policy "own_rows" on public.categorias
    for all using (auth.uid() = user_id) with check (auth.uid() = user_id);

drop policy if exists "own_rows" on public.config_usuario;
create policy "own_rows" on public.config_usuario
    for all using (auth.uid() = user_id) with check (auth.uid() = user_id);

-- ══════════════════════════════════════════════════════════════════
-- Trigger updated_at — refresca el timestamp en cada UPDATE
-- ══════════════════════════════════════════════════════════════════
create or replace function public.set_updated_at()
returns trigger language plpgsql as $$
begin
    new.updated_at = now();
    return new;
end $$;

drop trigger if exists trg_tx_updated on public.transacciones;
create trigger trg_tx_updated before update on public.transacciones
    for each row execute function public.set_updated_at();

drop trigger if exists trg_config_updated on public.config_usuario;
create trigger trg_config_updated before update on public.config_usuario
    for each row execute function public.set_updated_at();

-- ══════════════════════════════════════════════════════════════════
-- FIN — Tablas: transacciones, patrimonio, categorias, config_usuario
-- Todas con RLS activo. La migración (servicio backend con service_role
-- key) debe pasar user_id explícito porque auth.uid() es null fuera de
-- una sesión autenticada.
-- ══════════════════════════════════════════════════════════════════
