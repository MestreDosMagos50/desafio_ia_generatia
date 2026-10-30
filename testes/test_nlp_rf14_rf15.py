#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
==============================================================================
TESTES DA EXTRAÇÃO ESTRUTURADA, REGRAS DE NEGÓCIO E FICHA NLP (RF14, RF15)
==============================================================================
Sem rede (adaptador simulado ou SDK falso da OpenAI):
- T01: contrato estrito aceito pela API e erros classificados em chave extra,
  tipo incorreto, campo obrigatório ausente, valor fora do domínio e JSON inválido;
- T02: data impossível, valor sem apoio no texto e incoerências bloqueiam a
  minuta; entidade sem apoio encaminha à revisão;
- validação local com no máximo 1 correção e rejeição antes da minuta;
  esquema nativo sem repetição; entrada, erro e decisão preservados;
- RF15: resumo de até 100 palavras com uma tentativa de redução, entidades
  literais separadas das inferidas e números sem lastro sinalizados;
- T03: avaliação contra o gabarito com numerador e denominador.
==============================================================================
"""

import json
import sys
from pathlib import Path

import pytest
from openai.lib._pydantic import to_strict_json_schema

raiz_projeto = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(raiz_projeto))

from src.adaptadores import OpenAIAdapter
from src.llm_client import LLMClient
from src.nlp import (
    BLOQUEAR_REGRA, ENCAMINHAR_REVISAO, GERAR_MINUTA, REJEITAR_SAIDA,
    ExtratorSolicitacoes, ResultadoExtracao, _registro_de_conferencia, avaliar_contra_gabarito,
    classificar_erros_contrato, conferir_regras_negocio, datas_do_texto, decidir, numeros_sem_lastro,
    relatorio_avaliacao_md,
)
from src.prompts import VERSOES_PROMPTS
from src.schemas import CATEGORIAS, ContratoSolicitacaoV2, FichaCompreensaoNLP, ResumoNLP
from test_adaptadores_openai import CFG_OPENAI, SDKFalso, resposta_falsa

CONFIG = json.loads((raiz_projeto / "config.json").read_text(encoding="utf-8"))


def carregar(chave: str) -> dict:
    return json.loads((raiz_projeto / CONFIG["desafio02"][chave]).read_text(encoding="utf-8"))


GABARITO = carregar("gabarito_solicitacoes")
CASOS = {c["id"]: c for c in GABARITO["casos"]}
ENTRADAS = {s["id"]: s for s in carregar("solicitacoes")["solicitacoes"]}
NEGATIVOS = carregar("casos_negativos_t01_t02")


def texto_de(id_caso: str) -> str:
    return (raiz_projeto / ENTRADAS[id_caso]["arquivo"]).read_text(encoding="utf-8")


def contrato_esperado(id_caso: str, **alteracoes) -> ContratoSolicitacaoV2:
    return ContratoSolicitacaoV2.model_validate({**CASOS[id_caso]["esperado"], **alteracoes})


def extrator_simulado(responder, tmp_path) -> ExtratorSolicitacoes:
    cliente = LLMClient(provedor="simulado")
    cliente.adaptador.responder = responder
    return ExtratorSolicitacoes(llm_client=cliente, dir_saida=tmp_path)


def resumo_json(resumo: str, inferidas=()) -> str:
    return ResumoNLP(resumo=resumo, informacoes_inferidas=list(inferidas)).model_dump_json()


# ------------------------------------------------------------------------------
# Contrato e T01
# ------------------------------------------------------------------------------
def test_categorias_do_contrato_sao_as_documentadas_no_config():
    assert set(CATEGORIAS) == set(CONFIG["classificacao"]["categorias_desafio02"])
    assert {"OUTROS", "REVISAO"} <= set(CATEGORIAS)


@pytest.mark.parametrize("modelo", [ContratoSolicitacaoV2, ResumoNLP])
def test_esquema_segue_o_subconjunto_estrito_da_api(modelo):
    esquema = to_strict_json_schema(modelo)
    texto = json.dumps(esquema)
    for objeto in [esquema, *esquema.get("$defs", {}).values()]:
        assert objeto["additionalProperties"] is False
        assert set(objeto["required"]) == set(objeto["properties"])
    for palavra in ("pattern", "minimum", "maximum", "minLength", "maxLength", "format"):
        assert f'"{palavra}"' not in texto


def test_t01_payloads_classificados_como_no_gabarito():
    for caso in NEGATIVOS["t01_payloads"]:
        assert sorted({e["codigo"] for e in classificar_erros_contrato(caso["payload"])}) == sorted(caso["erros_esperados"]), caso["id"]


def test_t01_json_invalido_e_categoria_fora_do_dominio():
    assert [e["codigo"] for e in classificar_erros_contrato('{"protocolo": ')] == ["JSON_INVALIDO"]
    payload = {**CASOS["SOL-01"]["esperado"], "categoria": "MATRICULA"}
    assert [e["codigo"] for e in classificar_erros_contrato(payload)] == ["VALOR_FORA_DO_DOMINIO"]
    assert classificar_erros_contrato(CASOS["SOL-01"]["esperado"]) == []


def test_tipo_incorreto_nao_e_convertido_em_silencio():
    """Modo strict: 'false' em texto não vira booleano (seria um erro escondido)."""
    payload = {**CASOS["SOL-01"]["esperado"], "necessita_revisao": "false"}
    assert [e["codigo"] for e in classificar_erros_contrato(payload)] == ["TIPO_INCORRETO"]


def test_interface_mostra_nao_localizado_nos_campos_null():
    exibicao = contrato_esperado("SOL-05").para_exibicao_interface()
    assert exibicao["pedido"] == "não localizado"
    assert exibicao["versao_esquema"] == "2.0.0"
    assert contrato_esperado("SOL-05").pedido is None


# ------------------------------------------------------------------------------
# Regras de negócio e T02
# ------------------------------------------------------------------------------
@pytest.mark.parametrize("id_caso", sorted(CASOS))
def test_gabarito_passa_nas_regras_e_leva_a_decisao_esperada(id_caso):
    """As regras não podem acusar o próprio gabarito: sem alertas e com a decisão esperada."""
    contrato = contrato_esperado(id_caso)
    alertas = conferir_regras_negocio(contrato, texto_de(id_caso))
    assert alertas == [], [a.mensagem for a in alertas]
    assert decidir(contrato, alertas)[0] == CASOS[id_caso]["decisao_esperada"]


def test_datas_reais_e_impossiveis_do_texto():
    validas, impossiveis = datas_do_texto("Protocolo de 14 de outubro de 2026; retorno em 03/11/2026; prazo 31/02/2026.")
    assert validas == {"14/10/2026", "03/11/2026"}
    assert impossiveis == ["31/02/2026"]


def contrato_t02a(data):
    return ContratoSolicitacaoV2(
        protocolo="2026-000266", data_solicitacao=data, solicitante_ficticio="Débora Lins Ferraz Teste",
        curso="Técnico em Recursos Humanos", assunto="Declaração de matrícula",
        pedido="Emitir declaração de matrícula", categoria="OUTROS",
        entidades={"pessoas_ficticias": ["Débora Lins Ferraz Teste"], "orgaos": [], "locais": [],
                   "datas": [data] if data else [], "protocolos": ["2026-000266"]},
        campos_ausentes=[] if data else ["data_solicitacao"], necessita_revisao=False,
    )


@pytest.mark.parametrize("data", ["31/02/2026", None])
def test_t02_data_impossivel_bloqueia_mesmo_se_o_modelo_omitir(data):
    texto = (raiz_projeto / NEGATIVOS["t02_casos"][0]["arquivo"]).read_text(encoding="utf-8")
    alertas = conferir_regras_negocio(contrato_t02a(data), texto)

    assert "DATA_INVALIDA" in {a.codigo for a in alertas}
    assert decidir(contrato_t02a(data), alertas)[0] == BLOQUEAR_REGRA


def test_t02_valor_sem_apoio_no_texto_bloqueia():
    caso = NEGATIVOS["t02_casos"][1]
    contrato = ContratoSolicitacaoV2.model_validate(caso["extracao_candidata"])
    alertas = conferir_regras_negocio(contrato, (raiz_projeto / caso["texto_original"]).read_text(encoding="utf-8"))

    assert {a.campo for a in alertas if a.codigo == "NAO_ANCORADO"} == set(caso["campos_nao_ancorados"])
    assert decidir(contrato, alertas)[0] == BLOQUEAR_REGRA


def test_entidade_sem_apoio_encaminha_a_revisao_sem_bloquear():
    esperado = CASOS["SOL-04"]["esperado"]
    contrato = contrato_esperado("SOL-04", entidades={**esperado["entidades"], "pessoas_ficticias": ["Rafael Nogueira Prado Teste", "Pessoa Inventada"]})
    alertas = conferir_regras_negocio(contrato, texto_de("SOL-04"))

    assert [(a.codigo, a.bloqueia_minuta) for a in alertas] == [("ENTIDADE_SEM_APOIO", False)]
    assert decidir(contrato, alertas)[0] == ENCAMINHAR_REVISAO


@pytest.mark.parametrize("alteracoes, codigo", [
    ({"campos_ausentes": []}, "CAMPOS_AUSENTES_INCOERENTES"),
    ({"necessita_revisao": False}, "PEDIDO_AUSENTE_SEM_REVISAO"),
    ({"protocolo": "142"}, "PROTOCOLO_FORMATO"),
])
def test_incoerencias_do_contrato_bloqueiam(alteracoes, codigo):
    contrato = contrato_esperado("SOL-05", **alteracoes)
    alertas = conferir_regras_negocio(contrato, texto_de("SOL-05"))
    assert codigo in {a.codigo for a in alertas}
    assert decidir(contrato, alertas)[0] == BLOQUEAR_REGRA


def test_revisao_sem_marcacao_bloqueia():
    alertas = conferir_regras_negocio(contrato_esperado("SOL-06", necessita_revisao=False), texto_de("SOL-06"))
    assert "REVISAO_SEM_MARCACAO" in {a.codigo for a in alertas}


# ------------------------------------------------------------------------------
# Fluxo de extração
# ------------------------------------------------------------------------------
def test_extracao_valida_segue_para_minuta_e_preserva_o_registro(tmp_path):
    extrator = extrator_simulado(lambda prompt, schema: json.dumps(CASOS["SOL-01"]["esperado"]), tmp_path)
    resultado = extrator.extrair("SOL-01", texto_de("SOL-01"), "texto (e-mail)", ENTRADAS["SOL-01"]["arquivo"])

    assert resultado.decisao == GERAR_MINUTA
    registro = json.loads((tmp_path / "extracoes" / "SOL-01.json").read_text(encoding="utf-8"))
    assert registro["texto_entrada"] == texto_de("SOL-01") and len(registro["sha256_entrada"]) == 64
    assert registro["decisao"] == GERAR_MINUTA and registro["contrato"]["protocolo"] == "2026-000142"
    assert registro["prompt"] == {"id": "PROMPT_EXTRACAO_V2", "versao": VERSOES_PROMPTS["PROMPT_EXTRACAO_V2"]}
    assert registro["versao_esquema"] == "2.0.0"


def test_validacao_local_admite_uma_unica_correcao(tmp_path):
    respostas = ['{"protocolo": "2026-000142"}', json.dumps(CASOS["SOL-01"]["esperado"])]
    extrator = extrator_simulado(lambda prompt, schema: respostas.pop(0), tmp_path)
    resultado = extrator.extrair("SOL-01", texto_de("SOL-01"), "texto (e-mail)", "dados/originais/entrada_texto.txt")

    assert resultado.decisao == GERAR_MINUTA
    assert [c["etapa"] for c in resultado.chamadas] == ["extracao_contrato_v2", "correcao_contrato_v2"]


def test_saida_ainda_invalida_apos_a_correcao_e_rejeitada_antes_da_minuta(tmp_path):
    chamadas = []
    extrator = extrator_simulado(lambda prompt, schema: chamadas.append(prompt) or '{"nome": "x"}', tmp_path)
    resultado = extrator.extrair("SOL-01", texto_de("SOL-01"), "texto (e-mail)", "dados/originais/entrada_texto.txt")

    assert resultado.decisao == REJEITAR_SAIDA and resultado.contrato is None
    assert len(chamadas) == 2, "no máximo 1 tentativa de correção"
    assert {e["codigo"] for e in resultado.erros_validacao} == {"CHAVE_EXTRA", "CAMPO_OBRIGATORIO_AUSENTE"}
    assert (tmp_path / "extracoes" / "SOL-01.json").is_file(), "entrada, erro e decisão preservados"


def test_esquema_nativo_nao_repete_e_rejeita_saida_invalida(tmp_path):
    sdk = SDKFalso(resposta_falsa(conteudo='{"protocolo": 1}'))
    cliente = LLMClient(provedor="simulado")
    cliente.adaptador, cliente.provedor = OpenAIAdapter(CFG_OPENAI, cliente=sdk), "openai"
    resultado = ExtratorSolicitacoes(llm_client=cliente, dir_saida=tmp_path).extrair(
        "SOL-01", texto_de("SOL-01"), "texto (e-mail)", "dados/originais/entrada_texto.txt")

    assert resultado.decisao == REJEITAR_SAIDA
    assert len(sdk.chamadas) == 1
    metodo, argumentos = sdk.chamadas[0]
    assert metodo == "parse" and argumentos["response_format"] is ContratoSolicitacaoV2
    assert argumentos["reasoning_effort"] == "none"
    assert "<DADOS_EXTERNOS_NAO_CONFIAVEIS>" in argumentos["messages"][-1]["content"]


def test_falha_do_provedor_rejeita_sem_minuta(tmp_path):
    extrator = extrator_simulado(None, tmp_path)
    extrator.llm.adaptador.falha = "INDISPONIVEL"
    resultado = extrator.extrair("SOL-01", texto_de("SOL-01"), "texto (e-mail)", "dados/originais/entrada_texto.txt")

    assert resultado.decisao == REJEITAR_SAIDA
    assert "INDISPONIVEL" in resultado.motivo


# ------------------------------------------------------------------------------
# Ficha de compreensão (RF15)
# ------------------------------------------------------------------------------
def test_ficha_separa_literais_e_sinaliza_o_que_nao_tem_apoio(tmp_path):
    inferida = {"informacao": "O estudante tem direito ao auxílio", "base": "renda baixa comprovada"}
    resumo = "Rafael Nogueira Prado Teste, de Várzea Grande, pede o auxílio-transporte de R$ 150,00 e quer saber os documentos."
    extrator = extrator_simulado(lambda prompt, schema: resumo_json(resumo, [inferida]), tmp_path)
    esperado = CASOS["SOL-04"]["esperado"]
    contrato = contrato_esperado("SOL-04", entidades={**esperado["entidades"], "locais": ["Várzea Grande", "Cuiabá"]})

    ficha, chamadas = extrator.gerar_ficha("SOL-04", texto_de("SOL-04"), "texto", ENTRADAS["SOL-04"]["arquivo"], contrato)

    assert ficha.entidades_literais.locais == ["Várzea Grande"]
    assert ficha.entidades_sem_apoio == {"locais": ["Cuiabá"]}
    assert any(a.startswith("NUMERO_SEM_LASTRO_NO_RESUMO: 150,00") for a in ficha.alertas)
    assert any(a.startswith("INFERENCIA_SEM_BASE_LITERAL") for a in ficha.alertas)
    assert ficha.categoria == "ASSISTENCIA_ESTUDANTIL" and len(chamadas) == 1
    assert (tmp_path / "fichas" / "SOL-04.json").is_file()


@pytest.mark.parametrize("segundo_resumo, alerta", [("palavra " * 120, True), ("Resumo curto e fiel.", False)])
def test_resumo_longo_tem_uma_unica_tentativa_de_reducao(tmp_path, segundo_resumo, alerta):
    respostas = [resumo_json("palavra " * 120), resumo_json(segundo_resumo)]
    extrator = extrator_simulado(lambda prompt, schema: respostas.pop(0), tmp_path)
    ficha, chamadas = extrator.gerar_ficha("SOL-04", texto_de("SOL-04"), "texto", "x", contrato_esperado("SOL-04"))

    assert len(chamadas) == 2
    assert any(a.startswith("RESUMO_EXCEDE_LIMITE") for a in ficha.alertas) is alerta


def test_numeros_do_resumo_conferidos_contra_o_texto():
    texto = texto_de("SOL-02")
    assert numeros_sem_lastro("Protocolo 2026-000142 de 14/10/2026, nascido em 12/08/2008.", texto) == []
    assert numeros_sem_lastro("Curso com início em 01/02/2027.", texto) == ["01/02/2027"]


# ------------------------------------------------------------------------------
# Avaliação contra o gabarito (T03)
# ------------------------------------------------------------------------------
def saidas_iguais_ao_gabarito():
    resultados, fichas = {}, {}
    for id_caso, caso in CASOS.items():
        contrato = contrato_esperado(id_caso)
        decisao, motivo = decidir(contrato, [])
        resultados[id_caso] = ResultadoExtracao(
            id_caso=id_caso, canal="", arquivo_origem="", sha256_entrada="", texto_entrada=texto_de(id_caso),
            versao_esquema="2.0.0", prompt={}, modo_esquema="", contrato=contrato.model_dump(),
            erros_validacao=[], alertas=[], decisao=decisao, motivo=motivo)
        resumo = " ".join(f["fato"] for f in caso["fatos_essenciais"])
        fichas[id_caso] = FichaCompreensaoNLP(
            id_caso=id_caso, resumo=resumo, palavras_resumo=len(resumo.split()), categoria=contrato.categoria,
            entidades_literais=contrato.entidades, entidades_sem_apoio={}, informacoes_inferidas=[])
    return resultados, fichas


def test_saidas_iguais_ao_gabarito_tem_avaliacao_perfeita():
    avaliacao = avaliar_contra_gabarito(GABARITO, *saidas_iguais_ao_gabarito())
    agregados = avaliacao["agregados"]

    for nome in ("acuracia_categoria", "decisoes_corretas", "campos_exatos_corretos", "fatos_essenciais_preservados",
                 "resumos_no_limite_de_100_palavras", "contratos_validos", "assunto_e_pedido_com_presenca_correta"):
        assert agregados[nome]["numerador"] == agregados[nome]["denominador"] > 0, nome
    assert agregados["entidades_omitidas"]["numerador"] == 0
    assert (agregados["entidades_sem_suporte"], agregados["entidades_nao_esperadas"],
            agregados["resumos_com_termo_proibido"], agregados["resumos_com_numero_sem_lastro"]) == (0, 0, 0, 0)
    assert "| acuracia_categoria | 6 | 6 | 100.0% |" in relatorio_avaliacao_md(avaliacao, {
        "gerado_em": "x", "provedor": "simulado", "modelo": "x", "revisao_gabarito": "PENDENTE", "custo_total_usd": 0.0})


def test_erros_aparecem_na_avaliacao():
    resultados, fichas = saidas_iguais_ao_gabarito()
    contrato = dict(resultados["SOL-04"].contrato)
    contrato["categoria"] = "OUTROS"
    contrato["entidades"] = {**contrato["entidades"], "locais": [], "pessoas_ficticias": ["Rafael Nogueira Prado Teste", "Cuiabá"]}
    resultados["SOL-04"].contrato = contrato
    fichas["SOL-04"] = fichas["SOL-04"].model_copy(update={"resumo": "Pedido de auxílio deferido em 01/01/2027."})

    avaliacao = avaliar_contra_gabarito(GABARITO, resultados, fichas)
    caso = next(c for c in avaliacao["casos"] if c["id"] == "SOL-04")
    agregados = avaliacao["agregados"]

    assert agregados["acuracia_categoria"]["numerador"] == 5
    assert caso["entidades_omitidas"] == ["locais: Várzea Grande"]
    assert caso["entidades_sem_suporte"] == ["pessoas_ficticias: Cuiabá"]
    assert caso["resumo"]["termos_proibidos_encontrados"] == ["deferid"]
    assert caso["resumo"]["numeros_sem_lastro"] == ["01/01/2027"]


def test_pedido_deduzido_onde_o_gabarito_espera_null_conta_como_erro():
    """Erro real da 1ª execução (prompt v1.0): a ficha sem pedido escrito recebeu um pedido deduzido do tipo do documento."""
    resultados, fichas = saidas_iguais_ao_gabarito()
    resultados["SOL-05"].contrato = {**resultados["SOL-05"].contrato, "pedido": "Efetivação da matrícula no curso."}

    avaliacao = avaliar_contra_gabarito(GABARITO, resultados, fichas)
    caso = next(c for c in avaliacao["casos"] if c["id"] == "SOL-05")

    assert [d["campo"] for d in caso["nulidade_divergente"]] == ["pedido"]
    assert avaliacao["agregados"]["assunto_e_pedido_com_presenca_correta"]["numerador"] == 11
    assert "valor deduzido" in relatorio_avaliacao_md(avaliacao, {
        "gerado_em": "x", "provedor": "x", "modelo": "x", "revisao_gabarito": "x", "custo_total_usd": 0.0})


def test_conferencia_humana_nao_sobrescreve_anotacoes(tmp_path):
    avaliacao = avaliar_contra_gabarito(GABARITO, *saidas_iguais_ao_gabarito())
    caminho = tmp_path / "conferencia.json"
    assert _registro_de_conferencia(caminho, avaliacao) is True

    registro = json.loads(caminho.read_text(encoding="utf-8"))
    registro["casos"][0]["resumo_fiel"] = True
    caminho.write_text(json.dumps(registro), encoding="utf-8")
    assert _registro_de_conferencia(caminho, avaliacao) is False
    assert json.loads(caminho.read_text(encoding="utf-8"))["casos"][0]["resumo_fiel"] is True


def test_comparativo_json_sintatico_e_esquema(tmp_path):
    def responder(prompt, schema):
        return json.dumps(CASOS["SOL-01"]["esperado"]) if schema is ContratoSolicitacaoV2 else '{"nome": "Marcos"}'

    comparativo = extrator_simulado(responder, tmp_path).comparar_json_sintatico_e_esquema(
        "SOL-01", texto_de("SOL-01"), "texto (e-mail)", "dados/originais/entrada_texto.txt")
    generica, contrato_sem_esquema, esquema = comparativo["variantes"]

    assert generica["json_sintaticamente_valido"] and not generica["valido_no_contrato"]
    assert set(generica["erros_por_codigo"]) == {"CHAVE_EXTRA", "CAMPO_OBRIGATORIO_AUSENTE"}
    assert esquema["valido_no_contrato"] and esquema["garantia_da_api"].startswith("esquema")
    assert contrato_sem_esquema["garantia_da_api"] == "apenas sintaxe JSON"
