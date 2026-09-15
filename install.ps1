<#
.SYNOPSIS
  Install or update qBittorrent Cleaner on this Windows machine.

.DESCRIPTION
  Copies program files to the production folder, installs Python deps,
  and (re)starts the Windows service. Never overwrites rules.yaml, logs,
  or schedule_state.json. If rules.yaml has no schedule: block yet, one
  is inserted without rewriting the rest of the file.

.PARAMETER Action
  install   First-time setup (copy files, pip, install + start service).
  update    Default. Stop service/web, copy new code, pip, restart.
  restart   Bounce the Windows service (and web if it was running).
  status    Show service, web, Python, and schedule info.
  uninstall Stop and remove the Windows service (files are kept).

.PARAMETER Source
  Folder that contains the new code. Defaults to this script's directory.

.PARAMETER Dest
  Production install folder. Default: C:\qBittorrent Cleaner if that
  already has service.py, otherwise this script's directory (in-place).

.PARAMETER Python
  python.exe to use for pip and the service. Auto-detected if omitted.

.EXAMPLE
  # From cmd or Explorer (avoids execution-policy errors)
  install.cmd update

.EXAMPLE
  powershell.exe -ExecutionPolicy Bypass -File .\install.ps1 update

.EXAMPLE
  .\install.ps1 update -Python 'C:\Python314\python.exe'
#>
#Requires -Version 5.1
[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [ValidateSet('install', 'update', 'restart', 'status', 'uninstall')]
    [string]$Action = 'update',

    [string]$Source = '',
    [string]$Dest = '',
    [string]$Python,
    [switch]$StartWeb,
    [switch]$RegisterTrayTask,
    [switch]$Purge,
    [switch]$DryRun
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$ServiceName = 'QBCleanerService'
$TrayTaskName = 'QBCleanerTray'
$CodeFiles = @(
    'cleaner.py',
    'qb_api.py',
    'schedule.py',
    'service.py',
    'tray.py',
    'web.py',
    'requirements.txt',
    'QBCleanerTray.xml',
    'readme.md',
    'install.ps1',
    'install.cmd',
    'update.cmd'
)
function Write-Step($message) { Write-Host ">> $message" -ForegroundColor Cyan }
function Write-Ok($message)   { Write-Host "   OK  $message" -ForegroundColor Green }
function Write-Warn($message) { Write-Host "   !!  $message" -ForegroundColor Yellow }
function Write-Info($message) { Write-Host "   --  $message" }

function Test-IsAdmin {
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    $p = New-Object Security.Principal.WindowsPrincipal($id)
    return $p.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Get-Pythonw([string]$pythonExe) {
    $dir = Split-Path -Parent $pythonExe
    $fallback = Join-Path $dir 'pythonw.exe'
    if (Test-Path -LiteralPath $fallback) { return $fallback }
    return $pythonExe
}

function Resolve-PythonPath([string]$explicit, [string]$dest, [string]$source) {
    $candidates = @()
    if ($explicit) { $candidates += $explicit }
    # Prefer a venv inside the install folder. Do not fall back to a *source*
    # venv when copying to a different dest - that would register the wrong
    # interpreter as the Windows service.
    $candidates += (Join-Path $dest '.venv\Scripts\python.exe')
    $candidates += @(
        "$env:LOCALAPPDATA\Programs\Python\Python314\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python313\python.exe",
        'C:\Python314\python.exe',
        'C:\Python313\python.exe'
    )
    $cmd = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($cmd) { $candidates += $cmd.Source }

    foreach ($c in $candidates) {
        if ($c -and (Test-Path -LiteralPath $c)) {
            return (Resolve-Path -LiteralPath $c).Path
        }
    }
    throw "Python not found. Pass -Python with the full path to python.exe"
}

function Get-WebPort([string]$rulesPath) {
    if (-not (Test-Path -LiteralPath $rulesPath)) { return 8081 }
    $text = Get-Content -LiteralPath $rulesPath -Raw -ErrorAction SilentlyContinue
    if ($text -match '(?m)^\s*port\s*:\s*(\d+)') { return [int]$Matches[1] }
    return 8081
}

function Test-PortOpen([int]$port) {
    try {
        $client = New-Object System.Net.Sockets.TcpClient
        $iar = $client.BeginConnect('127.0.0.1', $port, $null, $null)
        $ok = $iar.AsyncWaitHandle.WaitOne(800, $false)
        if (-not $ok) { $client.Close(); return $false }
        $client.EndConnect($iar)
        $client.Close()
        return $true
    } catch {
        return $false
    }
}

function Get-PythonProcessesMatching([string]$pattern) {
    @(Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -and ($_.CommandLine -match $pattern) })
}

function Stop-CleanerWeb([string]$dest) {
    $escaped = [regex]::Escape($dest.TrimEnd('\') )
    $procs = Get-PythonProcessesMatching 'web\.py'
    $stopped = 0
    foreach ($p in $procs) {
        $line = $p.CommandLine
        if ($line -notmatch $escaped -and $line -notmatch 'web\.py') { continue }
        Write-Info "Stopping web.py PID $($p.ProcessId)"
        if (-not $DryRun) {
            Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue
        }
        $stopped++
    }
    if ($stopped -eq 0) { Write-Info "No web.py process found" }
    return $stopped -gt 0
}

function Start-CleanerWeb([string]$pythonExe, [string]$dest) {
    $pythonw = Get-Pythonw $pythonExe
    Write-Info "Starting web.py with $pythonw"
    if ($DryRun) { return }
    Start-Process -FilePath $pythonw -ArgumentList 'web.py' -WorkingDirectory $dest -WindowStyle Hidden
    Start-Sleep -Seconds 2
}

function Get-ServiceCim {
    Get-CimInstance Win32_Service -Filter "Name='$ServiceName'" -ErrorAction SilentlyContinue
}

function Stop-CleanerService {
    $svc = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
    if (-not $svc) {
        Write-Info "Service $ServiceName is not installed"
        return
    }
    if ($svc.Status -eq 'Stopped') {
        Write-Info "Service already stopped"
        return
    }
    Write-Info "Stopping $ServiceName"
    if ($DryRun) { return }
    Stop-Service -Name $ServiceName -Force -ErrorAction SilentlyContinue
    try {
        $svc.WaitForStatus('Stopped', [TimeSpan]::FromSeconds(25))
        Write-Ok "Service stopped"
    } catch {
        Write-Warn "Service did not stop in time: $($_.Exception.Message)"
    }
}

function Start-CleanerService([string]$pythonExe, [string]$dest) {
    $svc = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
    if (-not $svc) {
        Write-Step "Installing Windows service"
        if (-not $DryRun) {
            Push-Location $dest
            try {
                & $pythonExe 'service.py' 'install'
                if ($LASTEXITCODE -and $LASTEXITCODE -ne 0) {
                    throw "service.py install exited $LASTEXITCODE"
                }
            } finally {
                Pop-Location
            }
        }
        $svc = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
    } else {
        Write-Info "Refreshing service registration"
        if (-not $DryRun) {
            Push-Location $dest
            try {
                & $pythonExe 'service.py' 'update' 2>$null
            } catch {
                Write-Warn "service.py update skipped: $($_.Exception.Message)"
            } finally {
                Pop-Location
            }
        }
    }

    Write-Info "Starting $ServiceName"
    if ($DryRun) { return }
    Start-Service -Name $ServiceName
    $svc = Get-Service -Name $ServiceName
    $svc.WaitForStatus('Running', [TimeSpan]::FromSeconds(20))
    Write-Ok "Service $($svc.Status)"
}

function Backup-Production([string]$dest) {
    $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
    $backup = Join-Path $dest ".backup\$stamp"
    Write-Step "Backing up current files to $backup"
    if ($DryRun) { return $backup }
    New-Item -ItemType Directory -Path $backup -Force | Out-Null
    foreach ($name in $CodeFiles) {
        $from = Join-Path $dest $name
        if (Test-Path -LiteralPath $from) {
            Copy-Item -LiteralPath $from -Destination (Join-Path $backup $name) -Recurse -Force
        }
    }
    foreach ($dir in @('templates', 'static')) {
        $from = Join-Path $dest $dir
        if (Test-Path -LiteralPath $from) {
            Copy-Item -LiteralPath $from -Destination (Join-Path $backup $dir) -Recurse -Force
        }
    }
    $rules = Join-Path $dest 'rules.yaml'
    if (Test-Path -LiteralPath $rules) {
        Copy-Item -LiteralPath $rules -Destination (Join-Path $backup 'rules.yaml') -Force
    }
    Write-Ok "Backup saved"
    return $backup
}

function Copy-Code([string]$source, [string]$dest) {
    $srcRoot = (Resolve-Path -LiteralPath $source).Path
    $dstRoot = $dest
    if (Test-Path -LiteralPath $dest) {
        $dstRoot = (Resolve-Path -LiteralPath $dest).Path
    }
    if ($srcRoot.TrimEnd('\') -eq $dstRoot.TrimEnd('\')) {
        Write-Info "Source and dest are the same folder; skipping copy (in-place update)"
        return
    }

    Write-Step "Copying program files to $dest"
    if (-not $DryRun) {
        New-Item -ItemType Directory -Path $dest -Force | Out-Null
    }
    foreach ($name in $CodeFiles) {
        $from = Join-Path $source $name
        if (-not (Test-Path -LiteralPath $from)) {
            Write-Warn "Not in source (skipped): $name"
            continue
        }
        Write-Info $name
        if (-not $DryRun) {
            Copy-Item -LiteralPath $from -Destination (Join-Path $dest $name) -Force
        }
    }
    foreach ($dir in @('templates', 'static')) {
        $from = Join-Path $source $dir
        if (-not (Test-Path -LiteralPath $from)) { continue }
        Write-Info "$dir\"
        if (-not $DryRun) {
            $to = Join-Path $dest $dir
            New-Item -ItemType Directory -Path $to -Force | Out-Null
            Copy-Item -Path (Join-Path $from '*') -Destination $to -Recurse -Force
        }
    }
    if (-not $DryRun) {
        Remove-Item -LiteralPath (Join-Path $dest '__pycache__') -Recurse -Force -ErrorAction SilentlyContinue
    }
    Write-Ok "Files copied (rules.yaml, logs, and schedule_state.json left untouched)"
}

function Ensure-RulesFile([string]$source, [string]$dest) {
    $destRules = Join-Path $dest 'rules.yaml'
    if (Test-Path -LiteralPath $destRules) {
        Write-Info "Keeping existing rules.yaml"
        return
    }
    $srcRules = Join-Path $source 'rules.yaml'
    Write-Step "No rules.yaml at dest; copying the template"
    if ($DryRun) { return }
    if (-not (Test-Path -LiteralPath $srcRules)) {
        throw "rules.yaml not found in source or dest"
    }
    Copy-Item -LiteralPath $srcRules -Destination $destRules -Force
}

function Ensure-ScheduleBlock([string]$rulesPath) {
    if (-not (Test-Path -LiteralPath $rulesPath)) { return }
    $text = [IO.File]::ReadAllText($rulesPath)
    if ($text -match '(?m)^schedule\s*:') {
        Write-Info "rules.yaml already has a schedule block"
        return
    }
    Write-Step "Inserting schedule: block into rules.yaml (comments preserved)"
    $block = @"

schedule:
  enabled: true
  interval_seconds: 30  # how often the Windows service runs all rules

"@
    if ($text -match '(?m)^rules\s*:') {
        $text = [regex]::Replace($text, '(?m)^rules\s*:', ($block.TrimEnd() + "`r`n`r`nrules:"), 1)
    } else {
        $text = $text.TrimEnd() + "`r`n" + $block
    }
    if ($DryRun) { return }
    $utf8 = New-Object System.Text.UTF8Encoding $false
    [IO.File]::WriteAllText($rulesPath, $text, $utf8)
    Write-Ok "schedule block added"
}

function Install-PythonDeps([string]$pythonExe, [string]$dest) {
    $req = Join-Path $dest 'requirements.txt'
    Write-Step "Installing Python packages ($pythonExe -m pip)"
    if ($DryRun) { return }
    & $pythonExe -m pip install --upgrade pip | Out-Host
    & $pythonExe -m pip install -r $req | Out-Host
    if ($LASTEXITCODE -and $LASTEXITCODE -ne 0) {
        throw "pip install failed with exit $LASTEXITCODE"
    }
    Write-Ok "Dependencies installed"
}

function Register-TrayTaskIfRequested([string]$pythonExe, [string]$dest) {
    if (-not $RegisterTrayTask) { return }
    $pythonw = Get-Pythonw $pythonExe
    Write-Step "Registering scheduled task $TrayTaskName"
    Write-Info "Execute: $pythonw `"$dest\tray.py`""
    if ($DryRun) { return }
    $action = New-ScheduledTaskAction -Execute $pythonw -Argument "`"$dest\tray.py`"" -WorkingDirectory $dest
    $trigger = New-ScheduledTaskTrigger -AtLogOn
    $principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Highest
    $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit ([TimeSpan]::Zero)
    Register-ScheduledTask -TaskName $TrayTaskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Force | Out-Null
    Write-Ok "Scheduled task $TrayTaskName registered"
}

function Show-Status([string]$pythonExe, [string]$dest) {
    Write-Host ""
    Write-Host "qBittorrent Cleaner status" -ForegroundColor Cyan
    Write-Host "  Dest:    $dest"
    Write-Host "  Python:  $pythonExe"

    $svc = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
    if ($svc) {
        Write-Host "  Service: $($svc.Status) ($ServiceName)"
        $cim = Get-ServiceCim
        if ($cim) { Write-Host "  Path:    $($cim.PathName)" }
    } else {
        Write-Host "  Service: not installed"
    }

    $rules = Join-Path $dest 'rules.yaml'
    $port = Get-WebPort $rules
    $webUp = Test-PortOpen $port
    Write-Host "  Web:     $(if ($webUp) { "listening on $port" } else { "not listening (port $port)" })"

    if (Test-Path -LiteralPath $rules) {
        $text = Get-Content -LiteralPath $rules -Raw
        if ($text -match '(?m)^schedule\s*:') {
            $enabled = if ($text -match '(?m)^\s*enabled\s*:\s*(true|false)') { $Matches[1] } else { '?' }
            $interval = if ($text -match '(?m)^\s*interval_seconds\s*:\s*(\d+)') { $Matches[1] } else { '?' }
            Write-Host "  Schedule: enabled=$enabled  interval=${interval}s"
        } else {
            Write-Host "  Schedule: (no schedule block in rules.yaml)"
        }
    } else {
        Write-Host "  rules.yaml: missing"
    }

    $schedulePy = Join-Path $dest 'schedule.py'
    $schedPage = Join-Path $dest 'templates\schedule.html'
    Write-Host "  New scheduler files: schedule.py=$(Test-Path $schedulePy)  schedule.html=$(Test-Path $schedPage)"

    $state = Join-Path $dest 'schedule_state.json'
    if (Test-Path -LiteralPath $state) {
        Write-Host "  State:   $state"
        Get-Content -LiteralPath $state -Raw
    } else {
        Write-Host "  State:   (none yet - created after the first cleanup run)"
    }
    Write-Host ""
}

function Assert-SourceLooksValid([string]$source) {
    foreach ($required in @('service.py', 'web.py', 'cleaner.py', 'tray.py')) {
        $path = Join-Path $source $required
        if (-not (Test-Path -LiteralPath $path)) {
            throw "Source does not look like a qBittorrent Cleaner tree (missing $required): $source"
        }
    }
}

function Uninstall-Cleaner([string]$dest) {
    Stop-CleanerWeb $dest | Out-Null
    Stop-CleanerService
    $svc = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
    if ($svc) {
        Write-Step "Removing Windows service"
        if (-not $DryRun) {
            $pythonExe = Resolve-PythonPath $Python $dest $Source
            Push-Location $dest
            try { & $pythonExe 'service.py' 'remove' } finally { Pop-Location }
        }
    }
    $task = Get-ScheduledTask -TaskName $TrayTaskName -ErrorAction SilentlyContinue
    if ($task) {
        Write-Step "Unregistering $TrayTaskName"
        if (-not $DryRun) {
            Unregister-ScheduledTask -TaskName $TrayTaskName -Confirm:$false
        }
    }
    if ($Purge) {
        Write-Warn "Deleting $dest"
        if (-not $DryRun) {
            Remove-Item -LiteralPath $dest -Recurse -Force
        }
    } else {
        Write-Info "Files kept at $dest (pass -Purge to delete the folder)"
    }
}

if ([string]::IsNullOrWhiteSpace($Source)) {
    if ($PSScriptRoot) {
        $Source = $PSScriptRoot
    } else {
        $Source = Split-Path -Parent $MyInvocation.MyCommand.Path
    }
}
$Source = [IO.Path]::GetFullPath($Source)
if ([string]::IsNullOrWhiteSpace($Dest)) {
    $classic = 'C:\qBittorrent Cleaner'
    if (Test-Path -LiteralPath (Join-Path $classic 'service.py')) {
        $Dest = $classic
    } else {
        $Dest = $Source
    }
}
$Dest = [IO.Path]::GetFullPath($Dest)

function ConvertTo-CmdQuoted([string]$value) {
    if ($null -eq $value) { return '""' }
    return '"' + ($value -replace '"', '""') + '"'
}

# --- elevation (not required for status / dry-run) ---
$needsAdmin = $Action -in @('install', 'update', 'restart', 'uninstall') -and -not $DryRun
if ($needsAdmin -and -not (Test-IsAdmin)) {
    Write-Host "Re-launching elevated..." -ForegroundColor Yellow
    $scriptPath = $PSCommandPath
    if ([string]::IsNullOrWhiteSpace($scriptPath)) {
        $scriptPath = $MyInvocation.MyCommand.Path
    }
    # One string, all paths quoted. Start-Process -ArgumentList rejects empty
    # array entries, which is what happened when -Source/-Dest were still blank.
    $argLine = @(
        '-NoProfile',
        '-ExecutionPolicy Bypass',
        '-File', (ConvertTo-CmdQuoted $scriptPath),
        $Action,
        '-Source', (ConvertTo-CmdQuoted $Source),
        '-Dest', (ConvertTo-CmdQuoted $Dest)
    )
    if ($Python) { $argLine += @('-Python', (ConvertTo-CmdQuoted $Python)) }
    if ($StartWeb) { $argLine += '-StartWeb' }
    if ($RegisterTrayTask) { $argLine += '-RegisterTrayTask' }
    if ($Purge) { $argLine += '-Purge' }
    $argString = [string]::Join(' ', $argLine)
    $powershell = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
    $proc = Start-Process -FilePath $powershell -Verb RunAs -Wait -PassThru -ArgumentList $argString
    if ($null -eq $proc) { exit 1 }
    exit $proc.ExitCode
}

Write-Host ""
Write-Host "qBittorrent Cleaner $Action" -ForegroundColor Cyan
Write-Host "  Source: $Source"
Write-Host "  Dest:   $Dest"
if ($DryRun) { Write-Warn "DRY RUN - no changes will be made" }

if ($Action -ne 'uninstall') {
    Assert-SourceLooksValid $Source
}

$pythonExe = $null
if ($Action -ne 'uninstall' -or (Test-Path -LiteralPath (Join-Path $Dest 'service.py'))) {
    $pythonExe = Resolve-PythonPath $Python $Dest $Source
    Write-Host "  Python: $pythonExe"
}

switch ($Action) {
    'status' {
        Show-Status $pythonExe $Dest
    }
    'restart' {
        $port = Get-WebPort (Join-Path $Dest 'rules.yaml')
        $webWasRunning = Test-PortOpen $port
        Stop-CleanerWeb $Dest | Out-Null
        Stop-CleanerService
        Start-CleanerService $pythonExe $Dest
        if ($StartWeb -or $webWasRunning) { Start-CleanerWeb $pythonExe $Dest }
        Show-Status $pythonExe $Dest
        Write-Warn "Restart the tray app (Quit, then run it again) if you also updated tray.py"
    }
    'uninstall' {
        Uninstall-Cleaner $Dest
    }
    default {
        # install or update
        if ($Action -eq 'update' -and -not (Test-Path -LiteralPath $Dest)) {
            Write-Warn "Dest does not exist; treating this as install"
            $Action = 'install'
        }

        $port = Get-WebPort (Join-Path $Dest 'rules.yaml')
        if (-not (Test-Path -LiteralPath (Join-Path $Dest 'rules.yaml'))) {
            $port = Get-WebPort (Join-Path $Source 'rules.yaml')
        }
        $webWasRunning = Test-PortOpen $port

        if ($Action -eq 'update' -or (Get-Service -Name $ServiceName -ErrorAction SilentlyContinue)) {
            Stop-CleanerWeb $Dest | Out-Null
            Stop-CleanerService
        }

        if ($Action -eq 'update' -and (Test-Path -LiteralPath $Dest)) {
            Backup-Production $Dest | Out-Null
        }

        Copy-Code $Source $Dest
        Ensure-RulesFile $Source $Dest
        Ensure-ScheduleBlock (Join-Path $Dest 'rules.yaml')
        Install-PythonDeps $pythonExe $Dest
        Start-CleanerService $pythonExe $Dest
        Register-TrayTaskIfRequested $pythonExe $Dest

        if ($StartWeb -or $webWasRunning) {
            Start-CleanerWeb $pythonExe $Dest
        } else {
            Write-Info "Web server was not running; not starting it. Pass -StartWeb to start it."
        }

        Show-Status $pythonExe $Dest
        Write-Host "Done. Open the Scheduler page after starting the web UI." -ForegroundColor Green
        Write-Warn "Restart the tray app (Quit, then run it again) so it loads the new tray.py"
    }
}
