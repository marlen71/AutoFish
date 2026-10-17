' ==========================================================================
'  Eternal FishMod - silent launch, no console window (double-click this file).
'
'  KEEP THIS FILE PURE ASCII WITH CRLF LINE ENDINGS: wscript.exe reads .vbs as
'  ANSI (on Russian Windows that is codepage 1251), so UTF-8 Cyrillic comments
'  become mojibake and can break parsing. Translated, human-readable output is
'  produced by launch.py; this file only starts it.
' ==========================================================================
Option Explicit

Dim sh, fso, folder, line

Set sh  = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

' the folder of this .vbs, so launch.py finds templates/, logs and the config there
folder = fso.GetParentFolderName(WScript.ScriptFullName)
sh.CurrentDirectory = folder

' pythonw = Python without a console, so no black window flashes on screen.
'   --yes          : install missing libraries without asking (nobody to ask)
'   --no-admin-ask : do not raise a UAC prompt; use start_admin.bat when the
'                    game itself runs as administrator
line = "pythonw " & Chr(34) & folder & "\launch.py" & Chr(34) & " --yes --no-admin-ask"

On Error Resume Next
sh.Run line, 0, False            ' 0 = hidden window, False = do not wait
If Err.Number <> 0 Then
    Err.Clear
    ' fall back to the official Windows launcher: pythonw may be missing
    line = "py -3w " & Chr(34) & folder & "\launch.py" & Chr(34) & " --yes --no-admin-ask"
    sh.Run line, 0, False
    If Err.Number <> 0 Then
        MsgBox "Eternal FishMod was not started: no Python launcher found." & vbCrLf & _
               "Tried: pythonw, then py -3w." & vbCrLf & vbCrLf & _
               "Details: " & Err.Description & vbCrLf & vbCrLf & _
               "Install Python from https://www.python.org/downloads/ and tick " & _
               Chr(34) & "Add Python to PATH" & Chr(34) & ", or run start.bat to see " & _
               "every message in a console window.", vbExclamation, "Eternal FishMod"
    End If
End If

Set sh  = Nothing
Set fso = Nothing
