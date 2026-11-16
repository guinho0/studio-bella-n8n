"""Ferramentas (tools) que o agente pode usar.

Cada tool tem: nome, descrição (o LLM lê isso para decidir quando usar),
parâmetros em JSON Schema e a função Python que realmente executa.

Regra de ouro: a tool VALIDA tudo. Nunca confie que o modelo mandou dados certos.
"""

import json
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Callable
from uuid import uuid4

from .banco import Banco

DIAS_SEMANA = ["segunda", "terca", "quarta", "quinta", "sexta", "sabado", "domingo"]


@dataclass
class Tool:
    nome: str
    descricao: str
    parametros: dict
    funcao: Callable[..., str]


@dataclass
class Contexto:
    """O que as tools sabem sobre a conversa atual.

    O telefone vem daqui, e não de um parâmetro: assim o modelo não consegue
    agir em nome de outro cliente, mesmo que alguém tente enganá-lo.

    `eventos` registra os efeitos colaterais que DE FATO aconteceram neste turno
    (agendou, cancelou, transferiu). Quem orquestra (n8n) ramifica por eles, e
    nunca pelo texto do LLM: o texto pode mudar de estilo, o evento não.
    """
    telefone: str
    banco: Banco
    negocio: dict
    agora: datetime
    eventos: list[dict] = field(default_factory=list)
    turno: str = field(default_factory=lambda: uuid4().hex)  # um por mensagem do cliente

    def emitir(self, tipo: str, **dados) -> None:
        self.eventos.append({"tipo": tipo, "dados": {"telefone": self.telefone, **dados}})

    def confirmado(self, acao: str, chave: str) -> bool:
        """Confirmação em duas etapas, garantida em CÓDIGO (não no prompt).

        1ª chamada: só registra a proposta e devolve False (nada é gravado).
        A ação só acontece se a MESMA proposta foi feita num turno ANTERIOR, ou seja,
        o cliente já teve a chance de ler e responder. Chamar duas vezes na mesma
        mensagem não fura a regra, seja por erro do modelo ou por prompt injection.
        """
        if self.banco.consumir_confirmacao(self.telefone, acao, chave, self.turno):
            return True
        self.banco.propor(self.telefone, acao, chave, self.turno)
        return False


INSTRUCAO_PENDENTE = ("AINDA NÃO FOI FEITO. Mostre estes dados ao cliente e pergunte se pode confirmar. "
                      "Só se ele confirmar, chame esta ferramenta de novo com exatamente os mesmos dados.")


def _json(obj) -> str:
    return json.dumps(obj, ensure_ascii=False)


def _achar_servico(negocio: dict, nome: str) -> dict | None:
    nome = nome.strip().lower()
    for s in negocio["servicos"]:
        if s["nome"].lower() == nome:
            return s
    return None


def _horarios_livres(ctx: Contexto, dia: date, servico: dict) -> list[str]:
    expediente = ctx.negocio["horario_funcionamento"].get(DIAS_SEMANA[dia.weekday()])
    if not expediente:
        return []
    abre = datetime.combine(dia, datetime.strptime(expediente[0], "%H:%M").time())
    fecha = datetime.combine(dia, datetime.strptime(expediente[1], "%H:%M").time())
    duracao = timedelta(minutes=servico["duracao_min"])
    passo = timedelta(minutes=ctx.negocio["intervalo_agenda_min"])
    ocupado = ctx.banco.ocupacoes_do_dia(dia.isoformat())

    livres = []
    inicio = abre
    while inicio + duracao <= fecha:
        fim = inicio + duracao
        conflita = any(inicio < o_fim and fim > o_ini for o_ini, o_fim in ocupado)
        if inicio > ctx.agora and not conflita:
            livres.append(inicio.strftime("%H:%M"))
        inicio += passo
    return livres


def criar_tools(ctx: Contexto) -> list[Tool]:

    def listar_servicos() -> str:
        return _json(ctx.negocio["servicos"])

    def consultar_horarios(data: str, servico: str) -> str:
        try:
            dia = date.fromisoformat(data)
        except ValueError:
            return _json({"erro": "Data inválida. Use o formato AAAA-MM-DD."})
        if dia < ctx.agora.date():
            return _json({"erro": "Essa data já passou."})
        s = _achar_servico(ctx.negocio, servico)
        if not s:
            return _json({"erro": "Serviço não encontrado.",
                          "servicos_validos": [x["nome"] for x in ctx.negocio["servicos"]]})
        if not ctx.negocio["horario_funcionamento"].get(DIAS_SEMANA[dia.weekday()]):
            return _json({"erro": f"Não abrimos nesse dia ({DIAS_SEMANA[dia.weekday()]})."})
        livres = _horarios_livres(ctx, dia, s)
        return _json({"data": data, "servico": s["nome"], "horarios_livres": livres})

    def criar_agendamento(nome_cliente: str, servico: str, data: str, hora: str) -> str:
        s = _achar_servico(ctx.negocio, servico)
        if not s:
            return _json({"erro": "Serviço não encontrado."})
        try:
            inicio = datetime.fromisoformat(f"{data}T{hora}")
        except ValueError:
            return _json({"erro": "Data/hora inválida. Use AAAA-MM-DD e HH:MM."})
        # Revalida a disponibilidade: o modelo pode ter "inventado" um horário.
        if hora not in _horarios_livres(ctx, inicio.date(), s):
            return _json({"erro": "Horário indisponível. Consulte os horários livres novamente."})
        nome = nome_cliente.strip()
        if not ctx.confirmado("agendar", f"{s['nome']}|{data}|{hora}|{nome.lower()}"):
            return _json({"pendente": True, "instrucao": INSTRUCAO_PENDENTE,
                          "proposta": {"servico": s["nome"], "nome_cliente": nome, "preco": s["preco"],
                                       "data": f"{DIAS_SEMANA[inicio.weekday()]} {inicio:%d/%m/%Y}",
                                       "hora": hora}})
        fim = inicio + timedelta(minutes=s["duracao_min"])
        id_ = ctx.banco.criar_agendamento(ctx.telefone, nome_cliente.strip(), s["nome"], inicio, fim)
        # O evento só é emitido DEPOIS da gravação: se algo falhou acima, não há evento.
        ctx.emitir("agendamento_criado", id_agendamento=id_, nome_cliente=nome_cliente.strip(),
                   servico=s["nome"], inicio=inicio.isoformat(timespec="minutes"),
                   fim=fim.isoformat(timespec="minutes"), preco=s["preco"])
        return _json({"ok": True, "id_agendamento": id_, "servico": s["nome"],
                      "inicio": inicio.strftime("%d/%m/%Y %H:%M"), "preco": s["preco"]})

    def listar_meus_agendamentos() -> str:
        return _json(ctx.banco.agendamentos_do_cliente(ctx.telefone, ctx.agora))

    def cancelar_agendamento(id_agendamento: int) -> str:
        id_agendamento = int(id_agendamento)
        a = ctx.banco.buscar_agendamento(id_agendamento)
        # Mesma resposta para "não existe" e "é de outro cliente": não vaza nada sobre terceiros.
        if not a or a["telefone"] != ctx.telefone or a["status"] != "confirmado":
            return _json({"erro": "Agendamento não encontrado para este cliente."})
        if not ctx.confirmado("cancelar", str(id_agendamento)):
            inicio = datetime.fromisoformat(a["inicio"])
            return _json({"pendente": True, "instrucao": INSTRUCAO_PENDENTE,
                          "proposta": {"cancelar": a["servico"], "nome_cliente": a["nome_cliente"],
                                       "data": f"{DIAS_SEMANA[inicio.weekday()]} {inicio:%d/%m/%Y}",
                                       "hora": f"{inicio:%H:%M}"}})
        ctx.banco.cancelar_agendamento(id_agendamento, ctx.telefone)
        ctx.emitir("agendamento_cancelado", id_agendamento=id_agendamento,
                   nome_cliente=a["nome_cliente"], servico=a["servico"],
                   inicio=a["inicio"], fim=a["fim"])
        return _json({"ok": True})

    def transferir_para_humano(motivo: str) -> str:
        ctx.banco.registrar_transferencia(ctx.telefone, motivo)
        ctx.emitir("transferido_humano", motivo=motivo,
                   ultimas_mensagens=ctx.banco.ultimas_falas(ctx.telefone))
        return _json({"ok": True, "aviso": "Uma atendente vai assumir a conversa."})

    return [
        Tool("listar_servicos", "Lista os serviços oferecidos, com duração (min) e preço (R$).",
             {"type": "object", "properties": {}}, listar_servicos),
        Tool("consultar_horarios",
             "Retorna os horários livres de um serviço numa data. Use SEMPRE antes de agendar.",
             {"type": "object",
              "properties": {
                  "data": {"type": "string", "description": "Data no formato AAAA-MM-DD"},
                  "servico": {"type": "string", "description": "Nome exato do serviço"}},
              "required": ["data", "servico"]},
             consultar_horarios),
        Tool("criar_agendamento",
             "Agenda um serviço, em DUAS etapas: a 1ª chamada só devolve uma proposta 'pendente' para "
             "o cliente confirmar; depois que ele confirmar, chame de novo com os mesmos dados.",
             {"type": "object",
              "properties": {
                  "nome_cliente": {"type": "string"},
                  "servico": {"type": "string", "description": "Nome exato do serviço"},
                  "data": {"type": "string", "description": "AAAA-MM-DD"},
                  "hora": {"type": "string", "description": "HH:MM"}},
              "required": ["nome_cliente", "servico", "data", "hora"]},
             criar_agendamento),
        Tool("listar_meus_agendamentos", "Lista os próximos agendamentos deste cliente.",
             {"type": "object", "properties": {}}, listar_meus_agendamentos),
        Tool("cancelar_agendamento",
             "Cancela um agendamento do cliente pelo id, em DUAS etapas: a 1ª chamada só devolve uma "
             "proposta 'pendente' para o cliente confirmar; depois que ele confirmar, chame de novo.",
             {"type": "object",
              "properties": {"id_agendamento": {"type": "integer"}},
              "required": ["id_agendamento"]},
             cancelar_agendamento),
        Tool("transferir_para_humano",
             "Passa a conversa para uma atendente humana. Use quando o cliente pedir, reclamar, "
             "ou quando você não souber responder com as informações que tem.",
             {"type": "object",
              "properties": {"motivo": {"type": "string"}},
              "required": ["motivo"]},
             transferir_para_humano),
    ]
