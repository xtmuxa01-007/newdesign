# PostgreSQL va rasmlarni Docker konteynerlaridan loyiha ichidagi backups papkasiga oladi.
# Binary dump PowerShell orqali matn sifatida yoʻnaltirilmaydi: docker compose cp ishlatiladi.
[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
Push-Location -LiteralPath $projectRoot
try {
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) { throw 'Docker topilmadi. Docker Desktopni oʻrnating va ishga tushiring.' }
    $stamp = (Get-Date -Format 'yyyyMMdd-HHmmss') + '-' + [Guid]::NewGuid().ToString('N').Substring(0,8)
    $backupDir = Join-Path $projectRoot "backups\$stamp"
    $containerDbPath = "/tmp/marva-$stamp.dump"
    $containerImagePath = "/tmp/marva-$stamp.tar.gz"
    New-Item -ItemType Directory -Path $backupDir -Force | Out-Null
    $dumpCommand = 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --format=custom --file={0}' -f $containerDbPath
    docker compose exec -T db sh -c $dumpCommand
    if ($LASTEXITCODE -ne 0) { throw 'PostgreSQL nusxasini yaratib boʻlmadi.' }
    docker compose cp "db:$containerDbPath" (Join-Path $backupDir 'database.dump')
    if ($LASTEXITCODE -ne 0) { throw 'PostgreSQL faylini olib boʻlmadi.' }
    docker compose exec -T api python -m app.backup_tools create --archive $containerImagePath
    if ($LASTEXITCODE -ne 0) { throw 'Rasmlar nusxasini yaratib boʻlmadi.' }
    docker compose cp "api:$containerImagePath" (Join-Path $backupDir 'images.tar.gz')
    if ($LASTEXITCODE -ne 0) { throw 'Rasmlar arxivini olib boʻlmadi.' }
    Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path $backupDir 'database.dump'), (Join-Path $backupDir 'images.tar.gz') |
        Select-Object Hash, Path | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $backupDir 'checksums.json') -Encoding UTF8
    docker compose exec -T db rm -f -- $containerDbPath
    docker compose exec -T api rm -f -- $containerImagePath
    Write-Host "Zaxira tayyor: $backupDir"
    Write-Host 'Bu papkani boshqa diskka ham koʻchiring. .env faylini alohida xavfsiz joyda saqlang.'
} finally { Pop-Location }
