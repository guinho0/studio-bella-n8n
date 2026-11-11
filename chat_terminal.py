"""Simula o WhatsApp no terminal, para testar o agente sem integração nenhuma.

Comandos:
  /novo      troca para outro cliente (outro telefone)
  /limpar    apaga a memória da conversa atual
  /liberar   devolve a conversa ao robô depois de uma transferência para humano
  /agenda    mostra todos os agendamentos
  /sair
"""

import logging
import random
import sys

from agente.agente import Agente
from agente.banco import Banco
from agente.config import carregar_negocio
from agente.llm import criar_llm


def novo_telefone() -> str:
    return f"55319{random.randint(10000000, 99999999)}"


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    # Mostra as chamadas de tool: é aqui que você "vê o agente pensando".
    logging.basicConfig(level=logging.INFO, format="   \033[90m%(message)s\033[0m")
    for barulhento in ("httpx", "openai", "anthropic"):
        logging.getLogger(barulhento).setLevel(logging.WARNING)

    negocio = carregar_negocio()
    banco = Banco()
    agente = Agente(criar_llm(), banco, negocio)
    telefone = novo_telefone()

    print(f"💬 {negocio['nome']} — você é o cliente {telefone}. Digite /sair para encerrar.\n")
    while True:
        try:
            texto = input("Você: ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not texto:
            continue
        if texto == "/sair":
            break
        if texto == "/novo":
            telefone = novo_telefone()
            print(f"   (agora você é o cliente {telefone})\n")
            continue
        if texto == "/limpar":
            banco.apagar_historico(telefone)
            print("   (memória apagada)\n")
            continue
        if texto == "/liberar":
            banco.resolver_transferencias(telefone)
            print("   (robô reassumiu a conversa)\n")
            continue
        if texto == "/agenda":
            for a in banco.todos_agendamentos():
                print(f"   #{a['id']} {a['inicio']} {a['servico']} — {a['nome_cliente']} ({a['status']})")
            print()
            continue

        try:
            resposta = agente.responder(telefone, texto)
        except Exception as e:
            print(f"   ❌ Erro ao falar com o LLM: {e}\n")
            continue
        if resposta is None:
            print("   👩 [conversa com atendente humana — use /liberar para devolver ao robô]\n")
        else:
            print(f"Bella: {resposta}\n")


if __name__ == "__main__":
    main()
