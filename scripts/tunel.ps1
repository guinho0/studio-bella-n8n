<#
Coloca o bot no ar: sobe o túnel HTTPS (cloudflared), descobre a URL pública,
grava em WEBHOOK_URL no .env e reinicia o n8n para ele registrar o webhook no Telegram.

A URL do quick tunnel muda a cada start do cloudflared, então rode este script
sempre que ligar o PC / o Docker.

Uso:  .\scripts\tunel.ps1
#>
Set-Location (Split-Path -Parent $PSScriptRoot)
. "$PSScriptRoot\_comum.ps1"

docker compose --profile tunel up -d
if ($LASTEXITCODE -ne 0) { throw 'docker compose falhou. O Docker Desktop está aberto?' }

# O cloudflared imprime a URL nos logs alguns segundos depois de conectar.
# Lemos só os logs desde o ÚLTIMO start do container: um container parado e religado
# guarda os logs antigos, com a URL antiga (que não funciona mais).
$inicio = (docker inspect -f '{{.State.StartedAt}}' (docker compose ps -q cloudflared)).Trim()
$url = $null
for ($i = 0; $i -lt 30 -and -not $url; $i++) {
    Start-Sleep -Seconds 2
    $logs = (docker compose logs --since $inicio cloudflared 2>&1 | Out-String)
    $achada = [regex]::Match($logs, 'https://[a-z0-9-]+\.trycloudflare\.com')
    if ($achada.Success) { $url = $achada.Value + '/' }
}
if (-not $url) { throw 'Não achei a URL do túnel. Veja: docker compose logs cloudflared' }
Write-Host "Túnel: $url" -ForegroundColor Green

if ((Ler-Env 'WEBHOOK_URL') -ne $url) {
    Gravar-Env 'WEBHOOK_URL' $url
    Write-Host 'WEBHOOK_URL atualizado no .env; recriando o n8n...'
    docker compose --profile tunel up -d n8n   # env mudou => o compose recria o container
}
Aguardar-N8n

# Confere com o próprio Telegram para onde ele está entregando as mensagens.
$token = Ler-Env 'TELEGRAM_BOT_TOKEN'
if (-not $token) {
    Write-Warning 'TELEGRAM_BOT_TOKEN vazio no .env: o túnel está no ar, mas não há bot configurado.'
    return
}
$info = $null
for ($i = 0; $i -lt 15; $i++) {
    $info = (Invoke-RestMethod "https://api.telegram.org/bot$token/getWebhookInfo").result
    if ($info.url -and $info.url.StartsWith($url)) { break }
    Start-Sleep -Seconds 2
}
if ($info.url -and $info.url.StartsWith($url)) {
    Write-Host "Webhook do Telegram OK: $($info.url)" -ForegroundColor Green
    Write-Host 'Mande uma mensagem para o bot!'
} else {
    Write-Warning "O Telegram ainda aponta para '$($info.url)'. O workflow está publicado? Rode .\scripts\importar_n8n.ps1"
}
