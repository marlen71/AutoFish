' ==========================================================================
'  Eternal FishMod — ТИХИЙ запуск без окна консоли (двойной клик).
'  Каждая строка подписана.
' ==========================================================================
Option Explicit

Dim sh, fso, dir, py, cmd
Set sh  = CreateObject("WScript.Shell")          ' объект для запуска процессов
Set fso = CreateObject("Scripting.FileSystemObject")

' каталог, где лежит этот .vbs (чтобы worked-dir был правильным для launch.py)
dir = fso.GetParentFolderName(WScript.ScriptFullName)
sh.CurrentDirectory = dir

' pythonw = Python без консоли; окна лаунчера не будет вовсе.
' --yes  : ставить недостающие библиотеки без вопроса (спрашивать всё равно некого)
' --no-admin-ask : не показывать UAC-вопрос (если нужны права — запусти start_admin.bat)
py = "pythonw"   ' если pythonw нет в PATH, замени на: py -3w  (или python)
cmd = py & " """ & dir & "\launch.py"" --yes --no-admin-ask"

' 3-й аргумент 0 = скрытое окно, False = не ждать окончания процесса
sh.Run cmd, 0, False

Set sh  = Nothing
Set fso = Nothing
