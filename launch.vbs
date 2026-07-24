' One-click launcher for the PC Health Dashboard — double-click to start
' the server with no visible console window. Safe to double-click
' repeatedly: it always tries to start the server, but src/main.py's own
' single-instance mutex + port-bind check (not duplicated here) makes a
' redundant launch a fast no-op instead of starting a second server.
'
' Opening the browser is deliberately NOT this script's job (it used to
' be, via its own shell.Run of the URL after a fixed delay) — main.py
' already opens the browser itself in both the fresh-start and
' already-running cases, once it actually knows which one just happened.
' Doing it here too meant an already-running dashboard got a *second*
' browser tab opened on top of main.py's own — one from each script. Let
' main.py own that decision entirely; this script's only job is to start
' the process.

Option Explicit

Dim shell, fso, projectDir

Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
projectDir = fso.GetParentFolderName(WScript.ScriptFullName)
shell.CurrentDirectory = projectDir

' pythonw.exe (the windowless counterpart to python.exe) so no console
' flashes up; window style 0 = hidden. "False" (don't wait) since this is
' the actual long-running server process when a new instance starts.
shell.Run "pythonw -m src.main", 0, False
