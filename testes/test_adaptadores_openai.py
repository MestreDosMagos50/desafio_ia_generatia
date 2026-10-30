#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
==============================================================================
TESTES DOS ADAPTADORES DE GERAÇÃO DO DESAFIO 02: OPENAI E SIMULADO (RF16, RF21)
==============================================================================
Valida, sem acessar a rede (o SDK da OpenAI é substituído por um falso):
- Chave ausente ou de exemplo, timeout e SDK sem repetições próprias;
- Parâmetros da família GPT-5.6 (max_completion_tokens, reasoning_effort, sem temperature);
- finish_reason="length", refusal e LengthFinishReasonError do parse;
- No máximo 1 repetição por falha transitória e nenhuma em falha definitiva;
- Tokens de raciocínio separados e custo por modelo (luna x terra);
- Esquema estrito, json_object com a palavra "json", PDF convertido em PNG;
- Adaptador simulado identificado, sem tokens e custo, com falha injetável (T12).
Todas as chaves usadas aqui são fictícias.
==============================================================================
"""

import json
import logging
import sys
from pathlib import Path
from types import SimpleNamespace

import httpx2
import openai
import pytest
from pydantic import BaseModel, ConfigDict
from typing import Literal

raiz_projeto = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(raiz_projeto))

from src.adaptadores import OpenAIAdapter, SimulatedAdapter
from src.llm_client import LLMClient

CONFIG = json.loads((raiz_projeto / "config.json").read_text(encoding="utf-8"))
CFG_OPENAI = CONFIG["llm"]["openai"]
CHAVE_FICTICIA = "sk-proj-" + "Z" * 40
REQUISICAO = httpx2.Request("POST", "https://api.openai.com/v1/chat/completions")


class SDKFalso:
    """Substitui openai.OpenAI: entrega os eventos em ordem (o último se repete) e guarda cada chamada."""

    def __init__(self, *eventos):
        self.eventos = list(eventos)
        self.chamadas = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._metodo("create"), parse=self._metodo("parse")))
        self.embeddings = SimpleNamespace(create=self._metodo("embeddings"))
        self.moderations = SimpleNamespace(create=self._metodo("moderations"))

    def _metodo(self, nome):
        def chamada(**kwargs):
            self.chamadas.append((nome, kwargs))
            evento = self.eventos.pop(0) if len(self.eventos) > 1 else self.eventos[0]
            if isinstance(evento, Exception):
                raise evento
            return evento
        return chamada


def resposta_falsa(conteudo="OK", finish="stop", prompt=1000, saida=500, raciocinio=200, recusa=None,
                   modelo="gpt-5.6-luna-2026-07-15"):
    uso = SimpleNamespace(prompt_tokens=prompt, completion_tokens=saida, total_tokens=prompt + saida,
                          completion_tokens_details=SimpleNamespace(reasoning_tokens=raciocinio))
    mensagem = SimpleNamespace(content=conteudo, refusal=recusa)
    return SimpleNamespace(model=modelo, usage=uso, choices=[SimpleNamespace(finish_reason=finish, message=mensagem)])


def erro_status(classe, status, mensagem="erro do provedor", codigo=None):
    return classe(mensagem, response=httpx2.Response(status, request=REQUISICAO), body={"message": mensagem, "code": codigo})


class Eco(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["OK"]


@pytest.fixture
def adaptador(monkeypatch):
    """Fábrica de OpenAIAdapter com SDK falso e sem espera real entre tentativas."""
    monkeypatch.setattr("src.adaptadores.time.sleep", lambda segundos: None)

    def criar(*eventos, modelo=None):
        return OpenAIAdapter(CFG_OPENAI, modelo=modelo, cliente=SDKFalso(*eventos))
    return criar


# ------------------------------------------------------------------------------
# Inicialização e chave
# ------------------------------------------------------------------------------
def test_chave_ausente_nao_cria_cliente():
    adaptador = OpenAIAdapter(CFG_OPENAI)
    resposta = adaptador.gerar("Solicitação de teste")

    assert adaptador.disponivel is False
    assert resposta.sucesso is False
    assert resposta.codigo_erro == "CHAVE_AUSENTE"
    assert "OPENAI_API_KEY" in resposta.erro
    assert resposta.tentativas == 0


def test_chave_de_exemplo_conta_como_ausente(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", OpenAIAdapter.PLACEHOLDER_CHAVE)
    assert OpenAIAdapter(CFG_OPENAI).indisponibilidade[0] == "CHAVE_AUSENTE"


def test_sdk_criado_com_timeout_e_sem_repeticoes_proprias(monkeypatch):
    """O SDK repete 2 vezes por padrão; o RF16 limita a 1 repetição, controlada pelo adaptador."""
    capturado = {}
    monkeypatch.setenv("OPENAI_API_KEY", CHAVE_FICTICIA)
    monkeypatch.setattr("src.adaptadores.openai.OpenAI", lambda **kwargs: capturado.update(kwargs) or SDKFalso(resposta_falsa()))

    adaptador = OpenAIAdapter(CFG_OPENAI)

    assert adaptador.disponivel is True
    assert capturado["max_retries"] == 0
    assert capturado["timeout"] == CFG_OPENAI["timeout_segundos"]


def test_llmclient_openai_delega_ao_adaptador_com_parametros_gpt56(monkeypatch):
    sdk = SDKFalso(resposta_falsa())
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", CHAVE_FICTICIA)
    monkeypatch.setattr("src.adaptadores.openai.OpenAI", lambda **kwargs: sdk)

    cliente = LLMClient()
    resposta = cliente.gerar("Qual o prazo de matrícula?", system_instruction="Instrução de sistema")

    assert (cliente.provedor, cliente.modelo, cliente.variavel_chave) == ("openai", "gpt-5.6-luna", "OPENAI_API_KEY")
    assert resposta.sucesso and resposta.provedor == "openai" and resposta.conteudo == "OK"
    metodo, argumentos = sdk.chamadas[0]
    assert metodo == "create"
    assert argumentos["model"] == "gpt-5.6-luna"
    assert argumentos["max_completion_tokens"] == CFG_OPENAI["max_completion_tokens_padrao"]
    assert argumentos["reasoning_effort"] == CFG_OPENAI["reasoning_effort_padrao"]
    assert "temperature" not in argumentos and "max_tokens" not in argumentos and "top_p" not in argumentos
    assert argumentos["messages"][0] == {"role": "system", "content": "Instrução de sistema"}


def test_provedor_desconhecido_orienta_os_suportados():
    cliente = LLMClient(provedor="outro")
    assert cliente.disponivel is False
    for provedor in ("openai", "google", "simulado"):
        assert provedor in cliente.motivo_indisponibilidade


# ------------------------------------------------------------------------------
# Telemetria e custo
# ------------------------------------------------------------------------------
def test_raciocinio_separado_e_custo_do_luna(adaptador):
    """completion_tokens da OpenAI já inclui o raciocínio: 500 = 300 visíveis + 200 de raciocínio."""
    resposta = adaptador(resposta_falsa()).gerar("Teste")

    assert (resposta.tokens_prompt, resposta.tokens_resposta, resposta.tokens_raciocinio) == (1000, 300, 200)
    assert resposta.tokens_total == 1500
    assert resposta.custo_estimado_usd == pytest.approx(1000 / 1e6 * 0.20 + 500 / 1e6 * 1.20)
    assert resposta.parametros["versao_modelo"] == "gpt-5.6-luna-2026-07-15"


def test_segunda_configuracao_terra_tem_preco_proprio(adaptador):
    falso = adaptador(resposta_falsa(modelo="gpt-5.6-terra"))
    resposta = falso.gerar("Teste", modelo=falso.modelo_alternativo)

    assert falso.cliente.chamadas[0][1]["model"] == "gpt-5.6-terra"
    assert resposta.modelo == "gpt-5.6-terra"
    assert resposta.custo_estimado_usd == pytest.approx(1000 / 1e6 * 2.00 + 500 / 1e6 * 12.00)


def test_modelo_sem_tabela_nao_tem_custo_estimado(adaptador):
    resposta = adaptador(resposta_falsa()).gerar("Teste", modelo="modelo-sem-tabela")

    assert resposta.custo_estimado_usd is None
    assert "sem tabela de preço" in resposta.parametros["observacao_custo"]


# ------------------------------------------------------------------------------
# Resposta truncada, recusa e formatos de saída
# ------------------------------------------------------------------------------
def test_finish_reason_length_vira_resposta_truncada(adaptador):
    """Limite apertado: o raciocínio consome tudo e o conteúdo volta vazio (Aula 08 §3.4)."""
    falso = adaptador(resposta_falsa(conteudo="", finish="length", saida=200, raciocinio=200))
    resposta = falso.gerar("Teste", reasoning_effort="high", max_completion_tokens=200)

    assert resposta.sucesso is False
    assert resposta.codigo_erro == "RESPOSTA_TRUNCADA"
    assert "max_completion_tokens" in resposta.erro
    assert resposta.tokens_raciocinio == 200
    assert len(falso.cliente.chamadas) == 1


def test_parse_truncado_tambem_e_tratado(adaptador):
    """No parse, o SDK lança LengthFinishReasonError; os tokens consumidos entram na resposta."""
    erro = openai.LengthFinishReasonError(completion=resposta_falsa(conteudo=None, finish="length", saida=300, raciocinio=300))
    falso = adaptador(erro)
    resposta = falso.gerar("Teste", schema=Eco)

    assert resposta.codigo_erro == "RESPOSTA_TRUNCADA"
    assert resposta.tokens_raciocinio == 300
    assert len(falso.cliente.chamadas) == 1


def test_recusa_do_modelo_nao_vira_resposta(adaptador):
    resposta = adaptador(resposta_falsa(conteudo=None, recusa="Não posso ajudar com isso.")).gerar("Teste", schema=Eco)

    assert resposta.sucesso is False
    assert resposta.codigo_erro == "RECUSA_MODELO"
    assert "Não posso ajudar" in resposta.erro


def test_resposta_vazia_com_stop_e_falha(adaptador):
    assert adaptador(resposta_falsa(conteudo="   ")).gerar("Teste").codigo_erro == "RESPOSTA_VAZIA"


def test_esquema_estrito_usa_parse_com_a_classe(adaptador):
    falso = adaptador(resposta_falsa(conteudo='{"status": "OK"}'))
    resposta = falso.gerar("Teste", schema=Eco)

    metodo, argumentos = falso.cliente.chamadas[0]
    assert metodo == "parse" and argumentos["response_format"] is Eco
    assert resposta.parametros["modo_saida"] == "json_schema_estrito"
    assert Eco.model_validate_json(resposta.conteudo).status == "OK"


def test_json_object_exige_a_palavra_json_nas_mensagens(adaptador):
    """A API recusa json_object se nenhuma mensagem contiver 'json' (Aula 08 §4.1)."""
    falso = adaptador(resposta_falsa(conteudo="{}"))
    sem_palavra = falso.gerar("Extraia os dados desta solicitação", modo_json=True)
    com_palavra = falso.gerar("Extraia os dados em JSON", modo_json=True)

    argumentos = falso.cliente.chamadas[0][1]
    assert argumentos["response_format"] == {"type": "json_object"}
    assert "JSON" in argumentos["messages"][0]["content"]
    assert sem_palavra.parametros["instrucao_json_acrescentada"] is True
    assert len(falso.cliente.chamadas[1][1]["messages"]) == 1
    assert "instrucao_json_acrescentada" not in com_palavra.parametros


def test_reasoning_effort_invalido_nao_chama_a_api(adaptador):
    """'minimal' foi descontinuado na família GPT-5.6 (Aula 08 §3.3)."""
    falso = adaptador(resposta_falsa())
    resposta = falso.gerar("Teste", reasoning_effort="minimal")

    assert resposta.codigo_erro == "PARAMETRO_INVALIDO"
    assert falso.cliente.chamadas == []


# ------------------------------------------------------------------------------
# Repetição única por falha transitória (RF16) e falhas definitivas
# ------------------------------------------------------------------------------
def test_falha_transitoria_repete_uma_unica_vez(adaptador):
    falso = adaptador(erro_status(openai.RateLimitError, 429, "Rate limit reached"))
    resposta = falso.gerar("Teste")

    assert resposta.codigo_erro == "LIMITE_REQUISICOES"
    assert resposta.tentativas == 2
    assert len(falso.cliente.chamadas) == 2


def test_falha_transitoria_seguida_de_sucesso(adaptador):
    falso = adaptador(erro_status(openai.InternalServerError, 503, "Service unavailable"), resposta_falsa())
    resposta = falso.gerar("Teste")

    assert resposta.sucesso is True
    assert resposta.tentativas == 2


def test_timeout_e_transitorio(adaptador):
    falso = adaptador(openai.APITimeoutError(request=REQUISICAO))
    resposta = falso.gerar("Teste")

    assert resposta.codigo_erro == "TIMEOUT"
    assert len(falso.cliente.chamadas) == 2


def test_cota_insuficiente_nao_repete(adaptador):
    falso = adaptador(erro_status(openai.RateLimitError, 429, "You exceeded your current quota", codigo="insufficient_quota"))
    resposta = falso.gerar("Teste")

    assert resposta.codigo_erro == "COTA_INSUFICIENTE"
    assert len(falso.cliente.chamadas) == 1


def test_autenticacao_invalida_nao_repete_nem_expoe_chave(adaptador, caplog):
    falso = adaptador(erro_status(openai.AuthenticationError, 401, f"Incorrect API key provided: {CHAVE_FICTICIA}"))
    with caplog.at_level(logging.WARNING, logger="LLMClient"):
        resposta = falso.gerar("Teste")

    assert resposta.codigo_erro == "AUTENTICACAO"
    assert len(falso.cliente.chamadas) == 1
    assert CHAVE_FICTICIA not in (resposta.erro or "")
    assert CHAVE_FICTICIA not in caplog.text


def test_modelo_inexistente(adaptador):
    resposta = adaptador(erro_status(openai.NotFoundError, 404, "The model does not exist")).gerar("Teste", modelo="gpt-x")

    assert resposta.codigo_erro == "MODELO_NAO_ENCONTRADO"
    assert "gpt-x" in resposta.erro


def test_requisicao_invalida_mostra_o_detalhe_do_provedor(adaptador):
    erro = erro_status(openai.BadRequestError, 400, "Unsupported parameter: 'max_tokens' is not supported with this model.")
    falso = adaptador(erro)
    resposta = falso.gerar("Teste")

    assert resposta.codigo_erro == "REQUISICAO_INVALIDA"
    assert "Unsupported parameter" in resposta.erro
    assert len(falso.cliente.chamadas) == 1


# ------------------------------------------------------------------------------
# Visão (T15) e serviços auxiliares
# ------------------------------------------------------------------------------
def test_pdf_vira_png_por_pagina_para_a_visao(adaptador):
    """Regressão T15: a ficha digitalizada do Desafio 01 é lida pela visão do gpt-5.6-luna."""
    import pymupdf
    arquivo = raiz_projeto / "dados" / "originais" / "entrada_pdf-imagem.pdf"
    with pymupdf.open(arquivo) as documento:
        paginas = len(documento)
    falso = adaptador(resposta_falsa(conteudo='{"status": "OK"}'))

    resposta = falso.gerar_multimodal(arquivo, "application/pdf", "Leia a ficha.", schema=Eco,
                                      resolucao="MEDIA_RESOLUTION_HIGH")

    partes = falso.cliente.chamadas[0][1]["messages"][-1]["content"]
    assert partes[0] == {"type": "text", "text": "Leia a ficha."}
    imagens = [p["image_url"] for p in partes[1:]]
    assert len(imagens) == paginas == resposta.parametros["paginas_enviadas"]
    assert all(img["url"].startswith("data:image/png;base64,") and img["detail"] == "high" for img in imagens)
    assert resposta.sucesso is True


def test_audio_nao_suportado_no_provedor_openai(adaptador):
    falso = adaptador(resposta_falsa())
    resposta = falso.gerar_multimodal(raiz_projeto / "dados" / "originais" / "entrada_audio.mp3", "audio/mp3", "Transcreva.")

    assert resposta.codigo_erro == "NAO_SUPORTADO"
    assert "google" in resposta.erro
    assert falso.cliente.chamadas == []


def test_chamar_servico_de_embeddings_com_telemetria(adaptador):
    resultado = SimpleNamespace(model="text-embedding-3-small", usage=SimpleNamespace(prompt_tokens=8, total_tokens=8),
                                data=[SimpleNamespace(embedding=[0.0] * 1536)])
    falso = adaptador(resultado)

    vetores, resposta = falso.chamar_servico(
        "embeddings", lambda c: c.embeddings.create(model=falso.modelo_embedding, input=["texto"]), falso.modelo_embedding)

    assert len(vetores.data[0].embedding) == CFG_OPENAI["dimensao_embedding"]
    assert resposta.sucesso and resposta.tokens_prompt == 8
    assert resposta.custo_estimado_usd == pytest.approx(8 / 1e6 * 0.02)


def test_chamar_servico_repete_uma_vez_em_falha_transitoria(adaptador):
    falso = adaptador(openai.APIConnectionError(request=REQUISICAO))
    vetores, resposta = falso.chamar_servico("moderacao", lambda c: c.moderations.create(input="x"), falso.modelo_moderacao)

    assert vetores is None
    assert resposta.codigo_erro == "SEM_CONEXAO"
    assert len(falso.cliente.chamadas) == 2


# ------------------------------------------------------------------------------
# Adaptador simulado (RF21 / T12)
# ------------------------------------------------------------------------------
def test_simulado_identificado_sem_tokens_nem_custo():
    cliente = LLMClient(provedor="simulado")
    resposta = cliente.gerar("Qual o prazo de matrícula?")

    assert cliente.disponivel is True and cliente.variavel_chave is None
    assert resposta.sucesso and resposta.provedor == "simulado"
    assert "SIMULADA" in resposta.conteudo and "sem equivalência de qualidade" in resposta.conteudo
    assert resposta.tokens_total is None and resposta.custo_estimado_usd is None
    assert resposta.parametros["simulado"] is True
    assert "indisponíveis" in resposta.parametros["observacao_custo"]


def test_simulado_e_deterministico():
    adaptador = SimulatedAdapter({})
    assert adaptador.gerar("mesmo prompt").conteudo == adaptador.gerar("mesmo prompt").conteudo
    assert adaptador.gerar("mesmo prompt").conteudo != adaptador.gerar("outro prompt").conteudo


def test_simulado_com_falha_injetada_para_o_t12():
    resposta = SimulatedAdapter({}, falha="INDISPONIVEL").gerar("Teste")

    assert resposta.sucesso is False
    assert resposta.codigo_erro == "INDISPONIVEL"
    assert "T12" in resposta.erro


def test_simulado_com_esquema():
    class ComPadrao(BaseModel):
        status: str = "não localizado"

    adaptador = SimulatedAdapter({})
    assert ComPadrao.model_validate_json(adaptador.gerar("x", schema=ComPadrao).conteudo).status == "não localizado"
    assert adaptador.gerar("x", schema=Eco).codigo_erro == "SIMULADO_SEM_RESPOSTA"
    assert adaptador.gerar("x", schema=Eco).sucesso is False
    personalizado = SimulatedAdapter({}, responder=lambda prompt, schema: '{"status": "OK"}')
    assert Eco.model_validate_json(personalizado.gerar("x", schema=Eco).conteudo).status == "OK"
