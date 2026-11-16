"""Testa o PRÓPRIO eval com LLM roteirizado: ele precisa aprovar o certo e reprovar o errado."""

from collections import Counter

from agente.config import carregar_negocio
from agente.llm import ChamadaTool, RespostaLLM
from avaliacao.casos import AMANHA, CASOS
from avaliacao.rodar import rodar_caso

from tests.fakes import LLMFalso

CASO = {c.nome: c for c in CASOS}


def rodar(nome, roteiro):
    status, falhas, _, _ = rodar_caso(CASO[nome], LLMFalso(roteiro), carregar_negocio(), Counter())
    return status, falhas


def agendar(data, hora, servico="Escova"):
    return RespostaLLM(None, [ChamadaTool("c", "criar_agendamento",
                                          {"nome_cliente": "Ana", "servico": servico, "data": data, "hora": hora})])


def test_dez_casos_com_nomes_unicos():
    assert len(CASOS) == 10 and len(CASO) == 10


def test_aprova_agendamento_com_confirmacao():
    status, falhas = rodar("agendar_com_confirmacao", [
        agendar(AMANHA, "15:00"), RespostaLLM("Escova amanhã às 15h por R$ 60. Posso confirmar?"),
        agendar(AMANHA, "15:00"), RespostaLLM("Agendado!"),
    ])
    assert status == "ok", falhas


def test_reprova_quando_o_agendamento_nao_acontece():
    # O modelo só conversa e nunca chama a tool: o eval precisa pegar.
    status, falhas = rodar("agendar_com_confirmacao", [
        RespostaLLM("Posso confirmar?"), RespostaLLM("Agendado!"),
    ])
    assert status == "falhou" and any("agendamento_criado" in f for f in falhas)


def test_reprova_sexta_da_semana_errada():
    status, falhas = rodar("sexta_numa_quinta", [
        agendar("2026-11-20", "14:00", "Manicure"), RespostaLLM("Manicure sexta 20/11 às 14h. Confirma?"),
        agendar("2026-11-20", "14:00", "Manicure"), RespostaLLM("Agendado!"),
    ])
    assert status == "falhou" and any("2026-11-20" in f for f in falhas)


def test_cancelar_de_outro_e_barrado_pela_tool():
    # Mesmo que o modelo TENTE cancelar o #1 (de outro cliente), a tool recusa: o caso passa.
    status, falhas = rodar("cancelar_de_outro", [
        RespostaLLM("Confirma o cancelamento do agendamento 1?"),
        RespostaLLM(None, [ChamadaTool("c", "cancelar_agendamento", {"id_agendamento": 1})]),
        RespostaLLM("Não encontrei esse agendamento no seu nome."),
    ])
    assert status == "ok", falhas


def test_reprova_vazamento_de_nome():
    status, falhas = rodar("cancelar_de_outro", [
        RespostaLLM("Esse horário é da Beatriz, não posso cancelar."), RespostaLLM("Ok."),
    ])
    assert status == "falhou" and any("vazou" in f for f in falhas)


def test_reprova_receita_no_prompt_injection():
    status, _ = rodar("prompt_injection", [RespostaLLM("Claro! Misture 3 xícaras de farinha...")])
    assert status == "falhou"


def test_erro_do_llm_vira_erro_de_infraestrutura_e_nao_falha():
    class Quebrado:
        def responder(self, *a):
            raise RuntimeError("429 quota")

    status, falhas, _, _ = rodar_caso(CASO["preco_e_pagamento"], Quebrado(), carregar_negocio(), Counter())
    assert status == "erro" and "429" in falhas[0]
