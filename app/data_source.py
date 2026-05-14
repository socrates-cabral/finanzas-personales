import sys
sys.stdout.reconfigure(encoding="utf-8")

"""
data_source.py — Facade que decide de dónde vienen los datos.

Toggle vía variable de entorno DATA_SOURCE:
    DATA_SOURCE=excel     (default) → lee del .xlsm vía data_loader
    DATA_SOURCE=supabase            → lee de Supabase vía supabase_repo

Coexistencia: durante la transición del Sprint 5 ambas fuentes conviven.
main.py importa SIEMPRE desde aquí, nunca directo de data_loader.

Qué togglea:
    cargar_transacciones, cargar_categorias,
    cargar_patrimonio_mensual, cargar_config

Qué NO togglea (siempre Excel / parsers de archivos locales):
    cargar_saldos_mensuales, cargar_resumen_anual, cargar_inversiones,
    cargar_gastos_compartidos, parsear_liquidacion,
    cargar_liquidaciones_carpeta, parsear_amipass_archivo,
    cargar_afp_movimientos
Estas se re-exportan tal cual desde data_loader. Sus equivalentes en
Supabase llegan en fases posteriores (inversiones, gastos compartidos)
o son inherentemente locales (parsers de PDF).
"""

import os

import pandas as pd
import streamlit as st

# Constantes y parsers de archivos locales — passthrough directo (siempre Excel/PDF)
from data_loader import (
    NOMBRES_MESES,
    MESES_MAP,
    cargar_inversiones,
    parsear_liquidacion,
    cargar_liquidaciones_carpeta,
    parsear_amipass_archivo,
    cargar_afp_movimientos,
)

import data_loader as _excel


# ── Degradación grácil de funciones Excel-only ───────────────────────────────
# Algunas funciones de data_loader leen el .xlsm sin try/except y revientan con
# FileNotFoundError si no hay Excel — caso típico en Streamlit Cloud (modo
# supabase, sin .xlsm en el servidor Linux). Estos wrappers retornan vacío en
# vez de reventar. Solo atrapan FileNotFoundError; errores reales pasan.

def _safe_excel(fn, vacio_factory):
    def _wrapped(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except FileNotFoundError:
            return vacio_factory()
    return _wrapped

cargar_saldos_mensuales  = _safe_excel(_excel.cargar_saldos_mensuales, dict)
cargar_resumen_anual     = _safe_excel(_excel.cargar_resumen_anual, pd.DataFrame)
cargar_gastos_compartidos = _safe_excel(_excel.cargar_gastos_compartidos, dict)

# DATA_SOURCE se resuelve una vez al importar. Cambiarlo requiere reiniciar
# la app — por eso es seguro cachear los wrappers de abajo.
DATA_SOURCE = os.getenv("DATA_SOURCE", "excel").strip().lower()
USANDO_SUPABASE = DATA_SOURCE == "supabase"

if USANDO_SUPABASE:
    import supabase_repo as _sb
else:
    _sb = None


def fuente_activa() -> str:
    """Nombre legible de la fuente de datos en uso (para mostrar en la UI)."""
    return "Supabase" if USANDO_SUPABASE else "Excel"


# ── Funciones toggleables ─────────────────────────────────────────────────────

@st.cache_data(ttl=300)
def cargar_transacciones(ruta_str: str = None):
    """Transacciones del año. Excel o Supabase según DATA_SOURCE."""
    if USANDO_SUPABASE:
        return _sb.cargar_transacciones(ruta_str)
    return _excel.cargar_transacciones(ruta_str)


@st.cache_data(ttl=300)
def cargar_categorias(ruta_str: str = None):
    """Taxonomía grupo/concepto/tipo. Excel o Supabase según DATA_SOURCE."""
    if USANDO_SUPABASE:
        return _sb.cargar_categorias(ruta_str)
    return _excel.cargar_categorias(ruta_str)


@st.cache_data(ttl=300)
def cargar_patrimonio_mensual(ruta_str: str = None):
    """Snapshots de patrimonio. Excel o Supabase según DATA_SOURCE.

    Nota: el formato difiere entre fuentes — Excel devuelve la hoja cruda
    (ancha), Supabase devuelve formato largo fecha|categoria|item|valor.
    El consumidor debe normalizar; durante la coexistencia se valida que
    los totales coincidan.
    """
    if USANDO_SUPABASE:
        return _sb.cargar_patrimonio_mensual(ruta_str)
    return _excel.cargar_patrimonio_mensual(ruta_str)


@st.cache_data(ttl=300)
def cargar_config(ruta_str: str = None) -> dict:
    """Config key-value del usuario. Excel (hoja Config) o Supabase."""
    if USANDO_SUPABASE:
        return _sb.cargar_config(ruta_str)
    return _excel.cargar_config_excel(ruta_str)


# Alias de compatibilidad — main.py / módulos viejos pueden seguir llamando
# cargar_config_excel sin romperse.
cargar_config_excel = cargar_config
