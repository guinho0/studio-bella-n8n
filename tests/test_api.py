"""Testes da API HTTP. O agente usa LLM roteirizado e SQLite em memória."""

import pytest
from fastapi.testclient import TestClient

from agente.llm import ChamadaTool, RespostaLLM
from api.main import criar_app

from tests.fakes import criar


def cliente(roteiro=(), api_token=""):
    agente, llm, banco = criar(roteiro)
    return TestClient(criar_app(agente, api_token=api_token)), banco


AGENDAR = RespostaLLM(None, [ChamadaTool("c1", "criar_agendamento",
                                         {"nome_cliente": "Ana", "servico": "Escova",
                                          "data": "2026-10-23", "hora": "15:00"})])


# ---------- POST /mensagem ----------

def test_mensagem_devolve_resposta_e_eventos():
    c, _ = cliente([AGENDAR, RespostaLLM("Agendado, Ana!")])
    r = c.post("/mensagem", json={"telefone": "5531999990000", "texto": "escova amanhã 15h"})
    assert r.status_code == 200
    corpo = r.json()
    assert corpo["resposta"] == "Agendado, Ana!"
    assert corpo["eventos"][0]["tipo"] == "agendamento_criado"
    assert corpo["eventos"][0]["dados"]["inicio"] == "2026-10-23T15:00"


def test_mensagem_sem_eventos_devolve_lista_vazia():
    c, _ = cliente([RespostaLLM("Oi! Como posso ajudar?")])
    r = c.post("/mensagem", json={"telefone": "1", "texto": "oi"})
    assert r.json() == {"resposta": "Oi! Como posso ajudar?", "eventos": []}


def test_aceita_chat_id_numerico_do_telegram():
    c, banco = cliente([RespostaLLM("Oi!")])
    r = c.post("/mensagem", json={"telefone": 123456789, "texto": "oi"})
    assert r.status_code == 200
    assert banco.carregar_historico("123456789")[0]["content"] == "oi"


@pytest.mark.parametrize("corpo", [
    {"telefone": "1", "texto": ""},
    {"telefone": "", "texto": "oi"},
    {"texto": "oi"},
])
def test_entrada_invalida_retorna_422(corpo):
    c, _ = cliente()
    assert c.post("/mensagem", json=corpo).status_code == 422


def test_conversa_com_humano_devolve_resposta_nula():
    c, banco = cliente()
    banco.registrar_transferencia("1", "reclamação")
    r = c.post("/mensagem", json={"telefone": "1", "texto": "alô?"})
    assert r.json() == {"resposta": None, "eventos": []}


def test_falha_do_llm_retorna_502():
    class LLMQuebrado:
        def responder(self, *a):
            raise RuntimeError("429 quota exceeded")

    agente, _, _ = criar([])
    agente.llm = LLMQuebrado()
    c = TestClient(criar_app(agente, api_token=""))
    r = c.post("/mensagem", json={"telefone": "1", "texto": "oi"})
    assert r.status_code == 502


def test_liberar_devolve_conversa_ao_robo():
    c, banco = cliente([RespostaLLM("Voltei!")])
    banco.registrar_transferencia("1", "teste")
    assert c.post("/conversas/1/liberar").status_code == 200
    assert c.post("/mensagem", json={"telefone": "1", "texto": "oi"}).json()["resposta"] == "Voltei!"


# ---------- autenticação ----------

def test_token_obrigatorio_quando_configurado():
    c, _ = cliente([RespostaLLM("Oi!")], api_token="segredo")
    assert c.post("/mensagem", json={"telefone": "1", "texto": "oi"}).status_code == 401
    assert c.get("/agendamentos", params={"data": "2026-10-23"},
                 headers={"X-API-Key": "errado"}).status_code == 401
    r = c.post("/mensagem", json={"telefone": "1", "texto": "oi"}, headers={"X-API-Key": "segredo"})
    assert r.status_code == 200


def test_health_nao_exige_token():
    c, _ = cliente(api_token="segredo")
    assert c.get("/health").json() == {"ok": True}


# ---------- GET /agendamentos ----------

def _popular_agenda(banco):
    from datetime import datetime
    banco.criar_agendamento("1", "Ana", "Escova", datetime(2026, 10, 23, 15), datetime(2026, 10, 23, 15, 45))
    banco.criar_agendamento("2", "Bia", "Manicure", datetime(2026, 10, 23, 9), datetime(2026, 10, 23, 9, 45))
    banco.criar_agendamento("3", "Cris", "Corte feminino", datetime(2026, 10, 24, 9), datetime(2026, 10, 24, 10))
    banco.cancelar_agendamento(2, "2")


def test_agendamentos_do_dia_so_confirmados_por_padrao():
    c, banco = cliente()
    _popular_agenda(banco)
    corpo = c.get("/agendamentos", params={"data": "2026-10-23"}).json()
    assert corpo["data"] == "2026-10-23"
    assert [(a["nome_cliente"], a["telefone"]) for a in corpo["agendamentos"]] == [("Ana", "1")]


def test_agendamentos_filtro_de_status():
    c, banco = cliente()
    _popular_agenda(banco)
    todos = c.get("/agendamentos", params={"data": "2026-10-23", "status": "todos"}).json()
    assert [a["nome_cliente"] for a in todos["agendamentos"]] == ["Bia", "Ana"]  # ordenado por horário
    cancel = c.get("/agendamentos", params={"data": "2026-10-23", "status": "cancelado"}).json()
    assert [a["nome_cliente"] for a in cancel["agendamentos"]] == ["Bia"]


@pytest.mark.parametrize("params", [{}, {"data": "23/10/2026"}, {"data": "2026-10-23", "status": "x"}])
def test_agendamentos_parametro_invalido_retorna_422(params):
    c, _ = cliente()
    assert c.get("/agendamentos", params=params).status_code == 422


# ---------- GET /conversas ----------

def test_conversas_desde_filtra_por_data_e_omite_tools():
    c, banco = cliente([AGENDAR, RespostaLLM("Agendado!"), RespostaLLM("Oi, Bia!")])
    c.post("/mensagem", json={"telefone": "1", "texto": "escova amanhã"})
    c.post("/mensagem", json={"telefone": "2", "texto": "oi"})
    # As mensagens do cliente 1 são "antigas"; as do cliente 2, recentes.
    banco.conn.execute("UPDATE mensagens SET criado_em = '2026-10-01T10:00:00' WHERE telefone = '1'")
    banco.conn.execute("UPDATE mensagens SET criado_em = '2026-10-20T10:00:00' WHERE telefone = '2'")

    corpo = c.get("/conversas", params={"desde": "2026-10-15"}).json()
    assert corpo["desde"] == "2026-10-15T00:00:00"
    assert corpo["conversas"] == [{"telefone": "2", "mensagens": [
        {"papel": "user", "texto": "oi", "em": "2026-10-20T10:00:00"},
        {"papel": "assistant", "texto": "Oi, Bia!", "em": "2026-10-20T10:00:00"},
    ]}]

    tudo = c.get("/conversas", params={"desde": "2026-09-01T00:00"}).json()["conversas"]
    falas_cliente_1 = [m["texto"] for m in tudo[0]["mensagens"]]
    assert falas_cliente_1 == ["escova amanhã", "Agendado!"]  # sem a tool call e o resultado dela


def test_conversas_exige_desde():
    c, _ = cliente()
    assert c.get("/conversas").status_code == 422
