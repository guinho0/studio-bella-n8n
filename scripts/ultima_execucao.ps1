<#
Mostra as últimas execuções do fluxo de atendimento e, para cada uma, os nós que rodaram
e os erros, inclusive os que o "continuar em caso de erro" deixa passar em silêncio.
Requer N8N_API_KEY no .env (.\scripts\definir_segredo.ps1 N8N_API_KEY).

Uso:  .\scripts\ultima_execucao.ps1          # a última do atendimento
      .\scripts\ultima_execucao.ps1 -Quantas 3
      .\scripts\ultima_execucao.ps1 -Fluxo LembreteDiario01   # ou RelatorioSemanal
#>
param([int]$Quantas = 1, [string]$Fluxo = 'AtendimentoTg001')
Set-Location (Split-Path -Parent $PSScriptRoot)
. "$PSScriptRoot\_comum.ps1"

$chave = Ler-Env 'N8N_API_KEY'
if (-not $chave) { throw 'Defina N8N_API_KEY: .\scripts\definir_segredo.ps1 N8N_API_KEY' }
$h = @{ 'X-N8N-API-KEY' = $chave }
$base = 'http://localhost:5678/api/v1/executions'

$lista = (Invoke-RestMethod "$base`?limit=$Quantas&workflowId=$Fluxo" -Headers $h).data
foreach ($e in $lista) {
    $d = Invoke-RestMethod "$base/$($e.id)?includeData=true" -Headers $h
    $inicio = ([datetime]$e.startedAt).ToLocalTime().ToString('dd/MM HH:mm:ss')
    Write-Host "`n=== execução #$($e.id)  $inicio  [$($e.status)]" -ForegroundColor Cyan
    foreach ($p in $d.data.resultData.runData.PSObject.Properties) {
        $run = $p.Value[0]
        $primeiro = $null
        foreach ($saida in @($run.data.main)) { if ($saida -and @($saida).Count) { $primeiro = @($saida)[0].json; break } }
        if ($run.error) {
            Write-Host ("  ✗ {0}: {1}" -f $p.Name, $run.error.message) -ForegroundColor Red
        } elseif ($primeiro -and $primeiro.error) {
            $msg = if ($primeiro.error.message) { $primeiro.error.message } else { "$($primeiro.error)" }
            Write-Host ("  ⚠ {0}: {1}" -f $p.Name, $msg) -ForegroundColor Yellow
        } else {
            Write-Host "  ✓ $($p.Name)"
        }
    }
}
