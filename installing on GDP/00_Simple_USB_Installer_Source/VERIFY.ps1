$ErrorActionPreference = 'Stop'
$packageRoot = $PSScriptRoot
$manifest = Join-Path $packageRoot 'MANIFEST.sha256'
if (-not (Test-Path -LiteralPath $manifest -PathType Leaf)) { throw 'MANIFEST.sha256 is missing.' }
$lines = @(Get-Content -LiteralPath $manifest)
$seen = @{}
$index = 0
foreach ($line in $lines) {
    if ($line -cnotmatch '^([0-9a-f]{64})  ([A-Za-z0-9_. /-]+)$') { throw "Invalid manifest line: $line" }
    $expected = $Matches[1]
    $relative = $Matches[2]
    if ($relative.StartsWith('/') -or $relative -match '(^|/)\.\.(/|$)' -or $seen.ContainsKey($relative)) {
        throw "Unsafe or duplicate manifest path: $relative"
    }
    $seen[$relative] = $true
    $file = Join-Path $packageRoot $relative
    if (-not (Test-Path -LiteralPath $file -PathType Leaf)) { throw "Missing package file: $relative" }
    $index++
    Write-Progress -Activity 'Verifying Academy USB package' -Status "$index / $($lines.Count): $relative" -PercentComplete (100 * $index / $lines.Count)
    if ((Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash.ToLowerInvariant() -cne $expected) {
        throw "Checksum failed: $relative. Recopy the package before installing."
    }
}
Write-Progress -Activity 'Verifying Academy USB package' -Completed
if ($index -lt 40) { throw 'Package manifest is incomplete.' }
Write-Output "ACADEMY USB PACKAGE VERIFIED: $index files."
