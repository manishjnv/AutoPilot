# Autopilot installer for Windows (PowerShell 5.1 or 7). Options: -DryRun, -SkipLogin.
# Env: AUTOPILOT_REF (git tag/branch to install), AUTOPILOT_DRY_RUN=1, AUTOPILOT_SKIP_LOGIN=1.
# Safe to run twice. Needs administrator rights only if winget installs Git. Edits no profile or PATH setting.
param([switch]$DryRun, [switch]$SkipLogin)
$ErrorActionPreference = 'Stop'
try { [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12 } catch { }

# ponytail: set this to the release tag when the first tag is made
$DefaultRef = 'main'

if ($env:AUTOPILOT_DRY_RUN -eq '1') { $DryRun = $true }
if ($env:AUTOPILOT_SKIP_LOGIN -eq '1') { $SkipLogin = $true }
$Ref = if ($env:AUTOPILOT_REF) { $env:AUTOPILOT_REF } else { $DefaultRef }
if ($Ref -notmatch '^[A-Za-z0-9][A-Za-z0-9._/-]{0,99}\z' -or $Ref -match '\.\.') {
    throw 'AUTOPILOT_REF must start with a letter or a digit, and may use only A-Z a-z 0-9 . _ / - (no "..", 100 characters at most).'
}

function Step($n, $name) { Write-Host "==> Step $n of 5: $name" }
function Fail($n, $cmd) { Write-Host "FAILED: step $n. Run this by hand: $cmd"; throw "Step $n failed." }
function Has($name) { [bool](Get-Command $name -ErrorAction SilentlyContinue) }
# Run a native program; its error text must not stop the script (Windows PowerShell 5.1). No named parameter:
# an argument such as -e would bind to it.
function Run {
    $ErrorActionPreference = 'Continue'
    $rest = @($args | Select-Object -Skip 1)   # an array also for one argument: a string would splat as characters
    & $args[0] @rest 2>&1
}
function Ver($name) { "$(Run $name --version | Select-Object -First 1)" }
# Show programs that an installer just added, to this script only. Built from the same parts each time: no growth.
$Path0 = $env:PATH
function Refresh {
    $parts = @($Path0 -split ';') +
        ([Environment]::GetEnvironmentVariable('Path', 'Machine') -split ';') +
        ([Environment]::GetEnvironmentVariable('Path', 'User') -split ';') + "$env:USERPROFILE\.local\bin"
    $env:PATH = ($parts | Where-Object { $_ } | Select-Object -Unique) -join ';'
}

# The official installer runs in its own PowerShell process: its settings and its exit stay there.
function Ensure($n, $name, $exe, $url) {
    Step $n $name
    $cmd = "powershell -NoProfile -ExecutionPolicy Bypass -Command `"irm $url | iex`""
    if (Has $exe) { Write-Host "found: $(Ver $exe)"; return }
    if ($DryRun) { Write-Host "would install. Command: $cmd"; return }
    Write-Host "run: $cmd"
    Run powershell -NoProfile -ExecutionPolicy Bypass -Command "irm $url | iex" | Out-Host
    if ($LASTEXITCODE -ne 0) { Fail $n $cmd }
    Refresh
    if (-not (Has $exe)) { Fail $n $cmd }
}

Refresh
Step 1 'git'
if (Has git) {
    Write-Host "found: $(Ver git)"
} else {
    $cmd = 'winget install --id Git.Git -e --source winget'
    Write-Host 'winget installs Git. Windows can ask for administrator rights.'
    if ($DryRun) { Write-Host "would install. Command: $cmd" }
    elseif (-not (Has winget)) { Fail 1 'install Git from https://git-scm.com/download/win, then run this script again' }
    else {
        Write-Host "run: $cmd"
        Run winget install --id Git.Git -e --source winget | Out-Host
        if ($LASTEXITCODE -ne 0) { Fail 1 $cmd }
        Refresh
        if (-not (Has git)) { Fail 1 "$cmd (then open a new terminal and run this script again)" }
    }
}

Ensure 2 'uv' 'uv' 'https://astral.sh/uv/install.ps1'
Ensure 3 'Claude Code' 'claude' 'https://claude.ai/install.ps1'

Step 4 'Autopilot'
$addr = "git+https://github.com/manishjnv/AutoPilot@$Ref"
if ((Has autopilot) -or ((Has uv) -and ("$(Run uv tool list)" -match 'dev-autopilot'))) {
    $v = if (Has autopilot) { Ver autopilot } else { 'dev-autopilot' }
    Write-Host "found: $v"
    Write-Host "To update, run: uv tool install --reinstall `"$addr`""
} elseif ($DryRun) {
    Write-Host "would install. Command: uv tool install `"$addr`""
} else {
    Write-Host "run: uv tool install `"$addr`""
    Run uv tool install $addr | Out-Host
    if ($LASTEXITCODE -ne 0) { Fail 4 "uv tool install `"$addr`"" }
    Refresh
    if (-not (Has autopilot)) { Fail 4 "uv tool install `"$addr`"" }
}

Step 5 'login check'
if ($SkipLogin) { Write-Host 'skipped (-SkipLogin)' }
elseif ($DryRun) { Write-Host 'would run: claude auth status' }
else {
    $null = Run claude auth status
    if ($LASTEXITCODE -eq 0) { Write-Host 'Claude Code is logged in.' }
    else {
        Write-Host 'Claude Code is not logged in. Run: claude auth login'
        Write-Host 'You need a paid Claude plan or an API key. This script does not log in for you.'
    }
}

if (-not $DryRun) { Write-Host "Installed: $(Ver autopilot)" }
Write-Host 'Done. Open a NEW terminal, then run: autopilot'
Write-Host 'To uninstall, run: uv tool uninstall dev-autopilot'
$global:LASTEXITCODE = 0   # keep a native exit code from an earlier step out of the CI result
