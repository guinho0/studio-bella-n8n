"""Contrato dos eventos: eles refletem o que as tools FIZERAM, nunca o que o LLM escreveu."""

from agente.llm import ChamadaTool, RespostaLLM

from tests.fakes import criar


def agendar(data="2026-10-23", hora="15:00", id_="c1"):
    return RespostaLLM(None, [ChamadaTool(id_, "criar_agendamento",
                                          {"nome_cliente": "Ana", "servico": "Escova",
                                           "data": data, "hora": hora})])


def cancelar(id_agendamento=1):
    return RespostaLLM(None, [ChamadaTool("c9", "cancelar_agendamento", {"id_agendamento": id_agendamento})])


# Roteiro do agendamento em duas etapas: proposta -> pergunta | "sim" -> efetiva -> texto final.
def roteiro_agendar(texto_final="Agendado!"):
    return [agendar(), RespostaLLM("Escova sexta 23/10 às 15h, R$ 60. Confirma?"),
            agendar(id_="c2"), RespostaLLM(texto_final)]


def test_proposta_nao_emite_evento():
    agente, _, banco = criar(roteiro_agendar())
    r = agente.processar("tel1", "escova amanhã 15h, sou a Ana")
    assert r.eventos == [] and banco.todos_agendamentos() == []


def test_agendamento_emite_evento_com_dados_para_o_calendar():
    agente, _, _ = criar(roteiro_agendar())
    agente.processar("tel1", "escova amanhã 15h, sou a Ana")
    r = agente.processar("tel1", "sim")
    assert r.resposta == "Agendado!"
    assert r.eventos == [{"tipo": "agendamento_criado", "dados": {
        "telefone": "tel1", "id_agendamento": 1, "nome_cliente": "Ana", "servico": "Escova",
        "inicio": "2026-10-23T15:00", "fim": "2026-10-23T15:45", "preco": 60.0}}]


def test_evento_vale_mesmo_que_o_texto_do_llm_seja_confuso():
    agente, _, _ = criar(roteiro_agendar("Hmm, não sei se deu certo..."))
    agente.processar("tel1", "escova amanhã 15h")
    r = agente.processar("tel1", "sim")
    assert [e["tipo"] for e in r.eventos] == ["agendamento_criado"]


def test_llm_dizer_que_agendou_sem_chamar_a_tool_nao_gera_evento():
    agente, _, banco = criar([RespostaLLM("Prontinho, agendado para amanhã às 15h!")])
    r = agente.processar("tel1", "escova amanhã 15h")
    assert r.eventos == []
    assert banco.todos_agendamentos() == []


def test_tool_que_falha_nao_emite_evento():
    # 26/10/2026 é segunda-feira: o salão está fechado, então a tool recusa.
    agente, llm, _ = criar([agendar(data="2026-10-26"), RespostaLLM("Segunda não abrimos.")])
    r = agente.processar("tel1", "escova segunda 15h")
    assert r.eventos == []
    assert "indisponível" in llm.recebido[1][-1]["content"]


def test_cancelamento_emite_evento_com_dados_do_agendamento():
    agente, _, _ = criar(roteiro_agendar() + [
        cancelar(), RespostaLLM("Cancelar a escova de sexta 15h?"),
        cancelar(), RespostaLLM("Cancelado."),
    ])
    agente.processar("tel1", "escova amanhã 15h")
    agente.processar("tel1", "sim")
    assert agente.processar("tel1", "cancela por favor").eventos == []   # só a proposta
    r = agente.processar("tel1", "sim, pode cancelar")
    assert r.eventos == [{"tipo": "agendamento_cancelado", "dados": {
        "telefone": "tel1", "id_agendamento": 1, "nome_cliente": "Ana", "servico": "Escova",
        "inicio": "2026-10-23T15:00", "fim": "2026-10-23T15:45"}}]


def test_cancelar_agendamento_de_outro_cliente_nao_emite_evento():
    agente, _, banco = criar(roteiro_agendar() + [
        cancelar(), RespostaLLM("Não encontrei."),
        cancelar(), RespostaLLM("Não encontrei."),
    ])
    agente.processar("tel1", "escova amanhã 15h")
    agente.processar("tel1", "sim")
    agente.processar("tel2", "cancela o agendamento 1")
    r = agente.processar("tel2", "sim, cancela")
    assert r.eventos == []
    assert banco.buscar_agendamento(1)["status"] == "confirmado"


def test_transferencia_emite_evento_com_resumo_da_conversa():
    agente, _, _ = criar([
        RespostaLLM(None, [ChamadaTool("c1", "transferir_para_humano", {"motivo": "reclamação"})]),
        RespostaLLM("Vou chamar uma atendente."),
    ])
    r = agente.processar("tel1", "meu cabelo ficou horrível")
    [evento] = r.eventos
    assert evento["tipo"] == "transferido_humano"
    assert evento["dados"]["motivo"] == "reclamação"
    assert evento["dados"]["ultimas_mensagens"] == [{"papel": "user", "texto": "meu cabelo ficou horrível"}]


def test_limite_de_passos_tambem_avisa_o_dono():
    loop = [RespostaLLM(None, [ChamadaTool(f"c{i}", "listar_servicos", {})]) for i in range(5)]
    agente, _, _ = criar(loop)
    agente.max_passos = 3
    r = agente.processar("tel1", "oi")
    assert [e["tipo"] for e in r.eventos] == ["transferido_humano"]


def test_eventos_nao_vazam_para_o_turno_seguinte():
    agente, _, _ = criar(roteiro_agendar() + [RespostaLLM("De nada!")])
    agente.processar("tel1", "escova amanhã 15h")
    assert agente.processar("tel1", "sim").eventos
    assert agente.processar("tel1", "obrigada").eventos == []


def test_em_atendimento_humano_nao_responde_nem_emite():
    agente, _, banco = criar([])
    banco.registrar_transferencia("tel1", "teste")
    r = agente.processar("tel1", "alô?")
    assert r.resposta is None and r.eventos == []
