@echo off
:: Este script necesita ejecutarse como Administrador (clic derecho → Ejecutar como administrador)
echo Abriendo puerto 8503 para acceso local en red...
netsh advfirewall firewall add rule name="Streamlit Finanzas Personales" dir=in action=allow protocol=TCP localport=8503
echo.
echo Listo. Ahora puedes acceder desde WireGuard con:
echo   http://172.16.12.184:8503
echo.
pause
