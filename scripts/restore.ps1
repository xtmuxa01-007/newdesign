# Faqat foydalanuvchi aniq roziligi bilan mavjud bazani zaxiradan almashtiradi.
[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$BackupFolder)
$ErrorActionPreference = 'Stop'
$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$backupDir = (Resolve-Path -LiteralPath $BackupFolder).Path
$databaseFile = Join-Path $backupDir 'database.dump'
$imageFile = Join-Path $backupDir 'images.tar.gz'
if (-not (Test-Path -LiteralPath $databaseFile) -or -not (Test-Path -LiteralPath $imageFile)) { throw 'database.dump va images.tar.gz fayllari kerak.' }
$checksumFile = Join-Path $backupDir 'checksums.json'
if (Test-Path -LiteralPath $checksumFile) {
    $expectedFiles = Get-Content -LiteralPath $checksumFile -Raw | ConvertFrom-Json
    if (@($expectedFiles).Count -ne 2 -or @($expectedFiles | ForEach-Object { Split-Path -Path $_.Path -Leaf } | Select-Object -Unique).Count -ne 2) { throw 'Checksum ichida ikkala zaxira fayli ham boʻlishi kerak.' }
    foreach ($entry in $expectedFiles) {
        $fileName = Split-Path -Path $entry.Path -Leaf
        if ($fileName -notin @('database.dump', 'images.tar.gz')) { throw 'Checksum faylida nomaʻlum fayl nomi bor.' }
        $actual = Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path $backupDir $fileName)
        if ($actual.Hash -ne $entry.Hash) { throw "Zaxira buzilgan yoki oʻzgargan: $fileName" }
    }
}
$answer = Read-Host 'Mavjud savdo va hisoblar zaxiradagi holatga ALMASHTIRILADI. Davom etish uchun TIKLASH deb yozing'
if ($answer -cne 'TIKLASH') { Write-Host 'Tiklash bekor qilindi.'; exit }
Push-Location -LiteralPath $projectRoot
try {
    # Bazaga tegishdan OLDIN rasm arxivini toʻliq oʻqib tekshiramiz.
    docker compose run --rm --no-deps --volume "${backupDir}:/restore:ro" api python -m app.backup_tools verify --archive /restore/images.tar.gz
    if ($LASTEXITCODE -ne 0) { throw 'Rasm arxivi tekshiruvdan oʻtmadi. Mavjud baza oʻzgartirilmadi.' }
    docker compose stop web api
    if ($LASTEXITCODE -ne 0) { throw 'Ilovani toʻxtatib boʻlmadi.' }
    docker compose up -d --wait db
    if ($LASTEXITCODE -ne 0) { throw 'Bazani ishga tushirib boʻlmadi.' }
    docker compose cp $databaseFile db:/tmp/marva-restore.dump
    if ($LASTEXITCODE -ne 0) { throw 'Dumpni koʻchirib boʻlmadi.' }
    docker compose exec -T db sh -c 'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists --no-owner --single-transaction /tmp/marva-restore.dump'
    if ($LASTEXITCODE -ne 0) { throw 'Bazani tiklash bajarilmadi. Ilova toʻxtagan holatda qoldi; xatoni tekshiring.' }
    # Arxiv faqat uploads ichiga yoziladi. Yoʻl traversaliga ruxsat yoʻq.
    docker compose run --rm --no-deps --volume "${backupDir}:/restore:ro" api python -m app.backup_tools restore --archive /restore/images.tar.gz
    if ($LASTEXITCODE -ne 0) { throw 'Rasmlarni tiklash bajarilmadi. Ilova toʻxtagan holatda qoldi.' }
    docker compose up -d api web
    if ($LASTEXITCODE -ne 0) { throw 'Ilovani qayta ishga tushirib boʻlmadi.' }
    Write-Host 'Baza va rasmlar tiklandi. Kirish va hisoblarni tekshiring.'
} finally { Pop-Location }
