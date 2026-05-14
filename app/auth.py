import sys
sys.stdout.reconfigure(encoding="utf-8")

"""
auth.py — Login contra Supabase Auth con sesión persistente.

Sprint 5, paso 3. Pantalla de login antes de acceder a cualquier página.

Diseño:
- Backend: Supabase Auth (sign_in_with_password). Un solo almacén de
  usuarios — agregar a alguien = crear su cuenta en Supabase, nada más.
- La sesión autenticada entrega el UUID → se enchufa en supabase_repo
  vía set_authenticated_client(). RLS pasa a ser la barrera real porque
  el cliente usa la anon/publishable key + el JWT del usuario.
- El login SOLO se exige cuando DATA_SOURCE=supabase. En modo Excel la
  app sigue funcionando sin login (uso local personal).

Persistencia (F5):
- Al login se guarda el refresh_token de Supabase en una cookie de
  navegador (7 días). Al recargar la página, require_login() restaura la
  sesión con ese token sin pedir credenciales de nuevo.
- Los refresh tokens rotan: cada restauración guarda el nuevo en la cookie.
- Logout borra la cookie.

Claves del .env:
    SUPABASE_FINANZAS_URL          (ya configurada)
    SUPABASE_FINANZAS_ANON_KEY     la "Publishable key" de Settings → API
                                   (NO la service_role)
"""

import os
from datetime import datetime, timedelta
from pathlib import Path

import streamlit as st
import extra_streamlit_components as stx
from dotenv import load_dotenv

load_dotenv(dotenv_path=Path(__file__).parent.parent.parent / ".env")

import supabase_repo
import data_source

_COOKIE_NAME = "finanzas_session"
_COOKIE_DAYS = 7


# ── Credenciales ──────────────────────────────────────────────────────────────

def _anon_credentials() -> tuple[str, str]:
    """URL + anon/publishable key (para auth y para el cliente con RLS)."""
    url = os.getenv("SUPABASE_FINANZAS_URL", "")
    key = (
        os.getenv("SUPABASE_FINANZAS_ANON_KEY")
        or os.getenv("SUPABASE_FINANZAS_PUBLISHABLE_KEY")
        or ""
    )
    return url, key


def _auth_enabled() -> bool:
    """El login solo se exige cuando la fuente de datos es Supabase."""
    return data_source.USANDO_SUPABASE


# ── Cookie de sesión ──────────────────────────────────────────────────────────
# El CookieManager de extra-streamlit-components renderiza un widget en su
# constructor (getAll), así que NO se puede cachear con @st.cache_resource.
# Debe instanciarse fresco una vez por run para que getAll re-sincronice las
# cookies del navegador. require_login() lo crea una vez y lo deja en
# session_state["_cm"] para que login()/logout() del mismo run lo reusen.

def _nuevo_cm() -> stx.CookieManager:
    """Instancia fresca del gestor de cookies. Llamar SOLO desde require_login."""
    cm = stx.CookieManager(key="finanzas_cookie_mgr")
    st.session_state["_cm"] = cm
    return cm


def _get_cm() -> stx.CookieManager:
    """Devuelve el CookieManager del run actual (creado por require_login)."""
    cm = st.session_state.get("_cm")
    if cm is None:
        # require_login no corrió este run — fallback defensivo
        cm = _nuevo_cm()
    return cm


def _guardar_cookie(refresh_token: str):
    if not refresh_token:
        return
    try:
        _get_cm().set(
            _COOKIE_NAME,
            refresh_token,
            expires_at=datetime.now() + timedelta(days=_COOKIE_DAYS),
        )
    except Exception:
        pass


def _borrar_cookie():
    try:
        _get_cm().delete(_COOKIE_NAME)
    except Exception:
        pass


# ── Sesión ────────────────────────────────────────────────────────────────────

def is_authenticated() -> bool:
    return bool(st.session_state.get("_auth_user_id"))


def current_email() -> str:
    return st.session_state.get("_auth_email", "")


def current_user_id() -> str:
    return st.session_state.get("_auth_user_id", "")


def _aplicar_sesion(client, user, refresh_token: str):
    """Guarda la sesión en session_state y engancha el repo al cliente JWT."""
    st.session_state["_auth_user_id"] = user.id
    st.session_state["_auth_email"]   = getattr(user, "email", "")
    st.session_state["_auth_client"]  = client
    supabase_repo.set_authenticated_client(client, user.id)
    if refresh_token:
        _guardar_cookie(refresh_token)


def login(email: str, password: str) -> tuple[bool, str]:
    """Autentica contra Supabase Auth. Retorna (ok, mensaje_error)."""
    url, key = _anon_credentials()
    if not url or not key:
        return False, ("Falta SUPABASE_FINANZAS_URL o SUPABASE_FINANZAS_ANON_KEY "
                       "en el .env (la 'Publishable key' del panel de Supabase).")

    email = (email or "").strip()
    if not email or not password:
        return False, "Ingresa email y contraseña."

    try:
        from supabase import create_client
        client = create_client(url, key)
        resp = client.auth.sign_in_with_password({"email": email, "password": password})
        user = getattr(resp, "user", None)
        session = getattr(resp, "session", None)
        if user is None:
            return False, "Credenciales inválidas."
    except Exception:
        # No exponer detalles del backend al usuario final
        return False, "Credenciales inválidas o error de conexión."

    refresh_token = getattr(session, "refresh_token", "") if session else ""
    _aplicar_sesion(client, user, refresh_token)

    # El caché de st.cache_data no distingue usuarios — limpiarlo en cada
    # login evita que datos de una sesión previa se sirvan a otra cuenta.
    st.cache_data.clear()
    return True, ""


def _restaurar_desde_cookie(refresh_token: str) -> bool:
    """Restaura la sesión a partir del refresh_token guardado en la cookie."""
    url, key = _anon_credentials()
    if not url or not key:
        return False
    try:
        from supabase import create_client
        client = create_client(url, key)
        resp = client.auth.refresh_session(refresh_token)
        user = getattr(resp, "user", None)
        session = getattr(resp, "session", None)
        if user is None:
            return False
    except Exception:
        _borrar_cookie()
        return False

    nuevo_refresh = getattr(session, "refresh_token", refresh_token) if session else refresh_token
    _aplicar_sesion(client, user, nuevo_refresh)
    return True


def logout():
    """Cierra la sesión y limpia todo rastro del usuario."""
    client = st.session_state.get("_auth_client")
    if client is not None:
        try:
            client.auth.sign_out()
        except Exception:
            pass
    for k in ("_auth_user_id", "_auth_email", "_auth_client", "_cookie_waited"):
        st.session_state.pop(k, None)
    supabase_repo.set_authenticated_client(None, None)
    _borrar_cookie()
    st.cache_data.clear()


# ── Gate ──────────────────────────────────────────────────────────────────────

def require_login():
    """Portón de entrada. Llamar al inicio de main.py, tras init_config().

    - DATA_SOURCE=excel  → no exige login, retorna de inmediato.
    - DATA_SOURCE=supabase + sesión activa → re-engancha el repo y retorna.
    - DATA_SOURCE=supabase + cookie válida → restaura sesión sin pedir login.
    - DATA_SOURCE=supabase + sin sesión → muestra el formulario y st.stop().
    """
    if not _auth_enabled():
        return

    # Instanciar el CookieManager UNA vez por run (su constructor renderiza
    # un widget — no puede ir en función cacheada ni llamarse dos veces).
    cm = _nuevo_cm()

    if is_authenticated():
        # Re-enganchar en cada rerun (los globals del módulo no persisten
        # garantizadamente entre reruns de Streamlit).
        client = st.session_state.get("_auth_client")
        uid = st.session_state.get("_auth_user_id")
        if client is not None and uid:
            supabase_repo.set_authenticated_client(client, uid)
        return

    # Sin sesión en memoria — intentar restaurar desde la cookie.
    # El componente de cookies es asíncrono: en el primer run de una carga
    # fresca devuelve {} aunque la cookie exista. Damos exactamente UN rerun
    # de gracia para que el componente sincronice antes de decidir.
    cookies = cm.get_all() or {}
    if not cookies and not st.session_state.get("_cookie_waited"):
        st.session_state["_cookie_waited"] = True
        st.stop()

    token = cookies.get(_COOKIE_NAME)
    if token and _restaurar_desde_cookie(token):
        return

    _render_login_form()
    st.stop()


def _render_login_form():
    """Formulario de login centrado, estilo oscuro coherente con la app."""
    st.markdown("""
    <style>
    .login-hero { text-align:center; margin: 8vh 0 2rem 0; }
    .login-hero h1 { font-size: 1.8rem; color:#E2E8F0; margin-bottom:0.2rem; }
    .login-hero p  { color:#94A3B8; font-size:0.9rem; }
    </style>
    <div class="login-hero">
        <h1>💰 Finanzas Personales</h1>
        <p>Ingresa con tu cuenta para continuar</p>
    </div>
    """, unsafe_allow_html=True)

    _c1, _c2, _c3 = st.columns([1, 1.4, 1])
    with _c2:
        with st.form("_login_form", clear_on_submit=False):
            email = st.text_input("Email", placeholder="tu@correo.com")
            password = st.text_input("Contraseña", type="password", placeholder="••••••••")
            submitted = st.form_submit_button("Ingresar", type="primary", use_container_width=True)
        if submitted:
            ok, err = login(email, password)
            if ok:
                st.rerun()
            else:
                st.error(err)
        st.caption("¿Sin cuenta? El administrador familiar la crea en Supabase.")


def render_logout_sidebar():
    """Bloque de sesión + botón de logout para el sidebar. Llamar desde main.py."""
    if not _auth_enabled() or not is_authenticated():
        return
    with st.sidebar:
        st.caption(f"👤 {current_email()}")
        if st.button("Cerrar sesión", use_container_width=True, key="_btn_logout"):
            logout()
            st.rerun()
