"""Persistência em SQLite: histórico de conversa (memória), agendamentos e transferências."""

import json
import sqlite3
from datetime import datetime
from pathlib import Path

from .config import RAIZ

CAMINHO_PADRAO = RAIZ / "dados" / "atendimento.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS mensagens (
    id INTEGER PRIMARY KEY,
    telefone TEXT NOT NULL,
    mensagem TEXT NOT NULL,          -- JSON no formato neutro (ver agente.py)
    criado_em TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS agendamentos (
    id INTEGER PRIMARY KEY,
    telefone TEXT NOT NULL,
    nome_cliente TEXT NOT NULL,
    servico TEXT NOT NULL,
    inicio TEXT NOT NULL,            -- ISO: 2026-10-23T14:00
    fim TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'confirmado',
    criado_em TEXT NOT NULL,
    cancelado_em TEXT
);
CREATE TABLE IF NOT EXISTS transferencias (
    id INTEGER PRIMARY KEY,
    telefone TEXT NOT NULL,
    motivo TEXT NOT NULL,
    resolvido INTEGER NOT NULL DEFAULT 0,
    criado_em TEXT NOT NULL
);
"""


def _agora() -> str:
    return datetime.now().isoformat(timespec="seconds")


class Banco:
    def __init__(self, caminho: str | Path = CAMINHO_PADRAO):
        if str(caminho) != ":memory:":
            Path(caminho).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(caminho, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self._migrar()

    def _migrar(self) -> None:
        """Migrações aditivas para bancos criados por versões anteriores.
        (CREATE TABLE IF NOT EXISTS não altera uma tabela que já existe.)"""
        colunas = {l["name"] for l in self.conn.execute("PRAGMA table_info(agendamentos)")}
        if "cancelado_em" not in colunas:
            self.conn.execute("ALTER TABLE agendamentos ADD COLUMN cancelado_em TEXT")
            self.conn.commit()

    # ---------- memória da conversa ----------

    def salvar_mensagem(self, telefone: str, mensagem: dict) -> None:
        self.conn.execute(
            "INSERT INTO mensagens (telefone, mensagem, criado_em) VALUES (?, ?, ?)",
            (telefone, json.dumps(mensagem, ensure_ascii=False), _agora()),
        )
        self.conn.commit()

    def carregar_historico(self, telefone: str, limite: int = 30) -> list[dict]:
        """Últimas `limite` mensagens. Corta o início até cair numa mensagem do usuário,
        senão poderíamos mandar ao LLM um resultado de tool sem a chamada que o originou."""
        linhas = self.conn.execute(
            "SELECT mensagem FROM mensagens WHERE telefone = ? ORDER BY id DESC LIMIT ?",
            (telefone, limite),
        ).fetchall()
        historico = [json.loads(l["mensagem"]) for l in reversed(linhas)]
        while historico and historico[0]["role"] != "user":
            historico.pop(0)
        return historico

    def ultimas_falas(self, telefone: str, limite: int = 10) -> list[dict]:
        """Só o que cliente e assistente disseram (sem tool calls): serve para um humano ler."""
        falas = [{"papel": m["role"], "texto": m["content"]}
                 for m in self.carregar_historico(telefone, limite * 3)
                 if m["role"] in ("user", "assistant") and m.get("content")]
        return falas[-limite:]

    def conversas_desde(self, desde: str) -> list[dict]:
        """Conversas com mensagens a partir de `desde` (ISO), agrupadas por cliente.
        Mensagens de tool ficam de fora: são detalhes internos e só gastariam tokens no resumo."""
        linhas = self.conn.execute(
            "SELECT telefone, mensagem, criado_em FROM mensagens WHERE criado_em >= ? ORDER BY id",
            (desde,),
        ).fetchall()
        conversas: dict[str, list[dict]] = {}
        for l in linhas:
            m = json.loads(l["mensagem"])
            if m["role"] in ("user", "assistant") and m.get("content"):
                conversas.setdefault(l["telefone"], []).append(
                    {"papel": m["role"], "texto": m["content"], "em": l["criado_em"]})
        return [{"telefone": t, "mensagens": msgs} for t, msgs in conversas.items()]

    def apagar_historico(self, telefone: str) -> None:
        self.conn.execute("DELETE FROM mensagens WHERE telefone = ?", (telefone,))
        self.conn.commit()

    # ---------- agenda ----------

    def criar_agendamento(self, telefone, nome_cliente, servico, inicio: datetime, fim: datetime) -> int:
        cur = self.conn.execute(
            "INSERT INTO agendamentos (telefone, nome_cliente, servico, inicio, fim, criado_em) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (telefone, nome_cliente, servico, inicio.isoformat(timespec="minutes"),
             fim.isoformat(timespec="minutes"), _agora()),
        )
        self.conn.commit()
        return cur.lastrowid

    def ocupacoes_do_dia(self, dia: str) -> list[tuple[datetime, datetime]]:
        linhas = self.conn.execute(
            "SELECT inicio, fim FROM agendamentos WHERE status = 'confirmado' AND inicio LIKE ?",
            (f"{dia}%",),
        ).fetchall()
        return [(datetime.fromisoformat(l["inicio"]), datetime.fromisoformat(l["fim"])) for l in linhas]

    def agendamentos_do_cliente(self, telefone: str, a_partir_de: datetime) -> list[dict]:
        linhas = self.conn.execute(
            "SELECT id, nome_cliente, servico, inicio FROM agendamentos "
            "WHERE telefone = ? AND status = 'confirmado' AND inicio >= ? ORDER BY inicio",
            (telefone, a_partir_de.isoformat(timespec="minutes")),
        ).fetchall()
        return [dict(l) for l in linhas]

    def buscar_agendamento(self, id_agendamento: int) -> dict | None:
        linha = self.conn.execute(
            "SELECT id, telefone, nome_cliente, servico, inicio, fim, status FROM agendamentos WHERE id = ?",
            (id_agendamento,),
        ).fetchone()
        return dict(linha) if linha else None

    def agendamentos_do_dia(self, dia: str, status: str | None = "confirmado") -> list[dict]:
        sql = ("SELECT id, telefone, nome_cliente, servico, inicio, fim, status "
               "FROM agendamentos WHERE inicio LIKE ?")
        params: list = [f"{dia}%"]
        if status:
            sql += " AND status = ?"
            params.append(status)
        return [dict(l) for l in self.conn.execute(sql + " ORDER BY inicio", params).fetchall()]

    def todos_agendamentos(self) -> list[dict]:
        linhas = self.conn.execute(
            "SELECT id, telefone, nome_cliente, servico, inicio, status FROM agendamentos ORDER BY inicio"
        ).fetchall()
        return [dict(l) for l in linhas]

    def cancelar_agendamento(self, id_agendamento: int, telefone: str) -> bool:
        # O filtro por telefone impede um cliente de cancelar o horário de outro.
        cur = self.conn.execute(
            "UPDATE agendamentos SET status = 'cancelado', cancelado_em = ? "
            "WHERE id = ? AND telefone = ? AND status = 'confirmado'",
            (_agora(), id_agendamento, telefone),
        )
        self.conn.commit()
        return cur.rowcount == 1

    # ---------- transferência para humano ----------

    def registrar_transferencia(self, telefone: str, motivo: str) -> None:
        self.conn.execute(
            "INSERT INTO transferencias (telefone, motivo, criado_em) VALUES (?, ?, ?)",
            (telefone, motivo, _agora()),
        )
        self.conn.commit()

    def em_atendimento_humano(self, telefone: str) -> bool:
        linha = self.conn.execute(
            "SELECT 1 FROM transferencias WHERE telefone = ? AND resolvido = 0", (telefone,)
        ).fetchone()
        return linha is not None

    # ---------- métricas (para o relatório semanal) ----------

    def metricas_desde(self, desde: str) -> dict:
        """Números do período calculados em SQL. O relatório usa estes valores; o LLM
        só resume o texto das conversas, porque contagem feita por LLM não é confiável."""
        def um(sql: str) -> int:
            return self.conn.execute(sql, (desde,)).fetchone()[0]

        servicos = self.conn.execute(
            "SELECT servico, COUNT(*) AS quantidade FROM agendamentos WHERE criado_em >= ? "
            "GROUP BY servico ORDER BY quantidade DESC, servico", (desde,),
        ).fetchall()
        return {
            "conversas": um("SELECT COUNT(DISTINCT telefone) FROM mensagens WHERE criado_em >= ?"),
            "mensagens_de_clientes": um(
                "SELECT COUNT(*) FROM mensagens WHERE criado_em >= ? "
                "AND json_extract(mensagem, '$.role') = 'user'"),
            "agendamentos_criados": um("SELECT COUNT(*) FROM agendamentos WHERE criado_em >= ?"),
            "agendamentos_cancelados": um("SELECT COUNT(*) FROM agendamentos WHERE cancelado_em >= ?"),
            "transferencias_humano": um("SELECT COUNT(*) FROM transferencias WHERE criado_em >= ?"),
            "servicos_agendados": [dict(s) for s in servicos],
        }

    def resolver_transferencias(self, telefone: str) -> None:
        self.conn.execute("UPDATE transferencias SET resolvido = 1 WHERE telefone = ?", (telefone,))
        self.conn.commit()
