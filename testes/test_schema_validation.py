#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
==============================================================================
TESTES DE VALIDAÇÃO DE SCHEMA JSON E TRATAMENTO DE LACUNAS (RF05)
==============================================================================
Garante o cumprimento do critério de aceite:
'a estrutura JSON deverá permanecer válida mesmo quando houver campos ausentes.'
==============================================================================
"""

import sys
import json
from pathlib import Path

raiz_projeto = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(raiz_projeto))

from src.parsers import SolicitacaoEstruturada, GeradorMinuta
from src.llm_client import LLMResponse


def test_schema_valido_com_campos_completamente_ausentes():
    """Valida se o schema instancia normalmente com campos ausentes sem disparar exceção."""
    solicitacao = SolicitacaoEstruturada()

    assert solicitacao.protocolo == "não localizado"
    assert solicitacao.solicitante.nome_completo == "não localizado"
    assert solicitacao.solicitante.cpf == "não localizado"
    assert solicitacao.curso.nome == "não localizado"
    assert solicitacao.declarou_ciencia_faltas is False

    # Valida serialização e integridade do JSON gerado
    json_str = solicitacao.model_dump_json()
    dados_recuperados = json.loads(json_str)

    assert isinstance(dados_recuperados, dict)
    assert dados_recuperados["protocolo"] == "não localizado"


class ClienteExtracaoFalso:
    """Simula a resposta do modelo na extração (sem rede)."""

    def __init__(self, conteudo: str):
        self.conteudo = conteudo

    def gerar(self, *args, **kwargs):
        return LLMResponse(conteudo=self.conteudo, modelo="falso", provedor="teste", sucesso=True, latencia_ms=1.0)


EXTRACAO_CASO_TEXTO = {
    "protocolo": "2026-000142", "data_solicitacao": "14/10/2026", "canal_origem": "E-mail",
    "solicitante": {"nome_completo": "Marcos Vinícius de Almeida Santos", "data_nascimento": "12/08/2008",
                    "cpf": "123.456.789-00", "rg": "1234567-8", "nome_mae": "Lúcia Helena de Almeida Santos",
                    "email": "marcos.almeida.teste@examplo.com"},
    "curso": {"nome": "Técnico em Enfermagem", "turno": "Noturno", "data_inicio": "01/02/2027"},
    "declarou_ciencia_faltas": True, "categoria_tema": "MATRICULA_INICIAL", "nivel_confianca": "ALTO",
}


def test_extracao_caso_texto_gera_json_valido_e_lacunas(tmp_path):
    """Extração do caso oficial com resposta simulada: JSON salvo, lacunas calculadas pelo config.json."""
    gerador = GeradorMinuta(llm_client=ClienteExtracaoFalso(json.dumps(EXTRACAO_CASO_TEXTO, ensure_ascii=False)))
    gerador.dir_processados = tmp_path
    registro, resposta, prompt, saida = gerador.extrair_dados_texto("dados/originais/entrada_texto.txt")

    assert resposta.sucesso and saida == tmp_path / "extracao_texto.json"
    recarregado = SolicitacaoEstruturada(**json.loads(saida.read_text(encoding="utf-8")))
    assert recarregado.protocolo == "2026-000142"
    assert recarregado.solicitante.orgao_expedidor == "não localizado"
    assert {"orgao_expedidor", "uf", "nome_pai", "documentos_comprobatorios_anexos"} <= set(recarregado.campos_ausentes)
    assert recarregado.alertas == []  # todos os valores constam na fonte (ancoragem)
    assert "<DOCUMENTO>" in prompt


def test_extracao_com_json_invalido_continua_valida(tmp_path):
    """Resposta fora do esquema: o registro continua válido, com campos 'não localizado' e alerta (RF04 / RF05)."""
    gerador = GeradorMinuta(llm_client=ClienteExtracaoFalso("isto não é JSON"))
    gerador.dir_processados = tmp_path
    registro, resposta, _, _ = gerador.extrair_dados_texto("dados/originais/entrada_texto.txt")

    assert registro.protocolo == "não localizado"
    assert any("fora do esquema" in a for a in registro.alertas)


def test_minuta_com_json_invalido_falha_sem_texto_pronto(tmp_path):
    """Minuta fora do esquema: falha explícita, nenhum arquivo gravado (RF04 / RF09)."""
    gerador = GeradorMinuta(llm_client=ClienteExtracaoFalso('{"assunto": "incompleto"}'))
    gerador.dir_minutas = tmp_path
    res = gerador.gerar_minuta_institucional(SolicitacaoEstruturada(protocolo="2026-000142"), [])

    assert res["sucesso"] is False and res["resposta"].codigo_erro == "RESPOSTA_FORA_DO_ESQUEMA"
    assert list(tmp_path.iterdir()) == []
