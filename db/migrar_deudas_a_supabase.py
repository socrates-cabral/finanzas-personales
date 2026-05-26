"""
migrar_deudas_a_supabase.py — Sube deudas.json a la tabla deudas en Supabase.

Uso:
    py db/migrar_deudas_a_supabase.py
    py db/migrar_deudas_a_supabase.py --dry-run
"""

import sys
import json
import argparse
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

from dotenv import load_dotenv
load_dotenv(dotenv_path=Path(__file__).parent.parent.parent / ".env")

import os

DEUDAS_FILE = Path(__file__).parent.parent / "data" / "deudas.json"
USER_ID     = os.getenv("FINANZAS_USER_ID", "")
SB_URL      = os.getenv("SUPABASE_FINANZAS_URL", "")
SB_KEY      = os.getenv("SUPABASE_FINANZAS_SERVICE_ROLE_KEY", "")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not DEUDAS_FILE.exists():
        print(f"[ERROR] No se encontró {DEUDAS_FILE}")
        sys.exit(1)

    if not USER_ID or not SB_URL or not SB_KEY:
        print("[ERROR] Faltan FINANZAS_USER_ID / SUPABASE_FINANZAS_URL / SUPABASE_FINANZAS_SERVICE_ROLE_KEY en .env")
        sys.exit(1)

    deudas = json.loads(DEUDAS_FILE.read_text(encoding="utf-8"))
    print(f"Deudas a migrar: {len(deudas)}")

    if args.dry_run:
        for d in deudas:
            print(f"  DRY: {d['institucion']} | {d['tipo']} | ${d['saldo_actual']:,.0f}")
        return

    from supabase import create_client
    client = create_client(SB_URL, SB_KEY)

    migradas = 0
    for d in deudas:
        row = {
            "id":              d["id"],
            "user_id":         USER_ID,
            "institucion":     d["institucion"],
            "tipo":            d["tipo"],
            "saldo_actual":    d["saldo_actual"],
            "tasa_mensual":    d.get("tasa_mensual", 0),
            "tasa_anual":      d.get("tasa_anual", 0),
            "cuota_mensual":   d.get("cuota_mensual", 0),
            "meses_restantes": d.get("meses_restantes", 0),
            "descripcion":     d.get("descripcion", ""),
            "fecha_registro":  d.get("fecha_registro"),
        }
        resp = client.table("deudas").upsert(row, on_conflict="id").execute()
        print(f"  ✅ {d['institucion']} | {d['tipo']} | ${d['saldo_actual']:,.0f}")
        migradas += 1

    print(f"\n{migradas} deudas migradas a Supabase.")


if __name__ == "__main__":
    main()
