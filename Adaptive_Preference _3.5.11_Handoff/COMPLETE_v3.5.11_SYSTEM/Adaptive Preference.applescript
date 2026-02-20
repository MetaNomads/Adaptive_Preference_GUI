on run
    -- Change this if your folder name/path is different
    set projectFolderName to "COMPLETE_v3.5.11_SYSTEM"

    tell application "Finder"
        set appPath to (path to me) as text
        set appFolder to container of (appPath as alias) as alias
        set projectFolder to (appFolder as text) & projectFolderName & ":" as alias
    end tell

    set cmdFile to (projectFolder as text) & "Start_Adaptive_Preference_Mac.command"

    -- Run in Terminal so you can see logs if something fails
    tell application "Terminal"
        activate
        do script "cd " & quoted form of POSIX path of projectFolder & " && bash " & quoted form of POSIX path of (cmdFile as alias)
    end tell
end run