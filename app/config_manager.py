import sys
sys.stdout.reconfigure(encoding="utf-8")

"""
config_manager.py — Gestión de configuración de usuario en session_state.
Todos los parámetros editables por el usuario se centralizan aquí.
"""

import streamlit as st
from pathlib import Path
import os
from dotenv import load_dotenv

load_dotenv(dotenv_path=Path(__file__).parent.parent.parent / ".env")

# --- Defaults ---
DEFAULTS = {
    "sueldo_liquido":    int(os.getenv("SUELDO_LIQUIDO",    1_722_668)),
    "anticipo":          int(os.getenv("ANTICIPO",          380_000)),
    "amipass":           int(os.getenv("AMIPASS",           58_000)),
    "arriendo_cobrado":  int(os.getenv("ARRIENDO_COBRADO",  0)),
    "ingreso_variable":  int(os.getenv("INGRESO_VARIABLE",  0)),
    "bono_mensual":      int(os.getenv("BONO_MENSUAL",      0)),
    "otros_ingresos":    int(os.getenv("OTROS_INGRESOS",    0)),
    "total_ingresos": 2_160_668,
    "afp_saldo":         int(os.getenv("AFP_SALDO",         8_774_527)),
    "afp_aporte_mensual":int(os.getenv("AFP_APORTE_MENSUAL",224_155)),
    "afc_saldo":         int(os.getenv("AFC_SALDO",         0)),
    "afc_aporte_mensual":int(os.getenv("AFC_APORTE_MENSUAL",0)),
    "isapre_mensual":    int(os.getenv("ISAPRE_MENSUAL",    241_967)),
    "dividendo_mensual": int(os.getenv("DIVIDENDO_MENSUAL", 595_821)),
    "hipoteca_saldo": 0,
    "precio_usdt_clp": 960,
    "patrimonio_cc":           int(os.getenv("PATRIMONIO_CC", 0)),
    "patrimonio_ca":           int(os.getenv("PATRIMONIO_CA", 0)),
    "patrimonio_usdt":         float(os.getenv("PATRIMONIO_USDT", 0.0)),
    "patrimonio_dpto505":      int(os.getenv("PATRIMONIO_DPTO505", 120_000_000)),
    "patrimonio_otros_activos":int(os.getenv("PATRIMONIO_OTROS_ACTIVOS", 0)),
    "excel_path": os.getenv("EXCEL_FP_PATH", r"C:\ClaudeWork\Plantilla-para-controlar-gastos.xlsm"),
    "liquidaciones_carpeta": os.getenv(
        "LIQUIDACIONES_PATH",
        r"C:\Users\Socrates Cabral\OneDrive - EGA KAT LOGISTICA SPA\Mi PC\Mi Unidad\Desktop\EGA-KAT\Liquidaciones",
    ),
    # Presupuesto por grupo (0 = sin límite)
    "presupuesto": {
        "Alimentación": 300_000,
        "Transporte": 150_000,
        "Ocio y Vida Social": 100_000,
        "Suscripciones Digitales": 50_000,
    },
}


def init_config():
    """Inicializa valores en session_state si no existen."""
    for key, val in DEFAULTS.items():
        if f"cfg_{key}" not in st.session_state:
            st.session_state[f"cfg_{key}"] = val


def get_cfg(key: str):
    """Obtiene valor de configuración."""
    init_config()
    return st.session_state.get(f"cfg_{key}", DEFAULTS.get(key))


def set_cfg(key: str, val):
    """Actualiza valor de configuración."""
    st.session_state[f"cfg_{key}"] = val


def calc_total_ingresos() -> float:
    """Calcula total ingresos con todos los valores actuales de configuración."""
    return (
        get_cfg("sueldo_liquido")
        + get_cfg("amipass")
        + get_cfg("arriendo_cobrado")
        + get_cfg("ingreso_variable")
        + get_cfg("bono_mensual")
        + get_cfg("otros_ingresos")
    )


def render_ajustes_sidebar():
    """Renderiza sección de ajustes rápidos en el sidebar."""
    with st.sidebar.expander("⚙️ Config Rápida", expanded=False):
        nuevo_sueldo = st.number_input(
            "Sueldo líquido", value=get_cfg("sueldo_liquido"), step=10_000, format="%d"
        )
        set_cfg("sueldo_liquido", nuevo_sueldo)
        nuevo_usdt = st.number_input(
            "Precio USDT/CLP", value=get_cfg("precio_usdt_clp"), step=10, format="%d"
        )
        set_cfg("precio_usdt_clp", nuevo_usdt)
