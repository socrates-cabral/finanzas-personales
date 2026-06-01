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
    "excel_path": os.getenv("EXCEL_FP_PATH", r"C:\ClaudeWork\Plantilla-para-controlar-gastos.xlsm" if os.name == "nt" else ""),
    "liquidaciones_carpeta": os.getenv(
        "LIQUIDACIONES_PATH",
        r"C:\Users\Socrates Cabral\OneDrive - EGA KAT LOGISTICA SPA\Mi PC\Mi Unidad\Desktop\EGA-KAT\Liquidaciones" if os.name == "nt" else "",
    ),
    # Presupuesto por grupo (0 = sin límite)
    "presupuesto": {
        "Alimentación": 300_000,
        "Transporte": 150_000,
        "Ocio y Vida Social": 100_000,
        "Suscripciones Digitales": 50_000,
    },
}


_SUPABASE_KEYS = {
    "sueldo_liquido", "anticipo", "amipass", "arriendo_cobrado",
    "ingreso_variable", "bono_mensual", "otros_ingresos", "total_ingresos",
    "afp_saldo", "afp_aporte_mensual", "afc_saldo", "afc_aporte_mensual",
    "isapre_mensual", "dividendo_mensual", "precio_usdt_clp",
}


def init_config():
    """Inicializa valores en session_state. Con DATA_SOURCE=supabase carga
    desde config_usuario; recarga si el usuario autenticado cambia."""
    # Recargar si el usuario cambió (login post-render) o si es la primera vez
    current_uid = st.session_state.get("_auth_user_id", "")
    already_loaded_for = st.session_state.get("_cfg_loaded_for_uid", "__never__")
    needs_load = already_loaded_for != current_uid

    if needs_load:
        st.session_state["_cfg_loaded_for_uid"] = current_uid
        try:
            from data_source import USANDO_SUPABASE
            if USANDO_SUPABASE:
                from supabase_repo import cargar_config, is_available
                if is_available():
                    cfg_remota = cargar_config()
                    loaded = 0
                    for key, val in cfg_remota.items():
                        if key in _SUPABASE_KEYS and key in DEFAULTS:
                            try:
                                st.session_state[f"cfg_{key}"] = type(DEFAULTS[key])(val)
                                loaded += 1
                            except (TypeError, ValueError):
                                pass
                    st.session_state["_cfg_source"] = f"supabase ({loaded} claves)"
                else:
                    st.session_state["_cfg_source"] = "defaults (.env) — Supabase no disponible"
            else:
                st.session_state["_cfg_source"] = "defaults (.env) — modo Excel"
        except Exception as e:
            st.session_state["_cfg_source"] = f"defaults (.env) — error: {e}"

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
        + get_cfg("anticipo")
        + get_cfg("amipass")
        + get_cfg("arriendo_cobrado")
        + get_cfg("ingreso_variable")
        + get_cfg("bono_mensual")
        + get_cfg("otros_ingresos")
    )


def get_ingresos_mes(mes: int, anio: int) -> float:
    """Retorna los ingresos del mes usando lógica de prioridad:

    1. Control_gastos tipo_tx='Ingreso' del mes → suma real (source of truth)
    2. config_ingresos_mensual override del mes → valor configurado ese mes específico
    3. config_usuario global → fallback default

    Nunca retorna 0 si hay un default configurado.
    """
    try:
        from data_source import USANDO_SUPABASE
        if USANDO_SUPABASE:
            from supabase_repo import (
                cargar_ingresos_reales_mes as _real,
                cargar_config_mensual as _mensual,
                get_active_user as _uid,
            )
            _uid_cache = _uid() or ""
            # Prioridad 1: suma real de transacciones
            real = _real(mes, anio, _uid_cache)
            if real > 0:
                return real
            # Prioridad 2: override mensual configurado
            cfg_mes = _mensual(mes, anio, _uid_cache)
            if cfg_mes:
                return (
                    float(cfg_mes.get("sueldo_liquido") or 0)
                    + float(cfg_mes.get("anticipo") or 0)
                    + float(cfg_mes.get("amipass") or 0)
                    + float(cfg_mes.get("arriendo_cobrado") or 0)
                    + float(cfg_mes.get("ingreso_variable") or 0)
                    + float(cfg_mes.get("bono_mensual") or 0)
                    + float(cfg_mes.get("otros_ingresos") or 0)
                )
    except Exception:
        pass
    # Prioridad 3: config global
    return calc_total_ingresos()


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
