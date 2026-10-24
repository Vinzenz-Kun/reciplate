$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
Set-Location -LiteralPath $root

python -m pip install -q -r requirements.txt pyinstaller
python -m PyInstaller --noconfirm --clean Reciplate.spec

$built = Join-Path $root 'dist\Reciplate.exe'
$dest = Join-Path $root 'Reciplate.exe'
try {
    Copy-Item -LiteralPath $built -Destination $dest -Force
    Write-Host "Built $dest"
} catch {
    Write-Warning "Could not replace Reciplate.exe (is it running?). Use dist\Reciplate.exe or close the app and run Build.ps1 again."
    Write-Host "Built $built"
}
