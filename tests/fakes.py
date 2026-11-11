"""Dublês de teste compartilhados: nenhum teste chama um LLM de verdade."""

from datetime import datetime

from agente.agente import Agente
from agente.banco import Banco
from agente.config import carregar_negocio

AGORA = datetime(2026, 10, 22, 10, 0)  # quinta-feira


class LLMFalso:
    """Devolve respostas roteirizadas e guarda o que recebeu, para inspecionarmos."""

    def __init__(self, roteiro):
        self.roteiro = list(roteiro)
        self.recebido = []

    def responder(self, system, mensagens, tools):
        self.recebido.append(list(mensagens))
        return self.roteiro.pop(0)


def criar(roteiro):
    banco = Banco(":memory:")
    llm = LLMFalso(roteiro)
    return Agente(llm, banco, carregar_negocio(), relogio=lambda: AGORA), llm, banco
