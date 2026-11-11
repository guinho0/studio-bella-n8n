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
    r = json.loads(tool(ctx, "criar_agendamento")("Ana", "corte feminino", "2026-10-23", "14:00"))
    assert r["ok"]
    livres = json.loads(tool(ctx, "consultar_horarios")("2026-10-23", "Corte masculino"))["horarios_livres"]
    assert "14:00" not in livres and "14:30" not in livres and "15:00" in livres


def test_nao_agenda_horario_inventado(ctx):
    r = json.loads(tool(ctx, "criar_agendamento")("Ana", "Escova", "2026-10-23", "22:00"))
    assert "erro" in r


def test_cliente_nao_cancela_agendamento_de_outro(ctx):
    id_ = json.loads(tool(ctx, "criar_agendamento")("Ana", "Escova", "2026-10-23", "10:00"))["id_agendamento"]
    outro = Contexto("5531888880000", ctx.banco, ctx.negocio, AGORA)
    assert "erro" in json.loads(tool(outro, "cancelar_agendamento")(id_))
    assert json.loads(tool(ctx, "cancelar_agendamento")(id_))["ok"]
