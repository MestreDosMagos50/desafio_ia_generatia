#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
==============================================================================
TESTES DE TRATAMENTO DE FALHAS, RESILIÊNCIA E SANITIZAÇÃO DE LOGS (RF04)
==============================================================================
Valida, sem acessar a rede (o cliente do provedor é substituído por um falso):
- Chave ausente, autenticação inválida, limite de requisições (429),
  indisponibilidade (5xx), timeout e resposta vazia;
- Falhas retornam sucesso=False com mensagem compreensível e sem texto pronto;
- Ausência de credenciais em mensagens de erro e logs;
- Timeout repassado ao cliente do provedor;
- Telemetria de tokens (incluindo raciocínio) e custo estimado.
Todas as chaves usadas aqui são fictícias.
==============================================================================
"""

import sys
import logging
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from google.genai import errors as genai_errors

raiz_projeto = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(raiz_projeto))

from src.llm_client import LLMClient

CHAVE_FICTICIA_AQ = "AQ." + "X" * 40
CHAVE_FICTICIA_AIZA = "AIza" + "D" * 35
CHAVE_FICTICIA_SK = "sk-" + "a" * 32


class ClienteFalso:
    """Substitui google.genai.Client: entrega os eventos em ordem (o último se repete)."""

    def __init__(self, *eventos):
        self.eventos = list(eventos)
        self.chamadas = 0
        self.models = self

    def generate_content(self, **kwargs):
        self.chamadas += 1
        evento = self.eventos.pop(0) if len(self.eventos) > 1 else self.eventos[0]
        if isinstance(evento, Exception):
            raise evento
        return evento


def resposta_falsa(texto="Minuta de teste", prompt=100, saida=50, raciocinio=25):
    uso = SimpleNamespace(
        prompt_token_count=prompt,
        candidates_token_count=saida,
        thoughts_token_count=raciocinio,
        total_token_count=prompt + saida + raciocinio
    )
    return SimpleNamespace(
        text=texto,
        usage_metadata=uso,
        candidates=[SimpleNamespace(finish_reason="STOP")],
        prompt_feedback=None
    )


def erro_cliente(codigo, mensagem, status):
    return genai_errors.ClientError(codigo, {"error": {"code": codigo, "message": mensagem, "status": status}})


@pytest.fixture
def cliente(monkeypatch):
    """LLMClient com cliente falso, 3 tentativas e sem espera real entre elas."""
    monkeypatch.setattr("src.llm_client.time.sleep", lambda segundos: None)
    c = LLMClient()
    c.max_tentativas = 3
    c.indisponibilidade = None
    c.modelos_alternativos = []  # testes de um único modelo; o fallback tem testes próprios
    c.modelo = c.modelo_precificado  # independe do GEMINI_MODEL do .env
    return c


def test_sanitizacao_de_chaves_em_logs():
    """Garante que padrões de API key nunca são persistidos em logs (RF04 / RF11)."""
    client = LLMClient()
    for chave in (CHAVE_FICTICIA_AIZA, CHAVE_FICTICIA_AQ, CHAVE_FICTICIA_SK):
        sanitizado = client._sanitizar_mensagem(f"Erro ao conectar com a chave {chave} no servidor.")
        assert chave not in sanitizado
        assert "[CHAVE_OCULTADA_POR_SEGURANCA]" in sanitizado


def test_chave_ausente_retorna_falha_compreensivel(monkeypatch):
    """Sem chave: nenhuma chamada, sucesso=False e orientação clara ao usuário (RF04)."""
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    client = LLMClient()

    resposta = client.gerar("Solicitação de teste institucional")

    assert client.disponivel is False
    assert resposta.sucesso is False
    assert resposta.codigo_erro == "CHAVE_AUSENTE"
    assert "GEMINI_API_KEY" in resposta.erro
    assert resposta.conteudo == ""
    assert resposta.tentativas == 0


def test_timeout_repassado_ao_cliente_do_provedor(monkeypatch):
    """O timeout do config.json é enviado ao SDK em milissegundos (RF04)."""
    capturado = {}

    def cliente_capturador(**kwargs):
        capturado.update(kwargs)
        return SimpleNamespace(models=None)

    monkeypatch.setenv("GEMINI_API_KEY", CHAVE_FICTICIA_AQ)
    monkeypatch.setattr("src.llm_client.genai.Client", cliente_capturador)
    client = LLMClient()

    assert client.disponivel is True
    assert capturado["http_options"].timeout == client.timeout * 1000


def test_autenticacao_invalida_nao_retenta(cliente):
    falso = ClienteFalso(erro_cliente(401, "Request had invalid authentication credentials.", "UNAUTHENTICATED"))
    cliente.gemini_client = falso

    resposta = cliente.gerar("teste")

    assert resposta.sucesso is False
    assert resposta.codigo_erro == "AUTENTICACAO"
    assert falso.chamadas == 1


def test_chave_invalida_http_400_tratada_como_autenticacao(cliente):
    """O Gemini responde chave inválida com HTTP 400 (API_KEY_INVALID)."""
    falso = ClienteFalso(erro_cliente(400, "API key not valid. Please pass a valid API key.", "INVALID_ARGUMENT"))
    cliente.gemini_client = falso

    resposta = cliente.gerar("teste")

    assert resposta.codigo_erro == "AUTENTICACAO"
    assert falso.chamadas == 1


def test_limite_requisicoes_retenta_ate_o_maximo(cliente):
    falso = ClienteFalso(erro_cliente(429, "Resource has been exhausted.", "RESOURCE_EXHAUSTED"))
    cliente.gemini_client = falso

    resposta = cliente.gerar("teste")

    assert resposta.sucesso is False
    assert resposta.codigo_erro == "LIMITE_REQUISICOES"
    assert falso.chamadas == 3
    assert resposta.tentativas == 3


def test_limite_requisicoes_recupera_na_segunda_tentativa(cliente):
    falso = ClienteFalso(erro_cliente(429, "Resource has been exhausted.", "RESOURCE_EXHAUSTED"), resposta_falsa())
    cliente.gemini_client = falso

    resposta = cliente.gerar("teste")

    assert resposta.sucesso is True
    assert resposta.tentativas == 2
    assert resposta.conteudo == "Minuta de teste"


def test_indisponibilidade_do_servico(cliente):
    falso = ClienteFalso(genai_errors.ServerError(503, {"error": {"code": 503, "message": "The model is overloaded.", "status": "UNAVAILABLE"}}))
    cliente.gemini_client = falso

    resposta = cliente.gerar("teste")

    assert resposta.sucesso is False
    assert resposta.codigo_erro == "INDISPONIVEL"
    assert "indisponível" in resposta.erro
    assert falso.chamadas == 3


def test_timeout_de_rede(cliente):
    falso = ClienteFalso(httpx.ReadTimeout("tempo esgotado"))
    cliente.gemini_client = falso

    resposta = cliente.gerar("teste")

    assert resposta.codigo_erro == "TIMEOUT"
    assert str(cliente.timeout) in resposta.erro
    assert falso.chamadas == 3


def test_resposta_vazia(cliente):
    falso = ClienteFalso(resposta_falsa(texto=""))
    cliente.gemini_client = falso

    resposta = cliente.gerar("teste")

    assert resposta.sucesso is False
    assert resposta.codigo_erro == "RESPOSTA_VAZIA"
    assert "STOP" in resposta.erro
    assert resposta.conteudo == ""


def test_erro_do_provedor_nao_expoe_chave(cliente, caplog):
    """Mesmo que a mensagem do provedor contenha a chave, ela não chega à resposta nem ao log."""
    falso = ClienteFalso(erro_cliente(403, f"Chave {CHAVE_FICTICIA_AQ} bloqueada.", "PERMISSION_DENIED"))
    cliente.gemini_client = falso

    with caplog.at_level(logging.WARNING, logger="LLMClient"):
        resposta = cliente.gerar("teste")

    assert resposta.codigo_erro == "AUTENTICACAO"
    assert CHAVE_FICTICIA_AQ not in (resposta.erro or "")
    assert CHAVE_FICTICIA_AQ not in caplog.text


def test_telemetria_inclui_tokens_de_raciocinio(cliente):
    """Tokens de raciocínio entram no total e são cobrados como saída."""
    cliente.custo_input_1k = 0.00075
    cliente.custo_output_1k = 0.00375
    cliente.gemini_client = ClienteFalso(resposta_falsa(prompt=1000, saida=500, raciocinio=500))

    resposta = cliente.gerar("teste")

    assert resposta.sucesso is True
    assert resposta.tokens_total == 2000
    assert resposta.tokens_raciocinio == 500
    # 1000 * 0.00075/1k + (500 + 500) * 0.00375/1k = 0.00075 + 0.00375
    assert round(resposta.custo_estimado_usd, 6) == 0.0045
    assert resposta.parametros["temperatura"] == cliente.temperatura


def test_calculo_de_custos_usa_precos_do_config():
    """Valida se o cálculo de custo reflete os preços configurados."""
    client = LLMClient()
    esperado = 1.0 * client.custo_input_1k + 0.5 * client.custo_output_1k
    assert round(client.calcular_custo(1000, 500), 9) == round(esperado, 9)


class ClientePorModelo:
    """Cliente falso que responde conforme o modelo pedido: {modelo: evento}."""

    def __init__(self, eventos_por_modelo):
        self.eventos_por_modelo = eventos_por_modelo
        self.chamadas = []
        self.models = self

    def generate_content(self, **kwargs):
        self.chamadas.append(kwargs["model"])
        evento = self.eventos_por_modelo[kwargs["model"]]
        if isinstance(evento, Exception):
            raise evento
        return evento


def test_modelo_alternativo_quando_cota_diaria_acaba(cliente):
    """429 por cota diária: não insiste no mesmo modelo e usa o alternativo; custo não estimado (preço desconhecido)."""
    cliente.modelos_alternativos = ["modelo-b", "modelo-c"]
    cota_diaria = erro_cliente(429, "Quota exceeded for metric generate_content_free_tier_requests, "
                                    "quotaId: GenerateRequestsPerDayPerProjectPerModel-FreeTier", "RESOURCE_EXHAUSTED")
    falso = ClientePorModelo({cliente.modelo: cota_diaria, "modelo-b": resposta_falsa("ok do B"), "modelo-c": resposta_falsa()})
    cliente.gemini_client = falso

    resposta = cliente.gerar("teste")

    assert resposta.sucesso and resposta.conteudo == "ok do B" and resposta.modelo == "modelo-b"
    assert falso.chamadas == [cliente.modelo, "modelo-b"]  # uma tentativa só no modelo sem cota
    assert resposta.parametros["modelos_tentados"] == [cliente.modelo, "modelo-b"]
    assert resposta.custo_estimado_usd is None


def test_modelo_alternativo_quando_servico_sobrecarregado(cliente):
    cliente.modelos_alternativos = ["modelo-b"]
    sobrecarga = genai_errors.ServerError(503, {"error": {"code": 503, "message": "high demand", "status": "UNAVAILABLE"}})
    falso = ClientePorModelo({cliente.modelo: sobrecarga, "modelo-b": resposta_falsa()})
    cliente.gemini_client = falso

    resposta = cliente.gerar("teste")

    assert resposta.sucesso and resposta.modelo == "modelo-b"
    assert falso.chamadas.count(cliente.modelo) == 3  # sobrecarga é temporária: tenta de novo antes de trocar


def test_sem_alternativo_quando_erro_nao_e_de_cota(cliente):
    """Chave recusada não se resolve trocando de modelo."""
    cliente.modelos_alternativos = ["modelo-b"]
    falso = ClientePorModelo({cliente.modelo: erro_cliente(401, "API key not valid", "UNAUTHENTICATED"), "modelo-b": resposta_falsa()})
    cliente.gemini_client = falso

    resposta = cliente.gerar("teste")

    assert not resposta.sucesso and resposta.codigo_erro == "AUTENTICACAO" and falso.chamadas == [cliente.modelo]


def test_experimento_pode_proibir_alternativos(cliente):
    cliente.modelos_alternativos = ["modelo-b"]
    falso = ClientePorModelo({cliente.modelo: erro_cliente(429, "PerDay quota", "RESOURCE_EXHAUSTED"), "modelo-b": resposta_falsa()})
    cliente.gemini_client = falso

    resposta = cliente.gerar("teste", permitir_alternativos=False)

    assert not resposta.sucesso and resposta.codigo_erro == "LIMITE_REQUISICOES" and falso.chamadas == [cliente.modelo]
