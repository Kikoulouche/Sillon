# Compile Sillon en application Windows (dossier dist\Sillon + archive zip).
# Usage : .\tools\build.ps1 [-Version 1.2.3]
param([string]$Version = "")
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)

$py = if (Test-Path ".venv\Scripts\python.exe") { ".venv\Scripts\python.exe" } else { "python" }

if ($Version) {
    Set-Content -Path "sillon\__init__.py" -Value "__version__ = `"$Version`"" -Encoding utf8
}
$Version = & $py -c "import sillon; print(sillon.__version__)"
Write-Host "Build de Sillon $Version"

& $py -m PyInstaller --noconfirm --clean --windowed `
    --name Sillon `
    --icon assets\sillon.ico `
    --add-data "assets;assets" `
    --collect-all imageio_ffmpeg `
    --collect-data pymobiledevice3 `
    --collect-submodules yt_dlp `
    --exclude-module tkinter `
    --exclude-module av `
    --exclude-module jedi `
    --exclude-module IPython `
    --exclude-module matplotlib `
    --log-level WARN `
    Sillon.pyw
if ($LASTEXITCODE -ne 0) { throw "PyInstaller a echoue" }

$zip = "dist\Sillon-$Version-windows-x64.zip"
if (Test-Path $zip) { Remove-Item $zip }
Compress-Archive -Path "dist\Sillon" -DestinationPath $zip -CompressionLevel Optimal
Write-Host "OK : $zip ($([math]::Round((Get-Item $zip).Length / 1MB, 1)) Mo)"
