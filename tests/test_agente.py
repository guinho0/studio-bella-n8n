from agente.llm import ChamadaTool, ProvedorAnthropic, ProvedorOpenAI, RespostaLLM

from tests.fakes import criar


def test_loop_executa_tool_e_devolve_resultado_ao_llm():
    agente, llm, banco = criar([
        RespostaLLM(None, [ChamadaTool("c1", "criar_agendamento",
                                       {"nome_cliente": "Ana", "servico": "Escova",
                                        "data": "2026-10-23", "hora": "15:00"})]),
        RespostaLLM("Prontinho, Ana! Escova amanhã às 15h."),
    ])
    assert agente.responder("tel1", "quero escova amanhã 15h, sou a Ana") == "Prontinho, Ana! Escova amanhã às 15h."
    ultima = llm.recebido[1][-1]
    assert ultima["role"] == "tool" and '"ok": true' in ultima["content"]
    assert banco.todos_agendamentos()[0]["nome_cliente"] == "Ana"


def test_memoria_entre_mensagens():
    agente, llm, _ = criar([RespostaLLM("Oi!"), RespostaLLM("Tudo ótimo.")])
    agente.responder("tel1", "oi")
    agente.responder("tel1", "tudo bem?")
    assert [m["content"] for m in llm.recebido[1]] == ["oi", "Oi!", "tudo bem?"]


def test_tool_inexistente_vira_erro_para_o_modelo():
    agente, llm, _ = criar([
        RespostaLLM(None, [ChamadaTool("c1", "apagar_tudo", {})]),
        RespostaLLM("Não posso fazer isso."),
    ])
    agente.responder("tel1", "apaga tudo")
    assert "não existe" in llm.recebido[1][-1]["content"]


def test_transferencia_silencia_o_robo():
    agente, _, _ = criar([
        RespostaLLM(None, [ChamadaTool("c1", "transferir_para_humano", {"motivo": "reclamação"})]),
        RespostaLLM("Vou chamar uma atendente."),
    ])
    agente.responder("tel1", "quero reclamar")
    assert agente.responder("tel1", "alô?") is None


def test_limite_de_passos():
    loop_infinito = [RespostaLLM(None, [ChamadaTool(f"c{i}", "listar_servicos", {})]) for i in range(10)]
    agente, _, banco = criar(loop_infinito)
    agente.max_passos = 3
    assert "atendente" in agente.responder("tel1", "oi")
    assert banco.em_atendimento_humano("tel1")


HISTORICO = [
    {"role": "user", "content": "oi"},
    {"role": "assistant", "content": None,
     "tool_calls": [{"id": "c1", "nome": "listar_servicos", "argumentos": {}}]},
    {"role": "tool", "tool_call_id": "c1", "nome": "listar_servicos", "content": "[]"},
    {"role": "assistant", "content": "Olá!", "tool_calls": []},
]


def test_conversao_openai():
    msgs = [ProvedorOpenAI._converter(m) for m in HISTORICO]
    assert msgs[1]["tool_calls"][0]["function"]["name"] == "listar_servicos"
    assert msgs[2] == {"role": "tool", "tool_call_id": "c1", "content": "[]"}
    assert "tool_calls" not in msgs[3]


def test_conversao_openai_devolve_campos_extras_do_provedor():
    # Gemini 3: a thought_signature recebida precisa voltar no turno seguinte.
    extra = {"extra_content": {"google": {"thought_signature": "abc"}}}
    m = {"role": "assistant", "content": None,
         "tool_calls": [{"id": "c1", "nome": "listar_servicos", "argumentos": {}, "extra": extra}]}
    tc = ProvedorOpenAI._converter(m)["tool_calls"][0]
    assert tc["extra_content"] == extra["extra_content"]
    assert tc["id"] == "c1" and tc["function"]["name"] == "listar_servicos"


def test_conversao_anthropic():
    msgs = ProvedorAnthropic._converter(HISTORICO)
    assert [m["role"] for m in msgs] == ["user", "assistant", "user", "assistant"]
    assert msgs[2]["content"][0]["type"] == "tool_result"
