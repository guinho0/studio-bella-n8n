# Agente de atendimento com IA + n8n

Projeto de estudo e futuro produto: um agente de IA que atende clientes de pequenos negócios
(salão, clínica, pet shop...). Ele tira dúvidas, consulta horários, agenda, cancela e passa a
conversa para um humano quando precisa.

O agente Python é o **cérebro** (LLM + tools + memória) e fica exposto por uma API FastAPI.
O **n8n orquestra** o canal (Telegram), as integrações (Google Calendar, Sheets, alerta ao dono)
e as automações agendadas.

O exemplo configurado é o **Studio Bella** (salão de beleza). Para outro cliente, basta trocar a pasta [negocio/](negocio/).

## Como rodar (Docker: n8n + API)

```powershell
copy .env.example .env      # preencha OPENAI_API_KEY com a chave do Gemini (Google AI Studio)
docker compose up -d --build
```

- n8n: <http://localhost:5678> (no primeiro acesso, crie a conta de dono local)
- API: <http://localhost:8000/docs> (Swagger gerado pelo FastAPI)
- Dentro do compose, o n8n chama a API em `http://api:8000`

### Colocar o bot do Telegram no ar

Uma vez só:

1. No Telegram, fale com o **@BotFather** → `/newbot` → escolha nome e username (terminado em `bot`).
   Cole o token no `.env` em `TELEGRAM_BOT_TOKEN=` (não versionado).
2. Abra <http://localhost:5678> e crie a conta de dono do n8n.
3. `.\scripts\tunel.ps1`: sobe o túnel HTTPS e grava a URL pública em `WEBHOOK_URL`.
4. `.\scripts\importar_n8n.ps1`: valida o token, cria a credencial, importa os workflows de
   [n8n/workflows/](n8n/workflows/) e publica o fluxo de atendimento.

Sempre que ligar o PC/Docker: `.\scripts\tunel.ps1` (a URL do quick tunnel muda a cada start;
o script atualiza o n8n e confere no Telegram, via `getWebhookInfo`, se o webhook aponta para ela).

Editou um workflow na interface? `.\scripts\exportar_n8n.ps1` grava os JSONs em `n8n/workflows/`
para versionar no Git. O `importar_n8n.ps1` faz o caminho inverso (e **sobrescreve** o que está no n8n).

```
Telegram ──HTTPS──► cloudflared ──► nginx (só /webhook/*) ──► n8n ──► api:8000
                                    o editor do n8n NÃO fica exposto: só em localhost:5678
```

Fluxo **Atendimento Telegram**: mensagem → "digitando…" → `POST /mensagem` → responde ao cliente
→ separa `eventos[]` → Switch por `tipo`:

| Evento | Automação no n8n |
|---|---|
| `agendamento_criado` | Cria o evento no Google Calendar e grava a linha na planilha (com o id do evento) |
| `agendamento_cancelado` | Acha a linha pelo `id_agendamento`, apaga o evento do Calendar e marca `cancelado` |
| `transferido_humano` | Alerta o dono no Telegram com o motivo e as últimas mensagens |

Mensagem que não é texto recebe um aviso. Falha da API (502/timeout) vira "tive uma instabilidade".
Calendar e Sheets "continuam em caso de erro": uma falha do Google não afeta o atendimento.

**Handoff humano pelo próprio Telegram.** Depois de uma transferência, o robô fica em silêncio com
aquele cliente, e o que ele escreve é repassado ao dono (`DONO_TELEGRAM_CHAT_ID`). O dono comanda pelo bot:
- `/responder <id> <mensagem>`: envia a mensagem ao cliente
- `/liberar <id>`: devolve a conversa ao robô

**Google (uma vez):** projeto no Google Cloud com Calendar, Sheets e Drive API ativadas; cliente
OAuth "Aplicativo da Web" com redirect `http://localhost:5678/rest/oauth2-credential/callback`.
No n8n, crie as credenciais **`Google Calendar Studio Bella`** e **`Google Sheets Studio Bella`**
(o import liga os nós a elas pelo nome). Planilha com a aba `Agendamentos` e o cabeçalho:
`id_agendamento, status, nome_cliente, servico, inicio, fim, preco, telefone, calendar_evento_id, atualizado_em`.

### API

| Método | Rota | Uso |
|---|---|---|
| `POST` | `/mensagem` `{telefone, texto}` | Processa a mensagem. Devolve `{resposta, eventos[]}`. `resposta: null` = conversa com humano, não responder |
| `GET` | `/agendamentos?data=AAAA-MM-DD[&status=confirmado\|cancelado\|todos]` | Agenda do dia (lembrete D-1) |
| `GET` | `/conversas?desde=AAAA-MM-DD[THH:MM]` | Conversas agrupadas por cliente, sem detalhes de tool (relatório semanal) |
| `POST` | `/conversas/{telefone}/liberar` | Devolve a conversa ao robô depois de um handoff |
| `GET` | `/health` | Healthcheck (sem autenticação) |

Se `API_TOKEN` estiver no `.env`, todas as rotas (menos `/health`) exigem o header `X-API-Key`.

**Eventos**: emitidos pelas tools *depois* que a ação acontece no banco, nunca a partir do texto do LLM.
O n8n ramifica por `eventos[].tipo`:

```json
{"resposta": "Prontinho, Ana! ...",
 "eventos": [{"tipo": "agendamento_criado",
              "dados": {"telefone": "...", "id_agendamento": 1, "nome_cliente": "Ana", "servico": "Escova",
                        "inicio": "2026-11-11T15:00", "fim": "2026-11-11T15:45", "preco": 60.0}}]}
```

| `tipo` | `dados` |
|---|---|
| `agendamento_criado` | `id_agendamento, nome_cliente, servico, inicio, fim, preco` |
| `agendamento_cancelado` | `id_agendamento, nome_cliente, servico, inicio, fim` |
| `transferido_humano` | `motivo, ultimas_mensagens[{papel, texto}]` |

Todos incluem `telefone`. Horários em ISO local (`America/Sao_Paulo`).

## Desenvolvimento local (sem Docker)

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
python chat_terminal.py     # conversa no terminal
pytest                      # testes (LLM falso: não gastam API)
uvicorn api.main:criar_app --factory --reload   # API em http://localhost:8000
```

### Escolha um LLM no `.env`

| Opção | Custo | Configuração |
|---|---|---|
| **Ollama (local)** | grátis | Instale o [ollama.com](https://ollama.com), rode `ollama pull qwen3:8b`, e use `LLM_PROVEDOR=ollama` |
| **Gemini** | tem plano grátis | Gere a chave no Google AI Studio; `LLM_PROVEDOR=openai`, `OPENAI_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai/`, `LLM_MODELO=gemini-3.5-flash` |
| **Claude** | pago | `LLM_PROVEDOR=anthropic`, `ANTHROPIC_API_KEY=...` |
| **OpenAI / Groq / OpenRouter** | pago/variável | `LLM_PROVEDOR=openai` + `OPENAI_BASE_URL` e `OPENAI_API_KEY` |

> **Resiliência (Gemini grátis):** com `LLM_MODELOS_RESERVA`, se o modelo principal der 503/429/timeout,
> a mesma chamada vai para o próximo modelo da lista, e o que falhou fica 2 min em quarentena
> (circuit breaker), para as próximas mensagens não pagarem o timeout de novo. Erros 400/401/404
> não acionam o fallback: são bug ou configuração errada, e trocar de modelo só os esconderia.
> Veja no log: `docker compose logs -f api | Select-String llm`.

> Com 16 GB de RAM, modelos de 7–8B rodam bem no Ollama (mais lentos sem GPU). Modelos locais
> erram mais nas tools. Compare com um modelo de API: isso faz parte do aprendizado.

## Arquitetura

```
Telegram ──► n8n ──HTTP──► api/main.py ──┐
                                          ├──►  agente/agente.py   o LOOP: LLM → tools → LLM → ... → resposta
chat_terminal.py ─────────────────────────┘           │
                          ├── agente/llm.py      adaptadores: OpenAI-compatível (Ollama, Gemini...) e Anthropic
                          ├── agente/tools.py    ferramentas que o agente pode usar (com validação)
                          ├── agente/prompt.py   system prompt (persona, regras, calendário, FAQ)
                          └── agente/banco.py    SQLite: memória da conversa, agenda, transferências
negocio/          dados do cliente (serviços, horários, FAQ)
```

No terminal, as linhas cinzas `🔧 ferramenta(args)` mostram o agente "pensando". Observe-as.

## Conceitos que este projeto ensina (leia o código nesta ordem)

1. **[tools.py](agente/tools.py)**: o que é uma tool, JSON Schema, e por que *a tool valida tudo*
   (o telefone vem do contexto, não do modelo; o horário é rechecado antes de agendar).
2. **[agente.py](agente/agente.py)**: o loop do agente, o limite de passos e os erros devolvidos ao modelo para ele se corrigir.
3. **[llm.py](agente/llm.py)**: as diferenças entre APIs e por que usar um formato neutro.
4. **[prompt.py](agente/prompt.py)**: engenharia de prompt prática, entregando o calendário pronto em vez de pedir ao modelo que calcule datas.
5. **[banco.py](agente/banco.py)**: memória (histórico por cliente) e como cortar o histórico sem quebrar pares tool_call/tool_result.

> Por que não tem RAG? Um FAQ pequeno cabe inteiro no prompt, o que é mais simples e mais preciso.
> RAG (embeddings + busca) passa a valer a pena quando o conteúdo não cabe mais no prompt (exercício 4).

## Exercícios sugeridos

1. Converse e tente "quebrar" o agente: peça horário num domingo, invente um serviço, peça desconto, tente cancelar o agendamento `#1` de outro cliente (`/novo`).
2. Rode o mesmo roteiro com Ollama e com uma API. Anote onde cada um erra.
3. Crie uma tool `remarcar_agendamento`.
4. Troque o FAQ por um catálogo de 200 produtos e implemente RAG.
5. Escreva um **eval**: uma lista de conversas de teste com o resultado esperado, rodada contra o LLM real.

## Roadmap até virar produto

- [x] **Fase 1**: agente funcional no terminal
- [ ] **Fase 2** (em andamento): n8n como orquestrador
  - [x] API FastAPI com `eventos[]`, testes e docker-compose (n8n + API)
  - [x] Telegram (BotFather) + túnel cloudflared + fluxo principal no n8n
  - [x] Fallback de modelo com quarentena (o Gemini grátis sobrecarrega em horário de pico)
  - [x] Google Calendar e Sheets por evento + alerta de handoff ao dono (com `/responder` e `/liberar`)
  - [ ] Lembrete D-1 e relatório semanal resumido por LLM
- [ ] **Fase 3**: WhatsApp (Evolution API ou WhatsApp Cloud API) como canal, trocando só o gatilho no n8n
- [ ] **Fase 4**: painel web simples para o dono ver agenda, conversas e assumir atendimentos
- [ ] **Fase 5**: multi-cliente (um `negocio/` por empresa), deploy em VPS e cobrança mensal

**Modelo de negócio:** mensalidade de R$ 150 a R$ 500 por estabelecimento, mais uma taxa de implantação.
O custo de LLM por cliente com modelos baratos costuma ser de poucos reais por mês. Confira os preços atuais de cada provedor.
