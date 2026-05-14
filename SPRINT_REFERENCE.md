# CLAUDE CODE — Sprint 1: App Streamlit Finanzas Personales
**Proyecto:** finanzas_personales
**Responsable:** Sócrates Cabral
**Fecha:** Mar-2026
**Directorio de trabajo:** `C:\ClaudeWork\finanzas_personales\`
**Comando Python:** `py` (Python 3.14 64-bit — `C:\Users\Socrates Cabral\AppData\Local\Python\pythoncore-3.14-64\python.exe`)
**Archivo Excel fuente:** `Plantilla-para-controlar-gastos.xlsm`

---

## CONTEXTO DEL PROYECTO

App de gestión de finanzas personales para Sócrates Cabral, basada en un Excel .xlsm ya existente
que él usa como libro de gastos mensual. El proyecto sigue el mismo patrón arquitectónico que
`chiquito_financiero` (Streamlit + openpyxl + Plotly), adaptado a finanzas personales.

**Módulos del alcance:**
1. **Presupuesto mensual** — ingresos vs gastos, semáforo por categoría
2. **Patrimonio neto** — activos (cuentas, USDT, bienes raíces) vs pasivos (deudas)

---

## ESTRUCTURA DEL EXCEL (fuente de verdad)

### Hojas presentes (16 total):
| Hoja | Rol |
|------|-----|
| `01 Enero` … `12 Diciembre` | Libro de transacciones mensual |
| `Resumen` | SUMIF cruzado — gastos por concepto x mes |
| `Categorias` | Tabla maestra: GRUPOS / CONCEPTOS / Tipo |
| `Gastos Compartidos` | Desglose de gastos de vivienda compartidos |
| `Trámites` | Cálculos de trámites VE (apostilla, legalización) — NO leer en app |

### Estructura de cada hoja mensual (ej: `01 Enero`):
```
Fila 4: Saldo Actual (calculado) | F4 = fórmula con saldo inicial – gastos + cobros
Fila 5: Saldo Inicial            | F5 = suma cuentas + valor USDT en CLP
Fila 7: Headers: [col B] GRUPO | [col C] CONCEPTO | [col D] Fecha | [col E] DETALLE | [col F] IMPORTE
Fila 8+: Transacciones (gastos con importe positivo)
```

**CRÍTICO:** openpyxl lee fórmulas como strings — NO como valores calculados.
Para leer valores de saldo (F4, F5), usar `data_only=True` al abrir el workbook.
Para leer transacciones (texto + fechas + montos), también usar `data_only=True`.

### Categorías — 15 grupos con tipo:
| Grupo | Tipo |
|-------|------|
| Servicios Básicos | Fijo |
| Hogar y Vivienda | Fijo |
| Alimentación | Variable |
| Salud y Cuidado Personal | Variable |
| Transporte | Variable |
| Financiero - Deudas | Fijo |
| Seguros | Fijo |
| Familia e Hijos | Fijo |
| Educación y Formación | Variable |
| Ahorro e Inversión | Fijo |
| Mascotas | Variable |
| Suscripciones Digitales | Prescindible |
| Ocio y Vida Social | Prescindible |
| Regalos y Donaciones | Prescindible |
| Varios y Otros | Variable |

### Saldo Inicial Enero 2026 (referencia):
```
= 1,679,673  (cuenta corriente / vista)
+ 10,349,996 (cuenta ahorro / segunda cuenta)
+ 909.09 USDT × 22,000 CLP/USDT  (inversión cripto USDT)
≈ $31,700,000 total
```
**Nota:** El tipo de cambio USDT/CLP no está hardcodeado en el Excel — se actualiza manualmente.
En la app, el módulo Patrimonio debe permitir ingresar el precio actual de USDT para recalcular.

### Ingresos — NO están en el Excel actual:
El Excel solo registra gastos. Los ingresos de Sócrates son:
- **Sueldo fijo mensual** (Egakat SPA — Head of Control Management)
- **Arriendo cobrado** (propiedad que arrienda, dividido en la hoja `Gastos Compartidos`)

**Solución:** agregar hoja `Ingresos` al Excel en Sprint 2, O capturarlos como inputs configurables
en la app (sidebar o página de Ajustes). En Sprint 1 usar inputs manuales en la app.

---

## ESTRUCTURA DE CARPETAS A CREAR

```
C:\ClaudeWork\finanzas_personales\
├── app\
│   ├── main.py              ← Streamlit app principal
│   ├── data_loader.py       ← Lee el Excel .xlsm
│   ├── calculators.py       ← Lógica: presupuesto, patrimonio, ratios
│   ├── charts.py            ← Gráficos Plotly
│   └── requirements.txt     ← Dependencias
├── Plantilla-para-controlar-gastos.xlsm   ← Excel fuente (COPIAR aquí)
├── MEMORY.md                ← Documentación del proyecto
├── CLAUDE_CODE_SPRINT.md    ← Este archivo
└── Iniciar_FinanzasPersonales.bat  ← Lanzador Windows
```

**IMPORTANTE:** El Excel fuente está en:
`C:\Users\Socrates Cabral\OneDrive - EGA KAT LOGISTICA SPA\...` (o similar OneDrive personal)
Al leerlo, usar la ruta real o pedir al usuario que lo copie a la carpeta del proyecto.
Usar `python-dotenv` con variable `EXCEL_PATH` en `.env` para no hardcodear la ruta.

---

## PASO 1 — requirements.txt

```
streamlit>=1.32.0
pandas>=2.2.0
openpyxl>=3.1.2
plotly>=5.20.0
python-dotenv>=1.0.0
```

Instalar:
```bash
py -m pip install -r app\requirements.txt --break-system-packages
```

---

## PASO 2 — data_loader.py

```python
# app/data_loader.py
import openpyxl
import pandas as pd
from datetime import datetime
from pathlib import Path
import os
from dotenv import load_dotenv

load_dotenv(dotenv_path=Path(__file__).parent.parent.parent / '.env')

EXCEL_PATH = os.getenv('EXCEL_PATH', r'C:\ClaudeWork\finanzas_personales\Plantilla-para-controlar-gastos.xlsm')

MESES = {
    '01 Enero': 1, '02 Febrero': 2, '03 Marzo': 3, '04 Abril': 4,
    '05 Mayo': 5, '06 Junio': 6, '07 Julio': 7, '08 Agosto': 8,
    '09 Septiembre': 9, '10 Octubre': 10, '11 Noviembre': 11, '12 Diciembre': 12
}

@st.cache_data(ttl=300)
def cargar_transacciones() -> pd.DataFrame:
    """Lee todas las transacciones de los 12 meses."""
    wb = openpyxl.load_workbook(EXCEL_PATH, read_only=True, data_only=True, keep_vba=True)
    filas = []
    for nombre_hoja, num_mes in MESES.items():
        if nombre_hoja not in wb.sheetnames:
            continue
        ws = wb[nombre_hoja]
        for row in ws.iter_rows(min_row=8, values_only=True):
            grupo, concepto, fecha, detalle, importe = row[1], row[2], row[3], row[4], row[5]
            if grupo is None and concepto is None:
                continue
            if not isinstance(importe, (int, float)) or importe <= 0:
                continue
            filas.append({
                'mes': num_mes,
                'hoja': nombre_hoja,
                'grupo': str(grupo).strip() if grupo else '',
                'concepto': str(concepto).strip() if concepto else '',
                'fecha': fecha if isinstance(fecha, datetime) else None,
                'detalle': str(detalle).strip() if detalle else '',
                'importe': float(importe)
            })
    wb.close()
    return pd.DataFrame(filas)

def cargar_categorias() -> pd.DataFrame:
    """Lee la tabla de categorías con tipo (Fijo/Variable/Prescindible)."""
    wb = openpyxl.load_workbook(EXCEL_PATH, read_only=True, data_only=True, keep_vba=True)
    ws = wb['Categorias']
    filas = []
    for row in ws.iter_rows(min_row=2, values_only=True):
        grupo, concepto = row[0], row[1]
        if grupo and concepto:
            filas.append({'grupo': str(grupo).strip(), 'concepto': str(concepto).strip()})
    # Tipo por grupo (hardcodeado porque está en col F de Categorias)
    tipos = {
        'Servicios Básicos': 'Fijo', 'Hogar y Vivienda': 'Fijo',
        'Financiero - Deudas': 'Fijo', 'Seguros': 'Fijo',
        'Familia e Hijos': 'Fijo', 'Ahorro e Inversión': 'Fijo',
        'Alimentación': 'Variable', 'Salud y Cuidado Personal': 'Variable',
        'Transporte': 'Variable', 'Educación y Formación': 'Variable',
        'Mascotas': 'Variable', 'Varios y Otros': 'Variable',
        'Suscripciones Digitales': 'Prescindible',
        'Ocio y Vida Social': 'Prescindible', 'Regalos y Donaciones': 'Prescindible'
    }
    df = pd.DataFrame(filas)
    df['tipo'] = df['grupo'].map(tipos).fillna('Variable')
    wb.close()
    return df

def cargar_gastos_compartidos() -> dict:
    """Lee la hoja Gastos Compartidos y retorna dict con valores."""
    wb = openpyxl.load_workbook(EXCEL_PATH, read_only=True, data_only=True, keep_vba=True)
    ws = wb['Gastos Compartidos']
    datos = {}
    for row in ws.iter_rows(min_row=2, max_row=10, values_only=True):
        concepto, total, por_persona = row[0], row[1], row[2]
        if concepto and isinstance(total, (int, float)):
            datos[str(concepto)] = {
                'total': float(total),
                'por_persona': float(por_persona) if isinstance(por_persona, (int, float)) else float(total)
            }
    wb.close()
    return datos
```

**NOTA:** `@st.cache_data` requiere importar `streamlit as st` — mover el decorator a main.py
y llamar la función desde ahí, o usar `functools.lru_cache` en data_loader.

---

## PASO 3 — calculators.py

```python
# app/calculators.py

def calc_resumen_mensual(df: pd.DataFrame, mes: int) -> dict:
    """Gastos del mes agrupados por grupo y tipo."""
    df_mes = df[df['mes'] == mes]
    por_grupo = df_mes.groupby('grupo')['importe'].sum().to_dict()
    total = df_mes['importe'].sum()
    return {'por_grupo': por_grupo, 'total': total}

def calc_resumen_anual(df: pd.DataFrame) -> pd.DataFrame:
    """Gastos por mes × grupo — para gráfico de barras apiladas."""
    return df.pivot_table(
        index='mes', columns='grupo', values='importe',
        aggfunc='sum', fill_value=0
    ).reset_index()

def calc_patrimonio_neto(activos: dict, pasivos: dict) -> dict:
    """
    activos = {
        'Cuenta Vista/Corriente': monto,
        'Cuenta Ahorro': monto,
        'USDT': cantidad_usdt,
        'precio_usdt_clp': precio,
        'Bienes Raíces': valor_tasado,
        'Otros': monto
    }
    pasivos = {
        'Crédito Consumo': saldo,
        'Tarjetas de Crédito': saldo,
        'Crédito Hipotecario': saldo,
        'Otros': saldo
    }
    """
    valor_usdt = activos.get('USDT', 0) * activos.get('precio_usdt_clp', 22000)
    total_activos = (
        activos.get('Cuenta Vista/Corriente', 0) +
        activos.get('Cuenta Ahorro', 0) +
        valor_usdt +
        activos.get('Bienes Raíces', 0) +
        activos.get('Otros', 0)
    )
    total_pasivos = sum(v for k, v in pasivos.items() if k != 'precio_usdt_clp')
    return {
        'total_activos': total_activos,
        'total_pasivos': total_pasivos,
        'patrimonio_neto': total_activos - total_pasivos,
        'valor_usdt_clp': valor_usdt,
        'ratio_endeudamiento': total_pasivos / total_activos if total_activos > 0 else 0
    }

def calc_tasa_ahorro(ingresos: float, gastos_totales: float) -> dict:
    """Tasa de ahorro y clasificación según regla 50/30/20."""
    if ingresos <= 0:
        return {'tasa_ahorro': 0, 'ahorro_abs': 0, 'estado': 'Sin datos'}
    ahorro = ingresos - gastos_totales
    tasa = ahorro / ingresos
    estado = '🟢 Saludable' if tasa >= 0.20 else ('🟡 Ajustado' if tasa >= 0.05 else '🔴 Déficit')
    return {'tasa_ahorro': tasa, 'ahorro_abs': ahorro, 'estado': estado}

def clasificar_50_30_20(df_mes: pd.DataFrame, tipos: dict, ingresos: float) -> dict:
    """
    Regla 50/30/20:
    - 50% Necesidades (Fijo)
    - 30% Deseos (Variable + Prescindible no esenciales)
    - 20% Ahorro/Deudas
    Retorna gasto real vs presupuesto ideal por cada bucket.
    """
    ...
```

---

## PASO 4 — main.py (Streamlit)

### Páginas del sidebar:
```
💰 FINANZAS PERSONALES
─────────────────────
📊 Dashboard
📅 Mes Detalle
📈 Anual
💎 Patrimonio Neto
⚙️  Ajustes
```

### Dashboard (página principal):
**KPIs superiores (4 cards):**
- Ingresos mes actual (input manual si no está en Excel)
- Gastos mes actual (suma transacciones mes actual)
- Tasa de ahorro (%) con semáforo 🔴🟡🟢
- Patrimonio neto (valor configurado en Ajustes)

**Gráficos:**
- Barras horizontales: Top 5 categorías de gasto del mes
- Dona: distribución por tipo (Fijo / Variable / Prescindible)
- Línea: evolución de gastos totales mes a mes (todos los meses con datos)

**Alertas:**
- 🔴 Si gastos > ingresos
- 🟡 Si categoría "Ocio y Vida Social" > 15% del ingreso
- 🟡 Si "Financiero - Deudas" > 30% del ingreso

### Mes Detalle:
- Selector de mes (solo meses con datos)
- Tabla de transacciones filtrable por grupo/concepto
- Resumen por grupo con barra de progreso vs presupuesto (configurable en Ajustes)
- Botón "Ver Gastos Compartidos" — muestra desglose de la hoja Gastos Compartidos

### Anual:
- Barras apiladas: gastos por mes × grupo (todos los meses)
- Tabla Resumen anual (espejo del Resumen del Excel)
- Acumulado vs presupuesto anual

### Patrimonio Neto:
**Inputs (configurables, guardados en session_state):**
```
Activos:
  Cuenta Vista/Corriente   [input numérico]
  Cuenta Ahorro            [input numérico]
  USDT (cantidad)          [input numérico] | Precio USDT/CLP [input]  → valor auto
  Bienes Raíces            [input numérico — valor tasado aproximado]
  Otros activos            [input numérico]

Pasivos:
  Crédito Consumo BCI      [input numérico — saldo actual]
  Tarjetas de Crédito      [input numérico]
  Crédito Hipotecario      [input numérico — si aplica]
  Otros pasivos            [input numérico]
```

**Resultados:**
- KPI Patrimonio Neto = Activos – Pasivos (color verde/rojo)
- Ratio endeudamiento = Pasivos / Activos (semáforo: <30% verde, 30-60% amarillo, >60% rojo)
- Gráfico de barras apiladas horizontal: Activos vs Pasivos
- Línea de tiempo: si el usuario guarda snapshots mensuales (opcional Sprint 2)

### Ajustes:
- Ruta del Excel (detecta automáticamente si está en la carpeta del proyecto)
- Ingresos mensuales (sueldo fijo + arriendo cobrado) — editables
- Presupuesto por grupo (para comparar vs real)
- Precio actual USDT/CLP
- Botón "🔄 Recargar datos" → `st.cache_data.clear()`

---

## PASO 5 — Lanzador Windows

```bat
@echo off
title Finanzas Personales — Iniciando...
color 0B
cd /d "C:\ClaudeWork\finanzas_personales"
start "" "http://localhost:8503"
py -m streamlit run app\main.py --server.port 8503 --server.headless true --browser.gatherUsageStats false
pause
```

Puerto: **8503** (distinto al 8502 de chiquito_financiero para que puedan correr simultáneamente)

---

## ORDEN DE EJECUCIÓN — 10 PASOS

```
PASO 1: Crear estructura de carpetas
         mkdir C:\ClaudeWork\finanzas_personales\app

PASO 2: Crear requirements.txt y pip install

PASO 3: Copiar Excel a la carpeta del proyecto
         Agregar a .env: EXCEL_FP_PATH=C:\ClaudeWork\finanzas_personales\Plantilla-para-controlar-gastos.xlsm

PASO 4: Crear data_loader.py — validar con script de prueba
         py -c "from app.data_loader import cargar_transacciones; print(cargar_transacciones().head())"

PASO 5: Crear calculators.py

PASO 6: Crear charts.py (funciones Plotly reutilizables)

PASO 7: Crear main.py — comenzar con Dashboard mínimo (solo KPIs + 1 gráfico)

PASO 8: Agregar página Mes Detalle

PASO 9: Agregar página Patrimonio Neto con inputs

PASO 10: Crear lanzador .bat + probar ejecución completa
```

---

## ERRORES CONOCIDOS A EVITAR

| Error | Causa | Fix |
|-------|-------|-----|
| `openpyxl` lee fórmulas como strings | Por defecto lee fórmulas, no valores | Siempre usar `data_only=True` |
| `keep_vba=True` requerido para .xlsm | Sin esto da error al abrir | Siempre incluirlo |
| Columnas B y C intercambiadas en algunos meses | Inconsistencia en el Excel fuente | Intentar B primero (grupo), si None intentar C |
| Fechas como `datetime` vs string | Depende de si la celda tiene formato fecha | Validar con `isinstance(fecha, datetime)` |
| Saldo inicial incluye USDT a precio fijo | 909.09 × 22,000 = hardcodeado en el Excel | Ignorar F5 y recalcular en módulo Patrimonio |
| Hoja `Trámites` no leer en app | Datos de trámites Venezuela — irrelevantes | Excluir explícitamente |
| Puerto 8502 ocupado por chiquito_financiero | Conflicto de puertos | Usar puerto 8503 |

---

## DATOS DE REFERENCIA

**Saldo Inicial Enero 2026 (real del Excel):**
- Cuenta 1: $1,679,673
- Cuenta 2: $10,349,996
- USDT: 909.09 unidades (precio referencia: $22,000 CLP/USDT → $19,999,980)
- Total activos líquidos referencia: ~$32,000,000

**Gastos Compartidos (Marzo 2026 — referencia):**
- Arriendo: $450,000 total → $225,000 por persona
- GG.CC netos: $11,488 → $5,744 por persona
- Electricidad: $28,153 → $14,077 por persona
- Agua Andina: $21,020 → $10,510 por persona
- Agua Potable: $3,000 → $3,000 (sin dividir)
- **Total por persona: ~$258,330/mes**

**Ingresos mensuales (referencia — ingresar manualmente en Ajustes):**
- Sueldo fijo: a definir por Sócrates en Ajustes
- Arriendo cobrado: a definir (ingresa el monto que le pagan por su propiedad)

---

## REGLAS DEL AGENTE (heredadas de MEMORY.md)

1. Siempre usar `py` y `py -m pip`
2. Nunca hardcodear credenciales — leer desde `.env`
3. Scripts idempotentes
4. Todo proyecto en su subcarpeta `C:\ClaudeWork\finanzas_personales\`
5. Logs centralizados en `C:\ClaudeWork\logs\` si aplica
6. Comentar líneas deprecadas — nunca eliminar
