# -*- coding: utf-8 -*-
"""
Configuração dos testes.
Testes marcados com @pytest.mark.integracao chamam o provedor real e consomem cota:
são pulados, a menos que RODAR_TESTES_INTEGRACAO=1 e a chave do provedor ativo (LLM_PROVIDER) estejam configurados.
Os demais testes não dependem do .env local: as variáveis de provedor carregadas dele são removidas e o
provedor fica no Gemini legado, para o qual os testes do Desafio 01 (RF04) foram escritos. Os testes do
Desafio 02 escolhem o provedor explicitamente.
"""

import os
import sys
from pathlib import Path

import pytest

raiz_projeto = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(raiz_projeto))

VARIAVEIS_DO_PROVEDOR = (
    "LLM_PROVIDER", "OPENAI_API_KEY", "OPENAI_MODEL", "OPENAI_ALT_MODEL", "OPENAI_EMBEDDING_MODEL",
    "OPENAI_MODERATION_MODEL", "GEMINI_API_KEY", "GEMINI_MODEL", "HF_TOKEN",
)


@pytest.fixture(autouse=True)
def ambiente_isolado(request, monkeypatch):
    """Testes offline nunca usam as chaves do .env nem chamam a rede por engano."""
    if "integracao" in request.keywords:
        return
    for variavel in VARIAVEIS_DO_PROVEDOR:
        monkeypatch.delenv(variavel, raising=False)
    monkeypatch.setenv("LLM_PROVIDER", "google")


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
