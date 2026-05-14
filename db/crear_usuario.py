import sys
sys.stdout.reconfigure(encoding="utf-8")

"""
crear_usuario.py — Crea (o localiza) un usuario en Supabase Auth.

Sprint 5, paso 3. Usa la service_role key vía admin API — no necesita
pasar por el dashboard.

Diseño respetando la regla del .env:
    Este script LEE el .env por sí mismo (load_dotenv + os.getenv).
    NUNCA imprime la URL ni la key — solo confirma "presente / válida".
    El único secreto que imprime es la contraseña que TÚ pediste generar
    (la necesitas para loguearte después).

Uso:
    py finanzas_personales/db/crear_usuario.py --email tu@correo.com
    py finanzas_personales/db/crear_usuario.py --email tu@correo.com --password "MiClave123"
    py finanzas_personales/db/crear_usuario.py --check        (solo valida el .env)

Flujo:
    1. Valida que el .env tenga SUPABASE_FINANZAS_URL y _SERVICE_ROLE_KEY
       con valores reales (detecta placeholders).
    2. Conecta a Supabase y verifica que la key funcione.
    3. Si el email ya existe → reporta su UUID.
    4. Si no existe → lo crea (email_confirm=True, sin verificación de correo).
    5. Imprime el UUID para que lo agregues como FINANZAS_USER_ID en el .env.
"""

import argparse
import os
import secrets
import string
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(dotenv_path=Path(__file__).resolve().parent.parent.parent / ".env")

# Placeholders de la plantilla — si el .env los tiene, no se configuró de verdad
_PLACEHOLDERS = {
    "https://xxxx.supabase.co", "eyj...", "eyJ...", "sb_secret_...",
    "<el-uuid>", "<uuid>", "", "tu@correo.com",
}


def _es_placeholder(valor: str) -> bool:
    if valor is None:
        return True
    v = valor.strip().lower()
    return v in _PLACEHOLDERS or v.endswith("...") or v.startswith("<")


def _validar_env() -> tuple[str, str]:
    """Valida el .env sin imprimir secretos. Retorna (url, key) o aborta."""
    url = os.getenv("SUPABASE_FINANZAS_URL", "")
    key = (
        os.getenv("SUPABASE_FINANZAS_SERVICE_ROLE_KEY")
        or os.getenv("SUPABASE_FINANZAS_KEY", "")
    )

    problemas = []
    if _es_placeholder(url):
        problemas.append("SUPABASE_FINANZAS_URL falta o es un placeholder")
    elif not url.startswith("https://") or ".supabase.co" not in url:
        problemas.append("SUPABASE_FINANZAS_URL no parece una URL de Supabase válida")

    if _es_placeholder(key):
        problemas.append("SUPABASE_FINANZAS_SERVICE_ROLE_KEY falta o es un placeholder")
    elif len(key) < 30:
        problemas.append("SUPABASE_FINANZAS_SERVICE_ROLE_KEY parece demasiado corta")

    if problemas:
        print("✗ Problemas en el .env:")
        for p in problemas:
            print(f"    - {p}")
        print("\n  Edita el .env de la raíz del repo y vuelve a correr.")
        sys.exit(1)

    print("  ✓ .env: SUPABASE_FINANZAS_URL presente y con formato válido")
    print("  ✓ .env: SUPABASE_FINANZAS_SERVICE_ROLE_KEY presente")
    return url, key


def _conectar(url: str, key: str):
    from supabase import create_client
    try:
        client = create_client(url, key)
        # Llamada liviana para verificar que la key funciona (lista 1 usuario)
        client.auth.admin.list_users()
        print("  ✓ Conexión a Supabase OK — la Secret key funciona")
        return client
    except Exception as e:
        print(f"✗ No se pudo conectar a Supabase: {e}")
        print("  Revisa que la Secret key sea correcta (Settings → API → Secret key)")
        sys.exit(1)


def _buscar_usuario(client, email: str):
    """Retorna el user object si el email ya existe, si no None."""
    try:
        resp = client.auth.admin.list_users()
        usuarios = resp if isinstance(resp, list) else getattr(resp, "users", []) or resp
        for u in usuarios:
            u_email = getattr(u, "email", None) or (u.get("email") if isinstance(u, dict) else None)
            if u_email and u_email.lower() == email.lower():
                return u
    except Exception:
        pass
    return None


def _uid_de(user) -> str:
    return getattr(user, "id", None) or (user.get("id") if isinstance(user, dict) else None)


def _password_seguro(n: int = 16) -> str:
    alf = string.ascii_letters + string.digits
    return "".join(secrets.choice(alf) for _ in range(n))


def main():
    ap = argparse.ArgumentParser(description="Crea o localiza un usuario en Supabase Auth")
    ap.add_argument("--email", help="Email del usuario familiar")
    ap.add_argument("--password", help="Contraseña (si se omite, se genera una segura)")
    ap.add_argument("--check", action="store_true",
                    help="Solo valida el .env y la conexión, sin crear usuario")
    args = ap.parse_args()

    print("── Validando configuración ──────────────────────────────")
    url, key = _validar_env()
    client = _conectar(url, key)

    if args.check:
        print("\n  --check OK. El .env y la conexión están listos.")
        return

    if not args.email:
        print("\n✗ Falta --email. Ej: py crear_usuario.py --email tu@correo.com")
        sys.exit(1)

    print("\n── Usuario ──────────────────────────────────────────────")
    existente = _buscar_usuario(client, args.email)
    if existente:
        uid = _uid_de(existente)
        print(f"  El usuario {args.email} YA existe.")
        print(f"  UUID: {uid}")
        print("\n  Agrega esta línea al .env de la raíz:")
        print(f"    FINANZAS_USER_ID={uid}")
        return

    password = args.password or _password_seguro()
    try:
        resp = client.auth.admin.create_user({
            "email": args.email,
            "password": password,
            "email_confirm": True,   # sin verificación de correo
        })
        user = getattr(resp, "user", None) or resp
        uid = _uid_de(user)
    except Exception as e:
        print(f"✗ No se pudo crear el usuario: {e}")
        sys.exit(1)

    print(f"  ✓ Usuario creado: {args.email}")
    print(f"  UUID: {uid}")
    if not args.password:
        print(f"  Contraseña generada: {password}")
        print("  ⚠ Guárdala — la necesitarás para el login (Sprint 5 paso 3).")

    print("\n── Siguiente paso ───────────────────────────────────────")
    print("  Agrega esta línea al .env de la raíz:")
    print(f"    FINANZAS_USER_ID={uid}")
    print("\n  Luego corre la migración:")
    print(f"    py finanzas_personales/db/migrar_excel_a_supabase.py --user-id {uid}")


if __name__ == "__main__":
    main()
