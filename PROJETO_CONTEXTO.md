# PROJETO_CONTEXTO — ia_agent ("Studio Bella - n8n")

> Documento de continuidade escrito em 24/11/2026 a partir do código, do `git log` e do histórico
> de conversas com o Claude (11/11 a 16/11/2026). Leitor principal: o Claude numa sessão nova, sem contexto.

## Resumo

- **O que é:** atendente virtual com IA para pequenos negócios; o exemplo é o **Studio Bella** (salão de beleza).
  Pelo Telegram, tira dúvidas, consulta horários, **agenda e cancela** (com confirmação) e transfere para humano.
  O **n8n** orquestra canal, Google Calendar, Google Sheets, alertas ao dono, lembrete D-1 e relatório semanal por IA.
- **Para quem / objetivo:** projeto de portfólio do Thiago, feito para a candidatura à vaga **iFood GenAI (trilha AI Builder, residência)**,
  inscrição em **16/11/2026**. A vaga pedia experiência com n8n; o projeto existe para provar isso e para ser defendido em entrevista.
- **Status:** **concluído como MVP de portfólio e publicado** no GitHub (público) em 16/11/2026. Roda só localmente (Docker + túnel);
  não há deploy permanente. Pendências pequenas: 2 prints com dado pessoal fora do repo, vídeo demo não feito.
- **Última atividade:** 16/11/2026 (commit `ca6037f` + publicação no GitHub). Nada mudou depois disso; `git status` limpo.

## Stack e arquitetura

- **Python 3.12**: agente com LLM + *tool calling*, SQLite, API **FastAPI** (uvicorn, app factory `api.main:criar_app`).
- **LLM:** Gemini (plano grátis) via endpoint compatível com OpenAI (`openai` SDK). Camada de provedor neutra suporta também
  Ollama e Anthropic (`anthropic` SDK) — trocar é só mudar o `.env`.
- **n8n 2.47.3** (versão fixada) em Docker; **nginx 1.31.8** (só deixa passar `/webhook/*`); **cloudflared 2026.10.7** (quick tunnel, URL muda a cada start).
- **Docker Compose** (`name: ia-agent`): serviços `api`, `n8n` e, no profile `tunel`, `webhook-proxy` (nginx) e `cloudflared`.
  Portas presas em `127.0.0.1` (n8n :5678, API :8000). Volumes: `api_dados` (SQLite) e `n8n_data` (workflows, credenciais cifradas, conta do dono).
- **Scripts em PowerShell** (Windows) para túnel, import/export de workflows e segredos.

Fluxo: `Telegram → cloudflared → nginx → n8n (Telegram Trigger) → POST http://api:8000/mensagem → {resposta, eventos[]}` →
n8n responde e ramifica por `eventos[].tipo`:
- `agendamento_criado` → evento no Google Calendar + linha na planilha (aba `Agendamentos`)
- `agendamento_cancelado` → apaga evento do Calendar (pelo id guardado na planilha) + marca `cancelado`
- `transferido_humano` → alerta ao dono no Telegram; robô fica mudo com aquele cliente; dono usa `/responder <id> <texto>` e `/liberar <id>`

Mapa de pastas:
```
agente/       agente.py (loop, processar() -> Resultado(resposta, eventos)), tools.py (validação + eventos + confirmação em 2 etapas),
              llm.py (adaptadores + fallback/circuit breaker + thought_signature do Gemini 3), prompt.py, banco.py (SQLite + migração aditiva), config.py
api/main.py   rotas: POST /mensagem, GET /agendamentos?data=, GET /conversas?desde=, GET /metricas?desde=, POST /conversas/{telefone}/liberar, GET /health
n8n/workflows/ AtendimentoTg001.json, LembreteDiario01.json (18h), RelatorioSemanal.json (seg 8h)   | n8n/proxy-webhook.conf (nginx)
avaliacao/    casos.py + rodar.py: eval de 10 conversas contra o LLM real; resultados.md (10/10 em 13/11/2026)
scripts/      tunel.ps1, importar_n8n.ps1, exportar_n8n.ps1, definir_token.ps1, definir_segredo.ps1, ultima_execucao.ps1, _comum.ps1
tests/        73 testes pytest com LLM falso (tests/fakes.py) — não gastam API
negocio/      negocio.json (serviços, preços, horários) + faq.md — trocar de cliente = trocar esta pasta
chat_terminal.py  conversa com o agente no terminal (mostra tools chamadas)
docs/img/     prints do README (atendimento.png e relatorio.png versionados; telegram.png e planilha.png NÃO)
```

## Como rodar

Pré-requisitos: Docker Desktop, Python 3.12, Git, conta Telegram, conta Google (para Calendar/Sheets), chave Gemini.

```powershell
copy .env.example .env                    # preencher (ver variáveis abaixo)
docker compose up -d --build              # n8n http://localhost:5678 | API http://localhost:8000/docs
.\scripts\definir_token.ps1               # grava TELEGRAM_BOT_TOKEN com entrada oculta e valida no Telegram
# criar a conta de dono no n8n em http://localhost:5678 (conta local)
.\scripts\tunel.ps1                       # sobe túnel, grava WEBHOOK_URL, confere/corrige webhook no Telegram (rodar SEMPRE que ligar o PC)
.\scripts\importar_n8n.ps1                # cria credenciais Telegram/Gemini, importa e publica os 3 workflows
.\scripts\ultima_execucao.ps1             # depura execuções nó a nó (precisa N8N_API_KEY); aceita -Quantas N e parâmetro de qual fluxo
docker compose --profile tunel stop       # desliga tudo
```

Desenvolvimento sem Docker:
```powershell
python -m venv .venv; .\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
pytest                                    # 73 testes, sem LLM real
python chat_terminal.py
uvicorn api.main:criar_app --factory --reload
$env:PYTHONIOENCODING='utf-8'; python -m avaliacao.rodar   # eval real: GASTA cota do Gemini (~30-40 chamadas); --vezes 3 mede consistência
```

Credenciais Google (OAuth) — criadas **manualmente no n8n**, com estes nomes exatos (o import liga os nós pelo nome):
`Google Calendar Studio Bella` e `Google Sheets Studio Bella`. Passo a passo no README (Google Cloud: projeto, APIs Calendar/Sheets/Drive,
Google Auth Platform externo com o próprio Gmail como usuário de teste, cliente "Aplicativo da Web" com redirect
`http://localhost:5678/rest/oauth2-credential/callback`). Planilha com aba `Agendamentos` e cabeçalho
`id_agendamento, status, nome_cliente, servico, inicio, fim, preco, telefone, calendar_evento_id, atualizado_em`.

Variáveis de ambiente (`.env`, ignorado pelo Git; modelo em `.env.example`) — **só nomes**:

| Variável | Onde obter |
|---|---|
| `LLM_PROVEDOR`, `LLM_MODELO`, `LLM_MODELOS_RESERVA`, `LLM_TIMEOUT_S`, `OPENAI_BASE_URL` | não são segredos; valores sugeridos no `.env.example` (Gemini: `openai` + `gemini-3.5-flash`, reservas `gemini-3.5-flash-lite,gemini-3.1-flash-lite`, timeout 25) |
| `OPENAI_API_KEY` | chave do Gemini em https://aistudio.google.com (plano grátis, sem faturamento) |
| `ANTHROPIC_API_KEY` | só se usar Claude (console da Anthropic) |
| `API_TOKEN` | opcional; se preenchido, API exige header `X-API-Key` (hoje NÃO está no .env local) |
| `WEBHOOK_URL` | preenchida automaticamente pelo `tunel.ps1` |
| `TELEGRAM_BOT_TOKEN` | @BotFather no Telegram (`/mybots` → bot → API Token). Gravar com `definir_token.ps1` |
| `DONO_TELEGRAM_CHAT_ID` | chat_id do dono (mande msg ao bot e veja o "telefone" nos logs da API) |
| `GOOGLE_SHEET_ID` | trecho entre `/d/` e `/edit` na URL da planilha "Studio Bella - Agendamentos" |
| `GOOGLE_CALENDAR_ID` | Google Agenda → agenda "Studio Bella" → Configurações → Integrar agenda → ID (formato `...@group.calendar.google.com`) |
| `N8N_API_KEY` | n8n → Settings → n8n API → Create API key (gravar com `.\scripts\definir_segredo.ps1 N8N_API_KEY`) |

## Infra, deploy e serviços externos

- **GitHub:** https://github.com/guinho0/studio-bella-n8n (público, branch `main`, conta `guinho0`). Ativados: push protection de segredos,
  Dependabot (`.github/dependabot.yml`), reporte privado de vulnerabilidades (`SECURITY.md`), tópicos n8n/ai-agent/llm/telegram-bot/fastapi/gemini/automation.
- **Hospedagem:** nenhuma. Tudo local, custo zero (decisão de projeto). Bot só fica no ar com o PC ligado + `tunel.ps1`.
- **Telegram:** bot "Studio bella Demo", link `t.me/studiobella_bot` (há um bot de terceiros chamado "Salão Bella" — não confundir).
- **Google Cloud:** projeto `studio-bella-n8n` (OAuth em modo teste), agenda dedicada "Studio Bella", planilha "Studio Bella - Agendamentos" — tudo na conta Google pessoal do Thiago.
- **Gemini API:** plano grátis (Google AI Studio). Sofre 503/429/timeout em horário de pico.
- **Deploy de mudanças:** código da API → `docker compose up -d --build api`; workflows → editar JSON em `n8n/workflows/` e rodar `importar_n8n.ps1`
  (ou editar no editor do n8n e rodar `exportar_n8n.ps1` para versionar).

## Histórico e decisões importantes

Linha do tempo (plano de 7 dias em `C:\Users\Thiago Carvalho\Desktop\linkedin[\plano_n8n.md`, fora deste repo):
- **Antes de 10/11/2026:** já existia o agente Python (Fase 1, terminal, sem git, com Ollama).
- **10/11 (dia 1, `e43e19b`):** `git init`, API FastAPI com `eventos[]`, testes, Dockerfile + compose. Gemini 2.5 estava aposentado (404) → `gemini-3.5-flash`; corrigido o 400 da `thought_signature` do Gemini 3 só no adaptador `llm.py`.
- **12/11 (dia 2, `db99752`):** bot Telegram no ar via n8n + cloudflared + nginx; fallback de modelos com quarentena de 2 min.
- **12/11 (dia 3, `d9529de`):** Calendar + Sheets + handoff ao dono (`/responder`, `/liberar`); prompt passou a marcar HOJE/AMANHÃ.
- **13/11 (`a2c2ebb`):** fix do `tunel.ps1` (n8n reiniciado não refaz setWebhook; script compara com `getWebhookInfo` e republica).
- **13/11 (dia 4, `e452e96`):** lembrete D-1 (18h) e relatório semanal (seg 8h) com `GET /metricas`; gatilho manual "Testar agora".
- **13–16/11 (dia 5, `ca6037f`):** eval 10/10, confirmação de agendar/cancelar garantida em código, README final, SECURITY.md, Dependabot. Publicado no GitHub em 16/11.
- Obs.: os hashes citados no histórico de conversa (`755664f`, `2bcb8f8`, `1ecfe17`...) **não existem mais**: em 16/11 o histórico foi reescrito (filter-branch) para trocar o e-mail do autor pelo noreply do GitHub. Use os hashes acima.

Decisões (com o porquê):
- **n8n ramifica por `eventos[]` emitidos pelas tools, nunca pelo texto do LLM** — o texto varia; o modelo já escreveu "agendamento garantido!" sem agendar. Eventos só saem depois da gravação no banco.
- **Confirmação em 2 etapas em código** (1ª chamada da tool só cria proposta pendente; só executa se confirmada numa mensagem *posterior*) — a regra começou só no prompt e o modelo reserva "lite" agendou direto em produção (e numa "sexta" da semana errada). Ação irreversível não pode depender da obediência do LLM.
- **Telefone vem do contexto da conversa, não de parâmetro do modelo** — impede agir em nome de outro cliente.
- **Fallback de modelo com circuit breaker** só para 503/429/timeout; 400/401/404 não acionam (seria esconder bug).
- **Números do relatório vêm do SQL; LLM só resume texto** (proibido citar números; clientes anonimizados "Cliente 1, 2…"). Relatório usa `flash-lite`.
- **Sem RAG** de propósito: FAQ cabe no prompt.
- **Nós Google em "continuar em caso de erro"** — cliente já foi respondido; falha fica visível via `ultima_execucao.ps1`.
- **API "casca fina"**, endpoints `def` + uma trava global (LLM bloqueante; evita embaralhar histórico no SQLite). Trade-off: vazão. Falha do LLM → HTTP 502.
- **Versões de imagens fixadas** (n8n 2.47.3 etc.): workflows exportados dependem da versão.
- **`N8N_EDITOR_BASE_URL` fixo em localhost** — senão o callback OAuth do Google ia para a URL do túnel (que bloqueia `/rest/*`).
- **IDs pessoais (planilha, agenda, chat do dono) via `$env`** no n8n (`N8N_BLOCK_ENV_ACCESS_IN_NODE=false`), para os JSONs versionados não terem dados pessoais.
- **`importar_n8n.ps1` aborta antes de despublicar** se faltar credencial (n8n 2.x recusa publicar e derrubava o bot).
- **Agenda dedicada "Studio Bella"** em vez de `primary` — o nó Google Calendar do n8n exige ID em formato e-mail e rejeita `primary`.
- Descartados/fora de escopo (decisões "não reabrir" do Thiago): WhatsApp (só "próximo passo"), Railway/hospedagem paga, faturamento no Google.

## Onde parei

- **Último trabalho (16/11/2026):** commit do dia 5 (`ca6037f`), varredura com gitleaks (limpa), troca do e-mail dos commits para
  `101213387+guinho0@users.noreply.github.com` (config local do repo), criação do repositório público e ativação das proteções.
  O Thiago se inscreveu (ou ia se inscrever) na vaga nesse dia com o link do repo.
- **Mudanças não commitadas:** nenhuma (`git status` limpo, `main` sincronizada com `origin/main`).
- **Pela metade / pendente:**
  1. **Prints `docs/img/telegram.png` e `docs/img/planilha.png`** existem só localmente e estão bloqueados em `.git/info/exclude`
     porque mostram dados pessoais (chat_id, nome de uma pessoa real). Plano combinado: refazer com nome fictício
     (agendamento da "Ana" com confirmação; na planilha ocultar coluna H/telefone e a linha com o nome real), o Claude confere as imagens,
     remove do exclude, recoloca no README e faz push. Hoje o README só mostra `atendimento.png` e `relatorio.png`.
  2. **Vídeo demo (dia 6 do plano) não foi feito**: agendamento com confirmação no Telegram, evento aparecendo no Calendar, relatório via "Testar agora".
  3. Atualizar currículo/LinkedIn com o projeto (dia 6 do plano) — não há registro de que foi feito.
- **Bugs / limitações conhecidas:**
  - Ramo "mensagem não-texto" (sticker/foto) do workflow nunca foi exercitado com um sticker de verdade.
  - No relatório semanal o LLM uma vez atribuiu à assistente algo que o cliente disse (detalhe de qualidade do resumo).
  - n8n avisa que `WEBHOOK_URL` será substituída por `N8N_WEBHOOK_URL` (compose já passa `N8N_WEBHOOK_URL`; funciona).
  - Primeira linha do `.env` local é um comentário desatualizado ("Provedor ativo: Ollama") — o ativo é Gemini.
  - Cota do Gemini grátis estoura fácil (429) — evitar testar muito antes de gravar demo.

## Próximos passos

1. **Antes de perder a máquina:** backup do `.env` (gerenciador de senhas) — ver Armadilhas. Opcional: exportar backup do volume `n8n_data`.
2. Refazer `telegram.png` e `planilha.png` com dados fictícios, tirar do `.git/info/exclude`, recolocar no README, commit + push.
3. Gravar o vídeo demo de 1–2 min e linkar no README/LinkedIn.
4. Testar o ramo de sticker/foto no fluxo de atendimento.
5. Itens do "Próximos passos" do README (se o projeto continuar): WhatsApp (Evolution API ou Cloud API, troca só o gatilho no n8n);
   tool própria de **remarcar** (hoje é cancelar + agendar); deploy em VPS com URL fixa + Postgres; multi-cliente (um `negocio/` por estabelecimento).

## Preferências do Thiago neste projeto

- Escreve em português e quer respostas em português, com **explicação das decisões técnicas** ("quero conseguir defender este projeto em entrevista").
- Decisões que ele marcou como "não reabrir": Telegram, Gemini grátis, tudo local e custo zero, agente Python como cérebro, n8n ramificando por eventos.
- Ritmo rápido ("vamos continuar a todo vapor"); pede commit explicitamente ("de o commit e já vamos direto para o passo 3"). **Commit só quando ele pedir**
  (uma vez o Claude commitou sem pedir e avisou depois); commits direto na `main`, mensagem em português no estilo `feat:`/`fix:` com corpo explicativo.
- Gosta de passo a passo bem detalhado para tarefas manuais em consoles (Google Cloud, BotFather, n8n) — pediu "me explique direito as coisas".
- Muito cuidado com segredos e dados pessoais: nunca ler/exibir valores do `.env`; checar segredos antes de cada commit (`git grep` + gitleaks); não expor chat_id/IDs em prints.
- Usa VS Code no Windows, PowerShell; testa no próprio celular e manda prints. O Claude depura sozinho via `N8N_API_KEY` + `ultima_execucao.ps1` em vez de pedir prints.

## Armadilhas

- **Segredos que só existem nesta máquina:** `.env` (chave Gemini, token do bot, chave da API do n8n, IDs) e o volume Docker `n8n_data`
  (credenciais OAuth Google/Telegram/Gemini cifradas + conta de dono do n8n + chave de criptografia). Numa máquina nova: novo `.env`,
  nova conta no n8n, recriar as credenciais Google no n8n com os nomes exatos e rodar `importar_n8n.ps1`. O Client ID/Secret do OAuth
  pode ser recuperado/gerado de novo no Google Cloud (projeto `studio-bella-n8n` → Clientes). O banco SQLite (volume `api_dados`) só tem dados de teste.
- **URL do quick tunnel muda a cada start** → sempre rodar `.\scripts\tunel.ps1`. Reiniciar o n8n não refaz o `setWebhook`; o script detecta e republica.
  `cloudflared` está sem restart automático de propósito.
- **PowerShell 5.1:** coloca BOM em texto enviado por pipe (quebrava comandos no container — por isso os scripts vão como arquivo);
  corrompe aspas aninhadas em `docker compose exec ... python -c "..."` (use arquivo de script/here-string); `git commit -F -` com here-string falhou — usar arquivo de mensagem.
  Os `.ps1` são salvos em **UTF-8 com BOM** (necessário para acentos no PS 5.1).
- **CLI do n8n 2.x:** `update:workflow --active` virou `publish:workflow`/`unpublish:workflow`. `n8n execute` dentro do container conflita com o task broker → usar `-e N8N_RUNNERS_BROKER_PORT=5690`.
- **Nó Google Calendar não aceita `primary`** como calendar ID.
- **Gemini 3** exige devolver a `thought_signature` dos tool calls; histórico gravado sem ela dá 400 para sempre naquele cliente (apagar histórico).
  `gemini-2.5-flash` aparece na listagem mas dá 404 (aposentado).
- **API dentro do Docker precisa de `TZ=America/Sao_Paulo`** (já no Dockerfile); em UTC ofereceria horários 3h errados.
- Durante handoff humano o robô fica mudo para aquele cliente (por design) — mensagens como "cancelar" vão para o dono, não para o robô, até `/liberar`.
- O `.git/info/exclude` (local, não versionado) é o que bloqueia os 2 prints pessoais; num clone novo eles simplesmente não existem.
- Git local configurado com e-mail noreply do GitHub (`git config --local`); num clone novo, configurar de novo para não expor o Gmail.
