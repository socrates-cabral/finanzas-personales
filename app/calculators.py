import sys
sys.stdout.reconfigure(encoding="utf-8")

import math
from typing import Dict, List, Optional
import pandas as pd

_TIPOS_PATRIMONIALES = {
    "inversión", "inversion",
    "ahorro",
    "transferencia",
    "traspaso",
    "movimiento patrimonial",
}
_GRUPOS_PATRIMONIALES = {
    "ahorro e inversión",
    "ahorro e inversion",
}


def marcar_movimientos_patrimoniales(df: pd.DataFrame) -> pd.DataFrame:
    """Marca transacciones que son traspasos/ahorro/inversión y no gasto operacional."""
    if df is None or df.empty:
        df_out = df.copy() if isinstance(df, pd.DataFrame) else pd.DataFrame()
        if isinstance(df_out, pd.DataFrame) and "es_movimiento_patrimonial" not in df_out.columns:
            df_out["es_movimiento_patrimonial"] = False
        return df_out

    df_out = df.copy()
    mask = pd.Series(False, index=df_out.index)

    if "tipo_tx" in df_out.columns:
        tipos = df_out["tipo_tx"].fillna("").astype(str).str.strip().str.lower()
        mask = mask | tipos.isin(_TIPOS_PATRIMONIALES)

    if "grupo" in df_out.columns:
        grupos = df_out["grupo"].fillna("").astype(str).str.strip().str.lower()
        mask = mask | grupos.isin(_GRUPOS_PATRIMONIALES)

    df_out["es_movimiento_patrimonial"] = mask
    return df_out


def filtrar_transacciones_operativas(df: pd.DataFrame, incluir_ingresos: bool = True) -> pd.DataFrame:
    """Excluye movimientos patrimoniales; opcionalmente excluye también ingresos."""
    df_out = marcar_movimientos_patrimoniales(df)
    if df_out.empty:
        return df_out

    mask = ~df_out["es_movimiento_patrimonial"]
    if not incluir_ingresos and "tipo_tx" in df_out.columns:
        mask = mask & (df_out["tipo_tx"] != "Ingreso")
    return df_out[mask].copy()


def calc_ingresos_totales(liquido: float, amipass: float = 0, otros: float = 0) -> float:
    """Suma ingresos líquidos totales del mes."""
    return liquido + amipass + otros


def calc_resumen_mes(df: pd.DataFrame, mes: int) -> dict:
    """
    Retorna resumen del mes dado.
    {por_grupo: {grupo: total}, total: float, por_tipo: {tipo: total}, ingresos: float}
    total solo cuenta Gastos (no Ingresos) para no inflar el KPI de gastos.
    """
    df_mes = filtrar_transacciones_operativas(df[df["mes"] == mes].copy(), incluir_ingresos=True)
    if df_mes.empty:
        return {"por_grupo": {}, "total": 0.0, "por_tipo": {}, "ingresos": 0.0}
    col_tipo = "tipo_tx" if "tipo_tx" in df_mes.columns else "tipo"
    df_gastos  = df_mes[df_mes[col_tipo] != "Ingreso"] if col_tipo in df_mes.columns else df_mes
    df_ingresos = df_mes[df_mes[col_tipo] == "Ingreso"] if col_tipo in df_mes.columns else pd.DataFrame()
    por_grupo = df_gastos.groupby("grupo")["importe"].sum().to_dict()
    total     = df_gastos["importe"].sum()
    ingresos  = df_ingresos["importe"].sum() if not df_ingresos.empty else 0.0
    por_tipo  = df_mes.groupby(col_tipo)["importe"].sum().to_dict() if col_tipo in df_mes.columns else {}
    return {"por_grupo": por_grupo, "total": total, "por_tipo": por_tipo, "ingresos": ingresos}


def calc_tasa_ahorro(ingresos: float, gastos: float) -> dict:
    """
    Calcula tasa de ahorro.
    estado_semaforo: 'verde' >=20%, 'amarillo' 10-19%, 'rojo' <10%
    """
    if ingresos <= 0:
        return {"tasa": 0.0, "absoluto": 0.0, "estado_semaforo": "rojo"}
    ahorro = ingresos - gastos
    tasa = (ahorro / ingresos) * 100
    if tasa >= 20:
        estado = "verde"
    elif tasa >= 10:
        estado = "amarillo"
    else:
        estado = "rojo"
    return {"tasa": round(tasa, 1), "absoluto": ahorro, "estado_semaforo": estado}


_GRUPO_DEUDAS_RE = "financiero - deudas"


def calc_regla_50_30_20(
    df_mes: pd.DataFrame,
    ingresos: float,
    tipos_dict: Dict[str, str],
) -> dict:
    """
    Clasifica gastos según regla 50/30/20 (Elizabeth Warren):
    - Necesidades (Fijo, excl. deudas): 50% ideal
    - Deseos (Variable + Prescindible, excl. deudas): 30% ideal
    - Ahorro/Deudas: 20% ideal (pagos a deuda + ahorro neto restante)
    """
    df = filtrar_transacciones_operativas(df_mes, incluir_ingresos=False)
    ideal_nec = ingresos * 0.50
    ideal_des = ingresos * 0.30
    ideal_aho = ingresos * 0.20
    if df.empty:
        ahorro_real = max(ingresos, 0)
        return {
            "necesidades": 0.0,
            "deseos": 0.0,
            "ahorro_deudas": ahorro_real,
            "pagos_deuda": 0.0,
            "ahorro_neto": ahorro_real,
            "ideal_necesidades": ideal_nec,
            "ideal_deseos": ideal_des,
            "ideal_ahorro": ideal_aho,
            "diferencia_ahorro": ahorro_real - ideal_aho,
        }
    if "tipo" not in df.columns:
        df["tipo"] = df["grupo"].map(tipos_dict).fillna("Variable")
    es_deuda = df["grupo"].fillna("").astype(str).str.lower().str.contains(_GRUPO_DEUDAS_RE, na=False)
    pagos_deuda = float(df.loc[es_deuda, "importe"].sum())
    df_no_deuda = df.loc[~es_deuda]
    necesidades = float(df_no_deuda[df_no_deuda["tipo"] == "Fijo"]["importe"].sum())
    deseos = float(df_no_deuda[df_no_deuda["tipo"].isin(["Variable", "Prescindible"])]["importe"].sum())
    ahorro_neto = max(ingresos - necesidades - deseos - pagos_deuda, 0)
    ahorro_deudas = ahorro_neto + pagos_deuda
    return {
        "necesidades": necesidades,
        "deseos": deseos,
        "ahorro_deudas": ahorro_deudas,
        "pagos_deuda": pagos_deuda,
        "ahorro_neto": ahorro_neto,
        "ideal_necesidades": ideal_nec,
        "ideal_deseos": ideal_des,
        "ideal_ahorro": ideal_aho,
        "diferencia_ahorro": ahorro_deudas - ideal_aho,
    }


def calc_patrimonio_neto(
    activos_dict: dict,
    pasivos_dict: dict,
    ingresos_anuales: float = 0.0,
) -> dict:
    """
    Calcula patrimonio neto y ratios de endeudamiento.

    ratio_deuda_activos: pasivos/activos (Debt-to-Assets, mide solidez patrimonial)
    ratio_deuda_ingresos: pasivos/ingresos_anuales (estándar finanzas personales,
        sano <100%, regla común: deuda total no supera 35% del ingreso mensual = 420% anual)
    """
    total_activos = sum(v for v in activos_dict.values() if isinstance(v, (int, float)))
    total_pasivos = sum(v for v in pasivos_dict.values() if isinstance(v, (int, float)))
    neto = total_activos - total_pasivos
    ratio_da = (total_pasivos / total_activos * 100) if total_activos > 0 else 0
    ratio_di = (total_pasivos / ingresos_anuales * 100) if ingresos_anuales > 0 else 0
    return {
        "total_activos": total_activos,
        "total_pasivos": total_pasivos,
        "neto": neto,
        "ratio_deuda_activos": round(ratio_da, 1),
        "ratio_deuda_ingresos": round(ratio_di, 1),
        "ratio_endeudamiento": round(ratio_da, 1),
    }


def calc_proyeccion_afp(
    saldo_actual: float,
    aporte_neto_mensual: float,
    tasa_anual: float,
    anos: int,
) -> List[float]:
    """
    Proyecta saldo AFP mes a mes.
    Retorna lista de saldos anuales (longitud = anos + 1).
    """
    tasa_mensual = (1 + tasa_anual / 100) ** (1 / 12) - 1
    saldos_anuales = [saldo_actual]
    saldo = saldo_actual
    for _ano in range(anos):
        for _ in range(12):
            saldo = saldo * (1 + tasa_mensual) + aporte_neto_mensual
        saldos_anuales.append(saldo)
    return saldos_anuales


def calc_pe_financiero(ingresos: float, gastos_fijos: float) -> float:
    """Meses para punto de equilibrio si ingresos = gastos_fijos."""
    if ingresos >= gastos_fijos:
        return 0.0
    return round(gastos_fijos / ingresos, 1)


def calc_fire_number(gastos_anuales: float, tasa_retiro: float = 0.04) -> dict:
    """
    Calcula capital necesario para FIRE (Financial Independence, Retire Early).
    Regla del 4%.
    """
    capital = gastos_anuales / tasa_retiro
    return {
        "capital_necesario": capital,
        "tasa_retiro_pct": tasa_retiro * 100,
        "gastos_anuales": gastos_anuales,
    }


def calc_tiempo_para_meta(
    saldo_actual: float,
    meta: float,
    ahorro_mensual: float,
    tasa_anual: float = 0.0,
) -> dict:
    """
    Calcula meses para alcanzar una meta de ahorro.
    Considera rendimiento compuesto si tasa_anual > 0.
    """
    if ahorro_mensual <= 0:
        return {"meses": None, "anos": None, "imposible": True}
    if saldo_actual >= meta:
        return {"meses": 0, "anos": 0, "imposible": False}
    tasa_mensual = (1 + tasa_anual / 100) ** (1 / 12) - 1 if tasa_anual > 0 else 0
    if tasa_mensual == 0:
        meses = math.ceil((meta - saldo_actual) / ahorro_mensual)
    else:
        # FV = saldo*(1+r)^n + pmt*((1+r)^n - 1)/r = meta
        # Resolver numéricamente
        saldo = saldo_actual
        meses = 0
        while saldo < meta and meses < 600:
            saldo = saldo * (1 + tasa_mensual) + ahorro_mensual
            meses += 1
        if saldo < meta:
            return {"meses": None, "anos": None, "imposible": True}
    return {
        "meses": meses,
        "anos": round(meses / 12, 1),
        "imposible": False,
    }


def calc_amortizacion(
    saldo: float,
    tasa_mensual_pct: float,
    cuota: float,
) -> pd.DataFrame:
    """
    Genera tabla de amortización francesa.
    Retorna DataFrame con: mes, saldo_inicial, interes, capital, cuota, saldo_final
    """
    tasa = tasa_mensual_pct / 100
    filas = []
    mes = 1
    while saldo > 0.01 and mes <= 600:
        interes = saldo * tasa
        capital = cuota - interes
        if capital <= 0:
            break
        saldo_final = max(saldo - capital, 0)
        filas.append({
            "Mes": mes,
            "Saldo Inicial": round(saldo, 0),
            "Interés": round(interes, 0),
            "Capital": round(capital, 0),
            "Cuota": round(cuota, 0),
            "Saldo Final": round(saldo_final, 0),
        })
        saldo = saldo_final
        mes += 1
    return pd.DataFrame(filas)
