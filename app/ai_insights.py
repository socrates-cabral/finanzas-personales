import sys
sys.stdout.reconfigure(encoding="utf-8")

"""
ai_insights.py — Integración del Agente Financiero finanzas.py v2.0 con la app.

Toma datos reales del usuario (liquidaciones, Excel, saldos) y genera
análisis narrativos inteligentes usando Claude API + memoria evolutiva.

Roles usados:
  tesoreria  → saldo, flujo de caja, proyección liquidez
  fpa        → presupuesto vs real, varianza por grupo, forecast
  cartera    → ahorro, inversiones, asignación patrimonio
  consulta   → preguntas libres del usuario sobre su situación
"""

import os
import sys
import time
from pathlib import Path
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

import streamlit as st
from dotenv import load_dotenv

# ── SDKs opcionales ───────────────────────────────────────────────────────────
try:
    from openai import OpenAI as _OpenAI
    _HAS_OPENAI = True
except ImportError:
    _HAS_OPENAI = False

try:
    from google import genai as _genai
    _HAS_GEMINI = True
except ImportError:
    _HAS_GEMINI = False

load_dotenv(dotenv_path=Path(__file__).parent.parent.parent / ".env")

# ── Path al agente financiero ─────────────────────────────────────────────────
_AI_AGENT_DIR = Path(__file__).parent.parent.parent / "AI_Agent"
if str(_AI_AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(_AI_AGENT_DIR))

_agente_disponible = False
try:
    from agentes.finanzas import _claude, _mem, SYSTEM_ROLES
    _agente_disponible = True
except Exception as _err:
    print(f"[ai_insights] Agente no disponible: {_err}", file=sys.stderr)


# ── System prompt base para finanzas personales ───────────────────────────────
_SYSTEM_PERSONAL = """Eres un Asesor de Finanzas Personales Senior especializado en el mercado chileno.
Tu misión: analizar la situación financiera real del usuario con sus datos concretos,
entregar insights accionables, lenguaje técnico pero comprensible para cualquier audiencia.

Principios:
- Usa los datos exactos que te pasan — nunca inventes cifras.
- Personaliza: "tus gastos", "tu saldo", "tu situación" — no genérico.
- Si el caso lo amerita, cierra con recomendaciones concretas y priorizadas.
- Usa el contexto del mercado chileno: UF, AFP, ISAPRE, CMF, BCI, BancoEstado, etc.
- Formato: párrafos cortos, sin bullets excesivos, lenguaje directo.
- Respeta los límites de palabras que indique cada prompt.
- Responde en español.
"""

_CONTEXTO_CHILE = """
Contexto mercado Chile (referencia):
- TPM Banco Central: 5.0% | UF: ~$39.841 | USD/CLP: ~$913
- AFP promedio rentabilidad real: 3-7% anual según fondo (A=mayor riesgo, E=menor)
- Regla general: deuda total no debe superar 35% del ingreso mensual
- Tasa de ahorro saludable: ≥15% del ingreso mensual neto
- Regla 50/30/20: 50% necesidades, 30% deseos, 20% ahorro+deudas
"""


# ── Helpers ───────────────────────────────────────────────────────────────────

def _fmt(n: float) -> str:
    """Formatea número como CLP: 1.234.567"""
    try:
        return f"${int(n):,}".replace(",", ".")
    except Exception:
        return str(n)


def _pct(n: float, total: float) -> str:
    if total <= 0:
        return "0%"
    return f"{n / total * 100:.1f}%"


def _contexto_vivienda(arriendo_cobrado: float, dividendo_mensual: float, gastos_compartidos: dict | None) -> str:
    """
    Genera el bloque de contexto de vivienda para inyectar en los prompts.
    Explica al modelo que el gasto bruto de Hogar/Vivienda está parcialmente financiado
    por el arriendo cobrado, y que el costo neto real es solo el diferencial.
    """
    if not arriendo_cobrado and not dividendo_mensual and not gastos_compartidos:
        return ""

    lineas = [
        "",
        "⚠️ INSTRUCCIÓN CRÍTICA — VIVIENDA (aplicar antes de analizar este caso):",
        "El grupo 'Hogar y Vivienda' en los gastos contiene montos BRUTOS que están",
        "parcialmente recuperados como ingresos. NO evalúes vivienda como gasto neto total.",
        "La situación real es la siguiente:",
    ]

    # Gastos compartidos: el usuario reporta el total pero recupera la mitad como ingreso
    if gastos_compartidos and gastos_compartidos.get("items"):
        gc_bruto = gastos_compartidos.get("total", sum(
            i.get("total", 0) for i in gastos_compartidos["items"]
        ))
        gc_neto = gastos_compartidos.get("por_persona", gc_bruto / 2)
        lineas += [
            "",
            "  VIVIENDA ACTUAL (donde vive):",
            f"  • Gastos compartidos BRUTOS reportados en Excel: {_fmt(gc_bruto)}",
            f"    (arriendo + servicios — comparte con otra persona)",
        ]
        for item in gastos_compartidos["items"]:
            lineas.append(f"      - {item.get('concepto','?')}: total {_fmt(item.get('total',0))} → su parte {_fmt(item.get('por_persona', item.get('total',0)/2))}")
        lineas += [
            f"  • La otra mitad ({_fmt(gc_bruto - gc_neto)}) la RECUPERA como ingreso (ya incluida en ingresos).",
            f"  • COSTO NETO donde vive: {_fmt(gc_neto)}",
        ]

    # Dividendo vs arriendo cobrado del dpto propio
    if dividendo_mensual > 0 and arriendo_cobrado > 0:
        costo_neto_dpto = dividendo_mensual - arriendo_cobrado
        lineas += [
            "",
            "  DEPARTAMENTO PROPIO (inversión inmobiliaria):",
            f"  • Dividendo hipotecario (aparece en gastos): {_fmt(dividendo_mensual)}",
            f"  • Arriendo que cobra de su inquilino (en ingresos): {_fmt(arriendo_cobrado)}",
            f"  • COSTO NETO del dpto propio: {_fmt(costo_neto_dpto)} (solo el diferencial)",
        ]

    # Costo total real
    if gastos_compartidos and dividendo_mensual > 0 and arriendo_cobrado > 0:
        gc_neto = gastos_compartidos.get("por_persona", 0)
        costo_total_real = gc_neto + (dividendo_mensual - arriendo_cobrado)
        lineas += [
            "",
            f"  → COSTO TOTAL REAL DE VIVIENDA: {_fmt(costo_total_real)}",
            f"     (su parte gastos compartidos + diferencial dividendo)",
            f"  → Al analizar el % de vivienda, usa {_fmt(costo_total_real)}, NO el bruto reportado.",
        ]

    lineas.append("")
    return "\n".join(lineas) + "\n"


def _claude_personal(prompt_usuario: str, nivel: str = "senior") -> str:
    """Llama al agente con el system prompt de finanzas personales."""
    if not _agente_disponible:
        return "_Agente no disponible. Verifica ANTHROPIC_API_KEY en .env_"
    ultimo_error = None
    for intento in range(2):
        try:
            return _claude(
                system=_SYSTEM_PERSONAL + _CONTEXTO_CHILE,
                user=prompt_usuario,
                nivel=nivel,
            )
        except Exception as e:
            ultimo_error = e
            err = str(e).lower()
            if "credit balance" in err or "insufficient" in err or "402" in err:
                return "⚠️ **Análisis AI no disponible** — recarga saldo en [console.anthropic.com](https://console.anthropic.com)"
            es_sobrecarga = "529" in err or "overloaded" in err or "overload" in err
            if es_sobrecarga and intento == 0:
                time.sleep(1.2)
                continue
            if es_sobrecarga:
                return "_Claude temporalmente sobrecargado. Probando fallback._"
            return f"_Error al consultar el agente: {e}_"
    return f"_Error al consultar el agente: {ultimo_error}_"


def _openai_personal(prompt_usuario: str) -> str | None:
    """Llama a GPT-4o-mini con el system prompt de finanzas personales. Retorna texto o None."""
    if not _HAS_OPENAI:
        return None
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return None
    try:
        client = _OpenAI(api_key=api_key)
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            max_tokens=600,
            messages=[
                {"role": "system", "content": _SYSTEM_PERSONAL + _CONTEXTO_CHILE},
                {"role": "user",   "content": prompt_usuario},
            ]
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        print(f"[ai_insights] OpenAI error: {e}", file=sys.stderr)
        return None


def _gemini_personal(prompt_usuario: str) -> str | None:
    """Llama a Gemini 2.5 Flash con el system prompt de finanzas personales. Retorna texto o None."""
    if not _HAS_GEMINI:
        return None
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        return None
    try:
        client = _genai.Client(api_key=api_key)
        resp = client.models.generate_content(
            model="models/gemini-2.5-flash",
            contents=_SYSTEM_PERSONAL + _CONTEXTO_CHILE + "\n\n" + prompt_usuario,
        )
        return resp.text.strip()
    except Exception as e:
        print(f"[ai_insights] Gemini error: {e}", file=sys.stderr)
        return None


def _analizar_tres_modelos(prompt_usuario: str) -> str:
    """
    Llama a Claude, OpenAI y Gemini en paralelo con el mismo prompt.
    Si hay 2+ respuestas, Claude sintetiza una conclusión única consolidada.
    Si solo hay una respuesta disponible, la retorna directamente.
    """
    _INVALIDOS = ("_agente no disponible", "⚠️", "_error al consultar", "_sin respuesta")

    def _valida(texto: str | None) -> bool:
        if not texto:
            return False
        t = texto.strip().lower()
        return not any(t.startswith(m.lower()) for m in _INVALIDOS) and "no disponible" not in t

    resultados: dict[str, str] = {}

    def _run_claude():
        return "claude", _claude_personal(prompt_usuario)

    def _run_openai():
        r = _openai_personal(prompt_usuario)
        return "openai", r

    def _run_gemini():
        r = _gemini_personal(prompt_usuario)
        return "gemini", r

    with ThreadPoolExecutor(max_workers=3) as ex:
        for fut in as_completed([ex.submit(_run_claude), ex.submit(_run_openai), ex.submit(_run_gemini)]):
            modelo, texto = fut.result()
            if texto:
                resultados[modelo] = texto

    claude_r = resultados.get("claude", "")
    openai_r = resultados.get("openai", "")
    gemini_r = resultados.get("gemini", "")

    modelos_ok = [m for m, t in resultados.items() if _valida(t)]
    if len(modelos_ok) <= 1:
        # Solo un modelo disponible — retornar directamente sin síntesis
        return next((t for t in [claude_r, openai_r, gemini_r] if _valida(t)),
                    claude_r or openai_r or gemini_r or "_Sin respuesta disponible_")

    # Construir síntesis solo con modelos que dieron respuesta válida
    bloques = []
    if _valida(claude_r):
        bloques.append(f"ANÁLISIS CLAUDE:\n{claude_r}")
    if _valida(openai_r):
        bloques.append(f"ANÁLISIS GPT-4o-mini:\n{openai_r}")
    if _valida(gemini_r):
        bloques.append(f"ANÁLISIS GEMINI:\n{gemini_r}")

    synthesis_prompt = f"""Eres un árbitro financiero. Tienes {len(bloques)} análisis independientes del mismo caso:

{chr(10).join(bloques)}

Genera UNA SOLA conclusión consolidada de alto valor:

**Consenso:** qué puntos coinciden los modelos (lo más importante y accionable)
**Perspectivas complementarias:** qué aportó algún modelo que los otros no mencionaron (solo si agrega valor real)
**Recomendaciones finales:** 3 acciones concretas y priorizadas

Máximo 350 palabras. Directo, sin repetir obviedades. Español."""

    # Síntesis con fallback: Claude → OpenAI → Gemini
    sintesis = _claude_personal(synthesis_prompt)
    if sintesis and not sintesis.startswith("_") and "no disponible" not in sintesis.lower():
        return sintesis
    sintesis_oa = _openai_personal(synthesis_prompt)
    if sintesis_oa:
        return sintesis_oa
    sintesis_gm = _gemini_personal(synthesis_prompt)
    if sintesis_gm:
        return sintesis_gm
    return claude_r or openai_r or gemini_r


# ══════════════════════════════════════════════════════════════════════════════
#  ANÁLISIS POR MÓDULO
# ══════════════════════════════════════════════════════════════════════════════

def analizar_resumen_mes(
    mes_nombre: str,
    anio: int | None,
    ingresos: float,
    gastos: float,
    saldo_inicial: float,
    saldo_actual: float,
    por_grupo: dict,
    tasa_ahorro: float,
    indicadores: dict | None = None,
    arriendo_cobrado: float = 0,
    dividendo_mensual: float = 0,
    gastos_compartidos: dict | None = None,
) -> str:
    """
    Análisis ejecutivo del mes: qué pasó, cómo comparar, qué hacer.
    Úsalo en el Dashboard como "Resumen inteligente del mes".
    """
    periodo = f"{mes_nombre} {anio}" if anio else mes_nombre
    top_grupos = sorted(por_grupo.items(), key=lambda x: x[1], reverse=True)[:5]
    top_str = " | ".join(f"{g}: {_fmt(v)}" for g, v in top_grupos)

    uf = indicadores.get("uf", 39841) if indicadores else 39841
    dolar = indicadores.get("dolar", 913) if indicadores else 913

    ctx_vivienda = _contexto_vivienda(arriendo_cobrado, dividendo_mensual, gastos_compartidos)
    flujo_neto = ingresos - gastos

    prompt = f"""
Analiza el resumen financiero de {periodo}:

INGRESOS: {_fmt(ingresos)}
GASTOS TOTALES: {_fmt(gastos)} ({_pct(gastos, ingresos)} de los ingresos)
FLUJO NETO DEL MES (INGRESOS - GASTOS): {_fmt(flujo_neto)}
SALDO INICIAL: {_fmt(saldo_inicial)}
SALDO ACTUAL: {_fmt(saldo_actual)}
VARIACIÓN SALDO: {_fmt(saldo_actual - saldo_inicial)} ({'+' if saldo_actual >= saldo_inicial else ''}{_pct(abs(saldo_actual - saldo_inicial), saldo_inicial)})
TASA DE AHORRO: {tasa_ahorro:.1f}%
TOP GASTOS: {top_str}
UF del mes: {uf} | USD/CLP: {dolar}
{ctx_vivienda}
REGLAS CRITICAS PARA INTERPRETAR ESTOS DATOS:
- Si el flujo neto del mes es positivo y la tasa de ahorro es sana, NO describas el mes como deficitario.
- Una caida del saldo de caja puede deberse a timing, inversiones, pagos adelantados o movimientos no categorizados; trátala como contexto, no como contradicción principal, salvo que gastos > ingresos.
- Prioriza el diagnóstico sobre flujo mensual real (ingresos vs gastos) por sobre la variación puntual del saldo.

Entrega:
1) Diagnóstico del mes en 2 frases (positivo o preocupante, con datos concretos)
2) El gasto más relevante y si está dentro de parámetros sanos
3) 2 acciones concretas para mejorar o mantener el resultado
Máximo 200 palabras.
"""
    return _analizar_tres_modelos(prompt)


def analizar_historial_ingresos(liquidaciones: list) -> str:
    """
    Analiza el historial de liquidaciones: evolución sueldo, descuentos, tendencias.
    Úsalo en la página "Mis Ingresos".
    """
    if not liquidaciones:
        return "_Sin historial de liquidaciones disponible._"

    # Construir tabla resumen
    lineas = ["Período | Sueldo Base | Bono | Líquido | AFP | Salud | Impuesto"]
    for l in liquidaciones[-12:]:  # últimos 12 meses
        lineas.append(
            f"{l.get('periodo','?')} | "
            f"{_fmt(l.get('sueldo_base') or 0)} | "
            f"{_fmt(l.get('bono') or 0)} | "
            f"{_fmt(l.get('liquido') or 0)} | "
            f"{_fmt(l.get('afp') or 0)} | "
            f"{_fmt(l.get('salud') or 0)} | "
            f"{_fmt(l.get('impuesto') or 0)}"
        )

    ultimo = liquidaciones[-1]
    anterior = liquidaciones[-2] if len(liquidaciones) >= 2 else None
    var_liquido = ""
    if anterior and ultimo.get("liquido") and anterior.get("liquido"):
        delta = (ultimo["liquido"] - anterior["liquido"]) / anterior["liquido"] * 100
        var_liquido = f"Variación líquido vs mes anterior: {delta:+.1f}%"

    prompt = f"""
Analiza el historial de remuneraciones con los datos reales:

{chr(10).join(lineas)}

{var_liquido}

Entrega:
1) Tendencia del sueldo base y bonos en el período (crecimiento, estabilidad, caídas)
2) Análisis de descuentos legales: AFP, salud e impuesto — ¿son proporcionales al ingreso? ¿hay oportunidades de optimización?
3) Comparación del líquido real vs el ingreso bruto total: ¿qué % se queda en descuentos?
4) 2 recomendaciones específicas (ej: cambio AFP, negociación sueldo, optimización tributaria)
Máximo 280 palabras.
"""
    return _analizar_tres_modelos(prompt)


def analizar_presupuesto_vs_real(
    mes_nombre: str,
    ingresos: float,
    por_tipo: dict,
    por_grupo: dict,
    regla_5030_20: dict,
    arriendo_cobrado: float = 0,
    dividendo_mensual: float = 0,
    gastos_compartidos: dict | None = None,
) -> str:
    """
    Análisis FP&A personal: varianza por categoría, adherencia a regla 50/30/20.
    Úsalo en "Mes Detalle".
    """
    necesidades = regla_5030_20.get("necesidades", 0)
    deseos = regla_5030_20.get("deseos", 0)
    ahorro_deudas = regla_5030_20.get("ahorro_deudas", 0)
    ideal_nec = regla_5030_20.get("ideal_necesidades", ingresos * 0.5)
    ideal_des = regla_5030_20.get("ideal_deseos", ingresos * 0.3)

    top_grupos = sorted(por_grupo.items(), key=lambda x: x[1], reverse=True)[:6]
    grupos_str = "\n".join(f"  {g}: {_fmt(v)} ({_pct(v, ingresos)} ingresos)" for g, v in top_grupos)

    ctx_vivienda = _contexto_vivienda(arriendo_cobrado, dividendo_mensual, gastos_compartidos)

    prompt = f"""
Análisis FP&A personal — {mes_nombre}:

INGRESOS: {_fmt(ingresos)}

REGLA 50/30/20:
  Necesidades: {_fmt(necesidades)} (ideal {_fmt(ideal_nec)}, real {_pct(necesidades, ingresos)})
  Deseos: {_fmt(deseos)} (ideal {_fmt(ideal_des)}, real {_pct(deseos, ingresos)})
  Ahorro+Deudas: {_fmt(ahorro_deudas)} ({_pct(ahorro_deudas, ingresos)})

TOP GASTOS POR GRUPO:
{grupos_str}
{ctx_vivienda}
Entrega:
1) ¿Está la distribución dentro de parámetros sanos? Identifica la desviación más importante.
2) El grupo de gasto más preocupante y por qué.
3) Oportunidades concretas de optimización sin afectar calidad de vida.
Máximo 220 palabras.
"""
    return _analizar_tres_modelos(prompt)


def analizar_patrimonio(
    activos: dict,
    pasivos: dict,
    neto: float,
    ratio_endeudamiento: float,
    ingresos_mensuales: float,
    indicadores: dict | None = None,
) -> str:
    """
    Análisis del estado patrimonial: solidez, liquidez, riesgo de concentración.
    Úsalo en "Patrimonio Neto".
    """
    uf = indicadores.get("uf", 39841) if indicadores else 39841
    neto_uf = neto / uf if uf > 0 else 0
    activos_str = "\n".join(f"  {k}: {_fmt(v)}" for k, v in activos.items() if v > 0)
    pasivos_str = "\n".join(f"  {k}: {_fmt(v)}" for k, v in pasivos.items() if v > 0) or "  Sin pasivos registrados"

    meses_cubrir = (activos.get("Cta. Corriente/Vista", 0) + activos.get("Cta. Ahorro", 0)) / ingresos_mensuales if ingresos_mensuales > 0 else 0

    prompt = f"""
Análisis patrimonial:

ACTIVOS:
{activos_str}
TOTAL ACTIVOS: {_fmt(sum(v for v in activos.values() if v > 0))}

PASIVOS:
{pasivos_str}
TOTAL PASIVOS: {_fmt(sum(v for v in pasivos.values() if v > 0))}

PATRIMONIO NETO: {_fmt(neto)} ({neto_uf:.1f} UF)
DEUDA/ACTIVOS: {ratio_endeudamiento:.1f}% (solidez patrimonial — sano <40%)
FONDO EMERGENCIA: {meses_cubrir:.1f} meses de ingresos en activos líquidos
INGRESOS MENSUALES: {_fmt(ingresos_mensuales)}
UF actual: {uf}

Entrega:
1) Diagnóstico de la solidez patrimonial (concentración, liquidez, endeudamiento)
2) ¿Es adecuado el fondo de emergencia? (recomendación estándar: 3-6 meses)
3) Principal riesgo patrimonial y cómo mitigarlo
4) Próximo hito de construcción patrimonial recomendado
Máximo 280 palabras.
"""
    return _analizar_tres_modelos(prompt)


def analizar_afp(
    saldo_actual: float,
    aporte_mensual: float,
    edad_aprox: int,
    años_proyeccion: int,
    saldo_pesimista: float,
    saldo_base: float,
    saldo_optimista: float,
    indicadores: dict | None = None,
) -> str:
    """
    Análisis de la situación previsional: proyección, comisiones, estrategia.
    Úsalo en "AFP y Previsión".
    """
    uf = indicadores.get("uf", 39841) if indicadores else 39841
    saldo_uf = saldo_actual / uf

    prompt = f"""
Análisis previsional AFP:

SALDO ACTUAL: {_fmt(saldo_actual)} ({saldo_uf:.1f} UF)
APORTE MENSUAL NETO: {_fmt(aporte_mensual)}
AÑOS DE PROYECCIÓN: {años_proyeccion}
AFP ACTUAL: ProVida (comisión 1.45% — una de las más altas del mercado)

PROYECCIONES A {años_proyeccion} AÑOS:
  Pesimista (4% real): {_fmt(saldo_pesimista)}
  Base (6% real): {_fmt(saldo_base)}
  Optimista (8% real): {_fmt(saldo_optimista)}

Alternativas de menor comisión: Modelo (0.58%) | Uno AFP (0.49%)
UF actual: {uf}

Entrega:
1) ¿Es suficiente la proyección para una pensión digna? (referencia: pensión mínima ~$250.000 CLP 2026)
2) Impacto concreto de cambiar a una AFP de menor comisión (cálculo estimado del ahorro en {años_proyeccion} años)
3) 2 estrategias para acelerar el crecimiento previsional (APV, cambio de fondo, etc.)
Máximo 250 palabras.
"""
    return _analizar_tres_modelos(prompt)


def analizar_dividendo_historico(historico: list, arriendo_cobrado: float) -> str:
    """
    Analiza la evolución mensual del dividendo hipotecario vs arriendo cobrado (UF).
    historico: lista de dicts {mes_nombre, dividendo, neto, uf}
    """
    if not historico:
        return "_Sin historial de dividendo disponible._"

    lineas = ["Mes | Dividendo | Arriendo Cobrado | Costo Neto | Var Dividendo | Var Neto"]
    prev_div = None
    prev_neto = None
    for h in historico:
        div = h["dividendo"]
        neto = h["neto"]
        var_div = f"{(div - prev_div) / prev_div * 100:+.2f}%" if prev_div else "—"
        var_neto = f"{(neto - prev_neto) / prev_neto * 100:+.2f}%" if prev_neto else "—"
        lineas.append(
            f"{h['mes_nombre']} | {_fmt(div)} | {_fmt(arriendo_cobrado)} | {_fmt(neto)} | {var_div} | {var_neto}"
        )
        prev_div = div
        prev_neto = neto

    ultimo = historico[-1]
    primero = historico[0]
    variacion_total = (ultimo["dividendo"] - primero["dividendo"]) / primero["dividendo"] * 100 if primero["dividendo"] else 0

    prompt = f"""
Analiza la evolución mensual del costo neto de vivienda (dividendo UF - arriendo cobrado):

{chr(10).join(lineas)}

ARRIENDO COBRADO DE INQUILINO: {_fmt(arriendo_cobrado)} (fijo mensual)
VARIACIÓN TOTAL DEL DIVIDENDO ({primero['mes_nombre']} → {ultimo['mes_nombre']}): {variacion_total:+.2f}%
UF referencia último mes: {ultimo.get('uf', 'N/D')}

Entrega:
1) Tendencia del dividendo: ¿está subiendo por UF? ¿a qué ritmo mensual y anualizado?
2) Impacto en el costo neto real: variación en CLP y % respecto al mes anterior
3) Proyección: si la UF sigue su tendencia, ¿cuánto podría ser el dividendo en 6 y 12 meses?
4) ¿El arriendo cobrado ({_fmt(arriendo_cobrado)} fijo) está cubriendo bien el diferencial o la brecha se amplía?
Máximo 250 palabras.
"""
    return _analizar_tres_modelos(prompt)


_PALABRAS_ESTRATEGIA = (
    "plan", "meta", "ahorrar", "ahorrar más", "escenario", "estrategia",
    "mejorar", "optimizar", "subir tasa", "subir ahorro", "priorizar",
    "mecanismo", "qué hago", "que hago", "como debo", "cómo debo",
)


def _es_pregunta_estrategia(pregunta: str) -> bool:
    p = (pregunta or "").lower()
    return any(k in p for k in _PALABRAS_ESTRATEGIA)


def consulta_libre(pregunta: str, contexto_usuario: dict | None = None) -> str:
    """
    Responde preguntas libres del usuario sobre su situación financiera.
    El contexto_usuario puede incluir saldos, ingresos, etc. (opcional).
    """
    ctx = ""
    if contexto_usuario:
        ctx = "\nContexto del usuario:\n" + "\n".join(
            f"  {k}: {v}" for k, v in contexto_usuario.items() if v
        ) + "\n"

    es_estrategia = _es_pregunta_estrategia(pregunta)

    reglas_base = """REGLAS DE INTERPRETACIÓN DE DATOS:
- Usa SOLO el contexto entregado. No inventes cifras.
- Bases de planificación: "base_promedio" (ventana móvil de varios meses, usar para planes 3-6m y tendencias) vs "base_tactica" (mes actual ajustado, usar para decisiones del mes en curso). Nunca confundas un nombre con el otro.
- Si la pregunta menciona "promedio", "últimos meses", "3 a 6 meses" o "planificación" → usa base promedio.
- Si la pregunta menciona "este mes" → usa base táctica del mes actual.
- Si existe "regla_anclaje_planificacion" o "contexto_dividendo_planificacion", respétalas literalmente.
- Para fondo de emergencia: prioriza el promedio multimensual sobre el mes actual.
- "tasa_ahorro_ajustada_si_falta_dividendo" solo aplica a decisiones tácticas del mes, no a planes.

REGLAS DE RECOMENDACIÓN:
- NO recomiendes recortar gastos listados en "gastos_no_recortables_declarados".
- Evita usar manutención, pensión o gasto familiar base como palanca principal de ahorro.
- Distingue siempre: no recortable | estructural optimizable | discrecional recortable.
- No mezcles un concepto específico con el total del grupo (ej: "Crédito de Consumo" ≠ todo "Financiero - Deudas").
- Si una meta exige recortes inviables, dilo explícitamente; no la presentes como realista.
- Prioriza conceptos sobre su promedio reciente (ver "conceptos_sobre_promedio").
- Aterriza siempre los planes en CLP y conceptos concretos.

REGLAS DE INTERPRETACIÓN AMBIGUA:
- "Subir tasa de ahorro en X%": calcula ambas (relativo y puntos porcentuales) y di cuál usas.
- "Déficit": si ingresos > gastos pero el saldo bajó, es un tema de flujo/caja, no déficit operacional — explícalo así.

VALIDACIÓN MATEMÁTICA (antes de responder):
- Si propones una meta de ahorro, verifica:
  • ahorro_meta = ingresos - gasto_meta
  • brecha_ahorro = ahorro_meta - ahorro_actual
  • recorte_necesario = gasto_actual - gasto_meta
  • Si ingresos no cambian: brecha_ahorro ≈ recorte_necesario
  • Si propones aumentar ingresos en lugar de recortar: brecha_ahorro proviene del ingreso extra, recorte_necesario puede ser 0 — declarar explícitamente.
- Corrige cualquier cifra inconsistente antes de entregar.

FORMATO:
- Sin tablas. Sin markdown de énfasis (no **, *, _, #).
- Párrafos cortos o bullets simples con "-".
- Español claro, técnico, accionable."""

    if es_estrategia:
        formato_extra = """

ESTRUCTURA DE RESPUESTA (pregunta de estrategia/plan/meta):
1) Diagnóstico corto (2-3 frases)
2) Meta realista aterrizada en CLP
3) Medidas concretas por concepto (recorte viable vs estructural vs no viable)
4) Escenarios breves: Conservador / Base / Agresivo
   - meta mensual aproximada en CLP
   - principal mecanismo
   - exigencia esperada
5) Recomendación final priorizada (privilegia "Base" salvo razón clara)

Hasta 450 palabras."""
    else:
        formato_extra = """

ESTRUCTURA DE RESPUESTA (pregunta directa):
- Responde directo a lo que se pregunta con los datos del contexto.
- Si la pregunta es de hechos (cuánto, cuándo, cuál) → 1-2 párrafos cortos.
- Si pide opinión/diagnóstico → 2-3 párrafos máximo.
- Cierra con 1-2 acciones concretas SOLO si aplica.

Hasta 250 palabras."""

    prompt = f"""{reglas_base}{formato_extra}
{ctx}
Pregunta del usuario: {pregunta}"""
    resp_claude = _claude_personal(prompt)
    _resp_low = (resp_claude or "").strip().lower()
    if resp_claude and not _resp_low.startswith("_error al consultar") and "temporalmente sobrecargado" not in _resp_low:
        return resp_claude

    resp_openai = _openai_personal(prompt)
    if resp_openai:
        return resp_openai

    resp_gemini = _gemini_personal(prompt)
    if resp_gemini:
        return resp_gemini

    if resp_claude:
        return "⚠️ El proveedor principal está temporalmente sobrecargado. Reintenta en 30-60 segundos."
    return "_Sin respuesta disponible en este momento._"


# ══════════════════════════════════════════════════════════════════════════════
#  WIDGETS STREAMLIT
# ══════════════════════════════════════════════════════════════════════════════

def render_insight_card(titulo: str, contenido: str, tipo: str = "info"):
    """
    Renderiza un card de insight AI con estilo visual.
    tipo: "info" | "success" | "warning" | "error"
    """
    iconos = {"info": "🤖", "success": "✅", "warning": "⚠️", "error": "❌"}
    icono = iconos.get(tipo, "🤖")

    st.markdown(f"""
<div style="
    background: linear-gradient(135deg, #1E293B 0%, #0F172A 100%);
    border-left: 4px solid {'#10B981' if tipo=='success' else '#6366F1' if tipo=='info' else '#F59E0B' if tipo=='warning' else '#F43F5E'};
    border-radius: 8px;
    padding: 16px 20px;
    margin: 12px 0;
    box-shadow: 0 2px 8px rgba(0,0,0,0.3);
">
<div style="color: #94A3B8; font-size: 0.75rem; font-weight: 600; letter-spacing: 0.05em; margin-bottom: 8px;">
    {icono} {titulo.upper()}
</div>
<div style="color: #E2E8F0; font-size: 0.875rem; line-height: 1.6;">
    {contenido.replace(chr(10), '<br>')}
</div>
</div>
""", unsafe_allow_html=True)


def render_insight_con_spinner(titulo: str, funcion, *args, cache_key: str = "", **kwargs) -> str:
    """
    Llama a una función de análisis AI con spinner de carga.
    Cachea el resultado en session_state para no re-llamar la API.
    Retorna "" si la respuesta es inválida (error de API, sin créditos, etc.)

    Uso:
        resultado = render_insight_con_spinner(
            "Análisis del mes", analizar_resumen_mes, mes, ingresos, ...
        )
    """
    _INVALIDOS = ("_agente no disponible", "⚠️", "_error al consultar", "_sin respuesta")

    def _es_valido(texto: str | None) -> bool:
        if not texto:
            return False
        t = texto.strip().lower()
        return not any(t.startswith(m.lower()) for m in _INVALIDOS) and "no disponible" not in t

    clave = f"ai_cache_{cache_key}" if cache_key else f"ai_cache_{titulo}_{id(funcion)}"

    if clave not in st.session_state:
        with st.spinner(f"🤖 Generando análisis: {titulo}..."):
            resultado = funcion(*args, **kwargs)
            st.session_state[clave] = resultado if _es_valido(resultado) else ""

    return st.session_state.get(clave, "")


def limpiar_cache_ai():
    """Limpia todos los análisis AI cacheados en session_state."""
    claves = [k for k in st.session_state if k.startswith("ai_cache_")]
    for k in claves:
        del st.session_state[k]


def agente_disponible() -> bool:
    """Retorna True si el agente está disponible y tiene API key."""
    return _agente_disponible and bool(os.getenv("ANTHROPIC_API_KEY"))
