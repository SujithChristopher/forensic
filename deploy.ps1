<#
.SYNOPSIS
    Push code from this machine to the Raspberry Pi recorders over the LAN.

.DESCRIPTION
    No internet or GitHub involved: this pushes the local git repository straight to
    each Pi over SSH. The Pis are configured with receive.denyCurrentBranch=updateInstead,
    so a push updates their checked-out working tree in place — but only when that tree
    is clean, which is what protects any per-rig edits from being silently overwritten.

    Run -Setup once per Pi, then -Deploy for every subsequent update.

.PARAMETER Setup
    One-time per Pi: configure it to accept pushes into its checked-out branch.

.PARAMETER Deploy
    Push the branch and update each Pi's working tree. The default action.

.PARAMETER Status
    Report only: commit, dirty files, service state and recent log lines per Pi.

.PARAMETER Restart
    Restart the recorder service after a successful deploy. Needs sudo on the Pi.

.PARAMETER InstallKey
    Copy your SSH public key to each Pi so later runs stop asking for a password.
    Generates a key first if this machine has none. You type the Pi's password once
    per Pi, here and nowhere else — no password is stored in this script or the repo.

.PARAMETER Stash
    Stash uncommitted remote changes instead of refusing to deploy over them.
    The stash stays on the Pi; recover it there with `git stash pop`.

.EXAMPLE
    .\deploy.ps1 -InstallKey
    .\deploy.ps1 -Setup
    .\deploy.ps1 -Deploy -Restart

.EXAMPLE
    .\deploy.ps1 -Status
    .\deploy.ps1 -Deploy -ComputerName 192.168.0.101
#>

[CmdletBinding(DefaultParameterSetName = 'Deploy')]
param(
    [string[]]$ComputerName = @('192.168.0.100', '192.168.0.101'),
    [string]$User = 'cmc1',
    [string]$RemotePath = 'Documents/forensic',
    [string]$Branch,
    [string]$Service = 'data-recorder.service',

    [Parameter(ParameterSetName = 'Setup')][switch]$Setup,
    [Parameter(ParameterSetName = 'Deploy')][switch]$Deploy,
    [Parameter(ParameterSetName = 'Status')][switch]$Status,
    [Parameter(ParameterSetName = 'InstallKey')][switch]$InstallKey,

    [Parameter(ParameterSetName = 'Deploy')][switch]$Restart,
    [Parameter(ParameterSetName = 'Deploy')][switch]$Stash,
    [switch]$DryRun
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# ---------------------------------------------------------------------- helpers

function Write-Step { param([string]$Message) Write-Host "  $Message" -ForegroundColor DarkGray }
function Write-Ok { param([string]$Message) Write-Host "  $Message" -ForegroundColor Green }
function Write-Warn { param([string]$Message) Write-Host "  $Message" -ForegroundColor Yellow }
function Write-Fail { param([string]$Message) Write-Host "  $Message" -ForegroundColor Red }

function Invoke-Remote {
    <#
        Run a command on a Pi. Returns the output and exit code rather than throwing,
        so one unreachable Pi never aborts the run for the other.
    #>
    param(
        [Parameter(Mandatory)][string]$Target,
        [Parameter(Mandatory)][string]$Command,
        [switch]$Tty
    )

    $sshArgs = @('-o', 'ConnectTimeout=8', '-o', 'StrictHostKeyChecking=accept-new')
    if ($Tty) { $sshArgs += '-t' }
    $sshArgs += @($Target, $Command)

    $output = & ssh @sshArgs 2>&1
    [pscustomobject]@{
        Success = ($LASTEXITCODE -eq 0)
        Code    = $LASTEXITCODE
        Output  = (($output | ForEach-Object { $_.ToString() }) -join "`n").Trim()
    }
}

function Get-RemoteQuoted {
    # Single-quote a path for the remote POSIX shell.
    param([string]$Value)
    "'" + $Value.Replace("'", "'\''") + "'"
}

# ------------------------------------------------------------------- preflight

if (-not (Get-Command ssh -ErrorAction SilentlyContinue)) {
    throw "ssh not found. Install the Windows OpenSSH Client (Settings > Optional Features)."
}
if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    throw "git not found on PATH."
}

$repoRoot = (& git rev-parse --show-toplevel 2>$null)
if ($LASTEXITCODE -ne 0) { throw "Not inside a git repository." }
Set-Location $repoRoot

if (-not $Branch) {
    $Branch = (& git rev-parse --abbrev-ref HEAD).Trim()
}

$localCommit = (& git rev-parse HEAD).Trim()
$localShort = (& git rev-parse --short HEAD).Trim()
$remoteQuotedPath = Get-RemoteQuoted $RemotePath

# Which action to run — default to Deploy when no switch was given.
$action = $PSCmdlet.ParameterSetName
if (-not ($Setup -or $Deploy -or $Status -or $InstallKey)) { $action = 'Deploy' }

Write-Host ""
Write-Host "Repository : $repoRoot"
Write-Host "Branch     : $Branch @ $localShort"
Write-Host "Targets    : $($ComputerName -join ', ') (as $User)"
Write-Host "Action     : $action$(if ($DryRun) { '  [dry run]' })"
Write-Host ""

if ($action -eq 'Deploy') {
    $dirty = & git status --porcelain
    if ($dirty) {
        Write-Warn "Local working tree has uncommitted changes — only committed work is pushed:"
        $dirty | ForEach-Object { Write-Warn "    $_" }
        Write-Host ""
    }
}

# --------------------------------------------------------------------- actions

function Get-LocalPublicKey {
    <#
        Return the path to a public key, generating one if this machine has none.
        The key is what removes the password prompts; it is never sent anywhere but
        the Pis' authorized_keys, and the private half never leaves this machine.
    #>
    $sshDir = Join-Path $env:USERPROFILE '.ssh'
    foreach ($name in @('id_ed25519.pub', 'id_rsa.pub')) {
        $candidate = Join-Path $sshDir $name
        if (Test-Path $candidate) { return $candidate }
    }

    Write-Step "No SSH key on this machine — generating one"
    if (-not (Test-Path $sshDir)) { New-Item -ItemType Directory -Path $sshDir | Out-Null }

    $keyFile = Join-Path $sshDir 'id_ed25519'
    & ssh-keygen -t ed25519 -f $keyFile -N '""' -C "forensic-deploy-$env:COMPUTERNAME" -q
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path "$keyFile.pub")) {
        Write-Fail "ssh-keygen failed. Generate one manually: ssh-keygen -t ed25519"
        return $null
    }

    Write-Ok "Generated $keyFile"
    return "$keyFile.pub"
}

function Invoke-InstallKey {
    param([string]$Target)

    $keyPath = Get-LocalPublicKey
    if (-not $keyPath) { return $false }

    Write-Step "Installing $(Split-Path $keyPath -Leaf) — enter the Pi's password once when asked"
    if ($DryRun) { Write-Ok "would install key"; return $true }

    $publicKey = (Get-Content $keyPath -Raw).Trim()
    $install = "mkdir -p ~/.ssh && chmod 700 ~/.ssh && " +
               "touch ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys && " +
               "grep -qxF '$publicKey' ~/.ssh/authorized_keys || echo '$publicKey' >> ~/.ssh/authorized_keys"

    # No -o BatchMode here: this is the one call that must be able to ask for a password.
    & ssh -o ConnectTimeout=8 -o StrictHostKeyChecking=accept-new $Target $install
    if ($LASTEXITCODE -ne 0) { Write-Fail "Key install failed (exit $LASTEXITCODE)"; return $false }

    Write-Ok "Key installed"
    return $true
}

function Invoke-Setup {
    param([string]$Target)

    $probe = Invoke-Remote -Target $Target -Command "test -d $remoteQuotedPath/.git && echo ok"
    if (-not $probe.Success -or $probe.Output -ne 'ok') {
        Write-Fail "$RemotePath is not a git repository on this Pi."
        Write-Fail "Clone it there first, or copy this repo across and run 'git init' in it."
        if ($probe.Output) { Write-Fail $probe.Output }
        return $false
    }

    if ($DryRun) { Write-Ok "would set receive.denyCurrentBranch=updateInstead"; return $true }

    # updateInstead makes a push fast-forward the checked-out working tree, but only
    # when that tree is clean — so a push can never silently discard on-Pi edits.
    $configure = "cd $remoteQuotedPath && " +
                 "git config receive.denyCurrentBranch updateInstead && " +
                 "git config --get receive.denyCurrentBranch"
    $result = Invoke-Remote -Target $Target -Command $configure
    if (-not $result.Success) { Write-Fail "Configure failed: $($result.Output)"; return $false }

    Write-Ok "Configured to accept pushes (receive.denyCurrentBranch=$($result.Output))"
    return $true
}

function Invoke-Status {
    param([string]$Target)

    $query = "cd $remoteQuotedPath 2>/dev/null || { echo 'MISSING'; exit 1; }; " +
             "echo COMMIT:`$(git rev-parse --short HEAD 2>/dev/null); " +
             "echo BRANCH:`$(git rev-parse --abbrev-ref HEAD 2>/dev/null); " +
             "echo DIRTY:`$(git status --porcelain | wc -l); " +
             "echo SERVICE:`$(systemctl is-active $Service 2>/dev/null); " +
             "git status --porcelain"

    $result = Invoke-Remote -Target $Target -Command $query
    if (-not $result.Success) {
        Write-Fail "Unreachable or no repo: $($result.Output)"
        return $false
    }

    foreach ($line in $result.Output -split "`n") {
        switch -Regex ($line) {
            '^COMMIT:(.*)' {
                $commit = $Matches[1]
                if ($commit -and $localShort.StartsWith($commit)) {
                    Write-Ok "Commit  : $commit (matches local)"
                } else {
                    Write-Warn "Commit  : $commit (local is $localShort)"
                }
            }
            '^BRANCH:(.*)' { Write-Step "Branch  : $($Matches[1])" }
            '^DIRTY:(.*)' {
                $count = [int]$Matches[1]
                if ($count -eq 0) { Write-Step "Modified: none" }
                else { Write-Warn "Modified: $count file(s)" }
            }
            '^SERVICE:(.*)' {
                $state = $Matches[1]
                if ($state -eq 'active') { Write-Ok "Service : $state" }
                else { Write-Warn "Service : $(if ($state) { $state } else { 'not found' })" }
            }
            '^\s*$' { }
            default { Write-Warn "    $line" }
        }
    }
    return $true
}

function Invoke-Deploy {
    param([string]$Target, [string]$ComputerName)

    # Refuse to push over uncommitted work on the Pi. exposure.toml in particular is
    # tuned per rig, and losing that tuning is far more expensive than a failed deploy.
    $check = Invoke-Remote -Target $Target -Command "cd $remoteQuotedPath && git status --porcelain"
    if (-not $check.Success) {
        Write-Fail "Cannot reach repo at $RemotePath : $($check.Output)"
        return $false
    }

    if ($check.Output) {
        Write-Warn "Uncommitted changes on the Pi:"
        $check.Output -split "`n" | ForEach-Object { Write-Warn "    $_" }
        if (-not $Stash) {
            Write-Fail "Refusing to overwrite. Commit them on the Pi, or re-run with -Stash."
            return $false
        }
        if (-not $DryRun) {
            $stashed = Invoke-Remote -Target $Target -Command `
                "cd $remoteQuotedPath && git stash push -u -m 'deploy.ps1 $(Get-Date -Format s)'"
            if (-not $stashed.Success) { Write-Fail "Stash failed: $($stashed.Output)"; return $false }
            Write-Warn "Stashed on the Pi — recover there with: git stash pop"
        }
    }

    if ($DryRun) { Write-Ok "would push $Branch to ${ComputerName}:$RemotePath"; return $true }

    Write-Step "Pushing $Branch ..."
    & git push --force-with-lease "${User}@${ComputerName}:$RemotePath" "${Branch}:${Branch}"
    if ($LASTEXITCODE -ne 0) {
        Write-Fail "Push failed (exit $LASTEXITCODE)."
        Write-Fail "If it mentions denyCurrentBranch, run: .\deploy.ps1 -Setup"
        return $false
    }

    # Confirm the working tree really moved — a push can succeed while the checkout
    # stays behind if updateInstead was never configured.
    $verify = Invoke-Remote -Target $Target -Command "cd $remoteQuotedPath && git rev-parse HEAD"
    if (-not $verify.Success) { Write-Fail "Could not verify: $($verify.Output)"; return $false }

    if ($verify.Output -ne $localCommit) {
        Write-Fail "Pushed, but the Pi's working tree is at $($verify.Output.Substring(0,7)), not $localShort."
        Write-Fail "Run .\deploy.ps1 -Setup, then deploy again."
        return $false
    }
    Write-Ok "Working tree now at $localShort"

    # exposure.toml is per-rig. Show what this Pi ended up with rather than assuming.
    $toml = Invoke-Remote -Target $Target -Command `
        "cd $remoteQuotedPath && sed -n '/\[exposure.auto_exposure\]/,/^$/p' exposure.toml | grep -E '^[a-z_]+ *=' || true"
    if ($toml.Success -and $toml.Output) {
        Write-Step "Active auto-exposure settings:"
        $toml.Output -split "`n" | ForEach-Object { Write-Step "    $_" }
    }

    if ($Restart) {
        Write-Step "Restarting $Service ..."
        $restarted = Invoke-Remote -Target $Target -Tty -Command "sudo systemctl restart $Service"
        if (-not $restarted.Success) {
            Write-Fail "Restart failed: $($restarted.Output)"
            return $false
        }
        Start-Sleep -Seconds 2
        $state = Invoke-Remote -Target $Target -Command "systemctl is-active $Service"
        if ($state.Output -eq 'active') { Write-Ok "Service active" }
        else { Write-Fail "Service is '$($state.Output)' — check: journalctl -u $Service -n 50"; return $false }
    }

    return $true
}

# ----------------------------------------------------------------------- main

$results = @()

foreach ($computer in $ComputerName) {
    $target = "${User}@${computer}"
    Write-Host "[$computer]" -ForegroundColor Cyan

    # Every other action makes several SSH calls, so password auth would prompt once per
    # call. Check for key auth up front and say so, instead of surprising the operator.
    if ($action -ne 'InstallKey') {
        & ssh -o BatchMode=yes -o ConnectTimeout=8 -o StrictHostKeyChecking=accept-new `
              $target 'true' 2>&1 | Out-Null
        if ($LASTEXITCODE -ne 0) {
            Write-Warn "No key-based login — you will be asked for the password several times."
            Write-Warn "Run '.\deploy.ps1 -InstallKey' once to enter it a single time and be done."
        }
    }

    try {
        $ok = switch ($action) {
            'InstallKey' { Invoke-InstallKey -Target $target }
            'Setup' { Invoke-Setup -Target $target }
            'Status' { Invoke-Status -Target $target }
            'Deploy' { Invoke-Deploy -Target $target -ComputerName $computer }
        }
    } catch {
        Write-Fail $_.Exception.Message
        $ok = $false
    }

    $results += [pscustomobject]@{ Host = $computer; Ok = [bool]$ok }
    Write-Host ""
}

$failed = @($results | Where-Object { -not $_.Ok })
foreach ($r in $results) {
    if ($r.Ok) { Write-Ok "$($r.Host)  ok" } else { Write-Fail "$($r.Host)  FAILED" }
}
Write-Host ""

if ($failed.Count -gt 0) { exit 1 }
