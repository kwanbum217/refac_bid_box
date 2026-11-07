<#
.SYNOPSIS
    Reports whether the tools required to run refac_bid_box on Windows are ready.

.DESCRIPTION
    Read-only prerequisite check. This script never installs anything and never
    changes system state. It prints a status table, then prints the installation
    commands for missing items so the user can review and approve them first.

    Exit code 0: every required item is ready.
    Exit code 1: at least one required item is missing or not running.

    Port occupancy is informational only and does not change the exit code,
    because an already running stack legitimately holds those ports.
#>

[CmdletBinding()]
param()

$ErrorActionPreference = 'Continue'

$script:ready = $true
$results = New-Object System.Collections.Generic.List[object]
$pendingInstalls = New-Object System.Collections.Generic.List[string]

$installCommands = [ordered]@{
    'Git'            = 'winget install --id Git.Git -e --source winget'
    'Docker Desktop' = 'winget install --id Docker.DockerDesktop -e --source winget'
    'WSL2'           = 'wsl --install'
    'uv'             = 'winget install --id astral-sh.uv -e --source winget'
    'Python 3.13'    = 'winget install --id Python.Python.3.13 -e --source winget'
    'Node.js LTS'    = 'winget install --id OpenJS.NodeJS.LTS -e --source winget'
    'GNU Make'       = 'winget install --id GnuWin32.Make -e --source winget'
}

function Add-Result {
    param(
        [string]$Name,
        [string]$Status,
        [string]$Detail
    )
    $results.Add([pscustomobject]@{
        Item   = $Name
        Status = $Status
        Detail = $Detail
    })
}

function Add-Missing {
    param(
        [string]$Name,
        [string]$Status,
        [string]$Detail
    )
    Add-Result -Name $Name -Status $Status -Detail $Detail
    $script:ready = $false
    if ($installCommands.Keys -contains $Name) {
        $pendingInstalls.Add($Name)
    }
}

function Get-FirstLine {
    param([string]$Text)
    if ([string]::IsNullOrWhiteSpace($Text)) {
        return ''
    }
    return ($Text -split "`r?`n" | Where-Object { $_.Trim().Length -gt 0 } | Select-Object -First 1).Trim()
}

Write-Output ''
Write-Output 'refac_bid_box Windows prerequisite check (read-only, nothing is installed)'
Write-Output ''

# winget: needed only to run the install commands below.
$winget = Get-Command winget -ErrorAction SilentlyContinue
if ($winget) {
    $wingetVersion = Get-FirstLine ((& winget --version 2>$null | Out-String))
    Add-Result -Name 'winget' -Status 'OK' -Detail $wingetVersion
}
else {
    Add-Result -Name 'winget' -Status 'MISSING' -Detail 'Install App Installer from Microsoft Store'
}

# Git
$git = Get-Command git -ErrorAction SilentlyContinue
if ($git) {
    $gitVersion = Get-FirstLine ((& git --version 2>$null | Out-String))
    Add-Result -Name 'Git' -Status 'OK' -Detail $gitVersion
}
else {
    Add-Missing -Name 'Git' -Status 'MISSING' -Detail 'git command not found'
}

# Docker Desktop and Compose v2
$docker = Get-Command docker -ErrorAction SilentlyContinue
if (-not $docker) {
    Add-Missing -Name 'Docker Desktop' -Status 'MISSING' -Detail 'docker command not found'
}
else {
    $dockerVersion = Get-FirstLine ((& docker --version 2>$null | Out-String))
    $dockerOs = Get-FirstLine ((& docker info --format '{{.OSType}}' 2>$null | Out-String))
    $dockerExit = $LASTEXITCODE
    if ($dockerExit -ne 0) {
        Add-Missing -Name 'Docker Desktop' -Status 'NOT RUNNING' -Detail 'Docker Desktop is not running'
    }
    elseif ($dockerOs -ne 'linux') {
        Add-Missing -Name 'Docker Desktop' -Status 'WRONG MODE' -Detail ("OSType=" + $dockerOs + " (Linux containers required)")
    }
    else {
        Add-Result -Name 'Docker Desktop' -Status 'OK' -Detail ($dockerVersion + ' / ' + $dockerOs)
    }

    $composeVersion = Get-FirstLine ((& docker compose version 2>$null | Out-String))
    if ($LASTEXITCODE -eq 0) {
        Add-Result -Name 'Docker Compose' -Status 'OK' -Detail $composeVersion
    }
    else {
        Add-Missing -Name 'Docker Compose' -Status 'MISSING' -Detail 'docker compose plugin not found (update Docker Desktop)'
    }
}

# WSL2
$wsl = Get-Command wsl -ErrorAction SilentlyContinue
if (-not $wsl) {
    Add-Missing -Name 'WSL2' -Status 'MISSING' -Detail 'wsl command not found'
}
else {
    $null = & wsl --status 2>$null
    if ($LASTEXITCODE -eq 0) {
        Add-Result -Name 'WSL2' -Status 'OK' -Detail 'wsl --status succeeded'
    }
    else {
        Add-Missing -Name 'WSL2' -Status 'NOT READY' -Detail 'wsl --status failed; run wsl --update or install the WSL feature as administrator'
    }
}

# Hardware virtualization
try {
    $cpu = Get-CimInstance Win32_Processor -ErrorAction Stop | Select-Object -First 1
    $computer = Get-CimInstance Win32_ComputerSystem -ErrorAction Stop
    $firmware = [bool]$cpu.VirtualizationFirmwareEnabled
    $hypervisor = [bool]$computer.HypervisorPresent
    if ($firmware -or $hypervisor) {
        Add-Result -Name 'Virtualization' -Status 'OK' -Detail ("firmware=" + $firmware + " hypervisor=" + $hypervisor)
    }
    else {
        Add-Result -Name 'Virtualization' -Status 'DISABLED' -Detail 'Enable virtualization in BIOS/UEFI (human step)'
        $script:ready = $false
    }
}
catch {
    Add-Result -Name 'Virtualization' -Status 'UNKNOWN' -Detail 'Could not read Win32_Processor or Win32_ComputerSystem'
}

# uv
$uv = Get-Command uv -ErrorAction SilentlyContinue
if ($uv) {
    $uvVersion = Get-FirstLine ((& uv --version 2>$null | Out-String))
    Add-Result -Name 'uv' -Status 'OK' -Detail $uvVersion
}
else {
    Add-Missing -Name 'uv' -Status 'MISSING' -Detail 'uv command not found'
}

# Python 3.11 <= version < 3.14
$pythonFound = $false
foreach ($candidate in @('python', 'py')) {
    $command = Get-Command $candidate -ErrorAction SilentlyContinue
    if (-not $command) {
        continue
    }
    if ($candidate -eq 'py') {
        $raw = (& py -3 --version 2>&1 | Out-String)
    }
    else {
        $raw = (& python --version 2>&1 | Out-String)
    }
    $raw = Get-FirstLine $raw
    if ($raw -match '(\d+)\.(\d+)\.(\d+)') {
        $major = [int]$Matches[1]
        $minor = [int]$Matches[2]
        $pythonFound = $true
        if ($major -eq 3 -and $minor -ge 11 -and $minor -le 13) {
            Add-Result -Name 'Python 3.11-3.13' -Status 'OK' -Detail ($raw + ' (' + $candidate + ')')
        }
        else {
            Add-Missing -Name 'Python 3.13' -Status 'OUTDATED' -Detail ($raw + ' is outside requires-python >=3.11,<3.14')
        }
        break
    }
}
if (-not $pythonFound) {
    if ($uv) {
        Add-Result -Name 'Python 3.11-3.13' -Status 'OK (uv)' -Detail 'No python command; uv can download an interpreter (uv sync --python 3.13)'
    }
    else {
        Add-Missing -Name 'Python 3.13' -Status 'MISSING' -Detail 'python command not found'
    }
}

# Node.js 20 LTS or newer, plus npm
$node = Get-Command node -ErrorAction SilentlyContinue
if (-not $node) {
    Add-Missing -Name 'Node.js LTS' -Status 'MISSING' -Detail 'node command not found'
}
else {
    $nodeRaw = Get-FirstLine ((& node --version 2>$null | Out-String))
    $nodeMajor = 0
    if ($nodeRaw -match 'v(\d+)') {
        $nodeMajor = [int]$Matches[1]
    }
    if ($nodeMajor -ge 20) {
        Add-Result -Name 'Node.js LTS' -Status 'OK' -Detail $nodeRaw
    }
    else {
        Add-Missing -Name 'Node.js LTS' -Status 'OUTDATED' -Detail ($nodeRaw + ' is older than Node.js 20')
    }

    $npm = Get-Command npm -ErrorAction SilentlyContinue
    if ($npm) {
        $npmRaw = Get-FirstLine ((& npm --version 2>$null | Out-String))
        Add-Result -Name 'npm' -Status 'OK' -Detail $npmRaw
    }
    else {
        Add-Missing -Name 'Node.js LTS' -Status 'MISSING' -Detail 'npm command not found; reinstall Node.js LTS'
    }
}

# GNU Make
$make = Get-Command make -ErrorAction SilentlyContinue
if ($make) {
    $makeRaw = Get-FirstLine ((& make --version 2>$null | Out-String))
    Add-Result -Name 'GNU Make' -Status 'OK' -Detail $makeRaw
}
else {
    Add-Missing -Name 'GNU Make' -Status 'MISSING' -Detail 'make command not found; section 5 of the skill lists equivalent commands'
}

# Ports used by docker-compose.yml (informational only)
foreach ($port in @(3306, 6379, 7700, 8000)) {
    $listening = $false
    $ownerPid = $null
    if (Get-Command Get-NetTCPConnection -ErrorAction SilentlyContinue) {
        $connection = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($connection) {
            $listening = $true
            $ownerPid = $connection.OwningProcess
        }
    }
    else {
        $netstatLine = & netstat -ano 2>$null | Select-String -Pattern (":" + $port + "\s") | Select-Object -First 1
        if ($netstatLine) {
            $listening = $true
            $ownerPid = ($netstatLine.ToString().Trim() -split '\s+')[-1]
        }
    }

    if ($listening) {
        $processName = 'unknown'
        try {
            $processName = (Get-Process -Id $ownerPid -ErrorAction Stop).ProcessName
        }
        catch {
            $processName = 'unknown'
        }
        Add-Result -Name ("Port " + $port) -Status 'IN USE' -Detail ("PID " + $ownerPid + " (" + $processName + ")")
    }
    else {
        Add-Result -Name ("Port " + $port) -Status 'FREE' -Detail 'available'
    }
}

$results | Format-Table -AutoSize | Out-String -Width 240 | Write-Output

if ($pendingInstalls.Count -gt 0) {
    Write-Output 'Missing items. Review these install commands with the user before running any of them.'
    foreach ($name in $pendingInstalls) {
        Write-Output ('  ' + $name + ': ' + $installCommands[$name])
    }
    Write-Output ''
}

if ($script:ready) {
    Write-Output 'RESULT: READY'
    exit 0
}

Write-Output 'RESULT: NOT READY'
exit 1
