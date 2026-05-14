' Lanzador Finanzas Personales — siempre relanza con código fresco
' El proceso Streamlit corre oculto en segundo plano.
' Cada doble-click: mata la instancia previa y arranca una nueva.
' Esto garantiza que los cambios en .py se reflejen sin tener que matar manualmente.

Dim WshShell, puerto, url
puerto = 8501
url    = "http://localhost:" & puerto
Set WshShell = CreateObject("WScript.Shell")

' ── Matar cualquier instancia previa escuchando en el puerto ────────────────
' netstat -ano lista PIDs; findstr LISTENING filtra solo el proceso servidor.
' tokens=5 extrae el PID; taskkill /F lo termina.
Dim cmdKill
cmdKill = "cmd /c for /f ""tokens=5"" %a in ('netstat -ano ^| findstr :" & puerto & " ^| findstr LISTENING') do taskkill /F /PID %a >nul 2>&1"
WshShell.Run cmdKill, 0, True   ' 0 = oculto, True = esperar a que termine

' Esperar a que el puerto quede libre (Windows tarda en liberar sockets TIME_WAIT)
WScript.Sleep 2000

' ── Lanzar instancia fresca ─────────────────────────────────────────────────
WshShell.CurrentDirectory = "C:\ClaudeWork"

Dim cmd
cmd = "py -m streamlit run " & _
      "C:\ClaudeWork\finanzas_personales\app\main.py " & _
      "--server.port " & puerto & " " & _
      "--server.headless true " & _
      "--browser.gatherUsageStats false " & _
      "--server.fileWatcherType none"

WshShell.Run cmd, 0, False   ' 0 = oculto, False = no esperar

' Esperar a que Streamlit arranque
WScript.Sleep 7000

' Abrir navegador
WshShell.Run url, 1, False

Set WshShell = Nothing
