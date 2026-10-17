#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
==============================================================================
TESTES DE PRIVACIDADE E MINIMIZAÇÃO (RF12) E DAS MEDIÇÕES DO EXPERIMENTO (RF02)
==============================================================================
"""

import sys
import json
from pathlib import Path

raiz_projeto = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(raiz_projeto))
sys.path.insert(0, str(raiz_projeto / "testes"))

from src.privacidade import minimizar, mascarar_cpf, mascarar_rg, mascarar_email, mascarar_texto
from src.audit import AuditManager
from executar_experimento_prompts import medir_saida

REGISTRO = {
    "protocolo": "2026-000142",
    "solicitante": {"nome_completo": "Marcos Vinícius de Almeida Santos", "cpf": "123.456.789-00", "rg": "1234567-8",
                    "email": "marcos.almeida.teste@examplo.com", "nome_mae": "Lúcia Helena de Almeida Santos",
                    "nome_pai": "não localizado", "data_nascimento": "12/08/2008", "telefone_celular": "não localizado"},
    "curso": {"nome": "Técnico em Enfermagem", "turno": "Noturno"},
    "campos_ausentes": ["orgao_expedidor"],
    "texto_original": "Meu CPF é 123.456.789-00 e minha mãe é Lúcia Helena",
}


def test_mascaras_de_identificadores():
    assert mascarar_cpf("123.456.789-00") == "***.456.789-**"
    assert mascarar_cpf("não localizado") == "não localizado"
    assert mascarar_rg("1234567-8") == "****567-8"
    assert mascarar_email("marcos.almeida.teste@examplo.com") == "m***@examplo.com"
    assert mascarar_texto("CPF 12345678900, e-mail a.b@x.com") == "CPF ***.456.789-**, e-mail a***@x.com"


def test_minimizar_mascara_e_omite_para_a_minuta():
    payload = json.dumps(minimizar(REGISTRO), ensure_ascii=False)
    assert "123.456.789-00" not in payload and "***.456.789-**" in payload
    assert "1234567-8" not in payload and "marcos.almeida.teste@" not in payload
    assert "Lúcia" not in payload and "12/08/2008" not in payload and "Meu CPF" not in payload
    assert "Marcos Vinícius de Almeida Santos" in payload and "Órgão expedidor do RG" in payload


def test_auditoria_nao_guarda_cpf_nem_email_completos(tmp_path):
    audit = AuditManager()
    audit.arquivo_log_jsonl = tmp_path / "auditoria.jsonl"
    audit.arquivo_decisoes_json = tmp_path / "decisoes.json"
    audit.arquivo_decisoes_simuladas = tmp_path / "simuladas.json"
    audit.caminho_relatorio = tmp_path / "relatorio.md"
    audit.registrar_execucao(caso_id="C", etapa="teste", modalidade="texto", arquivo_origem="x.txt",
                             resumo_saida="cpf=123.456.789-00; email=marcos@examplo.com", observacao="CPF 123.456.789-00")
    audit.registrar_decisao_humana("E1", "C", "conferencia_cruzada", "CORRIGIDO_MANUALMENTE", "Estudante 1",
                                   "CPF conferido", "BAIXA", alteracoes=["solicitante.cpf: '123.456.789-01' -> '123.456.789-00'"])
    gravado = (tmp_path / "auditoria.jsonl").read_text(encoding="utf-8") + (tmp_path / "decisoes.json").read_text(encoding="utf-8")
    assert "123.456.789-00" not in gravado and "123.456.789-01" not in gravado and "marcos@" not in gravado
    assert "***.456.789-**" in gravado


def test_medicoes_do_experimento():
    entrada = (raiz_projeto / "dados" / "originais" / "entrada_texto.txt").read_text(encoding="utf-8")
    saida = ("CPF: 123.456.789-00. Mãe: Lúcia Helena de Almeida Santos. Faltas em 3 dias alternados. "
             "Traga histórico escolar e foto 3x4. Telefone: não localizado.")
    m = medir_saida(saida, entrada)
    assert m["cpf_completo_exposto"] and m["nome_mae_exposto"] and not m["email_exposto"]
    assert m["menciona_alternados"] and m["ocorrencias_nao_localizado"] == 1
    assert set(m["documentos_citados_fora_da_entrada"]) == {"histórico escolar", "foto 3x4"}
