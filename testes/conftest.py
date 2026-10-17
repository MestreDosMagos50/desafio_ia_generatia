# -*- coding: utf-8 -*-
"""
Configuração dos testes.
Testes marcados com @pytest.mark.integracao chamam o provedor real e consomem cota:
são pulados, a menos que RODAR_TESTES_INTEGRACAO=1 e a GEMINI_API_KEY estejam configurados.
"""

import os
import sys
from pathlib import Path

import pytest

raiz_projeto = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(raiz_projeto))


def pytest_collection_modifyitems(config, items):
    if os.getenv("RODAR_TESTES_INTEGRACAO") == "1":
        from src.llm_client import LLMClient
        cliente = LLMClient()
        if cliente.disponivel:
            return
        motivo = f"Integração pedida, mas o provedor está indisponível: {cliente.motivo_indisponibilidade}"
    else:
        motivo = "Teste de integração (consome cota da API): defina RODAR_TESTES_INTEGRACAO=1 para executar"
    pular = pytest.mark.skip(reason=motivo)
    for item in items:
        if "integracao" in item.keywords:
            item.add_marker(pular)
