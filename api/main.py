"""API HTTP do agente: a porta de entrada para o n8n (ou qualquer outro canal).

Esta camada é FINA de propósito: só traduz HTTP <-> Agente/Banco. Toda regra de
negócio continua em agente/. O n8n cuida de canal (Telegram), integrações e agendas.

    n8n ──POST /mensagem {telefone, texto}──► Agente.processar() ──► {resposta, eventos[]}

Rodar:  uvicorn api.main:criar_app --factory --port 8000
"""

import logging
import os
import threading
from datetime import date, datetime
from typing import Literal

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from pydantic import BaseModel, Field, field_validator

from agente.agente import Agente
from agente.banco import CAMINHO_PADRAO, Banco
from agente.config import carregar_negocio
from agente.llm import criar_llm

log = logging.getLogger("api")

TipoEvento = Literal["agendamento_criado", "agendamento_cancelado", "transferido_humano"]


class MensagemIn(BaseModel):
    telefone: str = Field(min_length=1, max_length=64,
                          description="Identificador do cliente no canal (no Telegram, o chat_id)")
    texto: str = Field(min_length=1, max_length=4000)

    @field_validator("telefone", mode="before")
    @classmethod
    def _aceita_numero(cls, v):
        # O chat_id do Telegram chega como número; tratamos tudo como texto.
        return str(v) if isinstance(v, int) else v


class Evento(BaseModel):
    tipo: TipoEvento
    dados: dict


class MensagemOut(BaseModel):
    resposta: str | None = Field(description="null = conversa com humano; o canal não deve responder")
    eventos: list[Evento]


def criar_app(agente: Agente | None = None, api_token: str | None = None) -> FastAPI:
    """Factory: os testes injetam um agente com LLM falso; em produção lemos o .env.

    api_token: None = lê API_TOKEN do ambiente; "" = sem autenticação.
    """
    if agente is None:
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
        banco = Banco(os.getenv("BANCO_CAMINHO") or CAMINHO_PADRAO)
        agente = Agente(criar_llm(), banco, carregar_negocio())
    banco = agente.banco
    if api_token is None:
        api_token = os.getenv("API_TOKEN", "")

    # Uma conexão SQLite compartilhada + histórico por cliente => serializamos o acesso.
    # Para um estabelecimento o volume é baixo; se crescer, a troca é trava por telefone
    # e um banco cliente/servidor (Postgres).
    trava = threading.Lock()

    def autenticar(x_api_key: str | None = Header(default=None)):
        if api_token and x_api_key != api_token:
            raise HTTPException(status_code=401, detail="X-API-Key inválida")

    app = FastAPI(title="Agente de atendimento", version="2.0.0")
    protegido = [Depends(autenticar)]  # tudo, menos /health (usado pelo healthcheck do Docker)

    # Endpoints `def` (não async): a chamada ao LLM é bloqueante, então o FastAPI
    # os executa num threadpool em vez de travar o event loop.

    @app.get("/health")
    def health():
        return {"ok": True}

    @app.post("/mensagem", response_model=MensagemOut, dependencies=protegido)
    def mensagem(m: MensagemIn):
        with trava:
            try:
                r = agente.processar(m.telefone, m.texto.strip())
            except Exception:
                log.exception("Falha ao processar mensagem de %s", m.telefone)
                # 502: o problema está num serviço de que dependemos (LLM). O n8n pode
                # tratar no ramo de erro (ex.: responder "tente de novo em instantes").
                raise HTTPException(status_code=502, detail="Falha ao consultar o LLM")
        return MensagemOut(resposta=r.resposta, eventos=r.eventos)

    @app.get("/agendamentos", dependencies=protegido)
    def agendamentos(data: date = Query(description="AAAA-MM-DD"),
                     status: Literal["confirmado", "cancelado", "todos"] = "confirmado"):
        with trava:
            itens = banco.agendamentos_do_dia(data.isoformat(), None if status == "todos" else status)
        return {"data": data.isoformat(), "agendamentos": itens}

    @app.get("/conversas", dependencies=protegido)
    def conversas(desde: datetime = Query(description="AAAA-MM-DD ou AAAA-MM-DDTHH:MM")):
        with trava:
            itens = banco.conversas_desde(desde.isoformat(timespec="seconds"))
        return {"desde": desde.isoformat(timespec="seconds"), "conversas": itens}

    @app.post("/conversas/{telefone}/liberar", dependencies=protegido)
    def liberar(telefone: str):
        """Devolve a conversa ao robô depois de uma transferência para humano."""
        with trava:
            banco.resolver_transferencias(telefone)
        return {"ok": True}

    return app
