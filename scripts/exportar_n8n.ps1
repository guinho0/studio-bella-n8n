<#
Exporta os workflows do n8n para n8n/workflows/ (um JSON por workflow, nomeado pelo ID),
para versionar no Git o que você editou pela interface. Credenciais NUNCA são exportadas.

Uso:  .\scripts\exportar_n8n.ps1    depois:  git diff n8n/workflows
#>
Set-Location (Split-Path -Parent $PSScriptRoot)

docker compose exec -T n8n sh -c 'rm -rf /tmp/exp && n8n export:workflow --all --separate --pretty --output=/tmp/exp/'
if ($LASTEXITCODE -ne 0) { throw 'Falha ao exportar do n8n.' }
docker compose cp n8n:/tmp/exp/. n8n/workflows/
Get-ChildItem n8n/workflows/*.json | ForEach-Object { Write-Host "  $($_.Name)" }
Write-Host 'Exportado. Revise com: git diff n8n/workflows' -ForegroundColor Green
