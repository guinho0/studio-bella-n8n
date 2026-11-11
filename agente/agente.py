"""O coração do projeto: o LOOP do agente.

    mensagem do cliente
          │
          ▼
    ┌─► LLM decide ──► respondeu com texto? ──► fim, envia ao cliente
    │     │
    │     └─► pediu tool(s) ──► executamos ──► resultado volta pro histórico
    └──────────────────────────────────────────────┘

Não tem mágica: frameworks como LangGraph fazem basicamente isso.
"""

import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Callable

from .banco import Banco
from .prompt import montar_prompt
from .tools import Contexto, Tool, criar_tools

log = logging.getLogger("agente")

MSG_FALHA = "Desculpe, tive um probleminha aqui. Vou chamar uma atendente para te ajudar!"


@dataclass
class Resultado:
    resposta: str | None              # None = humano assumiu, o robô não responde
    eventos: list[dict] = field(default_factory=list)


class Agente:
    def __init__(self, llm, banco: Banco, negocio: dict, max_passos: int = 8,
                 relogio: Callable[[], datetime] = datetime.now):
        self.llm = llm
        self.banco = banco
        self.negocio = negocio
        self.max_passos = max_passos  # trava de segurança contra loops infinitos
        self.relogio = relogio

    def responder(self, telefone: str, texto: str) -> str | None:
        """Atalho que devolve só o texto (usado no chat de terminal)."""
        return self.processar(telefone, texto).resposta

    def processar(self, telefone: str, texto: str) -> Resultado:
        """Processa uma mensagem do cliente: devolve a resposta e os eventos gerados pelas tools."""
        if self.banco.em_atendimento_humano(telefone):
            return Resultado(None)

        agora = self.relogio()
        historico = self.banco.carregar_historico(telefone)
        self._adicionar(telefone, historico, {"role": "user", "content": texto})

        ctx = Contexto(telefone, self.banco, self.negocio, agora)
        tools = criar_tools(ctx)
        por_nome = {t.nome: t for t in tools}
        system = montar_prompt(self.negocio, agora)

        for _ in range(self.max_passos):
            resp = self.llm.responder(system, historico, tools)
            self._adicionar(telefone, historico, {
                "role": "assistant",
                "content": resp.texto,
                "tool_calls": [asdict(c) for c in resp.chamadas],
            })

            if not resp.chamadas:
                return Resultado(resp.texto or "", ctx.eventos)

            for chamada in resp.chamadas:
                resultado = self._executar(por_nome, chamada.nome, chamada.argumentos)
                self._adicionar(telefone, historico, {
                    "role": "tool", "tool_call_id": chamada.id,
                    "nome": chamada.nome, "content": resultado,
                })

        log.warning("Limite de passos atingido para %s", telefone)
        motivo = "agente excedeu o limite de passos"
        self.banco.registrar_transferencia(telefone, motivo)
        ctx.emitir("transferido_humano", motivo=motivo,
                   ultimas_mensagens=self.banco.ultimas_falas(telefone))
        return Resultado(MSG_FALHA, ctx.eventos)

    def _adicionar(self, telefone: str, historico: list[dict], msg: dict) -> None:
        historico.append(msg)
        self.banco.salvar_mensagem(telefone, msg)

    @staticmethod
    def _executar(por_nome: dict[str, Tool], nome: str, argumentos: dict) -> str:
        log.info("🔧 %s(%s)", nome, argumentos)
        tool = por_nome.get(nome)
        if not tool:
            resultado = f'{{"erro": "Ferramenta {nome} não existe."}}'
        else:
            try:
                resultado = tool.funcao(**argumentos)
            except TypeError as e:
                # Devolver o erro ao modelo permite que ele se corrija sozinho.
                resultado = f'{{"erro": "Argumentos inválidos: {e}"}}'
            except Exception as e:
                log.exception("Erro na tool %s", nome)
                resultado = f'{{"erro": "Falha interna: {e}"}}'
        log.info("   ↳ %s", resultado[:300])
        return resultado
