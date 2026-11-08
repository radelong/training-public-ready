$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$manifest = Get-Content -LiteralPath (Join-Path $root 'MANIFEST.json') -Raw | ConvertFrom-Json
if ($manifest.package_type -cne 'installed-academy-callback-repair-v1') { throw 'Wrong package type.' }
$seen = @{}
foreach ($entry in $manifest.files) {
    $relative = [string]$entry.path
    if ($relative -match '(^/|\\|(^|/)\.\.(/|$))' -or $seen.ContainsKey($relative)) { throw 'Unsafe or duplicate package path.' }
    $seen[$relative] = $true
    $path = Join-Path $root $relative
    if ((Get-Item -LiteralPath $path).Length -ne $entry.bytes) { throw "Wrong file size: $relative" }
    Write-Output "Verifying $relative"
    if ((Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant() -cne $entry.sha256) {
        throw "Checksum failed: $relative. Recopy this file or replace the USB transport."
    }
}
foreach ($required in @('INSTALL.sh','install_callback.py','guest_callback.py','verify_package.py','callback-lab.json','worker.py','update_worker.py',
    'backups/vzdump-qemu-9251-2026_10_26-10_55_27.vma.zst','backups/vzdump-qemu-9252-2026_10_26-10_58_14.vma.zst')) {
    if (-not $seen.ContainsKey($required)) { throw "Incomplete package manifest: $required" }
}
if ($seen.Count -lt 11) { throw 'Incomplete package manifest.' }
Write-Output "CALLBACK USB PACKAGE VERIFIED: $($seen.Count) files."
