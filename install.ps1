# Autopilot installer for Windows (PowerShell 5.1 or 7; CMD users start install.cmd). Options: -DryRun, -SkipLogin,
# -Runner NAME, -Yes, -Rights. Env: AUTOPILOT_REF (git tag or branch), AUTOPILOT_DRY_RUN=1, AUTOPILOT_SKIP_LOGIN=1,
# AUTOPILOT_RUNNER=NAME. Four steps (pre-check, uv, Python, the package), then `ap setup` chooses and installs the one
# AI runner you pay for. N5.4: no administrator prompt on the normal path; -Rights is the one consent (N8), which
# `ap install --rights` names. Edits no profile or PATH setting. Q4: tool output goes to ~\.autopilot\install.log; the
# screen gets one sentence and one command per failure. Q5: keep this file under 220 lines; the logic is in Python.
param([switch]$DryRun, [switch]$SkipLogin, [switch]$Rights, [switch]$Yes, [string]$Runner = '')
$ErrorActionPreference = 'Stop'
try { [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12 } catch { }

# T1: a script from main installs main; the release workflow points the asset copy at its tag. MinVersion is this
# script's own version (bump.py writes it): an Autopilot below it, found or fresh from PyPI, is replaced.
$DefaultRef = 'main'
$MinVersion = '0.9.1'

if ($env:AUTOPILOT_DRY_RUN -eq '1') { $DryRun = $true }
if ($env:AUTOPILOT_SKIP_LOGIN -eq '1') { $SkipLogin = $true }
if (-not $Runner -and $env:AUTOPILOT_RUNNER) { $Runner = $env:AUTOPILOT_RUNNER }
$Ref = if ($env:AUTOPILOT_REF) { $env:AUTOPILOT_REF } else { $DefaultRef }
if ($Ref -notmatch '^[A-Za-z0-9][A-Za-z0-9._/-]{0,99}\z' -or $Ref -match '\.\.') {
    throw 'AUTOPILOT_REF must start with a letter or a digit, and may use only A-Z a-z 0-9 . _ / - (no "..", 100 characters at most).'
}
if ($Runner -and $Runner -notin @('claude', 'copilot', 'codex', 'cursor', 'kiro')) { Write-Host '-Runner must be claude, copilot, codex, cursor or kiro'; exit 2 }
$Log = Join-Path $(if ($env:AUTOPILOT_HOME) { $env:AUTOPILOT_HOME } else { Join-Path $env:USERPROFILE '.autopilot' }) 'install.log'

function Step($n, $name) { Write-Host "==> Step $n of 5: $name" }
function Has($name) { [bool](Get-Command $name -ErrorAction SilentlyContinue) }
# Run a native program; its error text must not stop the script (Windows PowerShell 5.1). No named parameter:
# an argument such as -e would bind to it.
function Run {
    $ErrorActionPreference = 'Continue'
    $rest = @($args | Select-Object -Skip 1)   # an array also for one argument: a string would splat as characters
    & $args[0] @rest 2>&1
}
function Ver($name) { "$(Run $name --version | Select-Object -First 1)" }
# One sentence for the common failures (the full catalogue lives in autopilot/install_errors.py); the rest is generic.
function Explain($text) {
    switch -Regex ($text) {
        'CRYPT_E_NO_REVOCATION_CHECK|curl: \(35\)' { return 'Windows could not check the certificate of the download server (a proxy or a security program blocks the revocation check).' }
        'Could not resolve host|No such host is known|getaddrinfo' { return 'No connection to the download server: check the network, and set HTTPS_PROXY when a proxy is in the way.' }
        'running scripts is disabled|UnauthorizedAccess' { return 'PowerShell may not run scripts on this PC: start it with the Bypass option.' }
        'Access is denied|Permission denied|EACCES' { return 'No permission to write to the install folder: install for your user only, without administrator rights.' }
        'not enough space on the disk|No space left' { return 'The disk is full: free some space, then run the step again.' }
        'Microsoft Store' { return 'Windows has only the Store shortcut for Python, not Python itself.' }
    }
    'The step did not finish. The full output is in the log.'
}
function Fail($n, $name, $cmd, $text) {
    Write-Host "FAILED  step ${n}: $name"; Write-Host "        $(Explain $text)"; Write-Host "        Run by hand: $cmd  -- details: $Log"
    throw "Step $n failed."
}
# Capture <n> <name> <command string>: runs it in a PowerShell of its own; the output goes to the log only.
function Capture($n, $name, $cmd) {
    Write-Host "run: $cmd"
    $out = Run powershell -NoProfile -ExecutionPolicy Bypass -Command $cmd | Out-String
    New-Item -ItemType Directory -Force (Split-Path $Log) | Out-Null
    Add-Content -Path $Log -Value "=== $name`: $cmd -> exit $LASTEXITCODE`n$out"
    if ($LASTEXITCODE -ne 0) { Fail $n $name $cmd $out }
}
# Show programs that an installer just added, to this script only. Built from the same parts each time: no growth.
$Path0 = $env:PATH
function Refresh {
    $parts = @($Path0 -split ';') +
        ([Environment]::GetEnvironmentVariable('Path', 'Machine') -split ';') +
        ([Environment]::GetEnvironmentVariable('Path', 'User') -split ';') + "$env:USERPROFILE\.local\bin"
    $env:PATH = ($parts | Where-Object { $_ } | Select-Object -Unique) -join ';'
}
function PyOk {
    foreach ($p in 'python3', 'python', 'py') {
        if (Has $p) { $null = Run $p -c 'import sys; sys.exit(sys.version_info < (3, 10))'; if ($LASTEXITCODE -eq 0) { return $true } }
    }
    $false
}

Refresh
# N8: the one consent. Starting this script is the consent; nothing below asks again, except the one runner question.
Write-Host 'Autopilot builds your software project while you are away. You write what you want in plain words and start it once. You get working software, tested, with a record of every step.'
Write-Host 'This script installs: uv, Python 3.12 (when missing), Autopilot. Then `ap setup` names the AI runner you pay for and installs that one CLI. Git is checked, not installed.'
if ($Rights) { Write-Host 'Rights it takes: one administrator prompt now, and the scheduled task Autopilot-Setup (highest run level) so later runs install winget packages with no prompt. Remove it later with: ap uninstall --rights' }
else { Write-Host 'Rights it takes: none. A run that needs a system tool later prints its install command; `ap install --rights` sets up the no-prompt path once.' }

Step 1 'pre-check'
if (Has git) { Write-Host "found: $(Ver git)" }
else { Write-Host 'skipped: git is missing (not needed for the package install). Get it from https://git-scm.com/download/win when a project needs it, or: winget install --id Git.Git -e --source winget --scope user' }
if ($DryRun -and $env:AUTOPILOT_PROBE -ne '1') { Write-Host 'would check: astral.sh, pypi.org, github.com are reachable' }
else {
    $bad = @()
    foreach ($host_ in 'astral.sh', 'pypi.org', 'github.com') {
        try { $null = Invoke-WebRequest -Uri "https://$host_/" -Method Head -UseBasicParsing -TimeoutSec 8 } catch { $bad += $host_ }
    }
    if ($bad.Count) { Fail 1 'pre-check' "Invoke-WebRequest https://$($bad[0])/ -Method Head   # then set HTTPS_PROXY when a proxy is in the way" "cannot reach: $($bad -join ', ')" }
    Write-Host 'found: astral.sh, pypi.org, github.com reachable'
}
if ($Rights) {
    # N8: one elevated PowerShell writes %ProgramData%\Autopilot\setup.ps1 (Administrators only) and the scheduled task
    # that runs it; the task installs the winget ids `ap` queues (ids only, checked by pattern). The body travels as
    # base64: no user-writable draft file that could be swapped before the administrator step reads it.
    $TaskName = 'Autopilot-Setup'
    $SetupDir = Join-Path $env:ProgramData 'Autopilot'; $SetupScript = Join-Path $SetupDir 'setup.ps1'; $SetupQueue = Join-Path $SetupDir 'setup-queue.txt'
    $SetupBody = @'
$q = Join-Path $env:ProgramData 'Autopilot\setup-queue.txt'
if (-not (Test-Path $q)) { exit 0 }
$ids = Get-Content $q | Where-Object { $_ -match '^[A-Za-z0-9][A-Za-z0-9.+_-]{1,99}$' } | Select-Object -Unique
Clear-Content $q
foreach ($id in $ids) { winget install --id $id -e --source winget --silent --accept-package-agreements --accept-source-agreements }
'@
    $SetupB64 = [Convert]::ToBase64String([Text.Encoding]::ASCII.GetBytes($SetupBody))
    $out = Run schtasks /Query /TN $TaskName /V /FO LIST
    $hasTask = ($LASTEXITCODE -eq 0) -and ("$out" -match [regex]::Escape($SetupScript))
    $taskCmd = "schtasks /Create /TN $TaskName /TR `"powershell -NoProfile -ExecutionPolicy Bypass -File $SetupScript`" /SC ONCE /ST 00:00 /RL HIGHEST /F"
    $aclCmd = "if (Test-Path '$SetupDir') { Remove-Item -Recurse -Force '$SetupDir' }; New-Item -ItemType Directory -Force '$SetupDir' | Out-Null; " +
        "icacls '$SetupDir' /setowner *S-1-5-32-544 | Out-Null; icacls '$SetupDir' /inheritance:r /grant:r '*S-1-5-32-544:(OI)(CI)F' '*S-1-5-18:(OI)(CI)F' '*S-1-5-32-545:(OI)(CI)RX' | Out-Null; " +
        "[IO.File]::WriteAllText('$SetupScript', [Text.Encoding]::ASCII.GetString([Convert]::FromBase64String('$SetupB64'))); " +
        "New-Item -ItemType File -Force '$SetupQueue' | Out-Null; icacls '$SetupQueue' /grant '*S-1-5-32-545:M' | Out-Null"
    if ($DryRun) { Write-Host "would write $SetupScript (Administrators only) and create the scheduled task (one administrator prompt). Command: $aclCmd; $taskCmd" }
    elseif (-not $hasTask) {
        $script = "$aclCmd; $taskCmd" + '; exit $LASTEXITCODE'
        Write-Host "run as administrator (one prompt): $script"
        $p = Start-Process powershell -Verb RunAs -Wait -PassThru -ArgumentList '-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command', $script
        if ($p.ExitCode -ne 0) { Write-Host "the elevated step returned $($p.ExitCode); later runs print install commands instead" }
    } else { Write-Host "found: scheduled task $TaskName" }
}

Step 2 'uv'
$uvCmd = 'irm https://astral.sh/uv/install.ps1 | iex'
if (Has uv) { Write-Host "done: $(Ver uv) (found, skipped)" }
elseif ($DryRun) { Write-Host "would install. Command: $uvCmd" }
else { Capture 2 'uv' $uvCmd; Refresh; if (-not (Has uv)) { Fail 2 'uv' $uvCmd 'uv is not on PATH after the install' } }

Step 3 'Python'
# N5: Autopilot cannot run without Python 3.10 or newer. This is the one system install; uv installs it for this user.
$pycmd = 'uv python install 3.12'
if (PyOk) { Write-Host 'done: Python 3.10 or newer (found, skipped)' }
elseif ($DryRun) { Write-Host "would install (no Python 3.10 or newer found). Command: $pycmd" }
else { Capture 3 'Python' $pycmd }

Step 4 'Autopilot'
# N5.3 + T1: PyPI first for a release copy; the archive of $Ref (no git needed) when PyPI is behind or $Ref is a branch.
# Single quotes around $addr: Windows PowerShell 5.1 drops inner double quotes on the way to a native program (the install CI job showed it).
$addr = "dev-autopilot @ https://github.com/manishjnv/AutoPilot/archive/$Ref.zip"
function ApVer { if (Has ap) { $w = "$(Run ap --version)".Split(' '); if ($w.Count -ge 2) { return $w[1] } } '' }
function AtLeast($v) { if (-not $v) { return $false }; try { [version]$v -ge [version]$MinVersion } catch { $false } }
if ((Has ap) -and (AtLeast (ApVer))) { Write-Host "done: $(Ver autopilot) (found, skipped)"; Write-Host 'To update, run: ap upgrade' }
elseif (Has ap) {
    Write-Host "found: $(Ver autopilot), older than this installer ($MinVersion): updating"
    if ($DryRun) { Write-Host "would run: uv tool install --reinstall '$addr'" } else { Capture 4 'Autopilot' "uv tool install --reinstall '$addr'"; Refresh }
} elseif ($DryRun) {
    Write-Host "would install. Command: uv tool install '$addr' (PyPI first when $Ref is a release)"
} else {
    $done = $false
    if ($Ref -match '^v\d') { Write-Host "run: uv tool install dev-autopilot==$($Ref.Substring(1))"; $null = Run uv tool install "dev-autopilot==$($Ref.Substring(1))"; $done = ($LASTEXITCODE -eq 0) }
    if (-not $done) { Capture 4 'Autopilot' "uv tool install '$addr'" }
    Refresh
}
if ($DryRun) { Write-Host "would check: ap is on PATH and at least $MinVersion" }
elseif (-not (Has ap)) { Fail 4 'Autopilot' "uv tool install --reinstall '$addr' (then make sure $env:USERPROFILE\.local\bin is on PATH)" 'ap is not on PATH' }
elseif (-not (AtLeast (ApVer))) { Fail 4 'Autopilot' "uv tool install --reinstall '$addr'" "ap $(ApVer) is older than $MinVersion" }
else { Write-Host "found: ap $(ApVer)" }

Step 5 'runner (ap setup)'
$setupArgs = @()
if ($SkipLogin) { $setupArgs += '--skip-login' }
if ($Yes) { $setupArgs += '--yes' }
if ($Runner) { $setupArgs += '--runner', $Runner }
if ($DryRun) {
    if (Has ap) { Run ap setup --dry-run @setupArgs | Out-Host } else { Write-Host "would run: ap setup --dry-run $setupArgs" }
} else {
    Run ap setup @setupArgs | Out-Host
    if ($LASTEXITCODE -eq 3) { Write-Host 'Autopilot is installed. Run the line above to name your runner.'; exit 3 }
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    Write-Host "Installed: $(Ver autopilot)"
}
Write-Host 'To uninstall, run: uv tool uninstall dev-autopilot (and ap uninstall --rights)'
$global:LASTEXITCODE = 0   # keep a native exit code from an earlier step out of the CI result
Write-Host 'Done. Open a NEW terminal if `ap` is not found.'
Write-Host 'Open a project folder and type `ap`.'
