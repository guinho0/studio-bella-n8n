# Funções compartilhadas pelos scripts. Não rode este arquivo diretamente.

function Ler-Env([string]$nome) {
    $linha = Select-String -Path .env -Pattern "^$nome=(.*)$" | Select-Object -First 1
    if ($linha) { return $linha.Matches[0].Groups[1].Value.Trim() }
    return ''
}

function Gravar-Env([string]$nome, [string]$valor) {
    $caminho = (Resolve-Path .env).Path
    $texto = [IO.File]::ReadAllText($caminho)
    if ($texto -match "(?m)^$nome=") {
        $texto = $texto -replace "(?m)^$nome=[^\r\n]*", "$nome=$valor"
    } else {
        if ($texto -and -not $texto.EndsWith("`n")) { $texto += "`r`n" }
        $texto += "$nome=$valor`r`n"
    }
    [IO.File]::WriteAllText($caminho, $texto, (New-Object Text.UTF8Encoding $false))
}

function Aguardar-N8n([int]$segundos = 90) {
    $limite = (Get-Date).AddSeconds($segundos)
    while ((Get-Date) -lt $limite) {
        $code = curl.exe -s -o NUL -w '%{http_code}' http://localhost:5678/healthz
        if ($code -eq '200') { return }
        Start-Sleep -Seconds 2
    }
    throw "O n8n não respondeu em $segundos s. Veja: docker compose logs n8n"
}
