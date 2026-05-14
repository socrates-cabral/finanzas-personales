import sys
sys.stdout.reconfigure(encoding="utf-8")

"""
debt_manager.py — Gestión de deudas personales.
Almacena en finanzas_personales/data/deudas.json (local, nunca en git).
Soporta: ingreso manual + parsing PDF CMF "Mi Deuda en el Sistema Financiero".
"""

import os
import re
import json
import uuid
from pathlib import Path
from datetime import datetime

from dotenv import load_dotenv
load_dotenv(dotenv_path=Path(__file__).parent.parent.parent / ".env")

_DATA_DIR  = Path(__file__).parent.parent / "data"
_DEUDAS_FILE = _DATA_DIR / "deudas.json"
_DATA_DIR.mkdir(exist_ok=True)

# Instituciones más comunes en Chile
INSTITUCIONES = [
    "BCI", "Banco Estado", "Santander", "Scotiabank", "Itaú", "BICE",
    "Security", "Falabella (CMR)", "Ripley", "Paris (Cencosud)",
    "Coopeuch", "La Araucana", "ServiEstado", "Otro",
]

TIPOS_DEUDA = [
    "Tarjeta de Crédito", "Crédito de Consumo", "Línea de Crédito",
    "Crédito Hipotecario", "Crédito Automotriz", "Crédito Educacional",
    "Deuda Retail", "Préstamo Personal", "Otro",
]

# TMC vigentes CMF (actualizados 2026-03-14 desde API)
# Se sobreescriben si CMF API retorna datos
TMC_REFERENCIA = {
    "CP_pequeño (<90d, <5kUF)": 49.02,   # operaciones corto plazo pequeñas
    "CP_grande (<90d, >5kUF)":  8.70,
    "LP_pequeño (>=90d, <50UF)": 40.90,
    "LP_grande (>=90d, >50UF)":  33.90,
}


# ══════════════════════════════════════════════════════════════════════════════
#  CRUD DEUDAS
# ══════════════════════════════════════════════════════════════════════════════

def _cargar() -> list:
    if _DEUDAS_FILE.exists():
        try:
            return json.loads(_DEUDAS_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return []


def _guardar(deudas: list):
    _DEUDAS_FILE.write_text(
        json.dumps(deudas, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def obtener_deudas() -> list:
    """Retorna lista de deudas guardadas."""
    return _cargar()


def agregar_deuda(
    institucion: str,
    tipo: str,
    saldo_actual: float,
    tasa_mensual: float,
    cuota_mensual: float,
    meses_restantes: int,
    descripcion: str = "",
) -> dict:
    """Agrega una deuda nueva. Retorna el dict guardado."""
    deudas = _cargar()
    nueva = {
        "id": f"deuda_{uuid.uuid4().hex[:12]}",
        "institucion": institucion,
        "tipo": tipo,
        "saldo_actual": saldo_actual,
        "tasa_mensual": tasa_mensual,       # % mensual
        "tasa_anual": round(tasa_mensual * 12, 2),
        "cuota_mensual": cuota_mensual,
        "meses_restantes": meses_restantes,
        "descripcion": descripcion,
        "fecha_registro": datetime.now().isoformat(),
    }
    deudas.append(nueva)
    _guardar(deudas)
    return nueva


def eliminar_deuda(deuda_id: str) -> bool:
    deudas = _cargar()
    nuevas = [d for d in deudas if d["id"] != deuda_id]
    if len(nuevas) == len(deudas):
        return False
    _guardar(nuevas)
    return True


def actualizar_deuda(deuda_id: str, **campos) -> bool:
    deudas = _cargar()
    for d in deudas:
        if d["id"] == deuda_id:
            d.update(campos)
            if "tasa_mensual" in campos:
                d["tasa_anual"] = round(campos["tasa_mensual"] * 12, 2)
            _guardar(deudas)
            return True
    return False


# ══════════════════════════════════════════════════════════════════════════════
#  CÁLCULOS
# ══════════════════════════════════════════════════════════════════════════════

def resumen_deudas(deudas: list, ingresos_mensuales: float = 0) -> dict:
    """Calcula KPIs consolidados del portfolio de deudas."""
    if not deudas:
        return {
            "total_deuda": 0, "cuota_total_mes": 0, "n_deudas": 0,
            "tasa_prom_ponderada": 0, "ratio_deuda_ingreso": 0,
            "meses_prom": 0, "estado_semaforo": "verde",
        }

    total_deuda     = sum(d["saldo_actual"] for d in deudas)
    cuota_total     = sum(d["cuota_mensual"] for d in deudas)
    meses_prom      = sum(d["meses_restantes"] for d in deudas) / len(deudas)

    # Tasa ponderada por saldo
    tasa_pond = sum(d["tasa_mensual"] * d["saldo_actual"] for d in deudas) / total_deuda if total_deuda > 0 else 0

    ratio = (cuota_total / ingresos_mensuales * 100) if ingresos_mensuales > 0 else 0

    if ratio > 40:
        semaforo = "rojo"
    elif ratio > 30:
        semaforo = "amarillo"
    else:
        semaforo = "verde"

    return {
        "total_deuda":          total_deuda,
        "cuota_total_mes":      cuota_total,
        "n_deudas":             len(deudas),
        "tasa_prom_ponderada":  round(tasa_pond, 2),
        "tasa_anual_ponderada": round(tasa_pond * 12, 2),
        "ratio_deuda_ingreso":  round(ratio, 1),
        "meses_prom":           round(meses_prom, 0),
        "estado_semaforo":      semaforo,
    }


def estrategia_avalanche(deudas: list) -> list:
    """Ordena deudas por mayor tasa mensual primero (ahorra más intereses)."""
    return sorted(deudas, key=lambda d: d["tasa_mensual"], reverse=True)


def estrategia_snowball(deudas: list) -> list:
    """Ordena deudas por menor saldo primero (motivación psicológica)."""
    return sorted(deudas, key=lambda d: d["saldo_actual"])


def proyeccion_pago(
    saldo: float, tasa_mensual: float, cuota: float, max_meses: int = 360
) -> list:
    """Simula tabla de amortización mensual. Retorna lista de dicts."""
    tabla = []
    s = saldo
    tm = tasa_mensual / 100

    for mes in range(1, max_meses + 1):
        if s <= 0:
            break
        interes   = s * tm
        capital   = min(cuota - interes, s)
        if capital <= 0:
            break
        s_nuevo   = s - capital
        tabla.append({
            "mes":         mes,
            "saldo_ini":   round(s, 0),
            "interes":     round(interes, 0),
            "capital":     round(capital, 0),
            "cuota":       round(min(cuota, s + interes), 0),
            "saldo_fin":   round(max(s_nuevo, 0), 0),
        })
        s = s_nuevo
    return tabla


def alertas_tmc(deudas: list, tmc: dict | None = None) -> list:
    """
    Verifica si alguna tasa supera la TMC vigente.
    Retorna lista de alertas con institución y detalle.
    """
    if tmc is None:
        tmc = TMC_REFERENCIA

    tmc_lp_pequena = tmc.get("LP_pequeño (>=90d, <50UF)", 40.9)   # %  anual
    alertas = []
    for d in deudas:
        tasa_anual = d.get("tasa_anual", d.get("tasa_mensual", 0) * 12)
        if tasa_anual > tmc_lp_pequena:
            alertas.append({
                "institucion": d["institucion"],
                "tipo":        d["tipo"],
                "tasa_anual":  tasa_anual,
                "tmc_ref":     tmc_lp_pequena,
                "exceso":      round(tasa_anual - tmc_lp_pequena, 2),
            })
    return alertas


# ══════════════════════════════════════════════════════════════════════════════
#  PARSER PDF CMF "MI DEUDA EN EL SISTEMA FINANCIERO"
# ══════════════════════════════════════════════════════════════════════════════

def parsear_informe_cmf(pdf_bytes: bytes) -> dict:
    """
    Parsea el PDF oficial 'Informe de Deudas' de CMF Chile.
    El PDF produce celdas de texto concatenado (no columnas separadas),
    por lo que se parsean línea por línea buscando patrones conocidos.
    Retorna dict con: deudas_directas, lineas_credito, total_deuda,
    total_disponible, fecha_informe, nombre_titular.
    """
    # Tipos de crédito reconocidos en el PDF CMF — ORDEN IMPORTA
    # (algunos son prefijo de otros, ej "Comercial" antes de "Comercial Exterior")
    _TIPOS_CMF = [
        "Vivienda", "Consumo", "Comercial", "Tarjeta", "Automotriz",
        "Leasing", "Factoring", "Hipotecario",
    ]

    def limpiar_monto(texto: str) -> int:
        limpio = re.sub(r'[^\d]', '', str(texto))
        return int(limpio) if limpio else 0

    def normalizar_institucion(nombre: str) -> str:
        _ALIAS = {
            "de credito e inversiones": "BCI",
            "banco de credito":         "BCI",
            "itaú chile":               "Banco Itaú Chile",
            "itaú":                     "Banco Itaú Chile",
            "itau":                     "Banco Itaú Chile",
            "banco estado":             "Banco Estado",
            "bancoestado":              "Banco Estado",
            "scotiabank":               "Scotiabank",
            "banco santander":          "Santander",
            "santander":                "Santander",
            "falabella":                "Banco Falabella",
            "ripley":                   "Banco Ripley",
            "consorcio":                "Banco Consorcio",
            "tenpo":                    "Tenpo",
        }
        n_low = nombre.strip().lower()
        for alias, canon in _ALIAS.items():
            if alias in n_low:
                return canon
        return nombre.strip()

    def parsear_linea_deuda(linea: str):
        """
        Busca patrón: {Institución} {Tipo} ${monto} ...
        Retorna (institucion, tipo, monto) o None.
        """
        for tipo in _TIPOS_CMF:
            # Buscar el tipo (case-insensitive) en la línea
            m = re.search(r'(.+?)\s+' + tipo + r'\s+(\$[\d.]+)', linea, re.IGNORECASE)
            if m:
                inst_raw = m.group(1).strip()
                monto    = limpiar_monto(m.group(2))
                # Descartar líneas de encabezado o total
                if monto < 1_000:
                    return None
                if any(w in inst_raw.lower() for w in ['tipo', 'instituc', 'total']):
                    return None
                return normalizar_institucion(inst_raw), tipo.capitalize(), monto
        return None

    def parsear_linea_credito(linea: str):
        """
        Busca patrón: {Institución} ${monto_directos} ${monto_indirectos}
        Retorna (institucion, disponible) o None.
        """
        montos = re.findall(r'\$([\d.]+)', linea)
        if not montos:
            return None
        # El primer monto es "Directos"
        disponible = limpiar_monto(montos[0])
        if disponible < 1_000:
            return None
        # La institución es todo lo que está antes del primer $
        inst_raw = linea[:linea.index('$')].strip()
        if not inst_raw or any(w in inst_raw.lower() for w in
                               ['total', 'instituc', 'directos', 'indirectos']):
            return None
        return inst_raw, disponible

    try:
        import pdfplumber
        import io

        resultado = {
            "deudas_directas": [],
            "lineas_credito": [],
            "total_deuda": 0,
            "total_disponible": 0,
            "fecha_informe": "",
            "nombre_titular": "",
        }

        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            # Concatenar TODO el texto de todas las celdas de todas las tablas
            texto_deudas  = ""
            texto_lineas  = ""

            for page in pdf.pages:
                full_text = page.extract_text() or ""

                # Fecha e informe desde texto libre
                if not resultado["fecha_informe"]:
                    fm = re.search(r'(\d{2}/\d{2}/\d{4})', full_text)
                    if fm:
                        resultado["fecha_informe"] = fm.group(1)

                # Nombre titular (primera línea del PDF)
                if not resultado["nombre_titular"]:
                    nm = re.search(r'^([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑ\s]{5,})\n', full_text, re.MULTILINE)
                    if nm:
                        resultado["nombre_titular"] = nm.group(1).strip()

                # Recopilar texto de tablas por sección
                for tabla in (page.extract_tables() or []):
                    for fila in tabla:
                        for celda in fila:
                            if not celda:
                                continue
                            c = str(celda)
                            if "Deuda Directa" in c:
                                texto_deudas += c + "\n"
                            elif "Créditos disponibles" in c or "Lineas de credito" in c.replace("í","i"):
                                texto_lineas += c + "\n"

        # ── Parsear Deuda Directa ────────────────────────────────────────────
        en_directa = False
        for linea in texto_deudas.splitlines():
            l = linea.strip()
            if not l:
                continue
            if "Deuda Directa" in l:
                en_directa = True
                continue
            if "Deuda Indirecta" in l or "No registra" in l:
                en_directa = False
                continue
            if not en_directa:
                continue

            parsed = parsear_linea_deuda(l)
            if parsed:
                inst, tipo, monto = parsed
                resultado["deudas_directas"].append({
                    "institucion":     inst,
                    "tipo":            tipo,
                    "saldo_actual":    monto,
                    "tasa_mensual":    0.0,
                    "cuota_mensual":   0,
                    "meses_restantes": 0,
                    "descripcion":     f"Importado PDF CMF {resultado['fecha_informe']}",
                })

        # ── Parsear Líneas de Crédito ────────────────────────────────────────
        en_lineas = False
        for linea in texto_lineas.splitlines():
            l = linea.strip()
            if not l:
                continue
            if "Líneas de crédito" in l or "Lineas de credito" in l.replace("í","i"):
                en_lineas = True
                continue
            if "Otros créditos" in l or "Total" in l:
                continue
            if not en_lineas:
                continue
            if "No registra" in l:
                continue

            parsed = parsear_linea_credito(l)
            if parsed:
                inst, disponible = parsed
                resultado["lineas_credito"].append({
                    "institucion": inst,
                    "disponible":  disponible,
                })

        resultado["total_deuda"]      = sum(d["saldo_actual"] for d in resultado["deudas_directas"])
        resultado["total_disponible"] = sum(l["disponible"]   for l in resultado["lineas_credito"])

    except Exception as e:
        print(f"[parsear_informe_cmf] Error: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc(file=sys.stderr)
        return {
            "deudas_directas": [], "lineas_credito": [],
            "total_deuda": 0, "total_disponible": 0,
            "fecha_informe": "", "nombre_titular": "",
            "error": str(e),
        }

    return resultado


# ══════════════════════════════════════════════════════════════════════════════
#  ACTUALIZAR TMC DESDE CMF API
# ══════════════════════════════════════════════════════════════════════════════

def obtener_tmc_cmf() -> dict:
    """Consulta TMC vigente desde CMF API. Retorna TMC_REFERENCIA si falla."""
    import requests
    key = os.getenv("CMF_API_KEY", "")
    if not key:
        return TMC_REFERENCIA

    try:
        r = requests.get(
            "https://api.cmfchile.cl/api-sbifv3/recursos_api/tmc",
            params={"apikey": key, "formato": "json"},
            timeout=8,
        )
        r.raise_for_status()
        tmc_raw = {}
        for item in r.json().get("TMCs", []):
            titulo    = str(item.get("Titulo") or "")
            subtitulo = str(item.get("SubTitulo") or "")
            valor_str = str(item.get("Valor") or "0").replace(",", ".")
            try:
                valor = float(valor_str)
            except ValueError:
                continue
            if "menos de 90" in titulo and "Inferiores" in subtitulo:
                tmc_raw["CP_pequeño (<90d, <5kUF)"] = valor
            elif "menos de 90" in titulo and "Superiores" in subtitulo:
                tmc_raw["CP_grande (<90d, >5kUF)"] = valor
            elif "90 días" in titulo and "Inferiores" in subtitulo:
                tmc_raw["LP_pequeño (>=90d, <50UF)"] = valor
            elif "90 días" in titulo and "Superiores" in subtitulo:
                tmc_raw["LP_grande (>=90d, >50UF)"] = valor
        return tmc_raw if tmc_raw else TMC_REFERENCIA
    except Exception as e:
        print(f"[debt_manager] TMC API error: {e}", file=sys.stderr)
        return TMC_REFERENCIA
