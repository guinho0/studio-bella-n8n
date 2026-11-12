"""Fallback de modelo + quarentena (circuit breaker) no adaptador OpenAI-compatível."""

from types import SimpleNamespace

import pytest

from agente.llm import QUARENTENA_S, ProvedorOpenAI


class ErroHTTP(Exception):
    def __init__(self, status_code):
        super().__init__(f"HTTP {status_code}")
        self.status_code = status_code


def resposta(texto):
    msg = SimpleNamespace(content=texto, tool_calls=None)
    return SimpleNamespace(choices=[SimpleNamespace(message=msg)])


class ClienteFalso:
    """Imita client.chat.completions.create; `comportamento[modelo]` = lista de resultados/erros."""

    def __init__(self, comportamento):
        self.comportamento = {m: list(r) for m, r in comportamento.items()}
        self.chamados = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, model, messages, tools):
        self.chamados.append(model)
        r = self.comportamento[model].pop(0)
        if isinstance(r, Exception):
            raise r
        return r


class Relogio:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def provedor(comportamento, reservas=("reserva",)):
    cliente = ClienteFalso(comportamento)
    relogio = Relogio()
    p = ProvedorOpenAI("principal", reservas=list(reservas), cliente=cliente, relogio=relogio)
    return p, cliente, relogio


def test_principal_ok_nao_usa_reserva():
    p, cliente, _ = provedor({"principal": [resposta("oi")], "reserva": []})
    assert p.responder("sys", [], []).texto == "oi"
    assert cliente.chamados == ["principal"]


@pytest.mark.parametrize("status", [429, 500, 503, 504])
def test_erro_transitorio_cai_para_reserva(status):
    p, cliente, _ = provedor({"principal": [ErroHTTP(status)], "reserva": [resposta("da reserva")]})
    assert p.responder("sys", [], []).texto == "da reserva"
    assert cliente.chamados == ["principal", "reserva"]


@pytest.mark.parametrize("status", [400, 401, 404])
def test_erro_nosso_nao_troca_de_modelo(status):
    # 400/401/404 indicam bug ou config errada: trocar de modelo esconderia o problema.
    p, cliente, _ = provedor({"principal": [ErroHTTP(status)], "reserva": [resposta("x")]})
    with pytest.raises(ErroHTTP):
        p.responder("sys", [], [])
    assert cliente.chamados == ["principal"]


def test_quarentena_pula_modelo_que_falhou_e_volta_depois():
    p, cliente, relogio = provedor({
        "principal": [ErroHTTP(503), resposta("principal voltou")],
        "reserva": [resposta("r1"), resposta("r2")],
    })
    p.responder("sys", [], [])                       # principal falha -> reserva
    assert p.responder("sys", [], []).texto == "r2"  # em quarentena: vai direto à reserva
    assert cliente.chamados == ["principal", "reserva", "reserva"]

    relogio.t += QUARENTENA_S + 1
    assert p.responder("sys", [], []).texto == "principal voltou"


def test_todos_falham_propaga_o_ultimo_erro():
    p, _, _ = provedor({"principal": [ErroHTTP(503)], "reserva": [ErroHTTP(429)]})
    with pytest.raises(ErroHTTP) as e:
        p.responder("sys", [], [])
    assert e.value.status_code == 429


def test_todos_em_quarentena_ainda_tenta():
    p, cliente, _ = provedor({
        "principal": [ErroHTTP(503), resposta("ok")],
        "reserva": [ErroHTTP(503)],
    })
    with pytest.raises(ErroHTTP):
        p.responder("sys", [], [])
    assert p.responder("sys", [], []).texto == "ok"  # não desiste só por estarem em quarentena


def test_sem_reservas_erro_transitorio_propaga():
    p, cliente, _ = provedor({"principal": [ErroHTTP(503)]}, reservas=())
    with pytest.raises(ErroHTTP):
        p.responder("sys", [], [])
