#Requires -Version 5.1
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$PatFile = Join-Path $Root ".github_pat"
$Repo = if ($env:GITHUB_REPO) { $env:GITHUB_REPO } else { "VB737373/Cursor" }

if (-not (Test-Path $PatFile)) { exit 0 }
$pat = (Get-Content $PatFile -Raw).Trim()
if (-not $pat) { exit 0 }

$headers = @{
    Authorization = "Bearer $pat"
    Accept        = "application/vnd.github+json"
    "X-GitHub-Api-Version" = "2022-11-28"
}
$body = '{"event_type":"scan"}'
try {
    Invoke-RestMethod -Uri "https://api.github.com/repos/$Repo/dispatches" `
        -Method Post -Headers $headers -Body $body -ContentType "application/json"
} catch {
    # silent
}
