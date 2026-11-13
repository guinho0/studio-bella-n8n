"""Métricas do relatório semanal e migração do banco."""

import sqlite3
from datetime import datetime

from fastapi.testclient import TestClient

from agente.banco import Banco
from agente.llm import ChamadaTool, RespostaLLM
from api.main import criar_app

from tests.fakes import criar


def _envelhecer(banco, tabela, coluna="criado_em", quando="2026-01-01T00:00:00"):
    banco.conn.execute(f"UPDATE {tabela} SET {coluna} = ?", (quando,))
    banco.conn.commit()


def test_metricas_contam_so_o_periodo():
    _, _, banco = criar([])
    # Período antigo: um agendamento cancelado, uma transferência, uma conversa
    banco.salvar_mensagem("velho", {"role": "user", "content": "oi"})
    banco.criar_agendamento("velho", "Ana", "Escova", datetime(2026, 1, 2, 10), datetime(2026, 1, 2, 11))
    banco.cancelar_agendamento(1, "velho")
    banco.registrar_transferencia("velho", "x")
    for t in ("mensagens", "agendamentos", "transferencias"):
        _envelhecer(banco, t)
    _envelhecer(banco, "agendamentos", "cancelado_em")

    # Período atual
    banco.salvar_mensagem("1", {"role": "user", "content": "oi"})
    banco.salvar_mensagem("1", {"role": "assistant", "content": "Olá!", "tool_calls": []})
    banco.salvar_mensagem("2", {"role": "user", "content": "preço?"})
    banco.salvar_mensagem("2", {"role": "tool", "tool_call_id": "c", "nome": "x", "content": "{}"})
    banco.criar_agendamento("1", "Bia", "Escova", datetime(2026, 12, 1, 10), datetime(2026, 12, 1, 11))
    banco.criar_agendamento("2", "Cris", "Manicure", datetime(2026, 12, 1, 12), datetime(2026, 12, 1, 13))
    banco.criar_agendamento("2", "Cris", "Escova", datetime(2026, 12, 2, 12), datetime(2026, 12, 2, 13))
    banco.cancelar_agendamento(4, "2")
    # Cancelar AGORA um agendamento criado no passado conta como cancelamento do período
    banco.criar_agendamento("velho", "Ana", "Pedicure", datetime(2026, 12, 3, 9), datetime(2026, 12, 3, 10))
    banco.conn.execute("UPDATE agendamentos SET criado_em = '2026-01-01T00:00:00' WHERE id = 5")
    banco.cancelar_agendamento(5, "velho")
    banco.registrar_transferencia("1", "reclamação")

    m = banco.metricas_desde("2026-06-01T00:00:00")
    assert m == {
        "conversas": 2,
        "mensagens_de_clientes": 2,          # mensagens de tool e do assistente não contam
        "agendamentos_criados": 3,
        "agendamentos_cancelados": 2,        # o #4 (novo) e o #5 (antigo, cancelado agora)
        "transferencias_humano": 1,
        "servicos_agendados": [{"servico": "Escova", "quantidade": 2},
                               {"servico": "Manicure", "quantidade": 1}],
    }


def test_endpoint_metricas():
    agente, _, banco = criar([
        RespostaLLM(None, [ChamadaTool("c1", "transferir_para_humano", {"motivo": "reclamação"})]),
        RespostaLLM("Vou chamar uma atendente."),
    ])
    c = TestClient(criar_app(agente, api_token=""))
    c.post("/mensagem", json={"telefone": "1", "texto": "quero reclamar"})
    r = c.get("/metricas", params={"desde": "2020-01-01"})
    assert r.status_code == 200
    corpo = r.json()
    assert corpo["desde"] == "2020-01-01T00:00:00"
    assert corpo["conversas"] == 1 and corpo["transferencias_humano"] == 1
    assert c.get("/metricas").status_code == 422


def test_migracao_adiciona_cancelado_em_em_banco_antigo(tmp_path):
    caminho = tmp_path / "antigo.db"
    antigo = sqlite3.connect(caminho)
    antigo.execute("CREATE TABLE agendamentos (id INTEGER PRIMARY KEY, telefone TEXT NOT NULL, "
                   "nome_cliente TEXT NOT NULL, servico TEXT NOT NULL, inicio TEXT NOT NULL, "
                   "fim TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'confirmado', criado_em TEXT NOT NULL)")
    antigo.execute("INSERT INTO agendamentos VALUES (1, 't', 'Ana', 'Escova', '2026-12-01T10:00', "
                   "'2026-12-01T10:45', 'confirmado', '2026-11-01T10:00:00')")
    antigo.commit()
    antigo.close()

    banco = Banco(caminho)   # abre o banco antigo: deve migrar sem perder dados
    assert banco.cancelar_agendamento(1, "t")
    linha = banco.conn.execute("SELECT status, cancelado_em FROM agendamentos").fetchone()
    assert linha["status"] == "cancelado" and linha["cancelado_em"]
    Banco(caminho)           # abrir de novo não tenta migrar outra vez
