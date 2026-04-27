# Smart Task Hub - Submodule Test Script
# Usage: .\run_tests.ps1

$env:PYTHONPATH = "."
$env:DB_NAME = "smart_task_test"
$env:DB_HOST = "localhost"
$env:DB_PORT = "5433"
$env:DB_USER = "smart_user"
$env:DB_PASSWORD = "smart_pass"

Write-Host ">>> Running Smart Task Hub Integration & Domain Tests..." -ForegroundColor Cyan

# Run all tests in the local tests/ directory
uv run pytest -s -v tests/
