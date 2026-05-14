import sys
sys.stdout.reconfigure(encoding="utf-8")

"""
fintoc_client.py — Integración Fintoc Open Banking (Chile).

Fintoc permite acceder al historial de movimientos bancarios reales.
Modo sandbox: sk_test_... / pk_test_... (gratis, sin contrato).
Modo live: requiere contrato con Fintoc (desde 6.5 UF/mes).

FLUJO:
1. Usuario abre el Fintoc Widget con pk_test_... en su browser.
2. Conecta su cuenta bancaria con sus credenciales.
3. Obtiene un link_token (ej: "link_token_xxxxx").
4. Pega el link_token en la app.
5. La app usa sk_test_... + link_token para obtener movimientos.

API docs: https://docs.fintoc.com/
"""

import os
import json
from pathlib import Path
from datetime import datetime, timedelta, date

import requests
import streamlit as st
from dotenv import load_dotenv

load_dotenv(dotenv_path=Path(__file__).parent.parent.parent / ".env")

_SK  = os.getenv("FINTOC_SECRET_KEY", "")
_PK  = os.getenv("FINTOC_PUBLIC_KEY", "")
_BASE = "https://api.fintoc.com/v1"
_LINKS_FILE = Path(__file__).parent.parent / "data" / "fintoc_links.json"
_MOVS_FILE  = Path(__file__).parent.parent / "data" / "fintoc_movimientos.json"

# Bancos disponibles en sandbox Fintoc Chile
BANCOS_SANDBOX = {
    "bci":          "Banco BCI",
    "banco_estado": "Banco Estado",
    "santander":    "Banco Santander",
    "scotiabank":   "Scotiabank",
    "itau":         "Itaú",
    "bice":         "Banco BICE",
}

# Mapeo tipo Fintoc → grupo del Excel
TIPO_A_GRUPO = {
    "transfer":         "Transferencias",
    "other":            "Otros",
    "charge":           "Gastos varios",
    "deposit":          "Ingresos",
    "withdrawal":       "Retiros",
    "payment":          "Pagos",
}


# ── I/O persistencia ─────────────────────────────────────────────────────────

def _cargar_links() -> list:
    if _LINKS_FILE.exists():
        try:
            return json.loads(_LINKS_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return []


def _guardar_links(links: list):
    _LINKS_FILE.parent.mkdir(exist_ok=True)
    _LINKS_FILE.write_text(json.dumps(links, ensure_ascii=False, indent=2), encoding="utf-8")


def _cargar_movimientos() -> list:
    if _MOVS_FILE.exists():
        try:
            return json.loads(_MOVS_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return []


def _guardar_movimientos(movs: list):
    _MOVS_FILE.parent.mkdir(exist_ok=True)
    _MOVS_FILE.write_text(json.dumps(movs, ensure_ascii=False, indent=2), encoding="utf-8")


# ── Cliente HTTP ─────────────────────────────────────────────────────────────

def _get(path: str, params: dict = None) -> tuple:
    """Llama a la API Fintoc. Retorna (data, error)."""
    if not _SK:
        return None, "FINTOC_SECRET_KEY no configurada en .env"
    try:
        r = requests.get(
            f"{_BASE}{path}",
            headers={"Authorization": _SK},
            params=params or {},
            timeout=15,
        )
        if r.status_code == 200:
            return r.json(), None
        err = r.json().get("error", {}).get("message", r.text[:100])
        return None, f"API error {r.status_code}: {err}"
    except Exception as e:
        return None, str(e)


# ── Links (cuentas conectadas) ────────────────────────────────────────────────

def listar_links() -> tuple:
    """Lista todos los links (cuentas bancarias conectadas)."""
    return _get("/links")


def obtener_link(link_token: str) -> tuple:
    """Obtiene información de un link específico."""
    return _get(f"/links/{link_token}")


def registrar_link_token(link_token: str, alias: str = "") -> dict:
    """
    Registra un link_token en el almacenamiento local.
    El usuario obtiene el link_token después de completar el widget Fintoc.
    """
    data, err = obtener_link(link_token)
    if err:
        return {"ok": False, "error": err}

    links = _cargar_links()
    # Evitar duplicados
    if any(l["token"] == link_token for l in links):
        return {"ok": True, "msg": "Link ya registrado", "data": data}

    entrada = {
        "token":         link_token,
        "alias":         alias or link_token[:20],
        "institucion":   data.get("institution", {}).get("name", "Desconocida") if data else "Desconocida",
        "username":      data.get("username", "") if data else "",
        "registrado":    datetime.now().isoformat(),
        "ultimo_sync":   None,
    }
    links.append(entrada)
    _guardar_links(links)
    return {"ok": True, "msg": "Link registrado correctamente", "data": data}


def eliminar_link(link_token: str) -> bool:
    links = _cargar_links()
    nuevos = [l for l in links if l["token"] != link_token]
    if len(nuevos) == len(links):
        return False
    _guardar_links(nuevos)
    return True


# ── Cuentas ───────────────────────────────────────────────────────────────────

def listar_cuentas(link_token: str) -> tuple:
    """Lista cuentas disponibles en un link."""
    return _get("/accounts", {"link_token": link_token})


# ── Movimientos ───────────────────────────────────────────────────────────────

def obtener_movimientos(
    link_token: str,
    account_id: str,
    desde: date | None = None,
    hasta: date | None = None,
) -> tuple:
    """
    Obtiene movimientos de una cuenta.
    Por defecto: últimos 90 días.
    Retorna (lista_movimientos, error).
    """
    if desde is None:
        desde = date.today() - timedelta(days=90)
    if hasta is None:
        hasta = date.today()

    params = {
        "link_token": link_token,
        "since":      desde.strftime("%Y-%m-%d"),
        "until":      hasta.strftime("%Y-%m-%d"),
    }
    return _get(f"/accounts/{account_id}/movements", params)


def sincronizar_movimientos(
    link_token: str,
    account_id: str,
    alias_cuenta: str = "",
    desde: date | None = None,
) -> dict:
    """
    Sincroniza movimientos y los guarda localmente.
    Retorna resumen: {ok, total, nuevos, error}.
    """
    movs, err = obtener_movimientos(link_token, account_id, desde)
    if err:
        return {"ok": False, "error": err, "total": 0, "nuevos": 0}

    existentes = _cargar_movimientos()
    ids_existentes = {m["id"] for m in existentes}

    nuevos = []
    for m in (movs or []):
        if m.get("id") not in ids_existentes:
            m["_cuenta_alias"] = alias_cuenta
            m["_link_token"]   = link_token[:20]
            m["_sincronizado"] = datetime.now().isoformat()
            nuevos.append(m)

    todos = existentes + nuevos
    # Mantener solo los últimos 2000 movimientos
    if len(todos) > 2000:
        todos = sorted(todos, key=lambda x: x.get("post_date", ""), reverse=True)[:2000]
    _guardar_movimientos(todos)

    # Actualizar último sync en el link
    links = _cargar_links()
    for l in links:
        if l["token"] == link_token:
            l["ultimo_sync"] = datetime.now().isoformat()
    _guardar_links(links)

    return {"ok": True, "total": len(movs or []), "nuevos": len(nuevos), "error": None}


# ── Conversión al formato del Excel ──────────────────────────────────────────

def movimientos_a_transacciones(movimientos: list) -> list:
    """
    Convierte movimientos Fintoc al formato de transacciones del Excel.
    Retorna lista de dicts compatibles con cargar_transacciones().

    Campos: mes, mes_nombre, grupo, concepto, fecha, detalle, importe
    """
    NOMBRES_MESES = {
        1:"Enero", 2:"Febrero", 3:"Marzo", 4:"Abril",
        5:"Mayo", 6:"Junio", 7:"Julio", 8:"Agosto",
        9:"Septiembre", 10:"Octubre", 11:"Noviembre", 12:"Diciembre",
    }

    transacciones = []
    for m in movimientos:
        try:
            fecha_str = m.get("post_date") or m.get("value_date") or ""
            fecha_dt  = datetime.strptime(fecha_str[:10], "%Y-%m-%d") if fecha_str else None
            mes_num   = fecha_dt.month if fecha_dt else 0

            # Fintoc: amount en centavos → convertir a pesos
            amount_raw = m.get("amount", 0) or 0
            # Fintoc Chile usa pesos (no centavos) para CLP
            importe = abs(float(amount_raw))

            if importe <= 0:
                continue

            tipo_fintoc = m.get("type", "other")
            grupo = TIPO_A_GRUPO.get(tipo_fintoc, "Fintoc - Otros")

            # Si es un débito (gasto), el amount es negativo en Fintoc
            # Si es crédito (ingreso), es positivo
            es_gasto = float(amount_raw) < 0

            if not es_gasto:
                grupo = "Ingresos Fintoc"

            transacciones.append({
                "mes":        mes_num,
                "mes_nombre": NOMBRES_MESES.get(mes_num, ""),
                "grupo":      grupo,
                "concepto":   m.get("description", "")[:50],
                "fecha":      fecha_dt,
                "detalle":    f"{m.get('_cuenta_alias','')} | {m.get('recipient_account',{}).get('name','')}",
                "importe":    importe,
                "fuente":     "fintoc",
                "id_fintoc":  m.get("id", ""),
            })
        except Exception:
            continue

    return transacciones


def obtener_movimientos_local() -> list:
    """Carga movimientos sincronizados desde disco."""
    return _cargar_movimientos()


def resumen_movimientos(movimientos: list) -> dict:
    """Calcula KPIs de los movimientos locales."""
    if not movimientos:
        return {"total": 0, "gastos": 0, "ingresos": 0, "ultimo_sync": None}

    gastos   = sum(abs(m["amount"]) for m in movimientos if (m.get("amount") or 0) < 0)
    ingresos = sum(abs(m["amount"]) for m in movimientos if (m.get("amount") or 0) > 0)
    fechas   = [m.get("_sincronizado") for m in movimientos if m.get("_sincronizado")]

    return {
        "total":       len(movimientos),
        "gastos":      gastos,
        "ingresos":    ingresos,
        "ultimo_sync": max(fechas) if fechas else None,
    }


# ── Widget HTML (para abrir en browser) ──────────────────────────────────────

def generar_widget_html(redirect_url: str = "http://localhost:8503") -> str:
    """
    Genera página HTML con el widget Fintoc.
    El usuario la abre en su browser, conecta su banco,
    y obtiene el link_token para pegar en la app.
    """
    return f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<title>Conectar Banco — Fintoc</title>
<style>
  body {{ font-family: Inter, Arial, sans-serif; background: #0F172A; color: #E2E8F0;
          display: flex; flex-direction: column; align-items: center; justify-content: center;
          min-height: 100vh; margin: 0; padding: 20px; }}
  h1 {{ color: #10B981; margin-bottom: 8px; }}
  p  {{ color: #94A3B8; margin-bottom: 24px; text-align: center; }}
  button {{ background: #10B981; color: #0F172A; border: none; border-radius: 8px;
            padding: 14px 32px; font-size: 1rem; font-weight: 700; cursor: pointer; }}
  button:hover {{ background: #34D399; }}
  #resultado {{ margin-top: 24px; background: #1E293B; border-radius: 8px;
                padding: 20px; max-width: 480px; width: 100%; display: none; }}
  #token {{ font-family: monospace; color: #10B981; word-break: break-all;
            background: #0F172A; padding: 12px; border-radius: 6px; margin: 8px 0; }}
  .copy-btn {{ background: #6366F1; font-size: 0.85rem; padding: 8px 16px; }}
</style>
</head>
<body>
<h1>💳 Conectar Banco</h1>
<p>Conecta tu cuenta bancaria de forma segura con Fintoc.<br>
Solo se accede a movimientos — nunca a credenciales.</p>
<button onclick="abrirFintoc()">🔗 Conectar mi banco</button>
<div id="resultado">
  <p style="color:#CBD5E1;margin:0 0 8px">✅ Banco conectado. Copia tu link_token:</p>
  <div id="token">—</div>
  <button class="copy-btn" onclick="copiar()">📋 Copiar</button>
  <p style="color:#64748B;font-size:0.8rem;margin-top:12px">
    Pega este token en la app → ⚙️ Ajustes → Fintoc.
  </p>
</div>
<script src="https://js.fintoc.com/v1/"></script>
<script>
function abrirFintoc() {{
  const widget = Fintoc.create({{
    publicKey: "{_PK}",
    product: "movements",
    country: "cl",
    holderType: "individual",
    onSuccess: function(link) {{
      document.getElementById("token").textContent = link.token;
      document.getElementById("resultado").style.display = "block";
    }},
    onExit: function() {{
      console.log("Widget cerrado");
    }}
  }});
  widget.open();
}}
function copiar() {{
  const txt = document.getElementById("token").textContent;
  navigator.clipboard.writeText(txt);
  alert("Link token copiado ✅");
}}
</script>
</body>
</html>"""


def guardar_widget_html() -> Path:
    """Guarda el widget HTML en data/ y retorna la ruta."""
    ruta = Path(__file__).parent.parent / "data" / "fintoc_widget.html"
    ruta.parent.mkdir(exist_ok=True)
    ruta.write_text(generar_widget_html(), encoding="utf-8")
    return ruta


# ── Estado de configuración ───────────────────────────────────────────────────

def fintoc_configurado() -> bool:
    return bool(_SK and _PK)


def fintoc_estado() -> dict:
    links = _cargar_links()
    movs  = _cargar_movimientos()
    return {
        "configurado":    fintoc_configurado(),
        "sandbox":        _SK.startswith("sk_test_"),
        "n_links":        len(links),
        "links":          links,
        "n_movimientos":  len(movs),
        "ultimo_sync":    max((l.get("ultimo_sync") or "" for l in links), default=None) or None,
    }
