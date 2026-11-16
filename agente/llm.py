"""Camada de LLM: esconde as diferenças entre provedores.

O agente guarda o histórico num formato NEUTRO (nosso), e cada provedor
converte para o formato da sua API. Assim dá para trocar de modelo mudando o .env.

Formato neutro das mensagens:
  {"role": "user",      "content": "texto"}
  {"role": "assistant", "content": "texto ou None", "tool_calls": [{"id", "nome", "argumentos", "extra"}]}
  {"role": "tool",      "tool_call_id": "...", "nome": "...", "content": "resultado"}

`extra` guarda campos próprios do provedor que precisam voltar intactos no turno
seguinte. Ex.: o Gemini 3 exige a `thought_signature` de cada tool call; sem ela, 400.
"""

import json
import logging
import os
import re
import time
from dataclasses import dataclass, field

from .tools import Tool

log = logging.getLogger("llm")

# Erros em que vale tentar outro modelo: sobrecarga, limite de cota, falha do servidor.
# 400/401/404 NÃO entram: são erro nosso (requisição/config), e trocar de modelo esconderia o bug.
STATUS_TRANSITORIOS = {408, 429, 500, 502, 503, 504}
QUARENTENA_S = 120


def _transitorio(e: Exception) -> bool:
    import openai
    if isinstance(e, openai.APIConnectionError):  # inclui APITimeoutError
        return True
    return getattr(e, "status_code", None) in STATUS_TRANSITORIOS


@dataclass
class ChamadaTool:
    id: str
    nome: str
    argumentos: dict
    extra: dict | None = None  # opaco: só o adaptador que gerou sabe o que é


@dataclass
class RespostaLLM:
    texto: str | None
    chamadas: list[ChamadaTool] = field(default_factory=list)


def _limpar_texto(texto: str | None) -> str | None:
    # Alguns modelos locais (ex.: qwen3) devolvem o "raciocínio" entre <think> tags.
    if not texto:
        return texto
    return re.sub(r"<think>.*?</think>", "", texto, flags=re.DOTALL).strip() or None


class ProvedorOpenAI:
    """Qualquer API compatível com OpenAI: OpenAI, Ollama, Gemini, Groq, OpenRouter...

    Resiliência: com `reservas`, uma falha transitória do modelo principal (503, 429,
    timeout) faz a MESMA chamada ir para o próximo modelo da lista. O modelo que falhou
    fica em quarentena por QUARENTENA_S (um "circuit breaker" simples), para as próximas
    mensagens não pagarem o timeout de novo enquanto ele está fora do ar.
    """

    def __init__(self, modelo: str, base_url: str | None = None, api_key: str | None = None,
                 reservas: list[str] | None = None, timeout: float = 60, cliente=None,
                 relogio=time.monotonic):
        self.modelos = [modelo] + [m for m in (reservas or []) if m and m != modelo]
        self.modelo = modelo
        if cliente is None:
            from openai import OpenAI
            # Com reservas, o fallback É a nova tentativa: retry no mesmo modelo só atrasaria.
            cliente = OpenAI(base_url=base_url or None, api_key=api_key or "nao-precisa",
                             timeout=timeout, max_retries=0 if reservas else 2)
        self.cliente = cliente
        self._relogio = relogio
        self._fora_ate: dict[str, float] = {}
        self.ultimo_modelo: str | None = None  # quem respondeu a última chamada (útil no eval)

    def responder(self, system: str, mensagens: list[dict], tools: list[Tool]) -> RespostaLLM:
        msgs = [{"role": "system", "content": system}] + [self._converter(m) for m in mensagens]
        tools_api = [{"type": "function",
                      "function": {"name": t.nome, "description": t.descricao, "parameters": t.parametros}}
                     for t in tools]

        agora = self._relogio()
        # Se todos estiverem em quarentena, tenta todos assim mesmo (melhor que desistir).
        candidatos = [m for m in self.modelos if self._fora_ate.get(m, 0) <= agora] or self.modelos
        ultimo_erro: Exception | None = None
        for modelo in candidatos:
            try:
                r = self.cliente.chat.completions.create(model=modelo, messages=msgs, tools=tools_api)
            except Exception as e:
                if not _transitorio(e) or len(self.modelos) == 1:
                    raise
                log.warning("Modelo %s indisponível (%s); quarentena de %ss",
                            modelo, getattr(e, "status_code", type(e).__name__), QUARENTENA_S)
                self._fora_ate[modelo] = self._relogio() + QUARENTENA_S
                ultimo_erro = e
                continue
            if modelo != self.modelo:
                log.info("Resposta do modelo reserva %s", modelo)
            self.ultimo_modelo = modelo
            return self._ler(r)
        raise ultimo_erro

    @staticmethod
    def _ler(r) -> RespostaLLM:
        msg = r.choices[0].message
        chamadas = []
        for tc in msg.tool_calls or []:
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            # Campos fora do padrão OpenAI (ex.: extra_content do Gemini) chegam em model_extra.
            chamadas.append(ChamadaTool(tc.id, tc.function.name, args, tc.model_extra or None))
        return RespostaLLM(_limpar_texto(msg.content), chamadas)

    @staticmethod
    def _converter(m: dict) -> dict:
        if m["role"] == "assistant":
            saida = {"role": "assistant", "content": m.get("content")}
            if m.get("tool_calls"):
                saida["tool_calls"] = [
                    {**(c.get("extra") or {}), "id": c["id"], "type": "function",
                     "function": {"name": c["nome"], "arguments": json.dumps(c["argumentos"])}}
                    for c in m["tool_calls"]
                ]
            return saida
        if m["role"] == "tool":
            return {"role": "tool", "tool_call_id": m["tool_call_id"], "content": m["content"]}
        return {"role": "user", "content": m["content"]}


class ProvedorAnthropic:
    """Claude (API da Anthropic)."""

    def __init__(self, modelo: str, api_key: str | None = None):
        from anthropic import Anthropic
        self.modelo = modelo
        self.cliente = Anthropic(api_key=api_key)

    def responder(self, system: str, mensagens: list[dict], tools: list[Tool]) -> RespostaLLM:
        r = self.cliente.messages.create(
            model=self.modelo,
            max_tokens=1024,
            system=system,
            messages=self._converter(mensagens),
            tools=[{"name": t.nome, "description": t.descricao, "input_schema": t.parametros}
                   for t in tools],
        )
        texto = "".join(b.text for b in r.content if b.type == "text") or None
        chamadas = [ChamadaTool(b.id, b.name, b.input) for b in r.content if b.type == "tool_use"]
        return RespostaLLM(texto, chamadas)

    @staticmethod
    def _converter(mensagens: list[dict]) -> list[dict]:
        # Na Anthropic, resultados de tool vão dentro de uma mensagem "user",
        # e mensagens seguidas do mesmo papel precisam ser unidas.
        saida: list[dict] = []
        for m in mensagens:
            if m["role"] == "assistant":
                role = "assistant"
                blocos = [{"type": "text", "text": m["content"]}] if m.get("content") else []
                blocos += [{"type": "tool_use", "id": c["id"], "name": c["nome"], "input": c["argumentos"]}
                           for c in m.get("tool_calls") or []]
            elif m["role"] == "tool":
                role = "user"
                blocos = [{"type": "tool_result", "tool_use_id": m["tool_call_id"], "content": m["content"]}]
            else:
                role = "user"
                blocos = [{"type": "text", "text": m["content"]}]
            if not blocos:  # a API rejeita mensagens vazias
                continue
            if saida and saida[-1]["role"] == role:
                saida[-1]["content"].extend(blocos)
            else:
                saida.append({"role": role, "content": blocos})
        return saida


def criar_llm():
    """Cria o provedor a partir das variáveis do .env."""
    provedor = os.getenv("LLM_PROVEDOR", "ollama").lower()
    modelo = os.getenv("LLM_MODELO")

    if provedor == "ollama":
        return ProvedorOpenAI(modelo or "qwen3:8b", base_url="http://localhost:11434/v1")
    if provedor == "openai":
        if not modelo:
            raise ValueError("Defina LLM_MODELO no .env")
        reservas = [m.strip() for m in os.getenv("LLM_MODELOS_RESERVA", "").split(",") if m.strip()]
        return ProvedorOpenAI(modelo, base_url=os.getenv("OPENAI_BASE_URL"),
                              api_key=os.getenv("OPENAI_API_KEY"), reservas=reservas,
                              timeout=float(os.getenv("LLM_TIMEOUT_S", "60")))
    if provedor == "anthropic":
        return ProvedorAnthropic(modelo or "claude-haiku-5-5", api_key=os.getenv("ANTHROPIC_API_KEY"))
    raise ValueError(f"LLM_PROVEDOR desconhecido: {provedor}")
