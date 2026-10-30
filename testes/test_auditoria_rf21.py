#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
==============================================================================
TESTES DA EVIDÊNCIA DE AUDITORIA DO RF21
==============================================================================
Uma resposta do RAG (adaptador simulado, índice com embeddings falsos) e a
decisão do operador sobre ela, gravadas por um AuditManager em pasta
temporária. A linha do log precisa permitir conferir a origem da minuta
sem expor credenciais: identificador, horários, versões do esquema e do
prompt, consulta mascarada, IDs recuperados, versão do índice, resultado,
erros, latência, tokens e custo (ou a indisponibilidade no simulado) e o
vínculo com a decisão humana.
==============================================================================
"""

import json
import sys
from pathlib import Path

raiz_projeto = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(raiz_projeto))

from src.audit import AuditManager
from src.embeddings import IndiceVetorial
from src.llm_client import LLMClient
from src.rag import AssistenteRAG
from test_guardrails_rf16 import guardrails_offline
from test_indice_rf17_rf18 import CHUNK_A, CONFIG, DOCS, EmbedderFalso
from test_rag_rf19 import PERGUNTA_FALTAS, responde_rag03

CONFIG_RAG = {**CONFIG, "rag": {**CONFIG["rag"], "limiar_similaridade": 0.0}}


def linhas(audit: AuditManager):
    return [json.loads(l) for l in audit.arquivo_log_jsonl.read_text(encoding="utf-8").splitlines()]


def test_linha_do_rag_tem_todos_os_campos_do_rf21_e_liga_a_decisao(tmp_path):
    indice = IndiceVetorial(CONFIG, EmbedderFalso(), diretorio_base=tmp_path / "indice")
    indice.indexar("acervo_principal", [DOCS["DOC-03"]], CHUNK_A)
    audit = AuditManager(dir_logs=tmp_path / "logs")
    llm = LLMClient(provedor="simulado")
    llm.adaptador.responder = responde_rag03
    guardrails, _, _ = guardrails_offline()
    pergunta = f"Meu CPF é 123.456.789-09 e meu telefone (65) 99999-1234. {PERGUNTA_FALTAS}"
    resposta = AssistenteRAG(indice, llm, CONFIG_RAG, guardrails=guardrails, audit=audit).responder(pergunta, id_caso="RAG-AUD")
    audit.registrar_decisao_minuta("RAG-AUD", "APROVADA", "Operadora", "Citações conferidas.", resposta.id_execucao,
                                   resposta.to_dict())

    rag, decisao = linhas(audit)
    assert rag["id_execucao"] == resposta.id_execucao and rag["etapa"] == "rag_resposta"
    assert rag["inicio"] < rag["timestamp"] and rag["duracao_ms"] > 0
    assert rag["versao_esquema"] == "1.0.0" and rag["prompt"]["versao"] == "1.0" and rag["prompt"]["sha256"]
    assert rag["versao_indice"] == CONFIG["indice"]["versao_indice"]
    assert rag["ids_recuperados"] == [f["chunk_id"] for f in resposta.fontes]
    assert "123.456.789-09" not in rag["consulta"] and "99999-1234" not in rag["consulta"] and "faltas" in rag["consulta"]
    assert rag["resumo_saida"].startswith("status=FUNDAMENTADA") and rag["sucesso"] and rag["codigo_erro"] is None
    assert rag["provedor"] == "simulado" and rag["tokens_total"] is None and rag["custo_estimado_usd"] is None
    assert "indisponíveis" in rag["parametros"]["observacao_custo"]
    assert decisao["etapa"] == "decisao_humana_minuta" and decisao["id_execucao_anterior"] == rag["id_execucao"]
    registro = audit.decisoes_minutas()[0]
    assert registro["id_execucao_referencia"] == rag["id_execucao"] and registro["participacao_ia"]["provedor"] == "simulado"
    texto = audit.arquivo_log_jsonl.read_text(encoding="utf-8")
    assert "123.456.789-09" not in texto and "sk-" not in texto


def test_falha_do_servico_fica_na_linha_com_codigo_e_mensagem(tmp_path):
    indice = IndiceVetorial(CONFIG, EmbedderFalso(), diretorio_base=tmp_path / "indice")
    indice.indexar("acervo_principal", [DOCS["DOC-03"]], CHUNK_A)
    audit = AuditManager(dir_logs=tmp_path / "logs")
    llm = LLMClient(provedor="simulado")
    llm.adaptador.falha = "INDISPONIVEL"
    AssistenteRAG(indice, llm, CONFIG_RAG, audit=audit).responder(PERGUNTA_FALTAS, id_caso="RAG-FALHA")
    linha = linhas(audit)[0]
    assert linha["sucesso"] is False and linha["codigo_erro"] == "INDISPONIVEL" and "T12" in linha["mensagem_erro"]
    assert linha["resumo_saida"].startswith("status=SEM_EVIDENCIA_SUFICIENTE; motivo=FALHA_NA_GERACAO")
