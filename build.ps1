# Script para construir el ejecutable de Letra Canción
# Uso: .\build.ps1

$ErrorActionPreference = "Stop"

Write-Host "🎵 Construcción del ejecutable de Letra Canción" -ForegroundColor Cyan
Write-Host "=============================================" -ForegroundColor Cyan
Write-Host ""

# Ir al directorio del proyecto
Set-Location $PSScriptRoot

# 1. Crear entorno virtual si no existe
if (-not (Test-Path ".venv")) {
    Write-Host "🔧 Creando entorno virtual..." -ForegroundColor Yellow
    python -m venv .venv
}

# 2. Activar entorno virtual
Write-Host "📦 Activando entorno virtual..." -ForegroundColor Yellow
& ".venv\Scripts\Activate.ps1"

# 3. Instalar/actualizar dependencias
Write-Host "📥 Instalando dependencias..." -ForegroundColor Yellow
pip install -q -r requirements.txt

# 4. Instalar PyInstaller
Write-Host "🔨 Instalando PyInstaller..." -ForegroundColor Yellow
pip install -q pyinstaller

# 5. Limpiar compilaciones anteriores
if (Test-Path "build") {
    Write-Host "🧹 Limpiando compilación anterior..." -ForegroundColor Yellow
    Remove-Item build -Recurse -Force
}
if (Test-Path "dist") {
    Remove-Item dist -Recurse -Force
}

# 6. Construir el ejecutable
Write-Host "🚀 Compilando ejecutable..." -ForegroundColor Green
pyinstaller app.spec

# 7. Verificar éxito
if (Test-Path "dist\LetraCancion") {
    Write-Host ""
    Write-Host "✅ ¡Éxito! Ejecutable creado:" -ForegroundColor Green
    Write-Host ""
    Write-Host "📁 Ubicación: ./dist/LetraCancion/" -ForegroundColor Cyan
    Write-Host "🚀 Ejecutable: ./dist/LetraCancion/LetraCancion.exe" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "Opciones:" -ForegroundColor Yellow
    Write-Host "  • Doble clic en LetraCancion.exe para ejecutar" -ForegroundColor White
    Write-Host "  • Crear acceso directo en el escritorio" -ForegroundColor White
    Write-Host "  • Anclar a inicio" -ForegroundColor White
    Write-Host ""
} else {
    Write-Host "❌ Error en la compilación" -ForegroundColor Red
    exit 1
}
