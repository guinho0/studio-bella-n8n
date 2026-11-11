import json
from pathlib import Path

from dotenv import load_dotenv

RAIZ = Path(__file__).resolve().parent.parent
load_dotenv(RAIZ / ".env")


def carregar_negocio(pasta: Path = RAIZ / "negocio") -> dict:
    """Lê os dados do negócio (serviços, horários) e o FAQ.

    Trocar de cliente = trocar esta pasta. O código do agente não muda.
    """
    negocio = json.loads((pasta / "negocio.json").read_text(encoding="utf-8"))
    negocio["faq"] = (pasta / "faq.md").read_text(encoding="utf-8")
    return negocio
