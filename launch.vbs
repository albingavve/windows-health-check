' One-click launcher for the PC Health Dashboard — double-click to start
' the server with no visible console window, then open it in the default
' browser. Safe to double-click repeatedly: it always tries to start the
' server, but src/main.py's own single-instance mutex + port-bind check
' (not duplicated here) makes a redundant launch a fast no-op that just
' points back at the already-running instance instead of starting a
' second server.

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

' Give the server a moment to actually bind its port before pointing a
' browser at it. Harmless when it was already running — the page just
' loads immediately either way.
WScript.Sleep 2500

shell.Run "http://127.0.0.1:8000", 1, False
