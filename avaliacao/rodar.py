"""Roda o eval contra o LLM REAL configurado no .env (gasta cota da API).

    python -m avaliacao.rodar                  # os 10 casos, 1 vez cada
    python -m avaliacao.rodar --vezes 3        # mede consistência (LLM não é determinístico)
    python -m avaliacao.rodar --so injection   # filtra casos pelo nome

Resultado no terminal e em avaliacao/resultados.md.
Falha = o agente se comportou errado. Erro = a infraestrutura falhou (ex.: cota do
Gemini esgotada); erros não contam contra o agente, mas aparecem no relatório.
"""

import argparse
import logging
import os
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

from agente.agente import Agente
from agente.banco import Banco
from agente.config import carregar_negocio
from agente.llm import criar_llm

from .casos import AGORA, CASOS, CLIENTE, Caso, Execucao

RELATORIO = Path(__file__).with_name("resultados.md")


def rodar_caso(caso: Caso, llm, negocio: dict, modelos: Counter) -> tuple[str, list[str], Execucao | None, float]:
    banco = Banco(":memory:")
    caso.preparar(banco)
    agente = Agente(llm, banco, negocio, relogio=lambda: AGORA)
    respostas, eventos = [], []
    inicio = time.monotonic()
    # Conta qual modelo respondeu cada chamada (o fallback pode trocar no meio).
    original = llm.responder

    def contando(*a, **k):
        r = original(*a, **k)
        modelos[getattr(llm, "ultimo_modelo", None) or getattr(llm, "modelo", "?")] += 1
        return r

    llm.responder = contando
    try:
        for texto in caso.turnos:
            r = agente.processar(CLIENTE, texto)
            respostas.append(r.resposta)
            eventos.append(r.eventos)
    except Exception as e:
        return "erro", [f"{type(e).__name__}: {str(e)[:160]}"], None, time.monotonic() - inicio
    finally:
        llm.responder = original
    ex = Execucao(respostas, eventos, banco)
    falhas = caso.verificar(ex)
    return ("ok" if not falhas else "falhou"), falhas, ex, time.monotonic() - inicio


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--vezes", type=int, default=1, help="repetições de cada caso")
    ap.add_argument("--so", default="", help="roda só os casos cujo nome contém este texto")
    ap.add_argument("--pausa", type=float, default=4, help="segundos entre casos (cota do plano grátis)")
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    logging.basicConfig(level=logging.WARNING, format="   %(name)s: %(message)s")

    llm = criar_llm()
    negocio = carregar_negocio()
    casos = [c for c in CASOS if args.so in c.nome]
    modelos: Counter = Counter()
    linhas = []   # (caso, rodada, status, falhas, execucao, segundos)

    for caso in casos:
        for rodada in range(1, args.vezes + 1):
            status, falhas, ex, seg = rodar_caso(caso, llm, negocio, modelos)
            marca = {"ok": "✓", "falhou": "✗", "erro": "!"}[status]
            print(f"{marca} {caso.nome:<26} rodada {rodada}  {seg:5.1f}s  {'; '.join(falhas)}")
            linhas.append((caso, rodada, status, falhas, ex, seg))
            time.sleep(args.pausa)

    validas = [l for l in linhas if l[2] != "erro"]
    ok = sum(1 for l in validas if l[2] == "ok")
    erros = len(linhas) - len(validas)
    print(f"\nResultado: {ok}/{len(validas)} corretos" + (f" ({erros} com erro de infraestrutura)" if erros else ""))
    print(f"Chamadas por modelo: {dict(modelos)}")
    escrever_relatorio(linhas, ok, len(validas), erros, modelos, args.vezes)
    print(f"Relatório: {RELATORIO}")
    return 0 if ok == len(validas) else 1


def escrever_relatorio(linhas, ok, validas, erros, modelos, vezes) -> None:
    principal = os.getenv("LLM_MODELO", "?")
    reservas = os.getenv("LLM_MODELOS_RESERVA", "") or "nenhum"
    out = [
        "# Resultado do eval",
        "",
        f"- Executado em: {datetime.now():%d/%m/%Y %H:%M}",
        f"- Modelo principal: `{principal}`; reservas: `{reservas}`",
        f"- Chamadas ao LLM por modelo: " + ", ".join(f"`{m}`: {n}" for m, n in modelos.most_common()),
        f"- Repetições por caso: {vezes}",
        f"- **Resultado: {ok}/{validas} corretos**" + (f" ({erros} rodada(s) com erro de infraestrutura, fora da conta)" if erros else ""),
        "",
        "| Caso | Objetivo | Resultado | Tempo |",
        "|---|---|---|---|",
    ]
    for caso, rodada, status, falhas, ex, seg in linhas:
        nome = caso.nome + (f" (#{rodada})" if vezes > 1 else "")
        res = {"ok": "✅ ok", "falhou": "❌ " + "; ".join(falhas), "erro": "⚠️ erro: " + "; ".join(falhas)}[status]
        out.append(f"| `{nome}` | {caso.objetivo} | {res} | {seg:.1f}s |")
    out += ["", "## Conversas", ""]
    for caso, rodada, status, falhas, ex, seg in linhas:
        if not ex:
            continue
        out.append(f"<details><summary><code>{caso.nome}</code> (rodada {rodada}): {status}</summary>\n")
        for i, (pergunta, resposta) in enumerate(zip(caso.turnos, ex.respostas)):
            out.append(f"- **Cliente:** {pergunta}")
            out.append(f"- **Agente:** {(resposta or '(silêncio: com humano)').replace(chr(10), ' ')}")
            tipos = [e['tipo'] for e in ex.eventos_por_turno[i]]
            if tipos:
                out.append(f"- *eventos:* `{', '.join(tipos)}`")
        out.append("\n</details>\n")
    RELATORIO.write_text("\n".join(out) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
