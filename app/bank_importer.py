import sys
sys.stdout.reconfigure(encoding="utf-8")

"""
bank_importer.py — Parser universal de archivos bancarios chilenos.

Bancos soportados: BCI, BancoEstado, Itaú, Falabella, Consorcio
Formatos: .xls / .xlsx

DataFrame normalizado de salida:
    fecha       datetime
    descripcion str     (descripción raw del banco → va a 'detalle' en el Excel)
    monto       float   (siempre positivo, en CLP o USD según moneda)
    tipo_mov    str     'cargo' | 'abono'
    moneda      str     'CLP' | 'USD'
    banco       str     'bci' | 'bancoestado' | 'itau' | 'falabella' | 'consorcio'
    cuenta      str     'cc' | 'tdc' | 'rut' | 'lc' | 'cuenta_mas'
    archivo     str     nombre del archivo fuente
"""

import os
import re
import json
from pathlib import Path
from datetime import datetime

import pandas as pd
from dotenv import load_dotenv

try:
    import pdfplumber as _pdfplumber
    _PDF_OK = True
except ImportError:
    _PDF_OK = False

load_dotenv(dotenv_path=Path(__file__).parent.parent.parent / ".env")

_DATA_DIR   = Path(__file__).parent.parent / "data"
_RULES_FILE = _DATA_DIR / "categorizacion_rules.json"

_COLS_OUT = ["fecha", "descripcion", "monto", "tipo_mov", "moneda", "banco", "cuenta", "archivo"]

# ── Patrones lógicos para comercios chilenos comunes ──────────────────────────
# (compiled_regex, tipo_tx, grupo, concepto)
# Orden importa: el primero que haga match gana.
_PATRONES_LOGICOS: list[tuple] = [
    # ── Alimentación: supermercados ───────────────────────────────────────────
    (re.compile(r"\blider\b|hip\s+lider|walmart", re.I), "Gasto", "Alimentación", "Supermercado"),
    (re.compile(r"\bjumbo\b", re.I),                      "Gasto", "Alimentación", "Supermercado"),
    (re.compile(r"unimarc", re.I),                        "Gasto", "Alimentación", "Supermercado"),
    (re.compile(r"santa\s+isabel", re.I),                 "Gasto", "Alimentación", "Supermercado"),
    (re.compile(r"tottus", re.I),                         "Gasto", "Alimentación", "Supermercado"),
    (re.compile(r"\bacuenta\b", re.I),                    "Gasto", "Alimentación", "Supermercado"),
    (re.compile(r"\bekono\b", re.I),                      "Gasto", "Alimentación", "Supermercado"),
    # ── Ocio y Vida Social: delivery + restaurantes ───────────────────────────
    (re.compile(r"uber\s+eats|ubereats", re.I),           "Gasto", "Ocio y Vida Social", "Comida Delivery"),
    (re.compile(r"pedidos\s*ya", re.I),                   "Gasto", "Ocio y Vida Social", "Comida Delivery"),
    (re.compile(r"\brappi\b", re.I),                      "Gasto", "Ocio y Vida Social", "Comida Delivery"),
    (re.compile(r"mc\s*donald|burger\s*king|pizza\s*hut|dominos|subway", re.I), "Gasto", "Ocio y Vida Social", "Restaurantes y Bares"),
    # ── Transporte ────────────────────────────────────────────────────────────
    (re.compile(r"\buber\b(?!\s*eats)", re.I),            "Gasto", "Transporte", "Apps Transporte (Uber/Cabify/Didi)"),
    (re.compile(r"\bcabify\b|\bdidi\b", re.I),            "Gasto", "Transporte", "Apps Transporte (Uber/Cabify/Didi)"),
    (re.compile(r"\bcopec\b", re.I),                      "Gasto", "Transporte", "Combustible"),
    (re.compile(r"\bpetrobras\b", re.I),                  "Gasto", "Transporte", "Combustible"),
    (re.compile(r"\bshell\b", re.I),                      "Gasto", "Transporte", "Combustible"),
    (re.compile(r"autopass|tag\s+express|autopista", re.I), "Gasto", "Transporte", "Tag y Peajes"),
    (re.compile(r"\bbip\b|tarjeta\s+bip|medio\s+de\s+pago\s+bip|medio\s+de\s+pago\s+fintoc|\bfintoc\b|\bmetro\s+s\.?\s*a\.?\b", re.I), "Gasto", "Transporte", "Transporte Público (Bip/Metro)"),
    # ── Salud y Cuidado Personal ──────────────────────────────────────────────
    (re.compile(r"smart\s*fit", re.I),                    "Gasto", "Salud y Cuidado Personal", "Gimnasio y Deportes"),
    (re.compile(r"salcobrand", re.I),                     "Gasto", "Salud y Cuidado Personal", "Farmacia y Medicamentos"),
    (re.compile(r"cruz\s+verde", re.I),                   "Gasto", "Salud y Cuidado Personal", "Farmacia y Medicamentos"),
    (re.compile(r"dr\.?\s*ahumada|farmacia\s+ahumada", re.I), "Gasto", "Salud y Cuidado Personal", "Farmacia y Medicamentos"),
    (re.compile(r"\bripley\b", re.I),                     "Gasto", "Salud y Cuidado Personal", "Ropa y Calzado (Adultos)"),
    (re.compile(r"\bparis\b", re.I),                      "Gasto", "Salud y Cuidado Personal", "Ropa y Calzado (Adultos)"),
    # ── Suscripciones Digitales ───────────────────────────────────────────────
    (re.compile(r"\bnetflix\b", re.I),                    "Gasto", "Suscripciones Digitales", "Streaming"),
    (re.compile(r"\bspotify\b", re.I),                    "Gasto", "Suscripciones Digitales", "Streaming"),
    (re.compile(r"amazon\s+prime|prime\s+video", re.I),   "Gasto", "Suscripciones Digitales", "Streaming"),
    (re.compile(r"disney\+?|hbo\s*max", re.I),            "Gasto", "Suscripciones Digitales", "Streaming"),
    (re.compile(r"anthropic|claude\.ai", re.I),           "Gasto", "Suscripciones Digitales", "IA y Productividad"),
    (re.compile(r"\bopenai\b|chatgpt", re.I),             "Gasto", "Suscripciones Digitales", "IA y Productividad"),
    # ── Servicios Básicos ─────────────────────────────────────────────────────
    (re.compile(r"\bgtd\b", re.I),                        "Gasto", "Servicios Básicos", "Internet Hogar / Cable"),
    (re.compile(r"\bentel\b", re.I),                      "Gasto", "Servicios Básicos", "Celular / Plan Móvil"),
    (re.compile(r"\bmovistar\b", re.I),                   "Gasto", "Servicios Básicos", "Celular / Plan Móvil"),
    (re.compile(r"\bclaro\b", re.I),                      "Gasto", "Servicios Básicos", "Celular / Plan Móvil"),
    (re.compile(r"\bwom\b", re.I),                        "Gasto", "Servicios Básicos", "Celular / Plan Móvil"),
    # ── Hogar y Vivienda ─────────────────────────────────────────────────────
    (re.compile(r"\bsodimac\b", re.I),                    "Gasto", "Hogar y Vivienda", "Muebles y Decoración"),
    (re.compile(r"\beasy\b", re.I),                       "Gasto", "Hogar y Vivienda", "Muebles y Decoración"),
]


_RE_PREFIJO_BCI = re.compile(
    r"^compra\s+con\s+tarjeta\s+de\s+d[eé]bito\s+en\s+"
    r"|^compra\s+tarjeta\s+d[eé]bito\s+en\s+"
    r"|^pago\s+en\s+l[íi]nea\s+",
    re.I,
)
_RE_PREFIJO_BE = re.compile(
    r"^compra\s+",
    re.I,
)
_RE_MERCADOPAGO = re.compile(r"(?:mercadopago|sumup|webpay|flow)\*([A-Z0-9][A-Z0-9 \-\*\.]+)", re.I)
_RE_SUFIJO_CL   = re.compile(r"\s+(CHL?|CHILE)\s*$", re.I)


def _extraer_comercio(desc: str) -> str:
    """
    Extrae el nombre del comercio real de descripciones bancarias con prefijos largos.

    BCI:  "Compra con Tarjeta de Débito en GTD M." → "GTD M."
    BE:   "COMPRA HIP LIDER MA CL"               → "HIP LIDER MA"
    MP:   "Compra ... en MERCADOPAGO*ALLFOO ..."  → "ALLFOO"  (sub-comercio)
    Otros: descripción original sin cambio
    """
    # MercadoPago: extraer sub-comercio
    m = _RE_MERCADOPAGO.search(desc)
    if m:
        return m.group(1).strip()

    # BCI: quitar prefijo "Compra con Tarjeta de Débito en "
    s = _RE_PREFIJO_BCI.sub("", desc).strip()
    if s != desc:
        return _RE_SUFIJO_CL.sub("", s).strip()

    # BancoEstado: quitar "COMPRA " inicial
    s = _RE_PREFIJO_BE.sub("", desc).strip()
    if s != desc:
        return _RE_SUFIJO_CL.sub("", s).strip()

    return desc


def _buscar_patron_logico(desc: str) -> dict | None:
    """
    Busca patrón lógico usando tanto la descripción original como el comercio extraído.
    Esto permite que 'Compra con Tarjeta de Débito en GTD M.' matchee el patrón GTD.
    """
    comercio = _extraer_comercio(desc)
    for texto in (comercio, desc) if comercio != desc else (desc,):
        for pattern, tipo_tx, grupo, concepto in _PATRONES_LOGICOS:
            if pattern.search(texto):
                return {"tipo_tx": tipo_tx, "grupo": grupo, "concepto": concepto}
    return None


def _infer_tipo_tx_desde_grupo(grupo: str) -> str:
    g = grupo.lower()
    if any(k in g for k in ("ingreso", "sueldo", "honorario", "remuneraci")):
        return "Ingreso"
    if any(k in g for k in ("ahorro", "inversión", "inversion", "financiero", "deuda")):
        return "Transferencia"
    return "Gasto"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _parse_monto(valor) -> float:
    """Parsea montos en formato chileno (punto=miles, coma=decimal) o numérico."""
    if valor is None or (isinstance(valor, float) and pd.isna(valor)):
        return 0.0
    if isinstance(valor, (int, float)):
        return abs(float(valor))
    s = str(valor).strip().replace("$", "").replace(" ", "").replace("\xa0", "")
    if not s or s in ("nan", "None", "-"):
        return 0.0
    negative = s.startswith("-")
    s = s.lstrip("+-")
    # Formato "1.234.567,89" → 1234567.89
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    # Formato "2.650" o "100.000" → miles (3 dígitos después del último punto)
    elif re.match(r"^\d{1,3}(\.\d{3})+$", s):
        s = s.replace(".", "")
    try:
        return abs(float(s))
    except ValueError:
        return 0.0


def _es_negativo(valor) -> bool:
    """Retorna True si el valor representa un número negativo."""
    if isinstance(valor, (int, float)):
        return float(valor) < 0
    s = str(valor).strip()
    return s.startswith("-")


_MESES_ES = {
    "ene": 1, "feb": 2, "mar": 3, "abr": 4, "may": 5, "jun": 6,
    "jul": 7, "ago": 8, "sep": 9, "oct": 10, "nov": 11, "dic": 12,
}


def _parse_fecha(valor, año_ctx: int = None) -> pd.Timestamp:
    if valor is None or (isinstance(valor, float) and pd.isna(valor)):
        return pd.NaT
    if isinstance(valor, (datetime, pd.Timestamp)):
        return pd.Timestamp(valor)
    s = str(valor).strip()
    # Formato BancoEstado Cartola: "02/Ene", "15/Mar"
    m = re.match(r"^(\d{1,2})/([A-Za-z]{3})$", s)
    if m:
        dia = int(m.group(1))
        mes = _MESES_ES.get(m.group(2).lower(), 0)
        if mes > 0:
            año = año_ctx or datetime.now().year
            try:
                return pd.Timestamp(año, mes, dia)
            except ValueError:
                return pd.NaT
    for fmt in ("%d-%m-%Y", "%d/%m/%Y", "%Y-%m-%d", "%d/%b/%Y", "%Y/%m/%d",
                "%d-%m-%Y %H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return pd.Timestamp(datetime.strptime(s[:19], fmt))
        except ValueError:
            pass
    try:
        return pd.to_datetime(s, dayfirst=True)
    except Exception:
        return pd.NaT


def _df_vacio() -> pd.DataFrame:
    return pd.DataFrame(columns=_COLS_OUT)


def _leer_excel(path: Path) -> pd.DataFrame:
    try:
        return pd.read_excel(path, header=None, dtype=str)
    except Exception:
        try:
            return pd.read_excel(path, header=None, engine="xlrd", dtype=str)
        except Exception:
            return pd.DataFrame()


def _texto_cabecera(raw: pd.DataFrame, nrows: int = 15) -> str:
    return " ".join(raw.iloc[:nrows].fillna("").astype(str).values.flatten()).lower()


def _find_col(headers: list[str], keywords: list[str]) -> int | None:
    for i, h in enumerate(headers):
        if any(k in str(h).lower() for k in keywords):
            return i
    return None


def _find_header_row(raw: pd.DataFrame, required: list[str]) -> int | None:
    for i, row in raw.iterrows():
        vals = " ".join(str(v).lower() for v in row if str(v) != "nan")
        if all(r in vals for r in required):
            return i
    return None


# ── Detección de banco ────────────────────────────────────────────────────────

def detectar_banco_formato(path: str | Path) -> dict:
    """
    Detecta banco y tipo de cuenta leyendo el contenido del archivo.
    Retorna {banco, cuenta, moneda}.
    """
    path = Path(path)
    ext = path.suffix.lower()

    # PDF: BancoEstado TDC (Estado de Cuenta) y Facturado
    if ext == ".pdf":
        if not _PDF_OK:
            return {"banco": "desconocido", "cuenta": "desconocido", "moneda": "CLP"}
        try:
            with _pdfplumber.open(path) as pdf:
                txt = " ".join(
                    (page.extract_text() or "") for page in pdf.pages[:3]
                ).lower()
        except Exception:
            return {"banco": "desconocido", "cuenta": "desconocido", "moneda": "CLP"}
        # Recibo individual: "Facturado nacional" o "Facturado internacional"
        if "facturado nacional" in txt:
            return {"banco": "bancoestado", "cuenta": "tdc_facturado", "moneda": "CLP"}
        if "facturado internacional" in txt:
            moneda = "USD" if "us$" in txt else "CLP"
            return {"banco": "bancoestado", "cuenta": "tdc_facturado", "moneda": moneda}
        # Estado de cuenta mensual
        if any(k in txt for k in ("estado de cuenta", "tarjeta de crédito", "tarjeta de credito", "bancoestado")):
            return {"banco": "bancoestado", "cuenta": "tdc", "moneda": "CLP"}
        return {"banco": "desconocido", "cuenta": "desconocido", "moneda": "CLP"}

    if ext not in (".xls", ".xlsx"):
        return {"banco": "desconocido", "cuenta": "desconocido", "moneda": "CLP"}

    raw = _leer_excel(path)
    if raw.empty:
        return {"banco": "desconocido", "cuenta": "desconocido", "moneda": "CLP"}

    txt = _texto_cabecera(raw, nrows=15)

    # ── Falabella — detectar primero (formato más único: titular/adicional) ──
    if "titular/adicional" in txt:
        return {"banco": "falabella", "cuenta": "tdc", "moneda": "CLP"}

    # ── Consorcio — detectar antes de Itaú (sus tx tienen "banco itaú" en descripción) ──
    if "cuenta corriente - ******" in txt or "cuenta m" in txt and "abono de intereses saldo" in txt:
        if "cuenta m" in txt and any(k in txt for k in ("cuenta mas", "cuenta más", "intereses saldo")):
            return {"banco": "consorcio", "cuenta": "cuenta_mas", "moneda": "CLP"}
        return {"banco": "consorcio", "cuenta": "cc", "moneda": "CLP"}

    # ── BCI ──
    # TDC: identificador único "detalle movimientos tarjeta de crédito" o "bci visa/mastercard"
    if any(k in txt for k in ("detalle movimientos tarjeta de cr", "bci visa", "bci mastercard")):
        if any(k in txt for k in ("internacional", "monto (usd)", "usd")):
            return {"banco": "bci", "cuenta": "tdc", "moneda": "USD"}
        return {"banco": "bci", "cuenta": "tdc", "moneda": "CLP"}
    # CC y LC: identificador "sobregiro disponible" o "movimientos de su cuenta" o "linea de sobregiro"
    if any(k in txt for k in ("sobregiro disponible", "movimientos de su cuenta", "linea de emergencia")):
        if "linea de sobregiro" in txt or "movimiento de su linea" in txt:
            return {"banco": "bci", "cuenta": "lc", "moneda": "CLP"}
        return {"banco": "bci", "cuenta": "cc", "moneda": "CLP"}

    # ── BancoEstado — "cuenta corriente n°" o "cuentarut" o "línea de crédito n°" ──
    if any(k in txt for k in ("cartola cuenta corriente", "ultimos movimientos cuenta corriente", "últimos movimientos cuenta corriente")):
        return {"banco": "bancoestado", "cuenta": "cc", "moneda": "CLP"}
    if any(k in txt for k in ("cartola cuentarut", "ultimos movimientos cuentarut", "últimos movimientos cuentarut")):
        return {"banco": "bancoestado", "cuenta": "rut", "moneda": "CLP"}
    if any(k in txt for k in ("ultimos movimientos línea de crédito", "ultimos movimientos linea de credito", "últimos movimientos línea")):
        return {"banco": "bancoestado", "cuenta": "lc", "moneda": "CLP"}

    # ── Itaú — identificar por patrones únicos (no por nombre del banco) ──
    # TDC Últimos Dólares/Pesos
    if any(k in txt for k in ("ultimas compras dólares", "ultimas compras dolares", "últimas compras dólares")):
        return {"banco": "itau", "cuenta": "tdc", "moneda": "USD"}
    if any(k in txt for k in ("ultimas compras pesos", "últimas compras pesos")):
        return {"banco": "itau", "cuenta": "tdc", "moneda": "CLP"}
    # TDC Estado de cuenta
    if "estado de cuenta internacional" in txt:
        return {"banco": "itau", "cuenta": "tdc_estado", "moneda": "USD"}
    if "estado de cuenta nacional" in txt and "tarjeta de cr" in txt:
        return {"banco": "itau", "cuenta": "tdc_estado", "moneda": "CLP"}
    # CC: "línea preferencial" es único de Itaú CC
    if any(k in txt for k in ("línea preferencial", "linea preferencial")):
        return {"banco": "itau", "cuenta": "cc", "moneda": "CLP"}
    # LC: "detalle de cartola histórica" o "cartola historica linea"
    if any(k in txt for k in ("detalle de cartola hist", "cartolahistoricalinea")) or ("linea de credito" in txt and "monto autorizado" in txt):
        return {"banco": "itau", "cuenta": "lc", "moneda": "CLP"}
    # Crédito consumo
    if any(k in txt for k in ("créditos de consumo vigentes", "creditos de consumo")):
        return {"banco": "itau", "cuenta": "credito_consumo", "moneda": "CLP"}

    return {"banco": "desconocido", "cuenta": "desconocido", "moneda": "CLP"}


# ── Parsers individuales ──────────────────────────────────────────────────────

def _parsear_bci_cc(path: Path) -> pd.DataFrame:
    raw = _leer_excel(path)
    txt = _texto_cabecera(raw)

    # "Últimos movimientos" → Fecha Transacción | Fecha Contable | Descripción | ... | Cargo $ | Abono $
    if "fecha transacci" in txt or "cargo $" in txt:
        hrow = _find_header_row(raw, ["cargo", "abono"])
        if hrow is None:
            return _df_vacio()
        headers = [str(v).lower() for v in raw.iloc[hrow]]
        idx_f = _find_col(headers, ["fecha transacci", "fecha"])
        idx_d = _find_col(headers, ["descripci"])
        idx_c = _find_col(headers, ["cargo"])
        idx_a = _find_col(headers, ["abono"])
        filas = []
        for _, row in raw.iloc[hrow + 1:].iterrows():
            fecha = _parse_fecha(row.iloc[idx_f] if idx_f is not None else None)
            if pd.isna(fecha):
                continue
            desc = str(row.iloc[idx_d]).strip() if idx_d is not None else ""
            if not desc or desc in ("nan", "None"):
                continue
            cargo = _parse_monto(row.iloc[idx_c]) if idx_c is not None else 0.0
            abono = _parse_monto(row.iloc[idx_a]) if idx_a is not None else 0.0
            if cargo > 0:
                filas.append({"fecha": fecha, "descripcion": desc, "monto": cargo, "tipo_mov": "cargo"})
            elif abono > 0:
                filas.append({"fecha": fecha, "descripcion": desc, "monto": abono, "tipo_mov": "abono"})

    else:
        # "Cartola actual" → Fecha | Descripción | Serie | Monto $ | Saldo $
        hrow = _find_header_row(raw, ["fecha", "descripci"])
        if hrow is None:
            return _df_vacio()
        headers = [str(v).lower() for v in raw.iloc[hrow]]
        idx_f = _find_col(headers, ["fecha"])
        idx_d = _find_col(headers, ["descripci"])
        idx_m = _find_col(headers, ["monto"])
        filas = []
        for _, row in raw.iloc[hrow + 1:].iterrows():
            fecha = _parse_fecha(row.iloc[idx_f] if idx_f is not None else None)
            if pd.isna(fecha):
                continue
            desc = str(row.iloc[idx_d]).strip() if idx_d is not None else ""
            if not desc or desc in ("nan", "None"):
                continue
            monto_raw = row.iloc[idx_m] if idx_m is not None else None
            monto = _parse_monto(monto_raw)
            if monto == 0:
                continue
            tipo_mov = "cargo" if _es_negativo(monto_raw) else "abono"
            filas.append({"fecha": fecha, "descripcion": desc, "monto": monto, "tipo_mov": tipo_mov})

    if not filas:
        return _df_vacio()
    df = pd.DataFrame(filas)
    df["moneda"] = "CLP"
    df["banco"] = "bci"
    df["cuenta"] = "cc"
    df["archivo"] = path.name
    return df[_COLS_OUT]


def _parsear_bci_lc(path: Path) -> pd.DataFrame:
    raw = _leer_excel(path)
    hrow = _find_header_row(raw, ["fecha", "monto"])
    if hrow is None:
        return _df_vacio()
    headers = [str(v).lower() for v in raw.iloc[hrow]]
    idx_f = _find_col(headers, ["fecha"])
    idx_d = _find_col(headers, ["descripci"])
    idx_m = _find_col(headers, ["monto", "deuda"])
    filas = []
    for _, row in raw.iloc[hrow + 1:].iterrows():
        fecha = _parse_fecha(row.iloc[idx_f] if idx_f is not None else None)
        if pd.isna(fecha):
            continue
        desc = str(row.iloc[idx_d]).strip() if idx_d is not None else ""
        if not desc or desc in ("nan", "None"):
            continue
        monto = _parse_monto(row.iloc[idx_m]) if idx_m is not None else 0.0
        if monto == 0:
            continue
        filas.append({"fecha": fecha, "descripcion": desc, "monto": monto, "tipo_mov": "cargo"})
    if not filas:
        return _df_vacio()
    df = pd.DataFrame(filas)
    df["moneda"] = "CLP"
    df["banco"] = "bci"
    df["cuenta"] = "lc"
    df["archivo"] = path.name
    return df[_COLS_OUT]


def _parsear_bci_tdc(path: Path, moneda: str = "CLP") -> pd.DataFrame:
    """Facturado + No facturado nacional e internacional."""
    raw = _leer_excel(path)
    hrow = _find_header_row(raw, ["fecha", "descripci"])
    if hrow is None:
        return _df_vacio()
    headers = [str(v).lower() for v in raw.iloc[hrow]]
    idx_f  = _find_col(headers, ["fecha"])
    idx_d  = _find_col(headers, ["descripci"])
    idx_c  = _find_col(headers, ["ciudad"])
    idx_m  = _find_col(headers, ["monto"])
    filas = []
    for _, row in raw.iloc[hrow + 1:].iterrows():
        fecha = _parse_fecha(row.iloc[idx_f] if idx_f is not None else None)
        if pd.isna(fecha):
            continue
        desc = str(row.iloc[idx_d]).strip() if idx_d is not None else ""
        if not desc or desc in ("nan", "None"):
            continue
        ciudad = str(row.iloc[idx_c]).strip() if idx_c is not None else ""
        full_desc = f"{desc} {ciudad}".strip() if ciudad and ciudad != "nan" else desc
        monto_raw = row.iloc[idx_m] if idx_m is not None else None
        monto = _parse_monto(monto_raw)
        if monto == 0:
            continue
        tipo_mov = "abono" if _es_negativo(monto_raw) else "cargo"
        filas.append({"fecha": fecha, "descripcion": full_desc, "monto": monto, "tipo_mov": tipo_mov})
    if not filas:
        return _df_vacio()
    df = pd.DataFrame(filas)
    df["moneda"] = moneda
    df["banco"] = "bci"
    df["cuenta"] = "tdc"
    df["archivo"] = path.name
    return df[_COLS_OUT]


def _parsear_bancoestado_cc(path: Path, cuenta: str = "cc") -> pd.DataFrame:
    raw = _leer_excel(path)

    # Extraer año del cartola si aplica (para fechas "DD/Mes")
    año_ctx = None
    txt_completo = " ".join(raw.fillna("").astype(str).values.flatten())
    m_año = re.search(r"(20\d{2})", txt_completo)
    if m_año:
        año_ctx = int(m_año.group(1))

    hrow = _find_header_row(raw, ["fecha", "descripci"])
    if hrow is None:
        return _df_vacio()
    headers = [str(v).lower() for v in raw.iloc[hrow]]
    idx_f = _find_col(headers, ["fecha"])
    idx_d = _find_col(headers, ["descripci"])
    idx_a = _find_col(headers, ["abono"])
    idx_c = _find_col(headers, ["cargo", "giro", "cheque"])
    idx_m = _find_col(headers, ["monto"])

    filas = []
    for _, row in raw.iloc[hrow + 1:].iterrows():
        fecha = _parse_fecha(row.iloc[idx_f] if idx_f is not None else None, año_ctx=año_ctx)
        if pd.isna(fecha):
            continue
        desc = str(row.iloc[idx_d]).strip() if idx_d is not None else ""
        if not desc or desc in ("nan", "None"):
            continue
        if idx_a is not None and idx_c is not None:
            abono = _parse_monto(row.iloc[idx_a])
            cargo = _parse_monto(row.iloc[idx_c])
            if cargo > 0:
                filas.append({"fecha": fecha, "descripcion": desc, "monto": cargo, "tipo_mov": "cargo"})
            elif abono > 0:
                filas.append({"fecha": fecha, "descripcion": desc, "monto": abono, "tipo_mov": "abono"})
        elif idx_m is not None:
            monto_raw = row.iloc[idx_m]
            monto = _parse_monto(monto_raw)
            if monto == 0:
                continue
            tipo_mov = "cargo" if _es_negativo(monto_raw) else "abono"
            filas.append({"fecha": fecha, "descripcion": desc, "monto": monto, "tipo_mov": tipo_mov})
    if not filas:
        return _df_vacio()
    df = pd.DataFrame(filas)
    df["moneda"] = "CLP"
    df["banco"] = "bancoestado"
    df["cuenta"] = cuenta
    df["archivo"] = path.name
    return df[_COLS_OUT]


def _parsear_itau_cc(path: Path) -> pd.DataFrame:
    raw = _leer_excel(path)
    hrow = _find_header_row(raw, ["fecha", "movimiento"])
    if hrow is None:
        return _df_vacio()
    headers = [str(v).lower() for v in raw.iloc[hrow]]
    idx_f = _find_col(headers, ["fecha"])
    idx_d = _find_col(headers, ["movimiento"])
    idx_c = _find_col(headers, ["cargo"])
    idx_a = _find_col(headers, ["abono"])
    filas = []
    for _, row in raw.iloc[hrow + 1:].iterrows():
        fecha = _parse_fecha(row.iloc[idx_f] if idx_f is not None else None)
        if pd.isna(fecha):
            continue
        desc = str(row.iloc[idx_d]).strip() if idx_d is not None else ""
        if not desc or desc in ("nan", "None"):
            continue
        cargo = _parse_monto(row.iloc[idx_c]) if idx_c is not None else 0.0
        abono = _parse_monto(row.iloc[idx_a]) if idx_a is not None else 0.0
        if cargo > 0:
            filas.append({"fecha": fecha, "descripcion": desc, "monto": cargo, "tipo_mov": "cargo"})
        elif abono > 0:
            filas.append({"fecha": fecha, "descripcion": desc, "monto": abono, "tipo_mov": "abono"})
    if not filas:
        return _df_vacio()
    df = pd.DataFrame(filas)
    df["moneda"] = "CLP"
    df["banco"] = "itau"
    df["cuenta"] = "cc"
    df["archivo"] = path.name
    return df[_COLS_OUT]


def _parsear_itau_tdc_ultimos(path: Path, moneda: str = "CLP") -> pd.DataFrame:
    """Últimas compras pesos / dólares."""
    raw = _leer_excel(path)
    hrow = _find_header_row(raw, ["fecha", "descripci"])
    if hrow is None:
        return _df_vacio()
    headers = [str(v).lower() for v in raw.iloc[hrow]]
    idx_f = _find_col(headers, ["fecha compra", "fecha"])
    idx_d = _find_col(headers, ["descripci"])
    idx_m = _find_col(headers, ["monto"])
    filas = []
    for _, row in raw.iloc[hrow + 1:].iterrows():
        fecha = _parse_fecha(row.iloc[idx_f] if idx_f is not None else None)
        if pd.isna(fecha):
            continue
        desc = str(row.iloc[idx_d]).strip() if idx_d is not None else ""
        if not desc or desc in ("nan", "None"):
            continue
        monto_raw = row.iloc[idx_m] if idx_m is not None else None
        monto = _parse_monto(monto_raw)
        if monto == 0:
            continue
        tipo_mov = "abono" if _es_negativo(monto_raw) else "cargo"
        filas.append({"fecha": fecha, "descripcion": desc, "monto": monto, "tipo_mov": tipo_mov})
    if not filas:
        return _df_vacio()
    df = pd.DataFrame(filas)
    df["moneda"] = moneda
    df["banco"] = "itau"
    df["cuenta"] = "tdc"
    df["archivo"] = path.name
    return df[_COLS_OUT]


def _parsear_itau_tdc_estado(path: Path, moneda: str = "CLP") -> pd.DataFrame:
    """Estado de cuenta Itaú TDC — formato complejo con secciones."""
    raw = _leer_excel(path)
    # Header contiene "Fecha operación" y "Descripción operación o cobro"
    hrow = _find_header_row(raw, ["fecha operaci", "descripci"])
    if hrow is None:
        return _df_vacio()
    headers = [str(v).lower() for v in raw.iloc[hrow]]
    idx_f = _find_col(headers, ["fecha operaci"])
    idx_d = _find_col(headers, ["descripci"])
    idx_m = _find_col(headers, ["monto operaci"])
    filas = []
    for _, row in raw.iloc[hrow + 1:].iterrows():
        fecha = _parse_fecha(row.iloc[idx_f] if idx_f is not None else None)
        if pd.isna(fecha):
            continue
        desc = str(row.iloc[idx_d]).strip() if idx_d is not None else ""
        if not desc or desc in ("nan", "None") or "." in desc and len(desc) < 5:
            continue
        monto_raw = row.iloc[idx_m] if idx_m is not None else None
        monto = _parse_monto(monto_raw)
        if monto == 0:
            continue
        tipo_mov = "abono" if _es_negativo(monto_raw) else "cargo"
        filas.append({"fecha": fecha, "descripcion": desc, "monto": monto, "tipo_mov": tipo_mov})
    if not filas:
        return _df_vacio()
    df = pd.DataFrame(filas)
    df["moneda"] = moneda
    df["banco"] = "itau"
    df["cuenta"] = "tdc"
    df["archivo"] = path.name
    return df[_COLS_OUT]


def _parsear_falabella(path: Path) -> pd.DataFrame:
    raw = _leer_excel(path)
    # Header en fila 0: FECHA | DESCRIPCION | TITULAR/ADICIONAL | MONTO | ...
    headers = [str(v).lower() for v in raw.iloc[0]]
    idx_f = _find_col(headers, ["fecha"])
    idx_d = _find_col(headers, ["descripcion"])
    idx_m = _find_col(headers, ["monto"])
    if idx_f is None or idx_m is None:
        return _df_vacio()
    filas = []
    for _, row in raw.iloc[1:].iterrows():
        fecha = _parse_fecha(row.iloc[idx_f])
        if pd.isna(fecha):
            continue
        desc = str(row.iloc[idx_d]).strip() if idx_d is not None else ""
        if not desc or desc in ("nan", "None"):
            continue
        monto = _parse_monto(row.iloc[idx_m])
        if monto == 0:
            continue
        is_pago = any(k in desc.lower() for k in ("pago tarjeta", "pago cmr", "cancelado", "abono"))
        tipo_mov = "abono" if is_pago else "cargo"
        filas.append({"fecha": fecha, "descripcion": desc, "monto": monto, "tipo_mov": tipo_mov})
    if not filas:
        return _df_vacio()
    df = pd.DataFrame(filas)
    df["moneda"] = "CLP"
    df["banco"] = "falabella"
    df["cuenta"] = "tdc"
    df["archivo"] = path.name
    return df[_COLS_OUT]


def _parsear_consorcio(path: Path, cuenta: str = "cc") -> pd.DataFrame:
    raw = _leer_excel(path)
    hrow = _find_header_row(raw, ["fecha", "descripci"])
    if hrow is None:
        return _df_vacio()
    headers = [str(v).lower() for v in raw.iloc[hrow]]
    idx_f = _find_col(headers, ["fecha"])
    idx_d = _find_col(headers, ["descripci"])
    idx_c = _find_col(headers, ["cargo"])
    idx_a = _find_col(headers, ["abono"])
    filas = []
    for _, row in raw.iloc[hrow + 1:].iterrows():
        fecha = _parse_fecha(row.iloc[idx_f] if idx_f is not None else None)
        if pd.isna(fecha):
            continue
        desc = str(row.iloc[idx_d]).strip() if idx_d is not None else ""
        if not desc or desc in ("nan", "None"):
            continue
        cargo = _parse_monto(row.iloc[idx_c]) if idx_c is not None else 0.0
        abono = _parse_monto(row.iloc[idx_a]) if idx_a is not None else 0.0
        if cargo > 0:
            filas.append({"fecha": fecha, "descripcion": desc, "monto": cargo, "tipo_mov": "cargo"})
        elif abono > 0:
            filas.append({"fecha": fecha, "descripcion": desc, "monto": abono, "tipo_mov": "abono"})
    if not filas:
        return _df_vacio()
    df = pd.DataFrame(filas)
    df["moneda"] = "CLP"
    df["banco"] = "consorcio"
    df["cuenta"] = cuenta
    df["archivo"] = path.name
    return df[_COLS_OUT]


_RE_USD_PREFIX = re.compile(r"US\$\s*", re.I)

_RE_FECHA_PDF  = re.compile(r"^\d{2}/\d{2}/\d{4}$")
_RE_FOLIO_PDF  = re.compile(r"^\d{6,12}$")
_RE_MONTO_PDF  = re.compile(r"^-?\$[\d.,]+$")
_SKIP_DESC_PDF = re.compile(
    r"^(total\s+operaci|total\s+pago|saldo\s+anterior|total|n[°º]?\s+cuotas)",
    re.I,
)


def _parsear_bancoestado_tdc_facturado_pdf(path: Path, moneda: str = "CLP") -> pd.DataFrame:
    """
    Parsea recibos individuales de BancoEstado TDC ('Movimiento Facturado').
    Formato: tabla clave-valor con Monto, Descripción, Fecha (1 transacción por PDF).
    """
    if not _PDF_OK:
        return _df_vacio()
    kv: dict[str, str] = {}
    try:
        with _pdfplumber.open(path) as pdf:
            for page in pdf.pages:
                for tabla in page.extract_tables():
                    for row in tabla:
                        if row and len(row) >= 2 and row[0] and row[1]:
                            kv[str(row[0]).strip()] = str(row[1]).strip()
    except Exception:
        return _df_vacio()

    fecha_str = kv.get("Fecha", "")
    desc      = kv.get("Descripción", "Sin descripción").strip()
    monto_str = kv.get("Monto", "0")

    # Detectar USD en el campo Monto
    if _RE_USD_PREFIX.search(monto_str):
        moneda = "USD"
    monto_str_clean = _RE_USD_PREFIX.sub("", monto_str).strip()
    monto = _parse_monto(monto_str_clean)
    if monto == 0:
        return _df_vacio()

    try:
        fecha = pd.Timestamp(datetime.strptime(fecha_str, "%d/%m/%Y"))
    except ValueError:
        return _df_vacio()

    tipo_mov = "abono" if any(k in desc.lower() for k in ("cancelado", "pago deuda", "abono")) else "cargo"

    df = pd.DataFrame([{"fecha": fecha, "descripcion": desc, "monto": monto, "tipo_mov": tipo_mov}])
    df["moneda"]  = moneda
    df["banco"]   = "bancoestado"
    df["cuenta"]  = "tdc"
    df["archivo"] = path.name
    return df[_COLS_OUT]


def _parsear_bancoestado_tdc_pdf(path: Path) -> pd.DataFrame:
    """
    Parsea el "Estado de Cuenta" TDC de BancoEstado (PDF descargado del banco).

    Estructura de tabla por página:
      Col 0: Ciudad (puede estar vacío)
      Col 1: fecha DD/MM/YYYY
      Col 2: folio (≥6 dígitos)
      Col 3: descripción
      Col 4: monto total cuota
      Col 5: monto cuota
      Col 6: "X/Y" cuotas
      Col 7: monto a pagar  ← columna de importe efectivo

    Negativo → abono (pago de tarjeta).  Positivo → cargo (compra/comisión).
    """
    if not _PDF_OK:
        return _df_vacio()

    filas = []
    try:
        with _pdfplumber.open(path) as pdf:
            for page in pdf.pages:
                tablas = page.extract_tables()
                for tabla in tablas:
                    for row in tabla:
                        if not row or len(row) < 5:
                            continue
                        # Encontrar columna de fecha (DD/MM/YYYY)
                        # La tabla puede tener ciudad en col 0 (a veces None)
                        # Detectamos posición dinámica de la fecha
                        fecha_col = None
                        for ci, cell in enumerate(row):
                            if cell and _RE_FECHA_PDF.match(str(cell).strip()):
                                fecha_col = ci
                                break
                        if fecha_col is None:
                            continue

                        fecha_str = str(row[fecha_col]).strip()
                        try:
                            fecha = pd.Timestamp(datetime.strptime(fecha_str, "%d/%m/%Y"))
                        except ValueError:
                            continue

                        # descripción está justo después del folio (fecha+1 o fecha+2)
                        desc_col = fecha_col + 2  # col fecha+1 = folio, fecha+2 = desc
                        if desc_col >= len(row):
                            continue

                        desc = str(row[desc_col] or "").strip()
                        if not desc or desc in ("nan", "None"):
                            continue
                        if _SKIP_DESC_PDF.match(desc):
                            continue

                        # Monto a pagar = última columna con valor de monto
                        monto_raw = None
                        for cell in reversed(row):
                            if cell and _RE_MONTO_PDF.match(str(cell).strip()):
                                monto_raw = str(cell).strip()
                                break
                        if monto_raw is None:
                            continue

                        negativo = monto_raw.startswith("-")
                        monto = _parse_monto(monto_raw)
                        if monto == 0:
                            continue

                        # Pagos de tarjeta (MONTO CANCELADO) → patrimonial / abono
                        if "monto cancelado" in desc.lower():
                            tipo_mov = "abono"
                        else:
                            tipo_mov = "abono" if negativo else "cargo"

                        filas.append({
                            "fecha": fecha,
                            "descripcion": desc,
                            "monto": monto,
                            "tipo_mov": tipo_mov,
                        })
    except Exception as e:
        return _df_vacio()

    if not filas:
        return _df_vacio()
    df = pd.DataFrame(filas)
    df["moneda"]  = "CLP"
    df["banco"]   = "bancoestado"
    df["cuenta"]  = "tdc"
    df["archivo"] = path.name
    return df[_COLS_OUT]


# ── Entry point de parseo ─────────────────────────────────────────────────────

def parsear_archivo_banco(path: str | Path) -> tuple[pd.DataFrame, dict]:
    """
    Parsea un archivo bancario. Retorna (df_normalizado, info).
    info = {banco, cuenta, moneda, n_filas, error?}
    """
    path = Path(path)
    info = detectar_banco_formato(path)
    banco, cuenta, moneda = info["banco"], info["cuenta"], info["moneda"]

    try:
        if banco == "bci":
            if cuenta == "cc":
                df = _parsear_bci_cc(path)
            elif cuenta == "lc":
                df = _parsear_bci_lc(path)
            else:
                df = _parsear_bci_tdc(path, moneda)
        elif banco == "bancoestado":
            if path.suffix.lower() == ".pdf":
                if cuenta == "tdc_facturado":
                    df = _parsear_bancoestado_tdc_facturado_pdf(path, moneda)
                else:
                    df = _parsear_bancoestado_tdc_pdf(path)
            else:
                df = _parsear_bancoestado_cc(path, cuenta)
        elif banco == "itau":
            if cuenta == "cc":
                df = _parsear_itau_cc(path)
            elif cuenta == "tdc_estado":
                df = _parsear_itau_tdc_estado(path, moneda)
            elif cuenta == "credito_consumo":
                df = _df_vacio()  # solo info de saldo, no movimientos
            elif cuenta == "lc":
                df = _parsear_itau_cc(path)  # mismo formato que CC
            else:
                df = _parsear_itau_tdc_ultimos(path, moneda)
        elif banco == "falabella":
            df = _parsear_falabella(path)
        elif banco == "consorcio":
            df = _parsear_consorcio(path, cuenta)
        else:
            df = _df_vacio()
    except Exception as e:
        df = _df_vacio()
        info["error"] = str(e)

    info["n_filas"] = len(df)
    return df, info


def parsear_multiples_archivos(paths: list[str | Path]) -> pd.DataFrame:
    """Parsea varios archivos y concatena en un único DataFrame."""
    frames = []
    for p in paths:
        df, info = parsear_archivo_banco(p)
        if not df.empty:
            frames.append(df)
    return pd.concat(frames, ignore_index=True) if frames else _df_vacio()


def deduplicar_transacciones(
    df: pd.DataFrame,
) -> tuple[pd.DataFrame, int, list[str]]:
    """
    Elimina duplicados cross-file: cuando el mismo banco+cuenta aparece en más de
    un archivo, transacciones con idéntico (banco, cuenta, fecha, monto, tipo_mov)
    se consolidan en una sola, conservando la descripción más larga.

    Transacciones dentro de un mismo archivo nunca se tocan — dos recargas Bip de
    $5.000 el mismo día en el mismo archivo son dos movimientos legítimos.

    Retorna:
        df_dedup       DataFrame sin duplicados cross-file
        n_removidos    Número de filas eliminadas
        conflictos     Lista de strings describiendo qué archivos solapaban
    """
    if df.empty:
        return df, 0, []

    df = df.copy()
    df["_dl"] = df["descripcion"].str.len()

    # Detectar banco+cuenta que aparecen en múltiples archivos
    multi = (
        df.groupby(["banco", "cuenta"])["archivo"]
        .nunique()
    )
    multi_pares = multi[multi > 1].index.tolist()

    conflictos: list[str] = []
    for banco, cuenta in multi_pares:
        archs = df[
            (df["banco"] == banco) & (df["cuenta"] == cuenta)
        ]["archivo"].unique().tolist()
        conflictos.append(f"{banco.upper()} {cuenta}: {' + '.join(archs)}")

    n_antes = len(df)

    if not multi_pares:
        return df.drop(columns=["_dl"]), 0, []

    # Separar filas de cuentas con solapamiento vs sin solapamiento
    multi_set = set(multi_pares)
    mask_multi = df.apply(lambda r: (r["banco"], r["cuenta"]) in multi_set, axis=1)
    df_ok    = df[~mask_multi].drop(columns=["_dl"])
    df_multi = df[mask_multi].copy()

    _KEY = ["banco", "cuenta", "fecha", "monto", "tipo_mov"]

    # Para cada grupo de clave, conservar max(ocurrencias en cualquier archivo)
    # filas, tomándolas del archivo con descripciones más largas.
    kept = []
    for _, grp in df_multi.groupby(_KEY, sort=False):
        per_file = grp.groupby("archivo")
        max_count = per_file.size().max()          # máx legítimos en un solo archivo
        best_arch = per_file["_dl"].sum().idxmax() # archivo con descripciones más ricas
        best_rows = (
            grp[grp["archivo"] == best_arch]
            .sort_values("_dl", ascending=False)
            .head(max_count)
        )
        kept.append(best_rows)

    df_multi_dedup = (
        pd.concat(kept).drop(columns=["_dl"]) if kept
        else df_multi.drop(columns=["_dl"]).iloc[:0]
    )

    df_out = (
        pd.concat([df_ok, df_multi_dedup], ignore_index=True)
        .sort_values(["fecha", "banco"])
        .reset_index(drop=True)
    )
    return df_out, n_antes - len(df_out), conflictos


# ── Conversión USD → CLP ──────────────────────────────────────────────────────

def convertir_usd_clp(monto_usd: float) -> float:
    try:
        from market_data import obtener_indicadores_cached
        tasa = obtener_indicadores_cached().get("dolar", 913.98)
    except Exception:
        tasa = 913.98
    return round(monto_usd * tasa, 0)


def normalizar_a_clp(df: pd.DataFrame) -> pd.DataFrame:
    df_out = df.copy()
    mask = df_out["moneda"] == "USD"
    if mask.any():
        df_out.loc[mask, "monto"] = df_out.loc[mask, "monto"].apply(convertir_usd_clp)
        df_out.loc[mask, "moneda"] = "CLP"
    return df_out


# ── Categorizador con caché de reglas ─────────────────────────────────────────

# Bancos donde TODA transacción es movimiento patrimonial
_BANCOS_AUTO_PATRIMONIAL = {"consorcio"}

# Patrones de descripción → Transferencia automática
_RE_PATRIMONIAL = re.compile(
    r"tef\s+(a|de)\s+propia"
    r"|traspaso\s+de\s+fondos"
    r"|traspaso\s+a\s+otro\s+banco"
    r"|transferencia\s+(enviada|recibida)\s+a\s+s[oó]crates"
    r"|pago\s+automat\.\s+tarjeta"
    r"|pago\s+deuda\s+tarjeta"
    r"|transferencia\s+enviada\s+a\s+tarjeta\s+cmr"  # pago Falabella CMR
    r"|abono\s+desde\s+linea\s+de\s+credito"
    r"|liquid\s+intereses\s+pactados"
    r"|monto\s+cancelado"
    r"|tradolarpeso"
    r"|traspaso\s+deuda\s+internacional",
    re.IGNORECASE,
)


def cargar_reglas() -> dict:
    if _RULES_FILE.exists():
        try:
            return json.loads(_RULES_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def guardar_reglas(rules: dict):
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    _RULES_FILE.write_text(json.dumps(rules, ensure_ascii=False, indent=2), encoding="utf-8")


def _clave(desc: str) -> str:
    return re.sub(r"\s+", " ", desc.lower().strip())[:80]


def extraer_taxonomia(excel_path: str | Path) -> dict:
    """Extrae grupos→conceptos del Excel del usuario como contexto para la IA."""
    try:
        from data_loader import cargar_transacciones
        df = cargar_transacciones(str(excel_path))
        if df.empty:
            return {}
        tax = {}
        for grupo, gdf in df.groupby("grupo"):
            conceptos = sorted(gdf["concepto"].dropna().astype(str).unique().tolist())
            tax[str(grupo)] = [c for c in conceptos if c and c != "nan"]
        return tax
    except Exception:
        return {}


def _categorizar_con_ia(desc: str, tipo_mov: str, moneda: str, taxonomia: dict) -> dict:
    import anthropic

    tax_str = "\n".join(
        f"  {g}: {', '.join(cs[:8])}"
        for g, cs in list(taxonomia.items())[:20]
        if cs
    )

    prompt = (
        "Clasifica esta transacción bancaria chilena en la taxonomía del usuario.\n\n"
        f"TAXONOMÍA (grupo → conceptos):\n{tax_str}\n\n"
        f"TRANSACCIÓN:\n"
        f"Descripción: {desc}\n"
        f"Tipo: {'cargo (gasto del usuario)' if tipo_mov == 'cargo' else 'abono (ingreso o pago recibido)'}\n"
        f"Moneda: {moneda}\n\n"
        "Responde SOLO con JSON, sin texto extra:\n"
        '{"tipo_tx": "Gasto|Ingreso|Transferencia|Ahorro|Inversión", "grupo": "nombre grupo", "concepto": "concepto"}\n\n'
        "Reglas:\n"
        "- abono que parece pago de tarjeta o transferencia entre cuentas propias → Transferencia\n"
        "- abono de sueldo, honorarios, ingreso real → Ingreso\n"
        "- cargo normal → Gasto\n"
        "- elige el grupo y concepto más cercano al del usuario\n"
        "- si no existe concepto exacto, crea uno corto y descriptivo"
    )

    try:
        client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=120,
            messages=[{"role": "user", "content": prompt}],
        )
        return json.loads(msg.content[0].text.strip())
    except Exception:
        return {"tipo_tx": "Gasto", "grupo": "Varios y Otros", "concepto": "Sin categorizar"}


def categorizar_lote(
    df: pd.DataFrame,
    excel_path: str | Path = None,
    taxonomia: dict = None,
) -> pd.DataFrame:
    """
    Categoriza un DataFrame normalizado.
    Agrega columnas: tipo_tx, grupo, concepto, fuente_cat ('auto'|'cache'|'ai').
    """
    if df.empty:
        for col in ("tipo_tx", "grupo", "concepto", "fuente_cat"):
            df[col] = pd.Series(dtype=str)
        return df

    if taxonomia is None and excel_path is not None:
        taxonomia = extraer_taxonomia(excel_path)
    if not taxonomia:
        taxonomia = {
            "Alimentación": ["Supermercado", "Delivery"],
            "Hogar y Vivienda": ["Dividendo Hipotecario", "Servicios"],
            "Transporte": ["Bencina", "TAG"],
            "Salud y Bienestar": ["Farmacia", "Médico"],
            "Entretención": ["Streaming", "Restaurante"],
            "Varios y Otros": ["Varios"],
        }

    reglas = cargar_reglas()
    nuevas: dict = {}
    resultados = []

    for _, row in df.iterrows():
        desc     = str(row["descripcion"])
        banco    = str(row["banco"])
        tipo_mov = str(row["tipo_mov"])
        moneda   = str(row["moneda"])
        cuenta   = str(row.get("cuenta", ""))

        # 1. Auto-patrimonial por banco
        if banco in _BANCOS_AUTO_PATRIMONIAL:
            if "intereses" in desc.lower():
                r = {"tipo_tx": "Ingreso", "grupo": "Ahorro e Inversión", "concepto": "Intereses", "fuente_cat": "auto"}
            elif cuenta == "cuenta_mas":
                r = {"tipo_tx": "Ahorro", "grupo": "Ahorro e Inversión", "concepto": "Depósito Cuenta Más", "fuente_cat": "auto"}
            else:
                r = {"tipo_tx": "Transferencia", "grupo": "Ahorro e Inversión", "concepto": "Transferencia propia", "fuente_cat": "auto"}
            resultados.append(r)
            continue

        # 2. Auto-patrimonial por descripción
        if _RE_PATRIMONIAL.search(desc):
            resultados.append({"tipo_tx": "Transferencia", "grupo": "Ahorro e Inversión", "concepto": "Transferencia propia", "fuente_cat": "auto"})
            continue

        # 3. Caché de reglas — buscar por descripción original Y por comercio extraído
        clave          = _clave(desc)
        comercio       = _extraer_comercio(desc)
        clave_comercio = _clave(comercio) if comercio != desc else None

        hit = reglas.get(clave) or (reglas.get(clave_comercio) if clave_comercio else None)
        if hit:
            r = dict(hit)
            r["fuente_cat"] = "cache"
            resultados.append(r)
            continue

        # 4. Patrones lógicos (busca en comercio extraído + descripción completa)
        cat_patron = _buscar_patron_logico(desc)
        if cat_patron:
            nuevas[clave] = cat_patron
            cat_patron = dict(cat_patron)
            cat_patron["fuente_cat"] = "patron"
            resultados.append(cat_patron)
            continue

        # 5. Claude Haiku — último recurso; pasa comercio limpio para mejor contexto
        desc_ia = comercio if comercio != desc else desc
        cat = _categorizar_con_ia(desc_ia, tipo_mov, moneda, taxonomia)
        cat["fuente_cat"] = "ai"
        # Solo guardar en caché si la IA dio una categorización específica
        # (no guardar respuestas genéricas que envenenen futuras importaciones)
        if cat.get("concepto") != "Sin categorizar" and cat.get("grupo") != "Varios y Otros":
            nuevas[clave] = {k: v for k, v in cat.items() if k != "fuente_cat"}
        resultados.append(cat)

    if nuevas:
        reglas.update(nuevas)
        guardar_reglas(reglas)

    df_out = df.copy()
    df_out["tipo_tx"]    = [r.get("tipo_tx", "Gasto")         for r in resultados]
    df_out["grupo"]      = [r.get("grupo", "Varios y Otros")   for r in resultados]
    df_out["concepto"]   = [r.get("concepto", "")              for r in resultados]
    df_out["fuente_cat"] = [r.get("fuente_cat", "?")           for r in resultados]
    return df_out


# ── Pre-populación de caché desde historial Excel del usuario ─────────────────

def construir_cache_desde_excel(
    excel_path: str | Path,
    sobrescribir: bool = False,
) -> dict:
    """
    Lee todas las hojas mensuales del Excel del usuario y extrae pares
    DETALLE → {tipo_tx, grupo, concepto} para pre-poblar la caché de reglas.

    El historial real del usuario tiene prioridad sobre los patrones lógicos:
    si el usuario ya clasificó "HIP LIDER" como Supermercado, eso queda en caché.

    Parámetros:
        sobrescribir: si True, descarta la caché existente y reconstruye desde cero.

    Retorna: {"leidas": int, "nuevas": int, "total": int}
    """
    excel_path = Path(excel_path)
    if not excel_path.exists():
        return {"leidas": 0, "nuevas": 0, "total": 0, "error": "Archivo no encontrado"}

    reglas = {} if sobrescribir else cargar_reglas()
    stats = {"leidas": 0, "nuevas": 0, "total": 0}

    try:
        xl = pd.ExcelFile(excel_path)
    except Exception as e:
        return {"leidas": 0, "nuevas": 0, "total": 0, "error": str(e)}

    _MESES = {
        "enero", "febrero", "marzo", "abril", "mayo", "junio",
        "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
    }
    hojas_mensuales = [h for h in xl.sheet_names if any(m in h.lower() for m in _MESES)]

    for hoja in hojas_mensuales:
        try:
            raw = pd.read_excel(excel_path, sheet_name=hoja, header=None, dtype=str)
        except Exception:
            continue

        # Encontrar fila de encabezado (contiene GRUPO y DETALLE)
        hrow = None
        for i, row in raw.iterrows():
            vals = " ".join(str(v).lower() for v in row if str(v) not in ("nan", "None"))
            if "grupo" in vals and "detalle" in vals:
                hrow = i
                break
        if hrow is None:
            continue

        headers = [str(v).lower().strip() for v in raw.iloc[hrow]]
        idx_g = _find_col(headers, ["grupo"])
        idx_c = _find_col(headers, ["concepto"])
        idx_d = _find_col(headers, ["detalle"])

        if idx_g is None or idx_d is None:
            continue

        for _, row in raw.iloc[hrow + 1:].iterrows():
            grupo    = str(row.iloc[idx_g]).strip()
            concepto = str(row.iloc[idx_c]).strip() if idx_c is not None else ""
            detalle  = str(row.iloc[idx_d]).strip()

            # Saltar filas vacías o de totales
            if not detalle or detalle in ("nan", "None", ""):
                continue
            if not grupo or grupo in ("nan", "None", ""):
                continue

            stats["leidas"] += 1
            clave = _clave(detalle)
            if not clave:
                continue

            # Historial del usuario tiene precedencia; no sobrescribir si ya existe
            if not sobrescribir and clave in reglas:
                continue

            tipo_tx = _infer_tipo_tx_desde_grupo(grupo)
            reglas[clave] = {
                "tipo_tx":  tipo_tx,
                "grupo":    grupo,
                "concepto": concepto if concepto not in ("nan", "None", "") else "Varios",
            }
            stats["nuevas"] += 1

    guardar_reglas(reglas)
    stats["total"] = len(reglas)
    return stats


# ── Export al formato del Excel del usuario ───────────────────────────────────

def preparar_para_excel(df: pd.DataFrame) -> pd.DataFrame:
    """
    Convierte el DataFrame categorizado al formato de la hoja Transacciones:
    fecha | tipo_tx | grupo | concepto | detalle | importe | cuenta
    """
    if df.empty:
        return pd.DataFrame(columns=["fecha", "tipo_tx", "grupo", "concepto", "detalle", "importe", "cuenta"])
    return pd.DataFrame({
        "fecha":    pd.to_datetime(df["fecha"]).dt.strftime("%d/%m/%Y"),
        "tipo_tx":  df["tipo_tx"],
        "grupo":    df["grupo"],
        "concepto": df["concepto"],
        "detalle":  df["descripcion"],
        "importe":  df["monto"].round(0).astype(int),
        "cuenta":   df["banco"].str.upper() + " " + df["cuenta"].str.upper(),
    })
