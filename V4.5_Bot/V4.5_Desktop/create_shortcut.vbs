' V4.5 Intelligence - create desktop/startup shortcuts (ASCII only)
Option Explicit

Dim args, openBat, workDir, mode, ws, fso
Set args = WScript.Arguments
If args.Count < 2 Then
  WScript.Echo "USAGE: cscript create_shortcut.vbs open.bat workdir [startup]"
  WScript.Quit 1
End If

openBat = args(0)
workDir = args(1)
mode = "desktop"
If args.Count >= 3 Then mode = LCase(args(2))

Set ws = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

If Not fso.FileExists(openBat) Then
  WScript.Echo "ERROR=open.bat not found"
  WScript.Quit 1
End If

Dim linkPath, sc

If mode = "desktop" Or mode = "both" Then
  linkPath = fso.BuildPath(ws.SpecialFolders("Desktop"), "V4.5 Intelligence.lnk")
  Set sc = ws.CreateShortcut(linkPath)
  sc.TargetPath = openBat
  sc.WorkingDirectory = workDir
  sc.WindowStyle = 1
  sc.Description = "V4.5 Intelligence"
  sc.Save
  If fso.FileExists(linkPath) Then
    WScript.Echo "OK_DESKTOP=" & linkPath
  Else
    WScript.Echo "FAIL_DESKTOP"
    WScript.Quit 1
  End If
End If

If mode = "startup" Or mode = "both" Then
  linkPath = fso.BuildPath(ws.SpecialFolders("Startup"), "V4.5 Intelligence.lnk")
  Set sc = ws.CreateShortcut(linkPath)
  sc.TargetPath = openBat
  sc.WorkingDirectory = workDir
  sc.WindowStyle = 1
  sc.Description = "V4.5 Intelligence"
  sc.Save
  If fso.FileExists(linkPath) Then
    WScript.Echo "OK_STARTUP=" & linkPath
  Else
    WScript.Echo "FAIL_STARTUP"
    WScript.Quit 1
  End If
End If

WScript.Quit 0
