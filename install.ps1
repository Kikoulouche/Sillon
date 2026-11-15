# Installe (ou reinstalle) la derniere version de Sillon.
# Usage, dans PowerShell :
#   irm https://raw.githubusercontent.com/Kikoulouche/Sillon/main/install.ps1 | iex
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
$repo = "Kikoulouche/Sillon"
$dest = Join-Path $env:LOCALAPPDATA "Programs\Sillon"

Write-Host "Recherche de la derniere version de Sillon..."
$rel = Invoke-RestMethod "https://api.github.com/repos/$repo/releases/latest" -Headers @{ "User-Agent" = "Sillon-installer" }
$asset = $rel.assets | Where-Object { $_.name -like "*windows-x64.zip" } | Select-Object -First 1
if (-not $asset) { throw "Aucune archive Windows dans la release $($rel.tag_name)" }

$zip = Join-Path $env:TEMP "sillon-install.zip"
Write-Host "Telechargement de Sillon $($rel.tag_name) ($([math]::Round($asset.size / 1MB)) Mo)..."
Invoke-WebRequest $asset.browser_download_url -OutFile $zip

Get-Process Sillon -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep -Milliseconds 500
if (Test-Path $dest) { Remove-Item $dest -Recurse -Force }
Expand-Archive $zip -DestinationPath (Split-Path $dest) -Force
Remove-Item $zip

$ws = New-Object -ComObject WScript.Shell
foreach ($dir in @([Environment]::GetFolderPath("Desktop"), (Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs"))) {
    $lnk = $ws.CreateShortcut((Join-Path $dir "Sillon.lnk"))
    $lnk.TargetPath = Join-Path $dest "Sillon.exe"
    $lnk.WorkingDirectory = $dest
    $lnk.Description = "Sillon - ta musique sur ton iPhone"
    $lnk.Save()
}

if (-not (Get-Service "Apple Mobile Device Service" -ErrorAction SilentlyContinue) -and -not (Get-AppxPackage *AppleInc.iTunes*)) {
    Write-Host "Attention : iTunes n'est pas installe. Il est necessaire pour parler a l'iPhone :" -ForegroundColor Yellow
    Write-Host "  winget install 9PB2MZ1ZMB1S   (ou depuis le Microsoft Store)" -ForegroundColor Yellow
}

Write-Host "Sillon $($rel.tag_name) est installe. Raccourcis crees sur le bureau et dans le menu Demarrer." -ForegroundColor Green
Start-Process (Join-Path $dest "Sillon.exe")
