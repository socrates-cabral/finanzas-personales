"""
Importa ingresos historicos enero-mayo 2026 a Control_gastos en Supabase.

Fuentes:
  - Liquidaciones PDF  → Sueldo liquido + Anticipo mensual (meses 01-04)
  - .env / config      → Sueldo+Anticipo mayo, Amipass, Arriendo cobrado,
                         Ingresos variables, Bono mensual, Otros ingresos

Uso:
    py finanzas_personales/db/importar_ingresos_control_gastos.py
    py finanzas_personales/db/importar_ingresos_control_gastos.py --dry-run
"""

import sys
import re
import calendar
from datetime import date
from pathlib import Path

from dotenv import load_dotenv
import os
from supabase import create_client

load_dotenv(Path(__file__).parent.parent.parent / ".env")

LIQUIDACIONES_DIR = Path(
    r"C:\Users\Socrates Cabral\OneDrive - EGA KAT LOGISTICA SPA"
    r"\Mi PC\Mi Unidad\Desktop\EGA-KAT\Liquidaciones"
)
MESES_2026 = [1, 2, 3, 4, 5]
NOMBRES_MES = {
    1: "Enero", 2: "Febrero", 3: "Marzo", 4: "Abril", 5: "Mayo",
    6: "Junio", 7: "Julio", 8: "Agosto", 9: "Septiembre",
    10: "Octubre", 11: "Noviembre", 12: "Diciembre",
}

SUPABASE_URL = os.getenv("SUPABASE_FINANZAS_URL")
SUPABASE_KEY = os.getenv("SUPABASE_FINANZAS_SERVICE_ROLE_KEY")
USER_ID      = os.getenv("FINANZAS_USER_ID")
TABLA        = "Control_gastos"

# Ingresos fijos desde .env (los mismos que Ajustes en la app)
CFG = {
    "sueldo_liquido":   int(os.getenv("SUELDO_LIQUIDO",   1_722_668)),
    "anticipo":         int(os.getenv("ANTICIPO",           380_000)),
    "amipass":          int(os.getenv("AMIPASS",             58_000)),
    "arriendo_cobrado": int(os.getenv("ARRIENDO_COBRADO",        0)),
    "ingreso_variable": int(os.getenv("INGRESO_VARIABLE",        0)),
    "bono_mensual":     int(os.getenv("BONO_MENSUAL",            0)),
    "otros_ingresos":   int(os.getenv("OTROS_INGRESOS",          0)),
}


# ── Parser de liquidacion (simplificado desde data_loader.py) ──────────────

def _parse_clp(linea: str):
    nums = re.findall(r'\d{1,3}(?:\.\d{3})+', linea)
    if not nums:
        return None
    try:
        return float(nums[-1].replace(".", ""))
    except ValueError:
        return None


def parsear_liquidacion_pdf(ruta: Path) -> dict:
    import pdfplumber, io
    resultado = {"liquido": None, "anticipo": None, "bono": None}
    try:
        with pdfplumber.open(ruta) as pdf:
            lineas = []
            for page in pdf.pages:
                lineas.extend((page.extract_text() or "").splitlines())
    except Exception as e:
        print(f"  WARN no se pudo leer {ruta.name}: {e}")
        return resultado

    for l in lineas:
        ll = l.strip().lower()
        if resultado["liquido"] is None and re.match(r'l[ií]quido a pagar:', ll):
            resultado["liquido"] = _parse_clp(l)
        if resultado["anticipo"] is None and re.match(r'anticipo\s*\$', ll):
            resultado["anticipo"] = _parse_clp(l)
        if resultado["bono"] is None and ll.startswith("bono"):
            v = _parse_clp(l)
            if v and v >= 1000:
                resultado["bono"] = v
    return resultado


# ── Helpers de fecha ────────────────────────────────────────────────────────

def ultimo_dia(year: int, month: int) -> date:
    return date(year, month, calendar.monthrange(year, month)[1])

def dia(year: int, month: int, d: int) -> date:
    ultimo = calendar.monthrange(year, month)[1]
    return date(year, month, min(d, ultimo))


# ── Construccion de registros ───────────────────────────────────────────────

def ingreso(concepto: str, importe: float, fecha: date, detalle: str, fuente: str) -> dict:
    return {
        "user_id":    USER_ID,
        "tipo_tx":    "Ingreso",
        "grupo":      "Ingresos",
        "concepto":   concepto,
        "detalle":    detalle,
        "importe":    float(importe),
        "forma_pago": "Transferencia",
        "fecha_date": fecha.isoformat(),
        "fuente":     fuente,
    }


def generar_ingresos() -> list[dict]:
    registros = []

    for mes in MESES_2026:
        year = 2026
        nombre_mes = f"{NOMBRES_MES[mes]} {year}"
        pdf_path = LIQUIDACIONES_DIR / f"Liquidacion_contrato_1_{year}-{mes:02d}_1.pdf"

        # ── Sueldo liquido + Anticipo ──────────────────────────────────────
        if pdf_path.exists():
            datos = parsear_liquidacion_pdf(pdf_path)
            liquido  = datos["liquido"]
            anticipo = datos["anticipo"]
            fuente_liq = "liquidacion_pdf"
            print(f"  PDF {pdf_path.name}: liquido={liquido}, anticipo={anticipo}")
        else:
            liquido  = CFG["sueldo_liquido"]
            anticipo = CFG["anticipo"]
            fuente_liq = "ajustes_env"
            print(f"  Sin PDF para {year}-{mes:02d}, usando valores .env")

        if liquido and liquido > 0:
            registros.append(ingreso(
                concepto="Sueldo liquido",
                importe=liquido,
                fecha=ultimo_dia(year, mes),
                detalle=f"Liquidacion sueldo {nombre_mes}",
                fuente=fuente_liq,
            ))

        if anticipo and anticipo > 0:
            registros.append(ingreso(
                concepto="Anticipo mensual",
                importe=anticipo,
                fecha=dia(year, mes, 15),
                detalle=f"Anticipo mensual {nombre_mes}",
                fuente=fuente_liq,
            ))

        # ── Ingresos fijos desde .env ──────────────────────────────────────

        if CFG["amipass"] > 0:
            registros.append(ingreso(
                concepto="Amipass / Alimentacion",
                importe=CFG["amipass"],
                fecha=dia(year, mes, 1),
                detalle=f"Beneficio Amipass {nombre_mes}",
                fuente="ajustes_env",
            ))
            # Amipass se gasta, no es transferencia
            registros[-1]["forma_pago"] = "Carga"

        if CFG["arriendo_cobrado"] > 0:
            registros.append(ingreso(
                concepto="Arriendo cobrado",
                importe=CFG["arriendo_cobrado"],
                fecha=dia(year, mes, 5),
                detalle=f"Pago arriendo departamento {nombre_mes}",
                fuente="ajustes_env",
            ))

        if CFG["ingreso_variable"] > 0:
            registros.append(ingreso(
                concepto="Ingresos variables",
                importe=CFG["ingreso_variable"],
                fecha=ultimo_dia(year, mes),
                detalle=f"Ingresos variables {nombre_mes}",
                fuente="ajustes_env",
            ))

        if CFG["bono_mensual"] > 0:
            registros.append(ingreso(
                concepto="Bono mensual",
                importe=CFG["bono_mensual"],
                fecha=ultimo_dia(year, mes),
                detalle=f"Bono mensual {nombre_mes}",
                fuente="ajustes_env",
            ))

        if CFG["otros_ingresos"] > 0:
            registros.append(ingreso(
                concepto="Otros ingresos",
                importe=CFG["otros_ingresos"],
                fecha=ultimo_dia(year, mes),
                detalle=f"Otros ingresos {nombre_mes}",
                fuente="ajustes_env",
            ))

    return registros


# ── Main ────────────────────────────────────────────────────────────────────

def main():
    dry_run = "--dry-run" in sys.argv

    if not SUPABASE_URL or not SUPABASE_KEY or not USER_ID:
        print("ERROR Faltan variables: SUPABASE_FINANZAS_URL, SUPABASE_FINANZAS_SERVICE_ROLE_KEY, FINANZAS_USER_ID")
        sys.exit(1)

    print("Generando registros de ingresos enero-mayo 2026...\n")
    registros = generar_ingresos()
    total = len(registros)

    print(f"\nTotal a insertar: {total} registros de ingreso")
    print(f"Config .env: sueldo={CFG['sueldo_liquido']:,} anticipo={CFG['anticipo']:,} "
          f"amipass={CFG['amipass']:,} arriendo={CFG['arriendo_cobrado']:,} "
          f"variable={CFG['ingreso_variable']:,} bono={CFG['bono_mensual']:,} "
          f"otros={CFG['otros_ingresos']:,}")

    por_concepto = {}
    for r in registros:
        por_concepto[r["concepto"]] = por_concepto.get(r["concepto"], 0) + 1
    for concepto, count in sorted(por_concepto.items()):
        print(f"  {concepto}: {count} registros")

    if dry_run:
        print("\n[DRY RUN] Sin cambios en Supabase.")
        for r in registros[:6]:
            print(" ", r)
        return

    sb = create_client(SUPABASE_URL, SUPABASE_KEY)

    LOTE = 100
    insertados = 0
    for i in range(0, total, LOTE):
        lote = registros[i:i + LOTE]
        sb.table(TABLA).insert(lote).execute()
        insertados += len(lote)
        print(f"  Insertados {insertados}/{total}...")

    print(f"\nLISTO {insertados} registros de ingreso insertados en {TABLA}")


if __name__ == "__main__":
    main()
