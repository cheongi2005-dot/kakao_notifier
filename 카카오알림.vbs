Set ws  = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
dir = fso.GetParentFolderName(WScript.ScriptFullName)
ws.Run "powershell -WindowStyle Hidden -NonInteractive -ExecutionPolicy Bypass -File """ & dir & "\run.ps1""", 0, False
