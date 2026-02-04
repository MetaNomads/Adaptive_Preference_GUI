Set WshShell = CreateObject("WScript.Shell")
' We use '1' at the end to make the window VISIBLE.
' This is important so the user can see if Python/Node is being installed.
WshShell.Run "Setup_Everything.bat", 1
Set WshShell = Nothing