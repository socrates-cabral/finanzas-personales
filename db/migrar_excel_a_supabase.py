import sys
sys.stdout.reconfigure(encoding="utf-8")

"""
migrar_excel_a_supabase.py — Carga el histórico del Excel a Supabase.

Sprint 5, paso 1. Puente Excel → Supabase para la fase de coexistencia.

Requisitos previos (los hace el usuario una sola vez):
    1. Crear el proyecto Supabase dedicado a finanzas.
    2. Ejecutar finanzas_personales/db/schema.sql en el SQL Editor.
    3. Crear el usuario familiar en Authentication → Users (email/password).
    4. Copiar el UUID de ese usuario (columna "UID" en la tabla de users).
    5. Agregar al .env de la raíz:
         SUPABASE_FINANZAS_URL=https://xxxx.supabase.co
         SUPABASE_FINANZAS_SERVICE_ROLE_KEY=eyJ...   (Settings → API → service_role)

Uso:
    py finanzas_personales/db/migrar_excel_a_supabase.py --user-id <UUID>
    py finanzas_personales/db/migrar_excel_a_supabase.py --user-id <UUID> --reset
    py finanzas_personales/db/migrar_excel_a_supabase.py --user-id <UUID> --excel "C:\\ruta\\al.xlsm"

Flags:
    --user-id   UUID del usuario destino (o variable de entorno FINANZAS_USER_ID)
    --excel     Ruta al .xlsm (default: EXCEL_FP_PATH del .env)
    --reset     Borra TODAS las filas del usuario antes de cargar (re-migración limpia)
    --dry-run   Lee y reporta qué migraría, sin escribir nada en Supabase

Idempotencia:
    categorias / patrimonio / config usan upsert → re-ejecutar es seguro.
    transacciones usa insert → re-ejecutar SIN --reset duplica filas.
    Para re-migrar limpio: usar --reset.
"""

import argparse
import os
from pathlib import Path

import pandas as pd

# Permite importar los módulos de app/ sin instalar el paquete
_APP_DIR = Path(__file__).resolve().parent.parent / "app"
sys.path.insert(0, str(_APP_DIR))

import data_loader as excel          # noqa: E402
import supabase_repo as repo         # noqa: E402
import config_manager                # noqa: E402

# Período "Ene-2026" → mes
_MES_ABBR = {
    "ene": 1, "feb": 2, "mar": 3, "abr": 4, "may": 5, "jun": 6,
    "jul": 7, "ago": 8, "sep": 9, "oct": 10, "nov": 11, "dic": 12,
}

# Mapeo de columnas de la hoja Patrimonio → (categoria, item)
# Las columnas no listadas se ignoran (Período es la fecha, Patrimonio Neto
# es derivado, USDT Uni / Precio USDT son componentes del valor CLP).
_PATRIMONIO_MAP = {
    "Cuenta Vista":       ("activo", "Cuenta Vista"),
    "Cuenta Ahorro":      ("activo", "Cuenta Ahorro"),
    "Valor USDT CLP":     ("activo", "USDT"),
    "AFP Saldo":          ("activo", "AFP"),
    "Propiedad 1":        ("activo", "Propiedad 1"),
    "Deuda Hipotecaria":  ("pasivo", "Deuda Hipotecaria"),
    "Otras Deudas":       ("pasivo", "Otras Deudas"),
}


def _parse_periodo(valor) -> pd.Timestamp | None:
    """'Ene-2026' → Timestamp(2026,1,1). Acepta también fechas reales."""
    if valor is None:
        return None
    if isinstance(valor, pd.Timestamp):
        return valor.normalize().replace(day=1)
    s = str(valor).strip().lower()
    parts = s.replace("/", "-").replace(" ", "-").split("-")
    if len(parts) == 2:
        mes_str, anio_str = parts
        mes = _MES_ABBR.get(mes_str[:3])
        if mes and anio_str.isdigit():
            try:
                return pd.Timestamp(int(anio_str), mes, 1)
            except ValueError:
                return None
    try:
        return pd.Timestamp(valor).normalize().replace(day=1)
    except Exception:
        return None


def _patrimonio_largo(df_wide: pd.DataFrame) -> pd.DataFrame:
    """Transforma la hoja Patrimonio (ancha) a formato largo fecha|categoria|item|valor."""
    if df_wide is None or df_wide.empty:
        return pd.DataFrame(columns=["fecha", "categoria", "item", "valor"])
    filas = []
    col_periodo = None
    for c in df_wide.columns:
        if str(c).strip().lower().startswith("per"):
            col_periodo = c
            break
    if col_periodo is None:
        return pd.DataFrame(columns=["fecha", "categoria", "item", "valor"])

    for _, row in df_wide.iterrows():
        fecha = _parse_periodo(row.get(col_periodo))
        if fecha is None:
            continue
        for col, (categoria, item) in _PATRIMONIO_MAP.items():
            if col not in df_wide.columns:
                continue
            val = row.get(col)
            if val is None or (isinstance(val, float) and pd.isna(val)):
                continue
            try:
                valor = float(val)
            except (TypeError, ValueError):
                continue
            filas.append({
                "fecha": fecha, "categoria": categoria,
                "item": item, "valor": valor,
            })
    return pd.DataFrame(filas) if filas else pd.DataFrame(
        columns=["fecha", "categoria", "item", "valor"]
    )


def main():
    ap = argparse.ArgumentParser(description="Migra el Excel de finanzas a Supabase")
    ap.add_argument("--user-id", default=os.getenv("FINANZAS_USER_ID", ""),
                    help="UUID del usuario destino en Supabase")
    ap.add_argument("--excel", default=None, help="Ruta al .xlsm (default: EXCEL_FP_PATH)")
    ap.add_argument("--reset", action="store_true",
                    help="Borra todas las filas del usuario antes de cargar")
    ap.add_argument("--dry-run", action="store_true",
                    help="Reporta qué migraría sin escribir nada")
    args = ap.parse_args()

    user_id = args.user_id.strip()
    if not user_id:
        print("✗ Falta --user-id (o variable FINANZAS_USER_ID en .env)")
        sys.exit(1)

    # ── Verificar conexión a Supabase ─────────────────────────────────────────
    repo.set_active_user(user_id)
    if not args.dry_run and repo._get_client() is None:
        print("✗ Supabase no configurado. Revisa SUPABASE_FINANZAS_URL y "
              "SUPABASE_FINANZAS_SERVICE_ROLE_KEY en el .env")
        sys.exit(1)

    # ── Resolver ruta del Excel ───────────────────────────────────────────────
    excel_path = Path(args.excel) if args.excel else None
    if excel_path is None:
        ruta_env = os.getenv("EXCEL_FP_PATH", "")
        if ruta_env and Path(ruta_env).exists():
            excel_path = Path(ruta_env)
        else:
            excel_path = Path(__file__).resolve().parent.parent / "Plantilla_FinanzasPersonales.xlsx"
    if not excel_path.exists():
        print(f"✗ Excel no encontrado: {excel_path}")
        sys.exit(1)

    print(f"  Excel:   {excel_path}")
    print(f"  Usuario: {user_id}")
    print(f"  Modo:    {'DRY-RUN (sin escritura)' if args.dry_run else 'MIGRACIÓN REAL'}")
    print()

    # ── Leer todo del Excel ───────────────────────────────────────────────────
    ruta = str(excel_path)
    df_tx   = excel.cargar_transacciones(ruta)
    df_cat  = excel.cargar_categorias(ruta)
    df_patr = _patrimonio_largo(excel.cargar_patrimonio_mensual(ruta))

    # Config: la hoja Config solo existe en el formato nuevo. Para el formato
    # antiguo (hojas mensuales) la config real vive en config_manager.DEFAULTS
    # (que a su vez lee del .env). Usamos ese fallback.
    config = excel.cargar_config_excel(ruta)
    fuente_config = "hoja Config del Excel"
    if not config:
        config = dict(config_manager.DEFAULTS)
        # excel_path / liquidaciones_carpeta son rutas locales — no migran a la nube
        config.pop("excel_path", None)
        config.pop("liquidaciones_carpeta", None)
        fuente_config = "config_manager.DEFAULTS (.env)"

    print(f"  Leído:")
    print(f"    transacciones : {len(df_tx)}")
    print(f"    categorias    : {len(df_cat)}")
    print(f"    patrimonio    : {len(df_patr)} filas (formato largo)")
    print(f"    config        : {len(config)} claves  [{fuente_config}]")
    print()

    if args.dry_run:
        print("  DRY-RUN — nada se escribió. Quita --dry-run para migrar de verdad.")
        if not df_tx.empty:
            print("\n  Muestra transacciones:")
            print(df_tx[["fecha", "tipo_tx", "grupo", "concepto", "importe"]].head(5).to_string(index=False))
        return

    # ── Reset opcional ────────────────────────────────────────────────────────
    if args.reset:
        print("  --reset: borrando datos previos del usuario...")
        repo.resetear_datos_usuario(confirmar=True)
        print("    ✓ tablas limpiadas\n")

    # ── Cargar a Supabase ─────────────────────────────────────────────────────
    n_cat  = repo.upsert_categorias(df_cat)
    print(f"  ✓ categorias    : {n_cat} upserted")

    n_tx   = repo.insertar_transacciones(df_tx, fuente="excel")
    print(f"  ✓ transacciones : {n_tx} insertadas")

    n_patr = repo.upsert_patrimonio(df_patr)
    print(f"  ✓ patrimonio    : {n_patr} upserted")

    n_cfg  = repo.guardar_config_bulk(config)
    print(f"  ✓ config        : {n_cfg} claves upserted")

    print()
    print("  Migración completa. Para validar en la app:")
    print("    1. Agregar  DATA_SOURCE=supabase  al .env")
    print("    2. Agregar  FINANZAS_USER_ID=<UUID>  al .env")
    print("    3. Reiniciar la app y comparar Dashboard/Gastos/Patrimonio con el Excel")


if __name__ == "__main__":
    main()
