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
#  CRUD DEUDAS — file (local) o Supabase según DATA_SOURCE
# ══════════════════════════════════════════════════════════════════════════════

def _usando_supabase() -> bool:
    try:
        from data_source import USANDO_SUPABASE
        return USANDO_SUPABASE
    except Exception:
        return False


def _sb():
    """Devuelve (client, user_id) desde supabase_repo o (None, None)."""
    try:
        import supabase_repo
        c = supabase_repo._get_client()
        u = supabase_repo.get_active_user()
        return c, u
    except Exception:
        return None, None


# ── Backends ──────────────────────────────────────────────────────────────────

def _sb_obtener() -> list:
    c, uid = _sb()
    if not c or not uid:
        return []
    try:
        resp = c.table("deudas").select("*").eq("user_id", uid).order("fecha_registro").execute()
        return resp.data or []
    except Exception:
        return []


def _sb_insertar(deuda: dict, user_id: str) -> bool:
    c, _ = _sb()
    if not c:
        return False
    try:
        row = {**deuda, "user_id": user_id}
        c.table("deudas").insert(row).execute()
        return True
    except Exception:
        return False


def _sb_eliminar(deuda_id: str) -> bool:
    c, uid = _sb()
    if not c or not uid:
        return False
    try:
        c.table("deudas").delete().eq("id", deuda_id).eq("user_id", uid).execute()
        return True
    except Exception:
        return False


def _sb_actualizar(deuda_id: str, campos: dict) -> bool:
    c, uid = _sb()
    if not c or not uid:
        return False
    try:
        c.table("deudas").update(campos).eq("id", deuda_id).eq("user_id", uid).execute()
        return True
    except Exception:
        return False


# ── Interfaz pública ──────────────────────────────────────────────────────────

def obtener_deudas() -> list:
    """Retorna lista de deudas guardadas."""
    if _usando_supabase():
        return _sb_obtener()
    if _DEUDAS_FILE.exists():
        try:
            return json.loads(_DEUDAS_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return []


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
    nueva = {
        "id": f"deuda_{uuid.uuid4().hex[:12]}",
        "institucion": institucion,
        "tipo": tipo,
        "saldo_actual": saldo_actual,
        "tasa_mensual": tasa_mensual,
        "tasa_anual": round(tasa_mensual * 12, 2),
        "cuota_mensual": cuota_mensual,
        "meses_restantes": meses_restantes,
        "descripcion": descripcion,
        "fecha_registro": datetime.now().isoformat(),
    }
    if _usando_supabase():
        _, uid = _sb()
        if uid:
            _sb_insertar(nueva, uid)
    else:
        deudas = obtener_deudas()
        deudas.append(nueva)
        _DEUDAS_FILE.write_text(json.dumps(deudas, ensure_ascii=False, indent=2), encoding="utf-8")
    return nueva


def eliminar_deuda(deuda_id: str) -> bool:
    if _usando_supabase():
        return _sb_eliminar(deuda_id)
    deudas = obtener_deudas()
    nuevas = [d for d in deudas if d["id"] != deuda_id]
    if len(nuevas) == len(deudas):
        return False
    _DEUDAS_FILE.write_text(json.dumps(nuevas, ensure_ascii=False, indent=2), encoding="utf-8")
    return True


def actualizar_deuda(deuda_id: str, **campos) -> bool:
    if _usando_supabase():
        if "tasa_mensual" in campos:
            campos["tasa_anual"] = round(campos["tasa_mensual"] * 12, 2)
        return _sb_actualizar(deuda_id, campos)
    deudas = obtener_deudas()
    for d in deudas:
        if d["id"] == deuda_id:
            d.update(campos)
            if "tasa_mensual" in campos:
                d["tasa_anual"] = round(campos["tasa_mensual"] * 12, 2)
            _DEUDAS_FILE.write_text(json.dumps(deudas, ensure_ascii=False, indent=2), encoding="utf-8")
            return True
    return False


def reemplazar_deudas_cmf(nuevas: list, fecha_pdf: str = "") -> int:
    """Elimina todas las deudas importadas desde CMF y guarda las nuevas.
    Retorna la cantidad guardada. Usar al importar un PDF actualizado."""
    existentes = obtener_deudas()
    for d in existentes:
        if "Importado PDF CMF" in d.get("descripcion", ""):
            eliminar_deuda(d["id"])
    for d in nuevas:
        agregar_deuda(
            d["institucion"], d["tipo"], d["saldo_actual"],
            d.get("tasa_mensual", 0), d.get("cuota_mensual", 0),
            d.get("meses_restantes", 0),
            f"Importado PDF CMF {fecha_pdf}".strip(),
        )
    return len(nuevas)


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
    Parsea el PDF 'Informe de Deudas' de CMF Chile usando extract_text().
    Pre-normaliza 'Tarjeta de crédito' que pdfplumber parte en 2-3 líneas
    por el layout de tabla multi-fila del PDF original.
    """
    _DATE_RE   = re.compile(r'\d{2}/\d{2}/\d{4}')
    _AMOUNT_RE = re.compile(r'\$[\d.]+')
    _FOOTNOTE  = re.compile(r'\s*\(\d+\)\s*$')

    # Multi-word tipos primero (evita match parcial)
    _TIPOS = [
        ("tarjeta de crédito",  "Tarjeta de Crédito"),
        ("tarjeta de credito",  "Tarjeta de Crédito"),
        ("línea de crédito",    "Línea de Crédito"),
        ("linea de crédito",    "Línea de Crédito"),
        ("linea de credito",    "Línea de Crédito"),
        ("vivienda",            "Vivienda"),
        ("consumo",             "Consumo"),
        ("hipotecario",         "Crédito Hipotecario"),
        ("automotriz",          "Automotriz"),
        ("comercial",           "Comercial"),
        ("leasing",             "Leasing"),
        ("factoring",           "Factoring"),
    ]

    def limpiar_monto(texto: str) -> int:
        limpio = re.sub(r'[^\d]', '', str(texto))
        return int(limpio) if limpio else 0

    def normalizar_institucion(nombre: str) -> str:
        _ALIAS = {
            "de crédito e inversiones": "BCI",
            "de credito e inversiones":  "BCI",
            "banco de credito":          "BCI",
            "itaú chile":                "Banco Itaú Chile",
            "itaú":                      "Banco Itaú Chile",
            "itau":                      "Banco Itaú Chile",
            "banco del estado de chile": "Banco Estado",
            "banco estado":              "Banco Estado",
            "bancoestado":               "Banco Estado",
            "scotiabank":                "Scotiabank",
            "banco santander":           "Santander",
            "santander":                 "Santander",
            "falabella":                 "Banco Falabella",
            "ripley":                    "Banco Ripley",
            "consorcio":                 "Banco Consorcio",
            "tenpo":                     "Tenpo",
        }
        n_low = nombre.strip().lower()
        for alias, canon in _ALIAS.items():
            if alias in n_low:
                return canon
        return nombre.strip()

    def parsear_linea_directa(linea: str):
        """Extrae (institucion, tipo, saldo) de una línea normalizada con fecha."""
        dm = _DATE_RE.search(linea)
        if not dm:
            return None
        amounts = _AMOUNT_RE.findall(linea)
        if not amounts:
            return None
        saldo = limpiar_monto(amounts[0])
        if saldo <= 0:
            return None

        pre    = linea[:dm.start()].strip()
        pre_lo = pre.lower()

        tipo_canon = None
        inst_raw   = pre
        for tipo_pat, tipo_c in _TIPOS:
            idx = pre_lo.rfind(tipo_pat)
            if idx >= 0:
                tipo_canon = tipo_c
                inst_raw   = pre[:idx].strip()
                break

        if not tipo_canon or not inst_raw:
            return None

        inst_raw = _FOOTNOTE.sub('', inst_raw).strip()
        if not inst_raw:
            return None
        if any(w in inst_raw.lower() for w in ('tipo', 'instituc', 'total', 'plazo')):
            return None

        return normalizar_institucion(inst_raw), tipo_canon, saldo

    try:
        import pdfplumber
        import io

        resultado = {
            "deudas_directas":  [],
            "lineas_credito":   [],
            "total_deuda":      0,
            "total_disponible": 0,
            "fecha_informe":    "",
            "nombre_titular":   "",
        }

        paginas = []
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            for page in pdf.pages:
                paginas.append(page.extract_text() or "")

        texto = "\n".join(paginas)

        # ── Fecha del informe ───────────────────────────────────────────────
        fm = re.search(r'INFORME EMITIDO EL (\d{2}/\d{2}/\d{4})', texto)
        if not fm:
            fm = re.search(r'(\d{2}/\d{2}/\d{4})', texto)
        if fm:
            resultado["fecha_informe"] = fm.group(1)

        # ── Nombre titular ──────────────────────────────────────────────────
        # Formato: "...sistema financiero NOMBRE APELLIDO APELLIDO2\n"
        nm = re.search(r'([A-ZÁÉÍÓÚÑ]{2,}(?:\s+[A-ZÁÉÍÓÚÑ]{2,}){2,})', texto)
        if nm:
            resultado["nombre_titular"] = nm.group(1).strip()

        # ── Normalizar "Tarjeta de crédito" multi-línea ─────────────────────
        # Pattern B: "{inst} Tarjeta de\n{date} {amounts}\n(N) crédito"
        texto = re.sub(
            r'(?m)^(.+?)\s+Tarjeta de\n(\d{2}/\d{2}/\d{4}[^\n]+)\n(?:\(\d+\) )?[Cc]rédito$',
            r'\1 Tarjeta de Crédito \2',
            texto,
        )
        # Pattern A: "Tarjeta de\n{inst} {date} {amounts}\ncrédito"
        texto = re.sub(
            r'(?m)^Tarjeta de\n(.+?)(\d{2}/\d{2}/\d{4}[^\n]+)\n(?:\(\d+\) )?[Cc]rédito$',
            r'\1Tarjeta de Crédito \2',
            texto,
        )

        # ── Sección Deuda Directa ───────────────────────────────────────────
        sec = re.search(
            r'Deuda Directa(.+?)(?:Deuda Indirecta|No registra deuda indirecta|$)',
            texto, re.DOTALL | re.IGNORECASE,
        )
        if sec:
            for linea in sec.group(1).splitlines():
                l = linea.strip()
                if not l:
                    continue
                if re.search(r'Tipo de Cr|Plazo|Directo|Indirecto|Contingente|^Total', l):
                    continue
                parsed = parsear_linea_directa(l)
                if parsed:
                    inst, tipo, saldo = parsed
                    resultado["deudas_directas"].append({
                        "institucion":     inst,
                        "tipo":            tipo,
                        "saldo_actual":    saldo,
                        "tasa_mensual":    0.0,
                        "cuota_mensual":   0,
                        "meses_restantes": 0,
                        "descripcion":     f"Importado PDF CMF {resultado['fecha_informe']}",
                    })

        # ── Sección Líneas de Crédito (página 2) ───────────────────────────
        sec_lc = re.search(
            r'(?:Líneas de crédito|Lineas de cr[eé]dito)(.+?)(?:Otros créditos|Total|$)',
            texto, re.DOTALL | re.IGNORECASE,
        )
        if sec_lc:
            for linea in sec_lc.group(1).splitlines():
                l = linea.strip()
                if not l or 'No registra' in l:
                    continue
                amounts = _AMOUNT_RE.findall(l)
                if not amounts:
                    continue
                disponible = limpiar_monto(amounts[0])
                if disponible <= 0:
                    continue
                inst_raw = l[:l.index('$')].strip()
                inst_raw = _FOOTNOTE.sub('', inst_raw).strip()
                if not inst_raw or any(w in inst_raw.lower() for w in
                                       ('total', 'instituc', 'directos', 'disponible')):
                    continue
                resultado["lineas_credito"].append({
                    "institucion": normalizar_institucion(inst_raw),
                    "disponible":  disponible,
                })

        resultado["total_deuda"]      = sum(d["saldo_actual"] for d in resultado["deudas_directas"])
        resultado["total_disponible"] = sum(lc["disponible"]  for lc in resultado["lineas_credito"])

    except Exception as e:
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
