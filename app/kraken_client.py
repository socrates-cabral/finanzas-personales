"""
kraken_client.py
Conector Kraken PRO API — solo lectura.
Obtiene saldos, recompensas (staking) e historial del libro mayor.
Autenticación: HMAC-SHA512 (estándar Kraken REST API).
"""
import sys
if sys.stdout:
    sys.stdout.reconfigure(encoding="utf-8")

import hashlib
import hmac
import base64
import time
import urllib.parse
import os
from pathlib import Path

import requests
import streamlit as st
from dotenv import load_dotenv

load_dotenv(dotenv_path=Path(__file__).parent.parent.parent / ".env")

KRAKEN_BASE = "https://api.kraken.com"

# Mapa de nombres internos Kraken → display
ASSET_NAMES = {
    "ZUSD":  "USD",
    "ZEUR":  "EUR",
    "XXBT":  "BTC",
    "XBT":   "BTC",
    "BT.B":  "BTC",
    "XETH":  "ETH",
    "ETH":   "ETH",
    "USDT":  "USDT",
    "XXLM":  "XLM",
    "SOL":   "SOL",
    "ADA":   "ADA",
    "DOT":   "DOT",
    "MATIC": "MATIC",
    "XRP":   "XRP",
    "USDC":  "USDC",
}


def _get_keys() -> tuple[str, str]:
    key    = os.getenv("KRAKEN_API_KEY", "")
    secret = os.getenv("KRAKEN_API_SECRET", "")
    return key, secret


def _sign(uri_path: str, data: dict, secret: str) -> str:
    """Genera la firma HMAC-SHA512 requerida por Kraken."""
    post_data   = urllib.parse.urlencode(data)
    encoded     = (str(data["nonce"]) + post_data).encode()
    message     = uri_path.encode() + hashlib.sha256(encoded).digest()
    mac         = hmac.new(base64.b64decode(secret), message, hashlib.sha512)
    return base64.b64encode(mac.digest()).decode()


def _post(endpoint: str, data: dict = None) -> dict:
    """Llamada privada autenticada a la API de Kraken."""
    api_key, api_secret = _get_keys()
    if not api_key or not api_secret:
        return {"error": ["No se encontraron KRAKEN_API_KEY / KRAKEN_API_SECRET en .env"]}

    uri_path = f"/0/private/{endpoint}"
    data     = data or {}
    data["nonce"] = str(int(time.time() * 1000))

    headers = {
        "API-Key":  api_key,
        "API-Sign": _sign(uri_path, data, api_secret),
        "Content-Type": "application/x-www-form-urlencoded",
    }
    try:
        resp = requests.post(
            KRAKEN_BASE + uri_path,
            headers=headers,
            data=data,
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        return {"error": [str(e)]}


@st.cache_data(ttl=120, show_spinner=False)
def get_balances() -> dict:
    """
    Retorna saldos de la cuenta Kraken.
    Formato: {symbol: cantidad_float}
    Solo incluye activos con saldo > 0.
    """
    result = _post("Balance")
    if result.get("error"):
        return {"_error": result["error"]}

    balances = {}
    for asset, qty in result.get("result", {}).items():
        cantidad = float(qty)
        if cantidad > 0.000001:
            # Normalizar nombre
            nombre = ASSET_NAMES.get(asset, asset.lstrip("XZ"))
            balances[nombre] = cantidad
    return balances


@st.cache_data(ttl=300, show_spinner=False)
def get_recompensas(dias: int = 30) -> list[dict]:
    """
    Retorna recompensas de staking de los últimos N días.
    Formato: [{fecha, activo, cantidad, usd_equiv}]
    """
    desde = int(time.time()) - (dias * 86400)
    result = _post("Ledgers", {
        "type":  "staking",
        "start": str(desde),
    })
    if result.get("error"):
        return []

    recompensas = []
    for _, entry in result.get("result", {}).get("ledger", {}).items():
        if entry.get("type") == "staking" and float(entry.get("amount", 0)) > 0:
            asset   = entry.get("asset", "")
            nombre  = ASSET_NAMES.get(asset, asset.lstrip("XZ"))
            recompensas.append({
                "fecha":    entry.get("time", 0),
                "activo":   nombre,
                "cantidad": float(entry.get("amount", 0)),
                "fee":      float(entry.get("fee", 0)),
            })

    recompensas.sort(key=lambda x: x["fecha"], reverse=True)
    return recompensas


@st.cache_data(ttl=120, show_spinner=False)
def get_resumen_recompensas() -> dict:
    """
    Resumen de recompensas: total acumulado por activo (últimos 90 días).
    Retorna {activo: cantidad_total}
    """
    recompensas = get_recompensas(dias=90)
    resumen = {}
    for r in recompensas:
        activo = r["activo"]
        resumen[activo] = resumen.get(activo, 0) + r["cantidad"]
    return resumen


def test_conexion() -> tuple[bool, str]:
    """Verifica que las claves funcionan. Retorna (ok, mensaje)."""
    key, secret = _get_keys()
    if not key or not secret:
        return False, "KRAKEN_API_KEY o KRAKEN_API_SECRET no configurados en .env"
    result = _post("Balance")
    if result.get("error"):
        return False, f"Error Kraken: {result['error']}"
    return True, f"{len(result.get('result', {}))} activos encontrados"
