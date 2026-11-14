' X-Stage Karaoke GUI launcher. Does not start cmd.exe or powershell.exe.
Option Explicit
Dim fs, shell, root, exe, data, command
Set fs = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")
root = fs.GetParentFolderName(WScript.ScriptFullName)
exe = root & "\App\XStageKaraoke.exe"
If Not fs.FileExists(exe) Then exe = root & "\XStageKaraoke.exe"
If Not fs.FileExists(exe) Then
  MsgBox "XStageKaraoke.exe not found. Build or install the Windows application first.", vbCritical, "X-Stage Karaoke"
  WScript.Quit 2
End If
command = Chr(34) & exe & Chr(34)
data = root & "\Data"
If fs.FolderExists(data) Then command = command & " --data-dir " & Chr(34) & data & Chr(34)
' The EXE is built in --windowed mode; no console is created by this launcher.
shell.Run command, 1, False
