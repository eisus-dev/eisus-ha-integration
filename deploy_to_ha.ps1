<#
.SYNOPSIS
    Deploy the EISUS Home Assistant custom component to a Home Assistant host.

.DESCRIPTION
    Copies .\custom_components\eisus to the Home Assistant configuration
    directory and (optionally) restarts Home Assistant so the component is
    picked up.  Works with three common setups:

      1. Docker on Debian over SSH (recommended, one command):
             .\deploy_to_ha.ps1 -SshTarget root@192.168.1.50
         Destination defaults to /opt/homeassistant/config, the folder that is
         bind-mounted into the container as /config, so the component lands in
         /opt/homeassistant/config/custom_components/eisus and the container is
         restarted with "docker restart".

      2. Local / network share  -Destination "C:\ha-config"
         or -Destination "\\homeassistant\config"

      3. Copy only             -SkipRestart

.PARAMETER Destination
    Target configuration directory. Use a UNC/Windows path for a mounted
    share, or a Linux path when combined with -SshTarget
    (default: /opt/homeassistant/config).

.PARAMETER SshTarget
    user@host of the machine that runs the Home Assistant container. When set,
    the component is copied over SCP and the container is restarted with
    "docker restart".

.PARAMETER Container
    Name of the Home Assistant container to restart (default: homeassistant).

.PARAMETER SkipRestart
    Copy the files but do not restart Home Assistant.

.EXAMPLE
    # Home Assistant in Docker on Debian at /opt/homeassistant/config
    .\deploy_to_ha.ps1 -SshTarget "root@192.168.1.50"

.EXAMPLE
    .\deploy_to_ha.ps1 -Destination "\\homeassistant\config"

.EXAMPLE
    .\deploy_to_ha.ps1 -Destination "/config" -SshTarget "root@192.168.1.50" -Container homeassistant
#>
[CmdletBinding()]
param(
    [string]$Destination = "/opt/homeassistant/config",
    [string]$SshTarget,
    [string]$Container = "homeassistant",
    [switch]$SkipRestart
)

$ErrorActionPreference = "Stop"
$source = Join-Path $PSScriptRoot "custom_components\eisus"

if (-not (Test-Path -LiteralPath $source)) {
    throw "Component not found: $source"
}

if (-not $SshTarget -and $Destination -like "/*") {
    throw "Destination '$Destination' is a Linux path but no -SshTarget was given. " +
          "Either add -SshTarget user@host (Docker over SSH) or pass a Windows/UNC path " +
          "for a mounted share, e.g. -Destination '\\homeassistant\config'."
}

Write-Host "EISUS HA integration deploy" -ForegroundColor Cyan
Write-Host "  source      : $source"
Write-Host "  destination : $Destination$(if ($SshTarget) { ' on ' + $SshTarget })"

if (-not $SshTarget) {
    # --- direct filesystem copy (local path or mounted share) -------------
    $targetRoot = Join-Path $Destination "custom_components"
    $target = Join-Path $targetRoot "eisus"
    New-Item -ItemType Directory -Force -Path $targetRoot | Out-Null
    if (Test-Path -LiteralPath $target) {
        Remove-Item -LiteralPath $target -Recurse -Force
    }
    Copy-Item -LiteralPath $source -Destination $target -Recurse -Force
    Write-Host "Copied to $target" -ForegroundColor Green
}
else {
    # --- stage, scp, then docker cp/restart over SSH ----------------------
    $sshAvailable = Get-Command ssh -ErrorAction SilentlyContinue
    $scpAvailable = Get-Command scp -ErrorAction SilentlyContinue
    if (-not $sshAvailable -or -not $scpAvailable) {
        throw "ssh/scp not found on PATH. Install the OpenSSH client or use -Destination with a shared folder."
    }

    $staging = Join-Path $env:TEMP ("eisus_deploy_" + [guid]::NewGuid().ToString("N"))
    $stagingComponent = Join-Path $staging "eisus"
    New-Item -ItemType Directory -Force -Path $stagingComponent | Out-Null
    Copy-Item -LiteralPath (Join-Path $source "*") -Destination $stagingComponent -Recurse -Force

    $remoteStage = "/tmp/eisus_deploy"
    Write-Host "Uploading to ${SshTarget}:$remoteStage ..." -ForegroundColor Cyan
    & ssh $SshTarget "rm -rf $remoteStage && mkdir -p $remoteStage"
    & scp -r $stagingComponent "${SshTarget}:${remoteStage}/"

    $remoteInstall = @(
        "mkdir -p '$Destination/custom_components'",
        "rm -rf '$Destination/custom_components/eisus'",
        "cp -r '$remoteStage/eisus' '$Destination/custom_components/eisus'",
        "rm -rf '$remoteStage'"
    ) -join " && "
    & ssh $SshTarget $remoteInstall
    Write-Host "Installed to $Destination/custom_components/eisus" -ForegroundColor Green

    if (-not $SkipRestart) {
        Write-Host "Restarting container '$Container' ..." -ForegroundColor Cyan
        & ssh $SshTarget "docker restart $Container"
        Write-Host "Home Assistant restarted" -ForegroundColor Green
    }

    Remove-Item -LiteralPath $staging -Recurse -Force
}

if (-not $SkipRestart -and -not $SshTarget) {
    Write-Host ""
    Write-Host "Now restart Home Assistant (or: Settings > System > Restart)," -ForegroundColor Yellow
    Write-Host "then add the device: Settings > Devices & Services > Add Integration > EISUS." -ForegroundColor Yellow
}
