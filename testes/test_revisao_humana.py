#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
==============================================================================
TESTES DA REVISÃO HUMANA E DO RELATÓRIO DE QUALIDADE (RF13)
==============================================================================
Sem rede: entradas do terminal simuladas com monkeypatch e auditoria em tmp_path.
"""

import sys
from pathlib import Path

import pytest

raiz_projeto = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(raiz_projeto))

from src import revisao_humana as revisao
from src.audit import AuditManager
from src.parsers import SolicitacaoEstruturada


class AuditFalso:
    """Guarda decisões e execuções em memória."""

    def __init__(self):
        self.decisoes, self.execucoes = [], []

    def registrar_decisao_humana(self, **kwargs):
        self.decisoes.append(kwargs)

    def registrar_execucao(self, **kwargs):
        self.execucoes.append(kwargs)
        return f"EXEC-{len(self.execucoes)}"


class AudioFalso:
    audio_cfg = {}

    def sintetizar_minuta_acessivel(self, registro, conteudo, protocolo):
        return {"sucesso": False, "caminho_texto": "x.txt", "caminho_audio": "x.mp3", "texto_locucao": "",
                "voz_utilizada": "teste", "parametros": {}, "tamanho_bytes": 0, "mensagem": "TTS desligado no teste"}


@pytest.fixture
def entradas(monkeypatch):
    """Simula as respostas digitadas no terminal, na ordem."""
    monkeypatch.setenv("REVISOR", "Estudante 1 - revisor")
    monkeypatch.setattr(revisao, "_operador_identificado", None)

    def definir(*respostas):
        fila = list(respostas)
        monkeypatch.setattr("builtins.input", lambda _mensagem="": fila.pop(0))
        return fila
    return definir


def _minuta(protocolo="2026-000142"):
    return {"sucesso": True, "protocolo": protocolo, "caminho_arquivo": "minuta.txt", "conteudo_minuta": "texto da minuta",
            "conteudo_gerado": {}, "alertas": []}


def test_enter_vazio_repete_a_pergunta(entradas):
    fila = entradas("", "9", "2")
    assert revisao._perguntar("Decisão: ", ("1", "2")) == "2"
    assert fila == []


def test_rejeicao_exige_justificativa_e_gravidade(entradas):
    audit = AuditFalso()
    entradas("2", "", "Contém instrução dirigida à IA", "4")
    decisao = revisao.revisar_minuta(audit, "EXEC-1", "CASO_04", SolicitacaoEstruturada(), _minuta(), AudioFalso(), False)

    assert decisao == "REJEITADO"
    d = audit.decisoes[-1]
    assert d["objeto"] == "minuta" and d["justificativa"] == "Contém instrução dirigida à IA"
    assert d["gravidade_erros_detectados"] == "CRITICA" and d["simulada"] is False
    assert d["operador"] == "Estudante 1 - revisor"


def test_corrigir_campo_gera_nova_minuta_ligada_a_anterior(entradas):
    audit = AuditFalso()
    chamadas = []

    def regerar(dados, id_anterior, motivo):
        chamadas.append((dados, id_anterior, motivo))
        return SolicitacaoEstruturada(**dados), _minuta(), "EXEC-2"

    indice_email = revisao.CAMPOS_EDITAVEIS_MINUTA.index("solicitante.email") + 1
    entradas("3", str(indice_email), "marcos.almeida.teste@examplo.com", "n", "2", "1", "")
    registro = SolicitacaoEstruturada(protocolo="2026-000142")
    decisao = revisao.revisar_minuta(audit, "EXEC-1", "CASO_03_AUDIO", registro, _minuta(), AudioFalso(), False, regerar=regerar)

    assert decisao == "APROVADO"
    dados, id_anterior, motivo = chamadas[0]
    assert dados["solicitante"]["email"] == "marcos.almeida.teste@examplo.com" and id_anterior == "EXEC-1"
    corrigido, aprovado = audit.decisoes
    assert corrigido["decisao"] == "CORRIGIDO_MANUALMENTE" and corrigido["id_execucao"] == "EXEC-1"
    assert "solicitante.email" in corrigido["alteracoes"][0]
    assert aprovado["decisao"] == "APROVADO" and aprovado["id_execucao"] == "EXEC-2"


def test_demo_registra_decisao_simulada(entradas):
    audit = AuditFalso()
    minuta = _minuta()
    minuta["alertas"] = ["A solicitação contém suspeita de prompt injection: revisar com atenção."]
    decisao = revisao.revisar_minuta(audit, "EXEC-1", "CASO_04", SolicitacaoEstruturada(), minuta, AudioFalso(), True)

    assert decisao == "REJEITADO"
    assert audit.decisoes[-1]["simulada"] is True and audit.decisoes[-1]["operador"] == revisao.OPERADOR_DEMO


def _audit_em(tmp_path) -> AuditManager:
    audit = AuditManager()
    audit.dir_logs = tmp_path
    audit.arquivo_log_jsonl = tmp_path / "auditoria.jsonl"
    audit.arquivo_decisoes_json = tmp_path / "decisoes_humanas.json"
    audit.arquivo_decisoes_simuladas = tmp_path / "decisoes_simuladas.json"
    audit.caminho_relatorio = tmp_path / "relatorio.md"
    return audit


def test_relatorio_usa_ultima_decisao_e_exclui_simuladas(tmp_path):
    audit = _audit_em(tmp_path)
    audit.registrar_decisao_humana("E1", "CASO_01_TEXTO", "minuta", "REJEITADO", "Estudante 1", "inventou prazo", "ALTA")
    audit.registrar_decisao_humana("E2", "CASO_01_TEXTO", "minuta", "APROVADO", "Estudante 1", "ok", "NENHUMA")
    audit.registrar_decisao_humana("E3", "CASO_03_AUDIO", "conferencia_cruzada", "CORRIGIDO_MANUALMENTE", "Estudante 1", "e-mail", "MEDIA")
    audit.registrar_decisao_humana("E4", "CASO_03_AUDIO", "minuta", "APROVADO", "Estudante 1", "ok", "NENHUMA")
    audit.registrar_decisao_humana("E5", "CASO_04_TEXTO_INJECTION", "minuta", "REJEITADO", "Estudante 1", "injection", "CRITICA")
    audit.registrar_decisao_humana("E6", "CASO_02_VISAO_DOCUMENTO", "ficha", "APROVADO", "SIMULADO", "demo", simulada=True)

    relatorio = (tmp_path / "relatorio.md").read_text(encoding="utf-8")
    assert "Casos com decisão final: **3**" in relatorio
    assert "Taxa de aprovação sem correção: 33.3%" in relatorio
    assert "1 registro(s) simulado(s) excluído(s)" in relatorio
    assert "| `CASO_01_TEXTO` | minuta | APROVADO | APROVADO | sim | NENHUMA |" in relatorio
    assert "| `CASO_03_AUDIO` | minuta | APROVADO | CORRIGIDO_MANUALMENTE | **não** | MEDIA |" in relatorio
    assert "| `CASO_04_TEXTO_INJECTION` | minuta | REJEITADO | REJEITADO | sim | CRITICA |" in relatorio
    assert "| `CASO_02_VISAO_DOCUMENTO` | ficha | APROVADO | sem decisão | - | - |" in relatorio
    assert (tmp_path / "decisoes_simuladas.json").exists()


def test_ficha_exige_conferencia_dos_campos_duvidosos(entradas, tmp_path):
    """Campos incertos (modelo) e esperados como incertos (gabarito) são conferidos um a um; pendências ficam registradas."""
    audit = AuditFalso()
    res_visao = {
        "dados_revisados": {"codigo_matricula": "2024-000142", "solicitante": {"cpf": "123.456.789-00"},
                            "trechos_incertos": [{"campo": "codigo", "rotulo": "CÓDIGO", "valor_lido": "2024-000142",
                                                  "situacao": "INCERTO", "observacao": "4 ou 6"}]},
        "comparacao_gabarito": {"incertos_esperados": {"sinalizados": ["codigo"], "nao_sinalizados": ["cpf"]}},
    }
    # codigo: corrigir; cpf: pendente; depois confirmar, observação vazia
    entradas("c", "2026-000142", "p", "1", "")
    confirmada = revisao.revisar_ficha(audit, res_visao, "EXEC-1", "CASO_02", False, tmp_path)

    assert confirmada["codigo_matricula"] == "2026-000142"
    assert confirmada["confirmacao_humana"]["pendentes"] == ["cpf"]
    # O campo pendente não segue para a conferência; o valor lido fica registrado
    assert confirmada["solicitante"]["cpf"] == "não localizado"
    assert confirmada["confirmacao_humana"]["valores_lidos_pendentes"]["cpf"] == "123.456.789-00"
    d = audit.decisoes[-1]
    assert d["decisao"] == "PENDENTE" and "Pendentes de confirmação: cpf" in d["justificativa"]
    assert (tmp_path / "visao_confirmada.json").exists()
