#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
==============================================================================
TESTES DA INTERFACE STREAMLIT (RF20, RF22, RF24 — T11)
==============================================================================
Com streamlit.testing.v1.AppTest, sem navegador e sem rede (sem chave, a
interface informa a indisponibilidade em vez de falhar):
- a interface carrega com as quatro abas e o seletor de geração;
- T11 pela própria interface: o operador aprova uma minuta e rejeita outra,
  com justificativa; sem justificativa, a decisão é recusada;
- o painel abre com a ficha técnica e omite o percentual num filtro com
  menos de 10 avaliações.
A auditoria e os rótulos dos testes ficam em pasta temporária.
==============================================================================
"""

import json
import sys
from pathlib import Path

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

raiz_projeto = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(raiz_projeto))

import src.atendimento
import src.audit
import src.sentiment
from src.sentiment import persistir_rotulos
from test_metricas_t13 import registros as registros_do_gabarito

APP = str(raiz_projeto / "src" / "app.py")


@pytest.fixture
def app(tmp_path, monkeypatch):
    """Interface com auditoria em pasta temporária e duas minutas sintéticas na fila."""
    original = src.audit.AuditManager
    monkeypatch.setattr(src.audit, "AuditManager", lambda *a, **k: original(dir_logs=tmp_path / "logs"))

    def fila(audit, *_):
        estados = audit.estado_das_minutas()
        itens = [{"caso_id": caso, "origem": "teste", "etapa": "MINUTA_GERADA", "status": "FUNDAMENTADA",
                  "minuta": f"MINUTA {caso}", "provedor": "simulado", "modelo": "simulado-deterministico",
                  "prompt": {"id": "PROMPT_RAG", "versao": "1.0"}, "id_execucao": f"EXEC-{caso}", "dados": {}}
                 for caso in ("ATD-TESTE-1", "ATD-TESTE-2")]
        for item in itens:
            item["estado"] = estados.get(item["caso_id"], {}).get("estado", "PENDENTE")
        return itens
    monkeypatch.setattr(src.atendimento, "minutas_para_revisao", fila)
    monkeypatch.setattr(src.sentiment, "arquivo_de_rotulos_mais_recente", lambda *_: None)
    st.cache_resource.clear()
    teste = AppTest.from_file(APP, default_timeout=120)
    teste.run()
    yield teste, tmp_path / "logs" / "decisoes_humanas_desafio02.json"
    st.cache_resource.clear()


def decidir(teste, posicao, estado, justificativa):
    teste.selectbox(key="item_revisao").select_index(posicao)
    teste.radio(key="estado_decisao").set_value(estado)
    teste.text_input(key="operador").input("Operadora de teste")
    teste.text_area(key="justificativa").input(justificativa)
    teste.button(key="registrar_decisao").click()
    teste.run()


def test_interface_carrega_com_as_quatro_abas(app):
    teste, _ = app
    assert not teste.exception
    assert [aba.label for aba in teste.tabs] == ["Acervo e índice", "Atendimento e revisão", "Painel de sentimentos",
                                                 "Provedor e auditoria"]
    assert teste.sidebar.selectbox[0].options and len(teste.sidebar.selectbox[0].options) == 4
    assert any("Nenhuma classificação gravada" in i.value for i in teste.info)


def test_operador_aprova_e_rejeita_pela_interface(app):
    teste, arquivo = app
    decidir(teste, 0, "APROVADA", "Citações conferidas na passagem original.")
    decidir(teste, 1, "REJEITADA", "A minuta usa a redação revogada.")
    assert not teste.exception
    decisoes = json.loads(arquivo.read_text(encoding="utf-8"))
    assert [(d["caso_id"], d["estado"]) for d in decisoes] == [("ATD-TESTE-1", "APROVADA"), ("ATD-TESTE-2", "REJEITADA")]
    assert all(d["envio_automatico_bloqueado"] and d["operador"] == "Operadora de teste" for d in decisoes)
    assert decisoes[0]["liberada_para_envio_manual"] and not decisoes[1]["liberada_para_envio_manual"]
    assert any("REJEITADA registrada" in s.value for s in teste.success)


def test_decisao_sem_justificativa_e_recusada_na_interface(app):
    teste, arquivo = app
    decidir(teste, 0, "REVISAR", "")
    assert any("justificativa é obrigatória" in e.value for e in teste.error)
    assert not arquivo.exists()


def test_painel_mostra_ficha_tecnica_e_omite_percentual_abaixo_do_minimo(tmp_path, monkeypatch):
    caminho_csv, _ = persistir_rotulos(registros_do_gabarito(), tmp_path)
    monkeypatch.setattr(src.sentiment, "arquivo_de_rotulos_mais_recente", lambda *_: caminho_csv)
    st.cache_resource.clear()
    teste = AppTest.from_file(APP, default_timeout=120)
    teste.run()
    assert not teste.exception
    metricas = {m.label: m.value for m in teste.metric}
    assert metricas["Avaliações"] == "12" and metricas["Limítrofes"] == "4/12 (33,3%)"
    assert not any("Percentual omitido" in w.value for w in teste.warning)
    teste.multiselect(key="filtro_canal").select("presencial")
    teste.run()
    assert any("Percentual omitido" in w.value and "abaixo do mínimo de 10" in w.value for w in teste.warning)
    st.cache_resource.clear()
