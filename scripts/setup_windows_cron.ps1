#Requires -Version 5.1
# Локальный будильник каждые 15 мин (если ПК включён). Запуск: powershell -ExecutionPolicy Bypass -File scripts/setup_windows_cron.ps1

$Repo = "VB737373/Cursor"
$TaskName = "CryptoSignalsGitHubScan"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root = Split-Path -Parent $ScriptDir
$PatFile = Join-Path $Root ".github_pat"

Write-Host ""
Write-Host "=== Настройка Windows Task Scheduler (каждые 15 мин) ===" -ForegroundColor Cyan
Write-Host ""

if (-not (Test-Path $PatFile)) {
    Write-Host "Создай файл .github_pat в корне проекта с токеном ghp_..." -ForegroundColor Yellow
    Write-Host "Токен: https://github.com/settings/tokens (scope: repo)" -ForegroundColor Yellow
    Write-Host ""
    $pat = Read-Host "Или вставь токен сейчас (Enter = пропустить)"
    if ($pat) {
        Set-Content -Path $PatFile -Value $pat.Trim() -NoNewline
        Write-Host "Сохранено в .github_pat (файл в .gitignore)" -ForegroundColor Green
    } else {
        Write-Host "Пропуск. Настрой Vercel cron: deploy/VERCEL_CRON.md" -ForegroundColor Yellow
        exit 1
    }
}

$TriggerScript = Join-Path $ScriptDir "trigger_github_scan.ps1"
$Action = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$TriggerScript`""

$Trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) `
    -RepetitionInterval (New-TimeSpan -Minutes 15) `
    -RepetitionDuration ([TimeSpan]::MaxValue)

Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger `
    -Description "Budit GitHub crypto-signals scan every 15 min" -Force | Out-Null

Write-Host "Задача '$TaskName' создана (каждые 15 мин, пока ПК включён)." -ForegroundColor Green
Write-Host "Для облака без ПК: deploy/VERCEL_CRON.md" -ForegroundColor Cyan
