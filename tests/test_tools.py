import json
from datetime import datetime

import pytest

from agente.banco import Banco
from agente.config import carregar_negocio
from agente.tools import Contexto, criar_tools

AGORA = datetime(2026, 10, 22, 10, 0)  # quinta-feira


@pytest.fixture
def ctx():
    return Contexto("5531999990000", Banco(":memory:"), carregar_negocio(), AGORA)


def tool(ctx, nome):
    return next(t for t in criar_tools(ctx) if t.nome == nome).funcao


def proximo_turno(ctx):
    """Simula a PRÓXIMA mensagem do mesmo cliente (novo turno, mesmo banco)."""
    return Contexto(ctx.telefone, ctx.banco, ctx.negocio, ctx.agora)


def em_dois_turnos(ctx, nome, *args):
    """Proposta num turno, confirmação no seguinte. Devolve a resposta da 2ª chamada."""
    assert json.loads(tool(ctx, nome)(*args))["pendente"]
    return json.loads(tool(proximo_turno(ctx), nome)(*args))


def test_horarios_de_hoje_ignoram_o_passado(ctx):
    r = json.loads(tool(ctx, "consultar_horarios")("2026-10-22", "Corte masculino"))
    assert r["horarios_livres"][0] == "10:30"
    assert r["horarios_livres"][-1] == "18:30"


def test_dia_fechado(ctx):
    r = json.loads(tool(ctx, "consultar_horarios")("2026-10-26", "Escova"))  # segunda
    assert "erro" in r


def test_servico_invalido_lista_opcoes(ctx):
    r = json.loads(tool(ctx, "consultar_horarios")("2026-10-23", "Progressiva"))
    assert "Escova" in r["servicos_validos"]


def test_agendar_ocupa_o_horario(ctx):
    r = em_dois_turnos(ctx, "criar_agendamento", "Ana", "corte feminino", "2026-10-23", "14:00")
    assert r["ok"]
    livres = json.loads(tool(ctx, "consultar_horarios")("2026-10-23", "Corte masculino"))["horarios_livres"]
    assert "14:00" not in livres and "14:30" not in livres and "15:00" in livres


def test_nao_agenda_horario_inventado(ctx):
    r = json.loads(tool(ctx, "criar_agendamento")("Ana", "Escova", "2026-10-23", "22:00"))
    assert "erro" in r


def test_cliente_nao_cancela_agendamento_de_outro(ctx):
    id_ = em_dois_turnos(ctx, "criar_agendamento", "Ana", "Escova", "2026-10-23", "10:00")["id_agendamento"]
    outro = Contexto("5531888880000", ctx.banco, ctx.negocio, AGORA)
    # Nem a proposta é feita para o outro cliente (e a resposta não revela que o id existe).
    assert json.loads(tool(outro, "cancelar_agendamento")(id_)) == {
        "erro": "Agendamento não encontrado para este cliente."}
    assert json.loads(tool(proximo_turno(outro), "cancelar_agendamento")(id_))["erro"]
    assert em_dois_turnos(ctx, "cancelar_agendamento", id_)["ok"]


# ---------- confirmação em duas etapas (garantida em código) ----------

def test_primeira_chamada_so_propoe_e_nao_grava(ctx):
    r = json.loads(tool(ctx, "criar_agendamento")("Ana", "Escova", "2026-10-23", "10:00"))
    assert r["pendente"] and r["proposta"]["data"] == "sexta 23/10/2026"
    assert ctx.banco.todos_agendamentos() == [] and ctx.eventos == []


def test_repetir_no_mesmo_turno_nao_fura_a_confirmacao(ctx):
    # Modelo "apressado" (ou prompt injection) chamando duas vezes na mesma mensagem.
    criar = tool(ctx, "criar_agendamento")
    for _ in range(3):
        assert json.loads(criar("Ana", "Escova", "2026-10-23", "10:00"))["pendente"]
    assert ctx.banco.todos_agendamentos() == []


def test_confirmar_dados_diferentes_vira_nova_proposta(ctx):
    tool(ctx, "criar_agendamento")("Ana", "Escova", "2026-10-23", "10:00")
    seguinte = proximo_turno(ctx)
    r = json.loads(tool(seguinte, "criar_agendamento")("Ana", "Escova", "2026-10-23", "11:00"))
    assert r["pendente"]                       # mudou a hora: o cliente precisa confirmar de novo
    assert json.loads(tool(proximo_turno(ctx), "criar_agendamento")("Ana", "Escova", "2026-10-23", "11:00"))["ok"]


def test_confirmacao_nao_vale_duas_vezes(ctx):
    r = em_dois_turnos(ctx, "criar_agendamento", "Ana", "Escova", "2026-10-23", "10:00")
    assert r["ok"]
    # Mesma proposta de novo, em outro turno: o horário já está ocupado, e não há confirmação sobrando.
    r2 = json.loads(tool(proximo_turno(ctx), "criar_agendamento")("Ana", "Escova", "2026-10-23", "10:00"))
    assert "erro" in r2 and len(ctx.banco.todos_agendamentos()) == 1


def test_proposta_expira(ctx):
    tool(ctx, "criar_agendamento")("Ana", "Escova", "2026-10-23", "10:00")
    ctx.banco.conn.execute("UPDATE pendencias SET criado_em = '2020-01-01T00:00:00'")
    r = json.loads(tool(proximo_turno(ctx), "criar_agendamento")("Ana", "Escova", "2026-10-23", "10:00"))
    assert r["pendente"]                       # expirou: vira uma proposta nova
