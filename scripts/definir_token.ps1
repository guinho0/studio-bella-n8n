<#
Pede o token do bot (entrada oculta), valida no Telegram e grava em TELEGRAM_BOT_TOKEN no .env.

Uso:  .\scripts\definir_token.ps1
#>
Set-Location (Split-Path -Parent $PSScriptRoot)
. "$PSScriptRoot\_comum.ps1"

Write-Host 'Cole o token do @BotFather e tecle Enter. Ele NÃO aparece na tela.'
Write-Host 'Dica: no terminal do VS Code, cole com o botão direito do mouse (ou Ctrl+Shift+V).' -ForegroundColor DarkGray
$seguro = Read-Host 'Token' -AsSecureString
$entrada = [Runtime.InteropServices.Marshal]::PtrToStringAuto(
    [Runtime.InteropServices.Marshal]::SecureStringToBSTR($seguro))

# Aceita o token mesmo com texto em volta (ex.: copiou a frase inteira do BotFather).
$achado = [regex]::Match($entrada, '\d{6,12}:[A-Za-z0-9_-]{30,}')
if (-not $achado.Success) {
    if (-not $entrada.Trim()) { throw 'Nada foi colado (entrada vazia). Tente colar com o botão direito do mouse.' }
    throw ("Não achei um token no que foi colado ({0} caracteres, contém ':'? {1}). " +
           'O formato é 123456789:AAH... (números, dois-pontos, ~35 letras).') -f $entrada.Length, $entrada.Contains(':')
}
$token = $achado.Value
try {
    $bot = (Invoke-RestMethod "https://api.telegram.org/bot$token/getMe").result
} catch {
    throw 'O Telegram recusou o token. Confira se copiou a linha inteira.'
}
Gravar-Env 'TELEGRAM_BOT_TOKEN' $token
Write-Host "Token salvo no .env. Bot: @$($bot.username)" -ForegroundColor Green
