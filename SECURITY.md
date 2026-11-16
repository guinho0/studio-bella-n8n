# Segurança

## Reportar uma vulnerabilidade

Não abra uma issue pública. Use **Security → Report a vulnerability** neste repositório
(reporte privado do GitHub). Respondo assim que possível.

## Como o projeto trata segredos

- **Nenhum segredo é versionado.** Chaves e tokens ficam no `.env` (ignorado pelo Git); o
  [`.env.example`](.env.example) só lista os nomes das variáveis.
- **Credenciais do n8n ficam cifradas** no volume do n8n. Os workflows versionados em
  [`n8n/workflows/`](n8n/workflows/) referenciam credenciais só pelo nome, e IDs pessoais
  (planilha, agenda, chat do dono) vêm de variáveis de ambiente.
- **Segredos não passam pela linha de comando.** Os scripts gravam o `.env` com entrada oculta
  e passam tokens aos containers por variável de ambiente, nunca como argumento.
- **Superfície pública mínima.** O túnel expõe só `/webhook/*` (filtrado por nginx); o editor do
  n8n e a API do agente ficam presos em `127.0.0.1`.
- **Ações irreversíveis exigem confirmação em código.** Agendar e cancelar só acontecem depois que o
  cliente confirma numa mensagem posterior, o que resiste a prompt injection. As tools usam o
  telefone do contexto da conversa, nunca um parâmetro do modelo, então um cliente não age em nome
  de outro.

Se você usar este projeto, gere suas próprias chaves e não reaproveite as de outra pessoa.
