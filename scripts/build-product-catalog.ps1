# Build Product Catalog Wrapper
Write-Host "Running Product Catalog Builder..." -ForegroundColor Cyan
python scripts/build-product-catalog.py
if ($LASTEXITCODE -eq 0) {
    Write-Host "Catalog built successfully." -ForegroundColor Green
} else {
    Write-Host "Catalog build failed." -ForegroundColor Red
}
