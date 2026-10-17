#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
==============================================================================
TESTES DA CONFERÊNCIA DE DADOS (RF05, RF06, RF08, RF13) — sem rede
==============================================================================
- Classificação campo a campo: correto, equivalente, inventado, omitido;
- WER e diferenças de transcrição com números por extenso ou com pontuação;
- Conferência cruzada entre canais e valor sugerido pela maioria;
- Verificação de ancoragem dos valores extraídos na fonte.
==============================================================================
"""

import sys
from pathlib import Path

raiz_projeto = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(raiz_projeto))

from src.conferencia import (
    comparar_valor, comparar_com_gabarito, taxa_erro_palavras, diferencas_transcricao,
    conferencia_cruzada, aplicar_valores_confirmados, verificar_ancoragem
)


def test_classificacao_de_campos():
    assert comparar_valor("Marcos", "Marcos") == "CORRETO"
    assert comparar_valor("MARCOS VINÍCIUS", "Marcos Vinicius") == "EQUIVALENTE"
    assert comparar_valor("123.456.789-00", "12345678900", numerico=True) == "EQUIVALENTE"
    assert comparar_valor("1200 horas", "1.200 horas") == "EQUIVALENTE"
    assert comparar_valor("não localizado", "SSP/MT") == "INVENTADO"
    assert comparar_valor("SSP/MT", "não localizado") == "OMITIDO"
    assert comparar_valor(["uf", "rg"], ["rg", "uf"]) == "CORRETO"


def test_comparacao_com_gabarito_usa_mapa_e_ignora_campos():
    obtido = {"canal_origem": "E-mail", "solicitante": {"nome_pai": "João"}}
    esperado = {"canal": "E-mail", "solicitante": {"nome_pai": "não localizado"}, "classificacao": {"assunto": "x"}}
    resultado = comparar_com_gabarito(obtido, esperado, mapa={"canal": "canal_origem"}, ignorar=["classificacao.assunto"])
    assert resultado["total_campos"] == 2
    assert resultado["inventados"] == ["solicitante.nome_pai"]


def test_wer_ignora_grafia_numerica():
    referencia = "faltar nos dois primeiros dias com carga de 1200 horas e CPF 123.456.789-00"
    hipotese = "faltar nos 2 primeiros dias com carga de 1.200 horas e CPF 123456789-00"
    assert taxa_erro_palavras(referencia, hipotese) == 0.0
    assert taxa_erro_palavras("meu nome é Marcos", "meu nome é Marcus") == 25.0


def test_diferenca_em_nome_e_critica():
    diferencas = diferencas_transcricao("meu nome é Marcos Santos", "meu nome é Marcus Santos", ["Marcos Santos"])
    assert diferencas and diferencas[0]["critico"] is True


def test_conferencia_cruzada_aponta_divergencia_e_sugere_maioria():
    fontes = {
        "texto": {"protocolo": "2026-000142", "solicitante": {"email": "a@examplo.com"}},
        "ficha": {"codigo_matricula": "2024-000142", "solicitante": {"email": "A@EXAMPLO.COM"}},
        "audio": {"protocolo": "2026-000142", "solicitante": {"email": "a@exemplo.com"}},
    }
    resultado = {item["campo"]: item for item in conferencia_cruzada(fontes)}
    assert resultado["protocolo"]["status"] == "DIVERGENTE"
    assert resultado["protocolo"]["valor_sugerido"] == "2026-000142"
    assert resultado["email"]["valor_sugerido"] == "a@examplo.com"
    assert resultado["nome_completo"]["status"] == "AUSENTE"


def test_aplicar_valores_confirmados():
    registro = {"protocolo": "x", "solicitante": {"email": "y"}}
    aplicar_valores_confirmados(registro, {"protocolo": "2026-000142", "email": "a@examplo.com"})
    assert registro["protocolo"] == "2026-000142"
    assert registro["solicitante"]["email"] == "a@examplo.com"


def test_ancoragem_detecta_valor_ausente_da_fonte():
    fonte = "Meu nome é Marcos Vinícius, CPF 123.456.789-00."
    ok = {"solicitante": {"nome_completo": "Marcos Vinícius", "cpf": "12345678900"}}
    inventado = {"solicitante": {"nome_completo": "Marcos Vinícius", "nome_mae": "Maria Souza"}}
    assert verificar_ancoragem(ok, fonte) == []
    assert any("nome_mae" in alerta for alerta in verificar_ancoragem(inventado, fonte))



def test_correcao_marca_texto_livre_e_registra_correcoes():
    registro = {"curso": {"nome": "Técnico em Informática", "turno": "vespertino"},
                "assunto": "Matrícula em Técnico em Informática", "pedido_detalhado": "Quero o turno vespertino"}
    atualizado = aplicar_valores_confirmados(registro, {"curso": "Técnico em Enfermagem", "turno": "noturno"})
    assert atualizado["curso"]["nome"] == "Técnico em Enfermagem"
    assert "Informática" not in atualizado["assunto"] and "corrigido pelo revisor" in atualizado["assunto"]
    assert atualizado["pedido_detalhado"] == "Quero o turno [noturno — corrigido pelo revisor]"
    assert atualizado["correcoes_revisor"] == ["curso: 'Técnico em Informática' -> 'Técnico em Enfermagem'",
                                               "turno: 'vespertino' -> 'noturno'"]
