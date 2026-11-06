$ErrorActionPreference = 'Stop'
$packageRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$remoteFolder = '/root/gdp-install'
try {
    & (Join-Path $packageRoot 'VERIFY.ps1')
    if (-not $?) { throw 'Package verification failed.' }
    $ssh = (Get-Command ssh.exe -ErrorAction Stop).Source
    $scp = (Get-Command scp.exe -ErrorAction Stop).Source
    Write-Host 'This installs the Academy on a dedicated, empty, standalone Proxmox VE 9 server.'
    Write-Host 'The USB drive can stay attached to this Windows PC for this method.'
    $targetIp = (Read-Host 'New Proxmox server LAN IPv4 address').Trim()
    $parsedIp = $null
    if (-not [Net.IPAddress]::TryParse($targetIp, [ref]$parsedIp) -or
        $parsedIp.AddressFamily -ne [Net.Sockets.AddressFamily]::InterNetwork) {
        throw 'Enter a valid IPv4 address.'
    }
    $remote = "root@$targetIp"
    Write-Host 'Compare the SSH fingerprint with the server console before accepting it.'
    Write-Host 'On the server, run: ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub'
    Write-Host 'Enter the Proxmox root password only when OpenSSH asks; it is not saved.'
    $options = @('-o', 'StrictHostKeyChecking=ask', '-o', 'ConnectTimeout=15')
    $packageBytes = [long](Get-ChildItem -LiteralPath $packageRoot -Recurse -File -Force | Measure-Object Length -Sum).Sum
    $requiredBytes = $packageBytes + 40GB
    $remoteCheck = 'test $(df -B1 --output=avail /root | tail -1) -ge ' + $requiredBytes +
        ' || { echo Insufficient or unreadable free space under /root: the package plus 40 GiB is required before copying. >&2; exit 1; }; ' +
        'test ! -e /root/gdp-install && mkdir -m 700 /root/gdp-install'
    & $ssh @options $remote $remoteCheck
    if ($LASTEXITCODE -ne 0) {
        throw 'Connection failed, free disk space is insufficient, or /root/gdp-install already exists. See the error above and the recovery instructions.'
    }
    $files = @(Get-ChildItem -LiteralPath $packageRoot -Force | ForEach-Object { $_.FullName })
    Write-Host 'Copying the complete verified package. Keep the PC awake until this step finishes.'
    & $scp @options -r -p @files "${remote}:${remoteFolder}/"
    if ($LASTEXITCODE -ne 0) { throw 'Copy failed. No installation was started. See the recovery instructions.' }
    & $ssh @options -tt $remote 'bash /root/gdp-install/INSTALL.sh'
    if ($LASTEXITCODE -ne 0) {
        throw 'Setup stopped or SSH disconnected. Reconnect to Proxmox and run bash /root/gdp-install/INSTALL.sh to see its status.'
    }
} catch {
    Write-Error $_
    exit 1
}
