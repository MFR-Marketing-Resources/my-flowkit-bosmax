$repoRoot = Split-Path $PSScriptRoot -Parent
cd $repoRoot

if (Test-Path ".\.venv\Scripts\python.exe") {
    Write-Host "Activating virtual environment..."
    & ".\.venv\Scripts\python.exe" -m agent.main
} else {
    Write-Host "Virtual environment not found. Running with system python..."
    python -m agent.main
}

Write-Host "Backend target: http://127.0.0.1:8100/health"
