import sys
sys.stdout.reconfigure(encoding="utf-8")

"""
supabase_repo.py — Capa de acceso a datos sobre Supabase.

Refleja la interfaz de data_loader.py para las entidades que migran a la
nube: transacciones, categorias, patrimonio, config_usuario.

Coexistencia: este módulo NO reemplaza data_loader.py. El facade
data_source.py decide cuál usar según la variable DATA_SOURCE.

Autenticación:
- Pre-login (Sprint 5 pasos 1-2): usa SUPABASE_SERVICE_ROLE_KEY y filtra
  por user_id explícito en cada query — mismo efecto que RLS.
- Post-login (Sprint 5 paso 3): streamlit-authenticator llama
  set_active_user() con el UUID de la sesión; se puede cambiar a anon key
  + JWT y RLS pasa a ser la barrera real.

Falla suave: si Supabase no está configurado, las lecturas devuelven
DataFrames/dicts vacíos en vez de reventar.
"""

import os
from pathlib import Path
from datetime import datetime, date

import pandas as pd
from dotenv import load_dotenv

load_dotenv(dotenv_path=Path(__file__).parent.parent.parent / ".env")

NOMBRES_MESES = {
    1: "Enero", 2: "Febrero", 3: "Marzo", 4: "Abril",
    5: "Mayo", 6: "Junio", 7: "Julio", 8: "Agosto",
    9: "Septiembre", 10: "Octubre", 11: "Noviembre", 12: "Diciembre",
}

_TX_COLS = ["mes", "mes_nombre", "tipo_tx", "grupo", "concepto",
            "fecha", "detalle", "importe", "cuenta"]

_client = None              # cliente service_role (migración / pre-login)
_auth_client = None         # cliente con JWT del usuario (post-login, RLS real)
_active_user_id: str | None = os.getenv("FINANZAS_USER_ID") or None


# ── Cliente ───────────────────────────────────────────────────────────────────

def _get_client():
    """Devuelve el cliente Supabase activo.

    - Si hay un cliente autenticado (post-login) → ese, con el JWT del
      usuario, RLS aplica de verdad.
    - Si no → el cliente service_role, para scripts backend (migración).
      Bypassa RLS, por eso las queries filtran por user_id explícito.
    """
    global _client
    if _auth_client is not None:
        return _auth_client
    if _client is not None:
        return _client
    url = os.getenv("SUPABASE_FINANZAS_URL") or os.getenv("SUPABASE_URL", "")
    key = (
        os.getenv("SUPABASE_FINANZAS_SERVICE_ROLE_KEY")
        or os.getenv("SUPABASE_FINANZAS_KEY")
        or os.getenv("SUPABASE_SERVICE_ROLE_KEY")
        or os.getenv("SUPABASE_KEY", "")
    )
    if not url or not key:
        return None
    from supabase import create_client
    _client = create_client(url, key)
    return _client


def set_active_user(user_id: str | None):
    """Define el usuario cuyas filas se leen/escriben.

    Lo usan los scripts backend (migración) que corren con service_role.
    El login de la app usa set_authenticated_client() en su lugar.
    """
    global _active_user_id
    _active_user_id = user_id


def set_authenticated_client(client, user_id: str | None):
    """Enchufa el cliente Supabase autenticado tras el login.

    A partir de aquí _get_client() devuelve este cliente (con el JWT del
    usuario) y RLS es la barrera real. Pasar (None, None) lo desconecta
    — vuelve al cliente service_role.
    """
    global _auth_client, _active_user_id
    _auth_client = client
    _active_user_id = user_id


def get_active_user() -> str | None:
    return _active_user_id


def is_available() -> bool:
    """True si hay cliente Supabase y un usuario activo."""
    return _get_client() is not None and _active_user_id is not None


def _require():
    """Devuelve (client, user_id) o lanza si no está listo."""
    client = _get_client()
    if client is None:
        raise RuntimeError("Supabase no configurado (faltan SUPABASE_FINANZAS_URL / KEY)")
    if not _active_user_id:
        raise RuntimeError("No hay usuario activo — llama set_active_user() tras el login")
    return client, _active_user_id


# ── Lecturas (reflejan data_loader.py) ────────────────────────────────────────

def cargar_transacciones(ruta_str: str = None) -> pd.DataFrame:
    """Carga todas las transacciones del usuario activo.

    El parámetro ruta_str se ignora — existe solo para que la firma sea
    idéntica a data_loader.cargar_transacciones() y el facade pueda
    delegar sin condicionales.
    """
    try:
        client, uid = _require()
    except RuntimeError:
        return pd.DataFrame(columns=_TX_COLS)

    try:
        resp = (
            client.table("Control_gastos")
            .select("fecha_date, tipo_tx, grupo, concepto, detalle, importe, forma_pago")
            .eq("user_id", uid)
            .order("fecha_date", desc=False)
            .execute()
        )
    except Exception:
        return pd.DataFrame(columns=_TX_COLS)

    filas = resp.data or []
    if not filas:
        return pd.DataFrame(columns=_TX_COLS)

    df = pd.DataFrame(filas)
    # Normalizar nombres al esquema interno del app
    df = df.rename(columns={"fecha_date": "fecha", "forma_pago": "cuenta"})
    df["fecha"] = pd.to_datetime(df["fecha"], errors="coerce")
    df["mes"] = df["fecha"].dt.month.fillna(1).astype(int)
    df["mes_nombre"] = df["mes"].map(NOMBRES_MESES).fillna("")
    df["importe"] = pd.to_numeric(df["importe"], errors="coerce").fillna(0.0)
    for col in ("tipo_tx", "grupo", "concepto", "detalle", "cuenta"):
        if col not in df.columns:
            df[col] = ""
        df[col] = df[col].fillna("").astype(str)
    return df[_TX_COLS]


def cargar_categorias(ruta_str: str = None) -> pd.DataFrame:
    """Carga la taxonomía grupo/concepto/tipo del usuario activo."""
    try:
        client, uid = _require()
    except RuntimeError:
        return pd.DataFrame(columns=["grupo", "concepto", "tipo"])

    try:
        resp = (
            client.table("categorias")
            .select("grupo, concepto, tipo")
            .eq("user_id", uid)
            .order("grupo", desc=False)
            .execute()
        )
    except Exception:
        return pd.DataFrame(columns=["grupo", "concepto", "tipo"])

    filas = resp.data or []
    if not filas:
        return pd.DataFrame(columns=["grupo", "concepto", "tipo"])
    df = pd.DataFrame(filas)
    if "tipo" not in df.columns:
        df["tipo"] = "Variable"
    df["tipo"] = df["tipo"].fillna("Variable")
    return df[["grupo", "concepto", "tipo"]]


def cargar_patrimonio_mensual(ruta_str: str = None) -> pd.DataFrame:
    """Carga snapshots de patrimonio. Formato largo: fecha|categoria|item|valor."""
    try:
        client, uid = _require()
    except RuntimeError:
        return pd.DataFrame(columns=["fecha", "categoria", "item", "valor"])

    try:
        resp = (
            client.table("patrimonio")
            .select("fecha, categoria, item, valor")
            .eq("user_id", uid)
            .order("fecha", desc=False)
            .execute()
        )
    except Exception:
        return pd.DataFrame(columns=["fecha", "categoria", "item", "valor"])

    filas = resp.data or []
    if not filas:
        return pd.DataFrame(columns=["fecha", "categoria", "item", "valor"])
    df = pd.DataFrame(filas)
    df["fecha"] = pd.to_datetime(df["fecha"], errors="coerce")
    df["valor"] = pd.to_numeric(df["valor"], errors="coerce").fillna(0.0)
    return df


def cargar_config(ruta_str: str = None) -> dict:
    """Carga la config key-value del usuario activo como dict {clave: valor}."""
    try:
        client, uid = _require()
    except RuntimeError:
        return {}

    try:
        resp = (
            client.table("config_usuario")
            .select("clave, valor")
            .eq("user_id", uid)
            .execute()
        )
    except Exception:
        return {}

    return {r["clave"]: r["valor"] for r in (resp.data or [])}


# ── Escrituras ────────────────────────────────────────────────────────────────

def _fecha_iso(v) -> str | None:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    if isinstance(v, (datetime, date, pd.Timestamp)):
        return pd.Timestamp(v).strftime("%Y-%m-%d")
    try:
        return pd.Timestamp(v).strftime("%Y-%m-%d")
    except Exception:
        return None


def insertar_transacciones(df: pd.DataFrame, fuente: str = "manual") -> int:
    """Inserta un DataFrame de transacciones. Retorna número de filas insertadas.

    Columnas esperadas: fecha, tipo_tx, grupo, concepto, detalle, importe, cuenta.
    Acepta también 'descripcion' como alias de 'detalle' y 'monto' de 'importe'
    (para enchufar directo la salida del importador bancario).
    """
    if df is None or df.empty:
        return 0
    client, uid = _require()

    registros = []
    for _, row in df.iterrows():
        detalle = row.get("detalle", row.get("descripcion", ""))
        importe = row.get("importe", row.get("monto", 0))
        # cuenta → forma_pago (nombre en Control_gastos)
        forma_pago = str(row.get("cuenta", row.get("forma_pago", "")) or "").strip()
        registros.append({
            "user_id":    uid,
            "fecha_date": _fecha_iso(row.get("fecha")),
            "tipo_tx":    str(row.get("tipo_tx", "Gasto")).strip() or "Gasto",
            "grupo":      str(row.get("grupo", "Varios y Otros")).strip() or "Varios y Otros",
            "concepto":   str(row.get("concepto", "") or "").strip(),
            "detalle":    str(detalle or "").strip(),
            "importe":    abs(float(importe or 0)),
            "forma_pago": forma_pago,
            "fuente":     fuente,
        })
    registros = [r for r in registros if r["fecha_date"] and r["importe"] > 0]
    if not registros:
        return 0

    total = 0
    for i in range(0, len(registros), 500):
        chunk = registros[i:i + 500]
        client.table("Control_gastos").insert(chunk).execute()
        total += len(chunk)
    return total


def actualizar_transaccion(tx_id: int, campos: dict) -> bool:
    """Actualiza campos de una transacción del usuario activo."""
    client, uid = _require()
    permitidos = {"fecha_date", "fecha", "tipo_tx", "grupo", "concepto", "detalle", "importe", "forma_pago", "cuenta", "fuente"}
    payload = {k: v for k, v in campos.items() if k in permitidos}
    # Normalizar nombres al esquema de Control_gastos
    if "fecha" in payload:
        payload["fecha_date"] = _fecha_iso(payload.pop("fecha"))
    if "fecha_date" in payload:
        payload["fecha_date"] = _fecha_iso(payload["fecha_date"])
    if "cuenta" in payload:
        payload["forma_pago"] = payload.pop("cuenta")
    if "importe" in payload:
        payload["importe"] = abs(float(payload["importe"] or 0))
    if not payload:
        return False
    try:
        client.table("Control_gastos").update(payload).eq("id", tx_id).eq("user_id", uid).execute()
        return True
    except Exception:
        return False


def eliminar_transaccion(tx_id: int) -> bool:
    """Elimina una transacción del usuario activo."""
    client, uid = _require()
    try:
        client.table("Control_gastos").delete().eq("id", tx_id).eq("user_id", uid).execute()
        return True
    except Exception:
        return False


def upsert_categorias(df: pd.DataFrame) -> int:
    """Upsert masivo de la taxonomía. Columnas: grupo, concepto, tipo."""
    if df is None or df.empty:
        return 0
    client, uid = _require()
    registros = []
    vistos = set()
    for _, row in df.iterrows():
        grupo = str(row.get("grupo", "") or "").strip()
        concepto = str(row.get("concepto", "") or "").strip()
        if not grupo or not concepto or (grupo, concepto) in vistos:
            continue
        vistos.add((grupo, concepto))
        registros.append({
            "user_id":  uid,
            "grupo":    grupo,
            "concepto": concepto,
            "tipo":     str(row.get("tipo", "Variable") or "Variable").strip(),
        })
    if not registros:
        return 0
    client.table("categorias").upsert(
        registros, on_conflict="user_id,grupo,concepto"
    ).execute()
    return len(registros)


def upsert_patrimonio(df: pd.DataFrame) -> int:
    """Upsert de snapshots de patrimonio. Columnas: fecha, categoria, item, valor."""
    if df is None or df.empty:
        return 0
    client, uid = _require()
    registros = []
    for _, row in df.iterrows():
        fecha = _fecha_iso(row.get("fecha"))
        cat = str(row.get("categoria", "") or "").strip().lower()
        item = str(row.get("item", "") or "").strip()
        if not fecha or cat not in ("activo", "pasivo") or not item:
            continue
        registros.append({
            "user_id":   uid,
            "fecha":     fecha,
            "categoria": cat,
            "item":      item,
            "valor":     float(row.get("valor", 0) or 0),
        })
    if not registros:
        return 0
    client.table("patrimonio").upsert(
        registros, on_conflict="user_id,fecha,categoria,item"
    ).execute()
    return len(registros)


def guardar_config(clave: str, valor) -> bool:
    """Upsert de un par clave-valor de configuración (valor → jsonb)."""
    client, uid = _require()
    try:
        client.table("config_usuario").upsert(
            {"user_id": uid, "clave": clave, "valor": valor},
            on_conflict="user_id,clave",
        ).execute()
        return True
    except Exception:
        return False


def guardar_config_bulk(config: dict) -> int:
    """Upsert masivo de configuración. Retorna número de claves guardadas."""
    if not config:
        return 0
    client, uid = _require()
    registros = [{"user_id": uid, "clave": k, "valor": v} for k, v in config.items()]
    client.table("config_usuario").upsert(
        registros, on_conflict="user_id,clave"
    ).execute()
    return len(registros)


def resetear_datos_usuario(confirmar: bool = False) -> dict:
    """PELIGRO: borra TODAS las filas del usuario activo en las 4 tablas.

    Requiere confirmar=True explícito. Lo usa el script de migración con
    la bandera --reset para permitir re-cargas limpias durante la
    validación del Sprint 5.
    """
    if not confirmar:
        raise RuntimeError("resetear_datos_usuario requiere confirmar=True")
    client, uid = _require()
    out = {}
    for tabla in ("Control_gastos", "patrimonio", "categorias", "config_usuario"):
        client.table(tabla).delete().eq("user_id", uid).execute()
        out[tabla] = "borrado"
    return out


def cargar_ingresos_reales_mes(mes: int, anio: int) -> float:
    """Suma importe de filas tipo_tx='Ingreso' del mes/anio dado.
    Retorna 0.0 si no hay datos o Supabase no disponible."""
    try:
        client, uid = _require()
    except RuntimeError:
        return 0.0
    import calendar
    fecha_ini = f"{anio}-{mes:02d}-01"
    ultimo = calendar.monthrange(anio, mes)[1]
    fecha_fin = f"{anio}-{mes:02d}-{ultimo:02d}"
    try:
        resp = (
            client.table("Control_gastos")
            .select("importe")
            .eq("user_id", uid)
            .eq("tipo_tx", "Ingreso")
            .gte("fecha_date", fecha_ini)
            .lte("fecha_date", fecha_fin)
            .execute()
        )
        return float(sum(r["importe"] for r in (resp.data or [])))
    except Exception:
        return 0.0


def cargar_config_mensual(mes: int, anio: int) -> dict:
    """Lee override de ingresos para el mes/anio dado desde config_ingresos_mensual.
    Retorna dict con claves de ingreso o {} si no hay fila para ese mes."""
    try:
        client, uid = _require()
    except RuntimeError:
        return {}
    try:
        resp = (
            client.table("config_ingresos_mensual")
            .select("sueldo_liquido,anticipo,amipass,arriendo_cobrado,ingreso_variable,bono_mensual,otros_ingresos,nota")
            .eq("user_id", uid)
            .eq("anio", anio)
            .eq("mes", mes)
            .execute()
        )
        rows = resp.data or []
        return rows[0] if rows else {}
    except Exception:
        return {}


def guardar_config_mensual(mes: int, anio: int, config: dict) -> bool:
    """Upsert de override mensual de ingresos en config_ingresos_mensual.
    config: dict con cualquier subconjunto de las claves de ingreso + nota opcional."""
    try:
        client, uid = _require()
    except RuntimeError:
        return False
    _campos = {
        "sueldo_liquido", "anticipo", "amipass", "arriendo_cobrado",
        "ingreso_variable", "bono_mensual", "otros_ingresos", "nota"
    }
    payload = {k: v for k, v in config.items() if k in _campos}
    payload.update({"user_id": uid, "anio": anio, "mes": mes})
    try:
        client.table("config_ingresos_mensual").upsert(
            payload, on_conflict="user_id,anio,mes"
        ).execute()
        return True
    except Exception:
        return False


def detectar_duplicados_potenciales(
    fecha_str: str,
    importe: float,
    ventana_dias: int = 15,
    grupo: str = "",
) -> list:
    """Busca transacciones con mismo importe en ventana +-ventana_dias dias.
    Retorna lista de dicts con id, fecha_date, tipo_tx, grupo, concepto, importe.
    Retorna [] si no hay candidatos o Supabase no disponible."""
    try:
        client, uid = _require()
    except RuntimeError:
        return []
    from datetime import datetime, timedelta
    try:
        fecha_dt = datetime.strptime(fecha_str, "%Y-%m-%d")
    except (ValueError, TypeError):
        return []
    fecha_ini = (fecha_dt - timedelta(days=ventana_dias)).strftime("%Y-%m-%d")
    fecha_fin = (fecha_dt + timedelta(days=ventana_dias)).strftime("%Y-%m-%d")
    try:
        resp = (
            client.table("Control_gastos")
            .select("id,fecha_date,tipo_tx,grupo,concepto,importe")
            .eq("user_id", uid)
            .eq("importe", importe)
            .gte("fecha_date", fecha_ini)
            .lte("fecha_date", fecha_fin)
            .execute()
        )
        candidatos = resp.data or []
        if grupo:
            candidatos.sort(key=lambda r: (0 if r.get("grupo") == grupo else 1))
        return candidatos
    except Exception:
        return []
