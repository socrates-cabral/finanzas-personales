import sys
sys.stdout.reconfigure(encoding="utf-8")

from typing import Dict, List
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px

# ── Paleta Dark Premium Fintech ───────────────────────────────────────────────
COLOR_BRAND    = "#10B981"   # teal-green — ingresos, positivo, marca
COLOR_POSITIVO = "#34D399"   # emerald — deltas positivos
COLOR_NEGATIVO = "#F43F5E"   # rose — gastos, deudas, negativo
COLOR_ALERTA   = "#F59E0B"   # amber — advertencias, presupuesto límite
COLOR_INVERSION= "#EAB308"   # gold — AFP, inversiones, patrimonio
COLOR_SECUNDARIO="#6366F1"   # indigo — gráficos secundarios, selección
COLOR_AHORRO   = "#38BDF8"   # sky blue — ahorro, metas, liquidez
COLOR_MUTED    = "#64748B"   # slate — elementos secundarios

COLORES_GRUPOS = [
    "#10B981", "#6366F1", "#38BDF8", "#F59E0B",
    "#EAB308", "#F43F5E", "#94A3B8", "#34D399",
    "#818CF8", "#FCD34D", "#FB7185", "#67E8F9",
]

# ── Paleta semántica por categoría de gasto ────────────────────────────────
COLOR_MAP = {
    'Hogar y Vivienda':          '#14b8a6',   # teal
    'Familia e Hijos':           '#60a5fa',   # azul
    'Financiero - Deudas':       '#f59e0b',   # amber
    'Alimentación':              '#818cf8',   # indigo
    'Salud y Cuidado Personal':  '#f472b6',   # pink
    'Transporte':                '#34d399',   # verde claro
    'Servicios Básicos':         '#fb923c',   # naranja
    'Educación y Formación':     '#a78bfa',   # violeta
    'Ahorro e Inversión':        '#4ade80',   # verde
    'Suscripciones Digitales':   '#38bdf8',   # sky
    'Ocio y Vida Social':        '#e879f9',   # fuchsia
    'Mascotas':                  '#fbbf24',   # yellow
    'Regalos y Donaciones':      '#f87171',   # red claro
    'Varios y Otros':            '#94a3b8',   # slate
    'Seguros':                   '#6ee7b7',   # emerald
}

_BG_CARD  = "#1E293B"
_BG_BASE  = "#0F172A"
_GRID_CLR = "#293548"
_FONT_CLR = "#94A3B8"
_TITLE_CLR= "#CBD5E1"

_LAYOUT_BASE = dict(
    font=dict(family="Inter, Segoe UI, Arial, sans-serif", size=13, color=_FONT_CLR),
    paper_bgcolor="#1E293B",
    plot_bgcolor="#1E293B",
    margin=dict(l=20, r=20, t=48, b=20),
    colorway=COLORES_GRUPOS,
    separators=",.",
    title_font_color=_TITLE_CLR,
    title_font_size=14,
    legend=dict(
        bgcolor="rgba(0,0,0,0)",
        font=dict(color=_FONT_CLR, size=11),
        orientation="h",
        yanchor="bottom", y=1.02,
        xanchor="right", x=1,
    ),
    hoverlabel=dict(
        bgcolor="#0F172A",
        font=dict(family="Inter, Segoe UI, Arial", size=12, color="#E2E8F0"),
        bordercolor="#334155",
    ),
    xaxis=dict(
        gridcolor="#1a2535",
        tickfont=dict(color=_FONT_CLR, size=11),
        linecolor="#334155",
        zerolinecolor="#334155",
    ),
    yaxis=dict(
        gridcolor="#1a2535",
        tickfont=dict(color=_FONT_CLR, size=11),
        linecolor="#334155",
        zerolinecolor="#334155",
        tickformat=",.0f",
    ),
)


def fmt_clp(v: float) -> str:
    return f"${v:,.0f}".replace(",", ".")


def badge_grupo(grupo: str) -> str:
    """Pill HTML con color semántico por categoría (usar con to_html escape=False)."""
    color = COLOR_MAP.get(grupo, "#94a3b8")
    return (
        f'<span style="background:{color}22;color:{color};padding:2px 8px;'
        f'border-radius:4px;font-size:11px;font-weight:500;white-space:nowrap">{grupo}</span>'
    )


def chart_barras_gastos_mes(df_mes: pd.DataFrame) -> go.Figure:
    """Barras horizontales top 10 grupos del mes."""
    if df_mes.empty:
        fig = go.Figure()
        fig.update_layout(title="Sin datos", **_LAYOUT_BASE)
        return fig
    top = (
        df_mes.groupby("grupo")["importe"]
        .sum()
        .sort_values(ascending=False)
        .head(10)
        .reset_index()
    )
    top = top.sort_values("importe", ascending=True)
    total = top["importe"].sum()
    colores = [COLOR_MAP.get(g, "#6366F1") for g in top["grupo"]]
    etiquetas = [
        f"{fmt_clp(v)}  {v/total*100:.0f}%" if total > 0 else fmt_clp(v)
        for v in top["importe"]
    ]
    fig = go.Figure(
        go.Bar(
            x=top["importe"],
            y=top["grupo"],
            orientation="h",
            marker=dict(color=colores, line=dict(width=0)),
            text=etiquetas,
            textposition="outside",
            hovertemplate="<b>%{y}</b><br>$%{x:,.0f}<extra></extra>",
        )
    )
    total_label = fmt_clp(total)
    fig.update_layout(
        title=dict(
            text=f"TOP GASTOS — <span style='font-size:11px;color:{_FONT_CLR}'>Total {total_label}</span>",
            font=dict(color=_TITLE_CLR, size=14),
        ),
        xaxis_title="",
        yaxis_title="",
        **_LAYOUT_BASE,
    )
    return fig


def chart_dona_tipos(por_tipo: dict) -> go.Figure:
    """Dona Fijo / Variable / Prescindible."""
    colores = {
        "Fijo":        COLOR_NEGATIVO,
        "Variable":    COLOR_ALERTA,
        "Prescindible":COLOR_MUTED,
    }
    labels = [k for k, v in por_tipo.items() if v > 0]
    values = [v for v in por_tipo.values() if v > 0]
    colors = [colores.get(l, COLOR_MUTED) for l in labels]
    if not labels:
        fig = go.Figure()
        fig.update_layout(title="Sin datos", **_LAYOUT_BASE)
        return fig
    fig = go.Figure(
        go.Pie(
            labels=labels,
            values=values,
            hole=0.45,
            marker_colors=colors,
            textinfo="label+percent",
            hovertemplate="%{label}: $%{value:,.0f}<extra></extra>",
        )
    )
    fig.update_layout(
        title="Distribución por Tipo",
        **_LAYOUT_BASE,
    )
    return fig


def chart_evolucion_mensual(df: pd.DataFrame) -> go.Figure:
    """Línea de gastos totales por mes."""
    if df.empty:
        fig = go.Figure()
        fig.update_layout(title="Sin datos", **_LAYOUT_BASE)
        return fig
    evol = df.groupby(["mes", "mes_nombre"])["importe"].sum().reset_index()
    evol = evol.sort_values("mes")
    fig = go.Figure(
        go.Scatter(
            x=evol["mes_nombre"],
            y=evol["importe"],
            mode="lines+markers+text",
            line=dict(color="#14b8a6", width=3),
            marker=dict(size=8),
            fill="tozeroy",
            fillcolor="rgba(20,184,166,0.08)",
            text=[fmt_clp(v) for v in evol["importe"]],
            textposition="top center",
            hovertemplate="%{x}: %{text}<extra></extra>",
        )
    )
    fig.update_layout(
        title="Evolución de Gastos Mensual",
        xaxis_title="",
        yaxis_title="CLP",
        **_LAYOUT_BASE,
    )
    return fig


def chart_50_30_20(regla_dict: dict) -> go.Figure:
    """Barras comparación real vs ideal (regla 50/30/20)."""
    categorias = ["Necesidades (50%)", "Deseos (30%)", "Ahorro/Deudas (20%)"]
    real = [
        regla_dict.get("necesidades", 0),
        regla_dict.get("deseos", 0),
        regla_dict.get("ahorro_deudas", 0),
    ]
    ideal = [
        regla_dict.get("ideal_necesidades", 0),
        regla_dict.get("ideal_deseos", 0),
        regla_dict.get("ideal_ahorro", 0),
    ]
    fig = go.Figure()
    fig.add_trace(go.Bar(
        name="Real",
        x=categorias,
        y=real,
        marker_color=COLOR_SECUNDARIO,
        text=[fmt_clp(v) for v in real],
        textposition="outside",
        hovertemplate="%{x}<br>Real: %{text}<extra></extra>",
    ))
    fig.add_trace(go.Bar(
        name="Ideal",
        x=categorias,
        y=ideal,
        marker_color=COLOR_BRAND,
        opacity=0.7,
        text=[fmt_clp(v) for v in ideal],
        textposition="outside",
        hovertemplate="%{x}<br>Ideal: %{text}<extra></extra>",
    ))
    fig.update_layout(
        title="Regla 50/30/20",
        barmode="group",
        bargap=0.3,
        **_LAYOUT_BASE,
    )
    return fig


def chart_patrimonio_waterfall(activos: dict, pasivos: dict) -> go.Figure:
    """Waterfall: activos → pasivos → patrimonio neto."""
    names = []
    values = []
    measures = []
    colors = []
    for nombre, val in activos.items():
        if val and val > 0:
            names.append(nombre)
            values.append(val)
            measures.append("relative")
            colors.append(COLOR_BRAND)
    for nombre, val in pasivos.items():
        if val and val > 0:
            names.append(nombre)
            values.append(-val)
            measures.append("relative")
            colors.append(COLOR_NEGATIVO)
    patrimonio_neto = sum(values)  # suma real antes de agregar el total
    names.append("Patrimonio Neto")
    values.append(0)
    measures.append("total")
    colors.append(COLOR_INVERSION)
    texts = [fmt_clp(abs(v)) if v != 0 else "" for v in values]
    texts[-1] = fmt_clp(abs(patrimonio_neto))  # valor real en la barra total
    fig = go.Figure(
        go.Waterfall(
            name="Patrimonio",
            orientation="v",
            measure=measures,
            x=names,
            y=values,
            connector=dict(line=dict(color=_GRID_CLR, width=1)),
            decreasing=dict(marker_color=COLOR_NEGATIVO),
            increasing=dict(marker_color=COLOR_BRAND),
            totals=dict(marker_color=COLOR_INVERSION),
            text=texts,
            textposition="outside",
        )
    )
    fig.update_layout(
        title="Waterfall Patrimonio Neto",
        **_LAYOUT_BASE,
    )
    return fig


def chart_afp_proyeccion(saldos_listas: List[List[float]], anos_lista: List[int], etiquetas: List[str]) -> go.Figure:
    """Área con 3 escenarios de proyección AFP."""
    colores_esc = [COLOR_NEGATIVO, COLOR_SECUNDARIO, COLOR_BRAND]
    fig = go.Figure()
    for i, (saldos, etiqueta) in enumerate(zip(saldos_listas, etiquetas)):
        anos = list(range(len(saldos)))
        fig.add_trace(go.Scatter(
            x=anos,
            y=saldos,
            mode="lines",
            name=etiqueta,
            line=dict(color=colores_esc[i % len(colores_esc)], width=2.5),
            fill="tozeroy" if i == 0 else "tonexty",
            fillcolor=f"rgba({','.join(str(int(c*255)) for c in px.colors.hex_to_rgb(colores_esc[i % len(colores_esc)].lstrip('#'))[:3])}, 0.1)",
            hovertemplate=f"{etiqueta} - Año %{{x}}: %{{y:,.0f}}<extra></extra>",
        ))
    fig.update_layout(
        title="Proyección AFP — 3 Escenarios",
        xaxis_title="Años desde hoy",
        yaxis_title="Saldo CLP",
        **_LAYOUT_BASE,
    )
    return fig


def chart_ingresos_vs_gastos(
    ingresos_lista: List[float],
    gastos_lista: List[float],
    meses_lista: List[str],
) -> go.Figure:
    """Barras agrupadas ingresos vs gastos por mes."""
    fig = go.Figure()
    fig.add_trace(go.Bar(
        name="Ingresos",
        x=meses_lista,
        y=ingresos_lista,
        marker_color="#14b8a6",
        text=[fmt_clp(v) for v in ingresos_lista],
        textposition="outside",
        hovertemplate="<b>%{x}</b><br>Ingresos: $%{y:,.0f}<extra></extra>",
    ))
    fig.add_trace(go.Bar(
        name="Gastos",
        x=meses_lista,
        y=gastos_lista,
        marker_color="#F43F5E",
        text=[fmt_clp(v) for v in gastos_lista],
        textposition="outside",
        hovertemplate="<b>%{x}</b><br>Gastos: $%{y:,.0f}<extra></extra>",
    ))
    fig.update_layout(
        title="Ingresos vs Gastos por Mes",
        barmode="group",
        bargap=0.25,
        **_LAYOUT_BASE,
    )
    return fig


def chart_barras_apiladas_grupos(df: pd.DataFrame) -> go.Figure:
    """Barras apiladas por grupo × mes."""
    if df.empty:
        fig = go.Figure()
        fig.update_layout(title="Sin datos", **_LAYOUT_BASE)
        return fig
    pivot = df.pivot_table(
        index="mes_nombre", columns="grupo", values="importe", aggfunc="sum", fill_value=0
    )
    orden_meses = ["Enero","Febrero","Marzo","Abril","Mayo","Junio",
                   "Julio","Agosto","Septiembre","Octubre","Noviembre","Diciembre"]
    pivot = pivot.reindex([m for m in orden_meses if m in pivot.index])
    fig = go.Figure()
    for i, grupo in enumerate(pivot.columns):
        fig.add_trace(go.Bar(
            name=grupo,
            x=pivot.index,
            y=pivot[grupo],
            marker_color=COLOR_MAP.get(grupo, COLORES_GRUPOS[i % len(COLORES_GRUPOS)]),
            hovertemplate=f"{grupo}<br>%{{x}}: $%{{y:,.0f}}<extra></extra>",
        ))
    fig.update_layout(
        title="Gastos por Grupo y Mes",
        barmode="stack",
        bargap=0.2,
        **_LAYOUT_BASE,
    )
    return fig


# ── Inversiones / Portafolio Crypto ───────────────────────────────────────────

CRYPTO_COLORS = [
    "#F7931A",  # Bitcoin orange
    "#627EEA",  # Ethereum blue
    "#26A17B",  # USDT green
    "#F3BA2F",  # BNB yellow
    "#9945FF",  # Solana purple
    "#2775CA",  # USDC blue
    "#00AAE4",  # XRP
    "#BA9F33",  # DOGE
    "#0098EA",  # TON
    "#0033AD",  # ADA
    "#E84142",  # AVAX
    "#E6007A",  # Polkadot
    "#375BD2",  # Chainlink
    "#FF060A",  # TRON
]


def chart_portafolio_dona(df_port: pd.DataFrame) -> go.Figure:
    """Dona distribución del portafolio por activo (valor CLP)."""
    if df_port.empty or "valor_clp" not in df_port.columns:
        fig = go.Figure()
        fig.update_layout(title="Sin datos", **_LAYOUT_BASE)
        return fig
    df_v = df_port[df_port["valor_clp"] > 0].copy()
    colores = [CRYPTO_COLORS[i % len(CRYPTO_COLORS)] for i in range(len(df_v))]
    fig = go.Figure(go.Pie(
        labels=df_v["activo"],
        values=df_v["valor_clp"],
        hole=0.5,
        marker_colors=colores,
        textinfo="label+percent",
        hovertemplate="<b>%{label}</b><br>$%{value:,.0f} CLP<br>%{percent}<extra></extra>",
    ))
    fig.update_layout(title="Distribución del Portafolio", **_LAYOUT_BASE)
    return fig


def chart_portafolio_pl(df_port: pd.DataFrame) -> go.Figure:
    """Barras horizontales P&L por activo."""
    if df_port.empty or "pl_clp" not in df_port.columns:
        fig = go.Figure()
        fig.update_layout(title="Sin datos", **_LAYOUT_BASE)
        return fig
    df_v = df_port[df_port["valor_clp"] > 0].copy().sort_values("pl_clp")
    colores = [COLOR_BRAND if v >= 0 else COLOR_NEGATIVO for v in df_v["pl_clp"]]
    fig = go.Figure(go.Bar(
        x=df_v["pl_clp"],
        y=df_v["activo"],
        orientation="h",
        marker=dict(color=colores, line=dict(width=0)),
        text=[f"${v:,.0f}" for v in df_v["pl_clp"]],
        textposition="outside",
        hovertemplate="<b>%{y}</b><br>P&L: $%{x:,.0f} CLP<extra></extra>",
    ))
    fig.update_layout(
        title="P&L por Activo",
        xaxis_title="",
        yaxis_title="",
        **_LAYOUT_BASE,
    )
    return fig


def chart_portafolio_evolucion(df_port: pd.DataFrame) -> go.Figure:
    """Barras apiladas: costo vs ganancia/pérdida por activo."""
    if df_port.empty:
        fig = go.Figure()
        fig.update_layout(title="Sin datos", **_LAYOUT_BASE)
        return fig
    df_v = df_port[df_port["valor_clp"] > 0].copy()
    fig = go.Figure()
    fig.add_trace(go.Bar(
        name="Costo",
        x=df_v["activo"],
        y=df_v["costo_total_clp"],
        marker_color=COLOR_MUTED,
        hovertemplate="<b>%{x}</b><br>Costo: $%{y:,.0f}<extra></extra>",
    ))
    fig.add_trace(go.Bar(
        name="Valor actual",
        x=df_v["activo"],
        y=df_v["valor_clp"],
        marker_color=COLOR_BRAND,
        opacity=0.85,
        hovertemplate="<b>%{x}</b><br>Valor: $%{y:,.0f}<extra></extra>",
    ))
    fig.update_layout(
        title="Costo vs Valor Actual por Activo",
        barmode="group",
        bargap=0.25,
        **_LAYOUT_BASE,
    )
    return fig
