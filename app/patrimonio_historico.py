import sys
sys.stdout.reconfigure(encoding="utf-8")

"""
patrimonio_historico.py — Historial mensual de patrimonio neto.
Guarda una snapshot por mes en data/patrimonio_historico.json.
Si ya existe una entrada para el mes actual, la sobreescribe.
"""

import json
from pathlib import Path
from datetime import datetime

_DATA_DIR  = Path(__file__).parent.parent / "data"
_HIST_FILE = _DATA_DIR / "patrimonio_historico.json"
_DATA_DIR.mkdir(exist_ok=True)


def _cargar() -> list:
    if _HIST_FILE.exists():
        try:
            return json.loads(_HIST_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return []


def _guardar(hist: list):
    _HIST_FILE.write_text(
        json.dumps(hist, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def guardar_snapshot(
    cc: int, ca: int, crypto_clp: int,
    dpto505: int, afp: int, otros_activos: int,
    hipoteca: int, tarjetas: int, consumo: int,
    linea_credito: int, otros_pasivos: int,
    afc: int = 0,
):
    """Guarda o actualiza la snapshot del mes actual."""
    hist = _cargar()
    mes_actual = datetime.now().strftime("%Y-%m")
    fecha_hoy  = datetime.now().strftime("%Y-%m-%d")

    total_activos  = cc + ca + crypto_clp + dpto505 + afp + afc + otros_activos
    total_pasivos  = hipoteca + tarjetas + consumo + linea_credito + otros_pasivos
    patrimonio_neto = total_activos - total_pasivos

    nueva = {
        "mes":            mes_actual,
        "fecha":          fecha_hoy,
        "cc":             cc,
        "ca":             ca,
        "crypto_clp":     crypto_clp,
        "dpto505":        dpto505,
        "afp":            afp,
        "afc":            afc,
        "otros_activos":  otros_activos,
        "hipoteca":       hipoteca,
        "tarjetas":       tarjetas,
        "consumo":        consumo,
        "linea_credito":  linea_credito,
        "otros_pasivos":  otros_pasivos,
        "total_activos":  total_activos,
        "total_pasivos":  total_pasivos,
        "patrimonio_neto":patrimonio_neto,
    }

    # Sobreescribir si ya existe el mes, si no agregar
    idx = next((i for i, e in enumerate(hist) if e["mes"] == mes_actual), None)
    if idx is not None:
        hist[idx] = nueva
    else:
        hist.append(nueva)

    hist.sort(key=lambda x: x["mes"])
    _guardar(hist)
    return nueva


def obtener_historico() -> list:
    return _cargar()
