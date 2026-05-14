import sys
sys.stdout.reconfigure(encoding="utf-8")

"""
market_data.py — Indicadores financieros en vivo desde CMF Chile API v3.
Fallback automático a valores de referencia si la API no está disponible.
"""

import os
import re
from datetime import datetime
from pathlib import Path

import requests
import streamlit as st
from dotenv import load_dotenv

load_dotenv(dotenv_path=Path(__file__).parent.parent.parent / ".env")

# ── Defaults (fallback sin conexión) ─────────────────────────────────────────
DEFAULTS = {
    "uf": 39841.0,
    "dolar": 913.98,
    "euro": 990.0,
    "ipc_mensual": -0.009,
}

_MINDICADOR_BASE = "https://mindicador.cl/api"
_CMF_KEY = os.getenv("CMF_API_KEY", "")  # Reservado para futuros endpoints CMF


# ── Helpers ───────────────────────────────────────────────────────────────────

def _mindicador_get(indicador: str) -> float | None:
    """Obtiene valor actual de mindicador.cl (API pública gratuita, sin key).
    Indicadores: uf, dolar, euro, ipc, utm, uf
    """
    try:
        resp = requests.get(f"{_MINDICADOR_BASE}/{indicador}", timeout=8)
        resp.raise_for_status()
        data = resp.json()
        serie = data.get("serie", [])
        if serie:
            return float(serie[0]["valor"])
        return None
    except Exception as e:
        print(f"[market_data] Error mindicador {indicador}: {e}", file=sys.stderr)
        return None


# ── Función principal ─────────────────────────────────────────────────────────

def obtener_indicadores() -> dict:
    """
    Retorna indicadores financieros en vivo desde mindicador.cl (datos CMF).
    Fallback automático a DEFAULTS si la API no está disponible.

    Returns:
        {
            "uf": float,           # CLP por 1 UF
            "dolar": float,        # CLP por 1 USD
            "euro": float,         # CLP por 1 EUR
            "ipc_mensual": float,  # Variación IPC último mes (%)
            "fuente": str,
            "actualizado": str,
            "error": str | None,
        }
    """
    resultado = {**DEFAULTS, "fuente": "Valores de referencia (sin conexión)",
                 "actualizado": datetime.now().strftime("%Y-%m-%d %H:%M"),
                 "error": None}

    errores = []
    ok = 0

    for clave, indicador in [("uf", "uf"), ("dolar", "dolar"), ("euro", "euro"), ("ipc_mensual", "ipc")]:
        v = _mindicador_get(indicador)
        if v is not None:
            resultado[clave] = v
            ok += 1
        else:
            errores.append(clave.upper())

    if ok > 0:
        resultado["fuente"] = f"mindicador.cl (CMF)" if not errores else f"mindicador.cl parcial"
        resultado["error"] = f"Sin datos para: {', '.join(errores)}" if errores else None
    else:
        resultado["error"] = "Sin conexión a mindicador.cl — usando valores de referencia"

    resultado["actualizado"] = datetime.now().strftime("%Y-%m-%d %H:%M")
    return resultado


@st.cache_data(ttl=600)
def obtener_indicadores_cached() -> dict:
    """Versión cacheada para Streamlit (TTL 10 minutos)."""
    return obtener_indicadores()


# ── Utilidades de cálculo ─────────────────────────────────────────────────────

def precio_usdt_estimado(dolar_clp: float) -> float:
    """USDT ≈ 1 USD con spread del 0.5%."""
    return round(dolar_clp * 1.005, 0)


def calcular_isapre_uf(uf_valor: float, plan_uf: float = 6.08) -> float:
    """Calcula descuento ISAPRE mensual en CLP desde valor del plan en UF.
    Default: Consalud 6.08 UF (valor real Feb 2026).
    """
    return round(uf_valor * plan_uf, 0)


def valor_en_uf(clp: float, uf_valor: float) -> float:
    """Convierte monto CLP a UF."""
    if uf_valor <= 0:
        return 0.0
    return round(clp / uf_valor, 2)


# ── Widget Streamlit ──────────────────────────────────────────────────────────

def render_widget_indicadores(indicadores: dict | None = None):
    """
    Renderiza fila de 4 métricas con indicadores de mercado en vivo.
    Si indicadores es None, llama obtener_indicadores_cached().
    """
    if indicadores is None:
        indicadores = obtener_indicadores_cached()

    uf = indicadores.get("uf", DEFAULTS["uf"])
    dolar = indicadores.get("dolar", DEFAULTS["dolar"])
    ipc = indicadores.get("ipc_mensual", DEFAULTS["ipc_mensual"])
    usdt = precio_usdt_estimado(dolar)

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("📐 UF", f"${uf:,.0f}".replace(",", "."))
    with col2:
        st.metric("💵 Dólar USD", f"${dolar:,.0f}".replace(",", "."))
    with col3:
        ipc_delta = f"{'▲' if ipc >= 0 else '▼'} {abs(ipc):.3f}%"
        st.metric("📊 IPC mensual", ipc_delta)
    with col4:
        st.metric("🪙 USDT est.", f"${usdt:,.0f}".replace(",", "."))

    fuente = indicadores.get("fuente", "")
    actualizado = indicadores.get("actualizado", "")
    st.caption(f"Fuente: {fuente} · {actualizado}")
    if indicadores.get("error"):
        st.caption(f"⚠️ {indicadores['error']}")
