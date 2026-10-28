$ErrorActionPreference = 'Stop'
$installerRoot = $PSScriptRoot
$packageRoot = Split-Path -Parent $installerRoot
$mediaRoot = Join-Path $packageRoot '30_Current_Offline_Media_2026-10-26'
$contentRoot = Join-Path $packageRoot '28_Fresh_Install_Content'
$templatesRoot = Join-Path $packageRoot '29_Current_Lab_Templates'
$updateRoot = Join-Path $packageRoot '33_Learning_Fixes_R3'
$remoteFolder = '/root/gdp-install'
$remote = $null

try {
    $archive = Join-Path $mediaRoot 'training-academy-offline-amd64.tar.gz'
    $provisionIso = Join-Path $mediaRoot 'academy-provision.iso'
    $pveIso = Join-Path $packageRoot '00_Proxmox_Installer\proxmox-ve_9.2-1.iso'
    foreach ($path in @($archive, $provisionIso, $pveIso,
                         (Join-Path $updateRoot 'Training_Academy_App_Update_28_Learning_Fixes_2026-10-27_r3.tar.gz'),
                         (Join-Path $contentRoot 'CONTENT-SHA256SUMS.txt'),
                         (Join-Path $templatesRoot 'fresh-labs.json'),
                         (Join-Path $templatesRoot 'backups\academy-template-sha256sums.txt'))) {
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "Package file missing: $path" }
    }
    $verifier = Join-Path $packageRoot 'Verify-GDP-Fresh.ps1'
    if (-not (Test-Path -LiteralPath $verifier -PathType Leaf)) { throw "Package verifier missing: $verifier" }
    Write-Host 'Verifying the complete GDP package and every included checksum. Large media files can take a little while.' -ForegroundColor Cyan
    & $verifier *> $null
    Write-Host 'All GDP package checksums passed.' -ForegroundColor Green

    $ssh = (Get-Command ssh.exe -ErrorAction Stop).Source
    $scp = (Get-Command scp.exe -ErrorAction Stop).Source
    Write-Host ''
    Write-Host 'This installs the current Academy on a dedicated, empty Proxmox VE 9 node.' -ForegroundColor Yellow
    Write-Host 'The eight classes, assessments, game and three lab templates are included. Users and results start fresh.'
    Write-Host 'The package supports LAN-only Academy access. It does not install Proxmox itself.'
    Write-Host ''
    Write-Host 'Install Proxmox from 00_Proxmox_Installer first. Keep the host dedicated and empty.'
    $targetIp = Read-Host 'Enter the new Proxmox LAN IPv4 address'
    $parsedIp = $null
    if (-not [Net.IPAddress]::TryParse($targetIp, [ref]$parsedIp) -or $parsedIp.AddressFamily -ne [Net.Sockets.AddressFamily]::InterNetwork) {
        throw 'Enter a valid IPv4 address.'
    }
    Write-Host "The first SSH connection will ask you to verify the Proxmox host key, then request root login." -ForegroundColor Cyan
    Write-Host 'Do not accept an unexpected host key. Passwords are entered only into OpenSSH and are not saved.'
    $remote = "root@${targetIp}"

    & $ssh -o ConnectTimeout=15 $remote 'mkdir -p /root/gdp-install'
    if ($LASTEXITCODE -ne 0) { throw 'Could not connect or create the remote staging directory.' }

    & $scp -r -p $mediaRoot $installerRoot $contentRoot $templatesRoot $updateRoot "${remote}:${remoteFolder}/"
    if ($LASTEXITCODE -ne 0) { throw 'Media transfer failed. Re-run only after checking the remote staging directory.' }

    Write-Host ''
    Write-Host 'Starting the Proxmox setup wizard. It will ask for the site hostname, LAN values, network ranges and storage IDs.' -ForegroundColor Cyan
    & $ssh -tt $remote "bash ${remoteFolder}/00_Click_To_Install_GDP/install-on-proxmox.sh ${remoteFolder}/30_Current_Offline_Media_2026-10-26 ${remoteFolder}/00_Click_To_Install_GDP"
    if ($LASTEXITCODE -ne 0) { throw 'The Proxmox installer stopped with an error. Read its recovery guidance before retrying.' }
    Write-Host 'Academy installation completed. Follow the displayed LAN acceptance steps before admitting learners.' -ForegroundColor Green
} catch {
    Write-Error $_
    exit 1
}
