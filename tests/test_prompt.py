from datetime import datetime

from agente.config import carregar_negocio
from agente.prompt import montar_prompt

QUINTA_A_NOITE = datetime(2026, 11, 12, 21, 47)


def test_calendario_marca_hoje_e_amanha():
    p = montar_prompt(carregar_negocio(), QUINTA_A_NOITE)
    assert "- HOJE, quinta-feira 12/11 = 2026-11-12" in p
    assert "- AMANHÃ, sexta-feira 13/11 = 2026-11-13" in p
    # a sexta seguinte aparece sem rótulo, depois da de amanhã
    assert p.index("sexta-feira 13/11") < p.index("sexta-feira 20/11")


def test_prompt_exige_confirmacao_antes_de_acoes():
    p = montar_prompt(carregar_negocio(), QUINTA_A_NOITE)
    assert "ANTES de criar_agendamento ou cancelar_agendamento" in p
    assert "PRÓXIMA ocorrência" in p
