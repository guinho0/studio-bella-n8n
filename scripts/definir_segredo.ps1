<#
Grava um segredo no .env pedindo o valor com entrada oculta (não aparece na tela
nem no histórico do terminal).

Uso:  .\scripts\definir_segredo.ps1 N8N_API_KEY
#>
param([Parameter(Mandatory)][string]$Nome)
Set-Location (Split-Path -Parent $PSScriptRoot)
. "$PSScriptRoot\_comum.ps1"

Write-Host "Cole o valor de $Nome e tecle Enter. Ele NÃO aparece na tela."
Write-Host 'Dica: no terminal do VS Code, cole com o botão direito do mouse (ou Ctrl+Shift+V).' -ForegroundColor DarkGray
$seguro = Read-Host $Nome -AsSecureString
$valor = [Runtime.InteropServices.Marshal]::PtrToStringAuto(
    [Runtime.InteropServices.Marshal]::SecureStringToBSTR($seguro)).Trim()
if (-not $valor) { throw 'Nada foi colado (entrada vazia). Tente colar com o botão direito do mouse.' }

if ($Nome -eq 'N8N_API_KEY') {
    $code = curl.exe -s -o NUL -w '%{http_code}' -H "X-N8N-API-KEY: $valor" 'http://localhost:5678/api/v1/workflows?limit=1'
    if ($code -ne '200') { throw "O n8n recusou a chave (HTTP $code). Confira se copiou a chave inteira." }
}
Gravar-Env $Nome $valor
Write-Host "$Nome salvo no .env ($($valor.Length) caracteres)." -ForegroundColor Green
