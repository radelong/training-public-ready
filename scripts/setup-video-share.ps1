param(
    [Parameter(Mandatory = $true)][string]$VideoRoot,
    [string]$ShareName = 'AcademyVideos',
    [string]$ReaderName = 'academy_video_reader',
    [string]$CredentialOutput = (Join-Path $env:LOCALAPPDATA 'TrainingAcademy\video-smb.credentials')
)

$ErrorActionPreference = 'Stop'
$principal = [Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'Run this script in an elevated PowerShell window.'
}
$folder = (Resolve-Path -LiteralPath $VideoRoot).Path
if (-not (Test-Path -LiteralPath $folder -PathType Container)) {
    throw 'VideoRoot must be an existing folder.'
}
$existingShare = Get-SmbShare -Name $ShareName -ErrorAction SilentlyContinue
if ($existingShare -and $existingShare.Path -ine $folder) {
    throw "Share $ShareName already points to a different folder."
}
$existingUser = Get-LocalUser -Name $ReaderName -ErrorAction SilentlyContinue
if (($existingUser -or $existingShare) -and -not (Test-Path -LiteralPath $CredentialOutput -PathType Leaf)) {
    throw 'A video reader or share already exists without its credential file. Inspect it before continuing.'
}

if (-not $existingUser) {
    $randomBytes = New-Object byte[] 24
    $random = [Security.Cryptography.RandomNumberGenerator]::Create()
    try { $random.GetBytes($randomBytes) } finally { $random.Dispose() }
    $password = [BitConverter]::ToString($randomBytes).Replace('-', '')
    [Array]::Clear($randomBytes, 0, $randomBytes.Length)
    $secure = ConvertTo-SecureString $password -AsPlainText -Force
    New-LocalUser -Name $ReaderName -Password $secure -Description 'Read-only Academy video library' -PasswordNeverExpires -UserMayNotChangePassword | Out-Null
    $credentialFolder = Split-Path -Parent $CredentialOutput
    New-Item -ItemType Directory -Path $credentialFolder -Force | Out-Null
    $sid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
    & icacls $credentialFolder /inheritance:r /grant:r "*$($sid):(OI)(CI)F" '*S-1-5-18:(OI)(CI)F' | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Could not restrict the credential folder.' }
    $credentialText = (@("username=$ReaderName", "password=$password", "domain=$env:COMPUTERNAME") -join "`n") + "`n"
    [IO.File]::WriteAllText($CredentialOutput, $credentialText, [Text.Encoding]::ASCII)
    $credentialText = $null
    $password = $null
}

if (-not $existingShare) {
    New-SmbShare -Name $ShareName -Path $folder -ReadAccess "$env:COMPUTERNAME\$ReaderName" -Description 'Read-only Training Academy video library' | Out-Null
}
$access = Get-SmbShareAccess -Name $ShareName
if (-not ($access | Where-Object { $_.AccountName -ieq "$env:COMPUTERNAME\$ReaderName" -and $_.AccessRight -eq 'Read' -and $_.AccessControlType -eq 'Allow' })) {
    throw 'The Academy reader does not have read-only share access.'
}
Write-Output "VIDEO_SHARE_READY \\$env:COMPUTERNAME\$ShareName"
Write-Output "Credential file: $CredentialOutput"
