<#
Importa no n8n a credencial do Telegram e os workflows versionados em n8n/workflows/,
e publica o fluxo de atendimento. Rode depois de criar o bot e sempre que mudar os JSONs.

As credenciais do Google (OAuth) são criadas pela interface do n8n; aqui elas são
encontradas PELO NOME e ligadas aos nós, então o mesmo JSON funciona em qualquer instalação:
  "Google Calendar Studio Bella"  (Google Calendar OAuth2 API)
  "Google Sheets Studio Bella"    (Google Sheets OAuth2 API)

ATENÇÃO: sobrescreve os workflows no n8n. Se você editou pela interface, exporte antes
(scripts/exportar_n8n.ps1) para não perder as mudanças.

Uso:  .\scripts\importar_n8n.ps1
#>
Set-Location (Split-Path -Parent $PSScriptRoot)
. "$PSScriptRoot\_comum.ps1"

$token = Ler-Env 'TELEGRAM_BOT_TOKEN'
if (-not $token) { throw 'Defina TELEGRAM_BOT_TOKEN no .env (.\scripts\definir_token.ps1).' }

# Valida o token antes de gravar qualquer coisa.
$bot = (Invoke-RestMethod "https://api.telegram.org/bot$token/getMe").result
Write-Host "Bot encontrado: @$($bot.username)" -ForegroundColor Green

# ---------- 1. Credenciais com segredo do .env: Telegram e Gemini ----------
# Os segredos entram no container por variável de ambiente (-e NOME, sem valor na linha
# de comando): não aparecem em histórico nem no `ps`. O script de shell abaixo NÃO contém
# segredo; vai por arquivo porque o PowerShell 5.1 prefixa um BOM em todo texto enviado
# por pipe a programas nativos, e o sh lê esse BOM como parte do primeiro comando.
# A chave do Gemini é a mesma que a API do agente usa (OPENAI_API_KEY, endpoint compatível).
$env:TELEGRAM_BOT_TOKEN = $token
$env:GEMINI_API_KEY = if ((Ler-Env 'OPENAI_BASE_URL') -match 'generativelanguage') { Ler-Env 'OPENAI_API_KEY' } else { '' }
if (-not $env:GEMINI_API_KEY) { Write-Warning 'Sem chave do Gemini no .env: o relatório semanal sairá só com os números.' }
$sh = @'
set -e
trap 'rm -f /tmp/cred.json' EXIT
printf '[{"id":"tgStudioBella001","name":"Telegram Studio Bella","type":"telegramApi","data":{"accessToken":"%s","baseUrl":"https://api.telegram.org"}}]' "$TELEGRAM_BOT_TOKEN" > /tmp/cred.json
n8n import:credentials --input=/tmp/cred.json
if [ -n "$GEMINI_API_KEY" ]; then
  printf '[{"id":"geminiStudioBe01","name":"Gemini Studio Bella","type":"googlePalmApi","data":{"apiKey":"%s","host":"https://generativelanguage.googleapis.com"}}]' "$GEMINI_API_KEY" > /tmp/cred.json
  n8n import:credentials --input=/tmp/cred.json
fi
'@
$arquivo = Join-Path $env:TEMP 'importar_cred.sh'
[IO.File]::WriteAllText($arquivo, ($sh -replace "`r", ''), (New-Object Text.UTF8Encoding $false))
docker compose cp $arquivo n8n:/tmp/importar_cred.sh | Out-Null
Remove-Item $arquivo
docker compose exec -T -e TELEGRAM_BOT_TOKEN -e GEMINI_API_KEY n8n sh /tmp/importar_cred.sh
$rc = $LASTEXITCODE
Remove-Item Env:TELEGRAM_BOT_TOKEN, Env:GEMINI_API_KEY
# Arquivos copiados com `docker cp` pertencem ao root; o n8n roda sem privilégios.
docker compose exec -T -u root n8n rm -f /tmp/importar_cred.sh
if ($rc -ne 0) { throw "Falha ao importar as credenciais (código $rc)." }

# ---------- 2. Liga as credenciais aos nós, pelo nome ----------
# export:credentials SEM --decrypted: os dados saem cifrados; só usamos id, nome e tipo.
$json = docker compose exec -T n8n sh -c 'n8n export:credentials --all --output=/tmp/creds.json >/dev/null 2>&1; cat /tmp/creds.json; rm -f /tmp/creds.json'
$creds = @(($json | Out-String) | ConvertFrom-Json)

$temp = Join-Path $env:TEMP 'n8n_workflows'
Remove-Item $temp -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory $temp | Out-Null
$faltando = @{}
foreach ($wf in Get-ChildItem n8n/workflows/*.json) {
    $texto = [IO.File]::ReadAllText($wf.FullName, [Text.Encoding]::UTF8)
    $nomes = [regex]::Matches($texto, '"id":\s*"[^"]*",\s*"name":\s*"([^"]+)"') | ForEach-Object { $_.Groups[1].Value } | Sort-Object -Unique
    foreach ($nome in $nomes) {
        $c = $creds | Where-Object { $_.name -eq $nome } | Select-Object -First 1
        if (-not $c) {
            if ($nome -match 'Studio Bella') { $faltando[$nome] = $true }  # só nomes de credencial
            continue
        }
        $padrao = '"id":\s*"[^"]*",(\s*)"name":\s*"' + [regex]::Escape($nome) + '"'
        $texto = [regex]::Replace($texto, $padrao, ('"id": "' + $c.id + '",$1"name": "' + $nome + '"'))
    }
    [IO.File]::WriteAllText((Join-Path $temp $wf.Name), $texto, (New-Object Text.UTF8Encoding $false))
}
if ($faltando.Count) {
    # O n8n 2.x recusa publicar com credencial inexistente, e o import DESATIVA a versão
    # em produção. Abortar aqui mantém o bot no ar com o fluxo que já estava publicado.
    Remove-Item $temp -Recurse -Force
    throw ("Crie no n8n (Credentials) antes de importar: " + (($faltando.Keys | ForEach-Object { "'$_'" }) -join ', ') +
           '. Nada foi alterado; o fluxo publicado continua no ar.')
}

# ---------- 3. Importa e publica ----------
docker compose exec -T -u root n8n rm -rf /tmp/wf
docker compose cp "$temp" n8n:/tmp/wf | Out-Null
Remove-Item $temp -Recurse -Force
# Publica todos os workflows versionados (o ID de cada um é o nome do arquivo).
$ids = (Get-ChildItem n8n/workflows/*.json | ForEach-Object { $_.BaseName }) -join ' '
docker compose exec -T n8n sh -c "n8n import:workflow --separate --input=/tmp/wf && for id in $ids; do n8n publish:workflow --id=`$id || exit 1; done"
$rc = $LASTEXITCODE
docker compose exec -T -u root n8n rm -rf /tmp/wf
if ($rc -ne 0) { throw "Falha ao importar/publicar os workflows (código $rc)." }
Write-Host "Workflows importados e publicados: $ids" -ForegroundColor Green

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
