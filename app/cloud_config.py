"""
cloud_config.py — Unifica la configuración entre desarrollo local y nube.

IMPORTAR PRIMERO en main.py, antes que cualquier módulo que use os.getenv()
(data_source, auth, config_manager, etc.). Su único trabajo es dejar todas
las variables de configuración en os.environ, vengan de donde vengan.

Dos fuentes, en orden de prioridad:
  1. Local — archivo .env. Busca primero finanzas_personales/.env (propio,
     patrón HackeaMetabolismo); si no existe, cae al .env del monorepo
     C:/ClaudeWork/.env. Así funciona durante y después de la extracción
     del repo dedicado.
  2. Nube — st.secrets de Streamlit Cloud. Allá no hay .env; los secretos
     se cargan desde el panel de Streamlit Cloud. Se copian a os.environ
     con setdefault (no pisan lo que ya exista localmente).

Resultado: el resto del código sigue usando os.getenv() sin cambios y
funciona idéntico en local y en la nube.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

_AQUI = Path(__file__).resolve().parent                 # finanzas_personales/app
_FINANZAS_ENV = _AQUI.parent / ".env"                   # finanzas_personales/.env
_MONOREPO_ENV = _AQUI.parent.parent / ".env"            # C:/ClaudeWork/.env

# ── 1. Local: .env (propio primero, monorepo como fallback) ──────────────────
for _envfile in (_FINANZAS_ENV, _MONOREPO_ENV):
    try:
        if _envfile.exists():
            load_dotenv(dotenv_path=_envfile, override=False)
    except Exception:
        pass


# ── 2. Nube: st.secrets → os.environ ─────────────────────────────────────────
def _bridge_streamlit_secrets() -> int:
    """Copia st.secrets a os.environ. Retorna cuántas claves puenteó.

    setdefault: si una clave ya está en os.environ (por el .env local) no se
    pisa. En la nube no hay .env, así que st.secrets es la única fuente.
    """
    try:
        import streamlit as st
        secrets = st.secrets
    except Exception:
        return 0  # streamlit no disponible o sin secrets.toml — modo local puro

    n = 0
    try:
        for clave in secrets:
            valor = secrets[clave]
            # Solo escalares al environment; secciones anidadas se ignoran
            if isinstance(valor, (str, int, float, bool)):
                if os.environ.setdefault(str(clave), str(valor)) == str(valor):
                    n += 1
    except Exception:
        pass
    return n


_secrets_bridged = _bridge_streamlit_secrets()


def entorno() -> str:
    """'nube' si se puentearon secretos de Streamlit Cloud, si no 'local'."""
    return "nube" if _secrets_bridged > 0 else "local"
