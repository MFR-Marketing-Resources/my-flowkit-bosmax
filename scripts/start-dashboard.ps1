$repoRoot = Split-Path $PSScriptRoot -Parent
cd "$repoRoot\dashboard"

Write-Host "Starting dashboard..."
npm run dev -- --host 127.0.0.1 --port 5173

Write-Host "Dashboard target: http://127.0.0.1:5173/operator"
