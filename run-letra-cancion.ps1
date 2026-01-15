# Script para ejecutar Letra Canción rápidamente
# Uso: .\run.ps1

$ErrorActionPreference = "Stop"

# Ir al directorio del proyecto
Set-Location $PSScriptRoot

# Verificar si existe el entorno virtual
if (-not (Test-Path ".venv")) {
    Write-Host "🔧 Creando entorno virtual..." -ForegroundColor Yellow
    python -m venv .venv
    
    Write-Host "📦 Instalando dependencias..." -ForegroundColor Yellow
    & ".venv\Scripts\pip.exe" install -r requirements.txt
}

# Activar entorno virtual y ejecutar
Write-Host "🎵 Iniciando Letra Canción..." -ForegroundColor Green
& ".venv\Scripts\Activate.ps1"
python -m src.main
