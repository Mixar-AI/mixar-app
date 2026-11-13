# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Windows Update Helper — PowerShell Steps

The PowerShell one-liners the helper batch script (:mod:`win_installer`)
runs. Each is embedded in ``-Command "..."``, so none may contain a double
quote, a percent sign or a line break (pinned by the helper tests); paths
reach them through environment variables the script sets.
"""

_PS_INSTALL = (
    "$q=[char]34;"
    "$a=@('/i',($q+$env:MSI+$q),'/passive','/norestart','REBOOT=ReallySuppress',"
    "'LAUNCHAPP=0','/l*v',($q+$env:MSILOG+$q));"
    "try{"
    "$p=Start-Process -FilePath ($env:SYS32+'\\msiexec.exe') -ArgumentList $a "
    "-Verb RunAs -Wait -PassThru -ErrorAction Stop;"
    # A launch failure must never become `exit $null` (success). Preserve
    # msiexec's actual status, including success-with-reboot (3010).
    "if($null -eq $p -or $null -eq $p.ExitCode){exit 1};"
    "exit $p.ExitCode"
    "}catch{"
    # PowerShell can wrap the Win32 exception; normalise UAC cancellation
    # to MSI's existing user-cancelled result so the next-start toast agrees.
    "$e=$_.Exception;"
    "while($e -and -not ($e -is [System.ComponentModel.Win32Exception]))"
    "{$e=$e.InnerException};"
    "if($e -and $e.NativeErrorCode -eq 1223){exit 1602};"
    "[Console]::Error.WriteLine($_.Exception.Message);exit 1"
    "}"
)

# Valid AND, when the app verified one, signed by exactly that certificate
# (-ne compares case-insensitively). An empty %SIGNER% keeps Valid-only.
_PS_VERIFY = (
    "$s=Get-AuthenticodeSignature -LiteralPath $env:MSI;"
    "if($s.Status -ne 'Valid'){exit 1};"
    "if($env:SIGNER -and $s.SignerCertificate.Thumbprint -ne $env:SIGNER){exit 1};"
    "exit 0"
)

# Exit 3 when any process runs a binary from the install directory, writing
# their basenames (never paths) to %LOCKS% as a ready-made result line.
# Anything else (no CIM, an error) is 0/1 and the install goes ahead, as it
# did before this check existed.
_PS_LOCKS = (
    "try{"
    "$d=$env:INSTALLDIR.TrimEnd('\\')+'\\';"
    "$n=@(Get-CimInstance -ClassName Win32_Process -ErrorAction Stop|"
    "Where-Object {$_.ExecutablePath -and "
    "$_.ExecutablePath.StartsWith($d,[StringComparison]::OrdinalIgnoreCase)}|"
    "ForEach-Object {$_.Name -replace '[^A-Za-z0-9._-]',''}|Sort-Object -Unique);"
    "if($n.Count -gt 0){"
    "Set-Content -LiteralPath $env:LOCKS -Value ('locks='+($n -join ',')) -Encoding ASCII;"
    "Write-Output ('Still running from the install directory: '+($n -join ', '));exit 3};"
    "exit 0"
    "}catch{[Console]::Error.WriteLine($_.Exception.Message);exit 1}"
)

# End every python running from the install directory that is NOT Mixar's
# own background work (one with a Mixar binary among its live ancestors):
# that is a Mixar connector an AI app respawned since the app's own check.
# Each end (or failure to) is one log line with basename and pid, never a
# path. The exit code is informational; the lock wait follows regardless.
_PS_END_CONNECTORS = (
    "try{"
    "$d=$env:INSTALLDIR.TrimEnd('\\')+'\\';"
    "$all=@(Get-CimInstance -ClassName Win32_Process -ErrorAction Stop);"
    "$by=@{};foreach($p in $all){$by[[int]$p.ProcessId]=$p};"
    "$mixar=@('mixar.exe','mixar-launcher.exe','blender.exe','blender-launcher.exe');"
    "foreach($p in $all){"
    "if(-not $p.ExecutablePath -or "
    "-not $p.ExecutablePath.StartsWith($d,[StringComparison]::OrdinalIgnoreCase)){continue};"
    "if($p.Name -notlike 'python*'){continue};"
    "$own=$false;$c=$p;$seen=@{};"
    "while($c -and -not $seen.ContainsKey([int]$c.ProcessId)){"
    "$seen[[int]$c.ProcessId]=$true;"
    "$q=$by[[int]$c.ParentProcessId];"
    # A parent younger than its child is a reused PID, not an ancestor.
    "if(-not $q -or ($q.CreationDate -and $c.CreationDate -and "
    "$q.CreationDate -gt $c.CreationDate)){break};"
    "if($mixar -contains $q.Name.ToLower()){$own=$true;break};"
    "$c=$q};"
    "if($own){continue};"
    "try{Stop-Process -Id $p.ProcessId -Force -ErrorAction Stop;"
    "Write-Output ('Ended Mixar connector '+$p.Name+' (pid '+$p.ProcessId+')')}"
    "catch{Write-Output ('Could not end Mixar connector '+$p.Name+' (pid '+$p.ProcessId+'): '"
    "+$_.Exception.Message)}};"
    "exit 0"
    "}catch{[Console]::Error.WriteLine($_.Exception.Message);exit 1}"
)

# After the installer (or instead of it): record what Windows Installer now
# says is installed and where, the MSI's first error code, and relaunch —
# the registered InstallLocation first, so the copy that comes back is the
# one the MSI upgraded. Exit 0 only once something was started; the batch
# falls back to its own candidate list otherwise.
_PS_FINISH = (
    "$o=@();$e=$null;"
    "try{"
    "$k=@(Get-ItemProperty -Path "
    "'HKLM:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\*',"
    "'HKLM:\\SOFTWARE\\WOW6432Node\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\*',"
    "'HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\*' "
    "-ErrorAction SilentlyContinue|"
    "Where-Object {$_.DisplayName -eq 'Mixar' -and $_.WindowsInstaller -eq 1});"
    "$e=@($k|Where-Object {$_.DisplayVersion -eq $env:VERSION})+$k|Select-Object -First 1"
    "}catch{};"
    "$loc='';"
    "if($e){$loc=[string]$e.InstallLocation;$o+=('installed_version='+$e.DisplayVersion)};"
    "$o+=('install_location='+$loc);"
    "if($env:STAGE -eq 'install' -and $env:INSTALL_EXIT -notin '0','3010' -and "
    "(Test-Path -LiteralPath $env:MSILOG)){"
    "$m=Select-String -LiteralPath $env:MSILOG -Pattern 'Error (\\d{4})\\.'|Select-Object -First 1;"
    "if($m){$o+=('msi_error='+$m.Matches[0].Groups[1].Value)}};"
    # Installed on quit (RELAUNCHMODE 0): Mixar stays closed unless a launch
    # was turned away meanwhile; one that read the marker just before it
    # went gets a moment to leave its PID. Turned-away launches are waited
    # for (bounded) so the relaunch does not race their exit. Exit 4 = stay closed.
    # An unset REOPEN (no list) is never handed to -LiteralPath, which
    # refuses an empty value with an error instead of answering "no file".
    "$go=$env:RELAUNCHMODE -eq '1';"
    "if(-not $go){Start-Sleep -Seconds ([int]$env:REOPENGRACE)};"
    "$q=$env:REOPEN;$r=@();if($q -and (Test-Path -LiteralPath $q)){"
    "$r=@(Get-Content -LiteralPath $q -ErrorAction SilentlyContinue|"
    "Where-Object {$_ -match '^[0-9]+$'})};"
    "if($r.Count -gt 0){$go=$true};"
    "if(-not $go){$o+='relaunch_kind=skipped';"
    "if($q){Remove-Item -LiteralPath $q -ErrorAction SilentlyContinue};"
    "Add-Content -LiteralPath $env:RESULT -Value $o -Encoding UTF8;exit 4};"
    "$t=(Get-Date).AddSeconds([int]$env:REOPENWAIT);"
    "foreach($i in $r){$w=[int][Math]::Ceiling(($t-(Get-Date)).TotalSeconds);"
    "if($w -gt 0){Wait-Process -Id ([int]$i) -Timeout $w -ErrorAction SilentlyContinue}};"
    "if($q){Remove-Item -LiteralPath $q -ErrorAction SilentlyContinue};"
    "$c=@();"
    "if($loc){foreach($x in 'mixar-launcher.exe','mixar.exe','blender-launcher.exe')"
    "{$c+=,@((Join-Path $loc $x),'registry')}};"
    "foreach($x in ($env:RELAUNCH -split '\\|')){if($x){$c+=,@($x,'candidate')}};"
    "$rc=1;"
    "foreach($p in $c){if(Test-Path -LiteralPath $p[0] -PathType Leaf){"
    "try{Start-Process -FilePath $p[0] -ErrorAction Stop;"
    "$o+=('relaunch='+$p[0]);$o+=('relaunch_kind='+$p[1]);$rc=0;break}catch{}}};"
    "if($rc -ne 0){$o+='relaunch_kind=none'};"
    "Add-Content -LiteralPath $env:RESULT -Value $o -Encoding UTF8;"
    "exit $rc"
)
