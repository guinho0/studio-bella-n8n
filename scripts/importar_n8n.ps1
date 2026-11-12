<#
Importa no n8n a credencial do Telegram e os workflows versionados em n8n/workflows/,
e publica o fluxo de atendimento. Rode depois de criar o bot e sempre que mudar os JSONs.

ATENÇÃO: sobrescreve o workflow no n8n. Se você editou pela interface, exporte antes
(scripts/exportar_n8n.ps1) para não perder as mudanças.

Uso:  .\scripts\importar_n8n.ps1
#>
Set-Location (Split-Path -Parent $PSScriptRoot)
. "$PSScriptRoot\_comum.ps1"

$token = Ler-Env 'TELEGRAM_BOT_TOKEN'
if (-not $token) { throw 'Defina TELEGRAM_BOT_TOKEN no .env (token gerado pelo @BotFather).' }

# Valida o token antes de gravar qualquer coisa.
$bot = (Invoke-RestMethod "https://api.telegram.org/bot$token/getMe").result
Write-Host "Bot encontrado: @$($bot.username)" -ForegroundColor Green

# O token entra no container por variável de ambiente (-e NOME, sem valor na linha de
# comando): não aparece em histórico nem no `ps`. O script de shell abaixo NÃO contém
# segredo; vai por arquivo porque o PowerShell 5.1 prefixa um BOM em todo texto enviado
# por pipe a programas nativos, e o sh lê esse BOM como parte do primeiro comando.
$env:TELEGRAM_BOT_TOKEN = $token
$sh = @'
set -e
printf '[{"id":"tgStudioBella001","name":"Telegram Studio Bella","type":"telegramApi","data":{"accessToken":"%s","baseUrl":"https://api.telegram.org"}}]' "$TELEGRAM_BOT_TOKEN" > /tmp/cred.json
trap 'rm -f /tmp/cred.json' EXIT
n8n import:credentials --input=/tmp/cred.json
n8n import:workflow --separate --input=/workflows
n8n publish:workflow --id=AtendimentoTg001
'@
$arquivo = Join-Path $env:TEMP 'importar_n8n.sh'
[IO.File]::WriteAllText($arquivo, ($sh -replace "`r", ''), (New-Object Text.UTF8Encoding $false))
docker compose cp $arquivo n8n:/tmp/importar_n8n.sh | Out-Null
Remove-Item $arquivo
docker compose exec -T -e TELEGRAM_BOT_TOKEN n8n sh /tmp/importar_n8n.sh
$rc = $LASTEXITCODE
Remove-Item Env:TELEGRAM_BOT_TOKEN
if ($rc -ne 0) { throw "Falha ao importar no n8n (código $rc)." }

Write-Host 'Workflow "Atendimento Telegram" importado e publicado.' -ForegroundColor Green

# Ao publicar, o n8n registra o webhook no Telegram. Conferimos com o próprio Telegram.
$url = Ler-Env 'WEBHOOK_URL'
if (-not $url.StartsWith('https://')) {
    Write-Warning 'WEBHOOK_URL não é HTTPS: o Telegram não entrega mensagens. Rode .\scripts\tunel.ps1'
    return
}
for ($i = 0; $i -lt 20; $i++) {
    $info = (Invoke-RestMethod "https://api.telegram.org/bot$token/getWebhookInfo").result
    if ($info.url -and $info.url.StartsWith($url)) { break }
    Start-Sleep -Seconds 2
}
if ($info.url -and $info.url.StartsWith($url)) {
    Write-Host "Webhook do Telegram OK: $($info.url)" -ForegroundColor Green
    Write-Host "Mande uma mensagem para @$($bot.username)!"
} else {
    Write-Warning "O Telegram aponta para '$($info.url)'. Veja: docker compose logs n8n --tail 50"
}
