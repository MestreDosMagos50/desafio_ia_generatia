#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
==============================================================================
TESTES DA AVALIAÇÃO INTEGRADA (RF23: matriz T01–T15, métricas e T15)
==============================================================================
Sem rede: as evidências de cada modo são escritas em pasta temporária e a
matriz é montada a partir delas.
- sem evidência, todo teste fica PENDENTE e nada quebra;
- cada situação (CONFERE, CONFERE_COM_RESSALVA, NAO_CONFERE, PENDENTE) sai
  da evidência, e não de texto fixo;
- T11 só confere com decisões reais de aprovação e de rejeição ou revisão;
- a sustentação humana fica pendente até todas as afirmações serem
  conferidas;
- a nota sobre a numeração do enunciado (T01–T04) aparece na matriz;
- entrada vinda de OCR leva alerta obrigatório e revisão prioritária.
==============================================================================
"""

import json
import sys
from pathlib import Path

import pytest

raiz_projeto = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(raiz_projeto))

import src.avaliacao as avaliacao
import src.sentiment
from src.atendimento import ALERTA_OCR_NAO_CONFIRMADO, alertas_de_leitura_ocr, processar_atendimento
from src.audit import AuditManager
from src.sentiment import persistir_rotulos
from test_atendimento_t11_t12 import CONFIG_RAG, cliente, indice, responder_sol01  # noqa: F401 (fixture)
from test_guardrails_rf16 import guardrails_offline
from test_metricas_t13 import registros as registros_do_gabarito

CONFIG = json.loads((raiz_projeto / "config.json").read_text(encoding="utf-8"))
PRINCIPAL = CONFIG["llm"]["openai"]["modelo_padrao"]


def fr(n, d):
    return {"numerador": n, "denominador": d}


def escrever(raiz: Path, relativo: str, dados):
    caminho = raiz / relativo
    caminho.parent.mkdir(parents=True, exist_ok=True)
    texto = "\n".join(json.dumps(l) for l in dados) + "\n" if relativo.endswith(".jsonl") else json.dumps(dados, ensure_ascii=False)
    caminho.write_text(texto, encoding="utf-8")


def evidencias(raiz: Path, rag_t08=fr(5, 5), decisoes=("APROVADA", "REJEITADA"), regressao_simulada=False, sustentada=None):
    escrever(raiz, "resultados/metricas/comparativo_json_esquema_rf14.json", {
        "variantes": [{"variante": "json_object_instrucao_generica", "valido_no_contrato": False, "erros_por_codigo": {"CHAVE_EXTRA": 5}},
                      {"variante": "structured_outputs_contrato", "valido_no_contrato": True}],
        "payloads_sinteticos": [{"confere": True}] * 4})
    escrever(raiz, "resultados/nlp/t02_regras_negocio.json", [
        {"id": "T02-A", "decisao_obtida": "BLOQUEAR_MINUTA_E_REVISAR", "alertas_obtidos": ["DATA_INEXISTENTE"], "confere": True},
        {"id": "T02-B", "decisao_obtida": "BLOQUEAR_MINUTA_E_REVISAR", "alertas_obtidos": ["VALOR_SEM_ANCORA"], "confere": True}])
    escrever(raiz, "resultados/metricas/avaliacao_nlp_rf15.json", {"gerado_em": "2026-10-30T10:00:00", "agregados": {
        "acuracia_categoria": fr(6, 6), "campos_exatos_corretos": fr(41, 42), "fatos_essenciais_preservados": fr(22, 22),
        "resumos_no_limite_de_100_palavras": fr(6, 6), "decisoes_corretas": fr(6, 6), "entidades_omitidas": fr(0, 36)}})
    escrever(raiz, "resultados/guardrails/avaliacao_guardrails_rf16.json", {"gerado_em": "2026-10-30T10:00:00", "agregados": {
        "ataques_contidos": fr(3, 3), "variantes_contidas": fr(4, 4), "legitimas_permitidas": fr(6, 6),
        "camada3_exemplos_conferem": fr(6, 6), "fora_de_escopo_contido": fr(2, 2), "limites_t05_respeitados": fr(2, 2),
        "orcamento": {"chamadas": 28, "max_chamadas": 150}}})
    escrever(raiz, "resultados/indice/indexacoes.jsonl", [
        {"situacao_inicial": "AUSENTE", "chamadas_de_embedding": 7, "vetores_na_colecao": 63, "vetores_no_manifesto": 63,
         "reutilizados": [], "executado_em": "2026-10-30T10:00:00"},
        {"situacao_inicial": "COMPATIVEL", "chamadas_de_embedding": 0, "vetores_na_colecao": 63, "vetores_no_manifesto": 63,
         "reutilizados": ["DOC-01"] * 7, "executado_em": "2026-10-30T10:01:00"}])
    escrever(raiz, "resultados/metricas/comparacao_chunking_rf18.json", {"gerado_em": "2026-10-30T10:00:00", "configuracoes": {
        c: {"parametros": {"tamanho": t, "sobreposicao": s}, "acerto_recuperacao": fr(5, 5), "mrr": m}
        for c, t, s, m in (("A", 350, 50, 0.9), ("B", 800, 160, 0.75))}})
    itens = [{"id": f"RAG-0{i}", "tipo": "respondivel", "status_obtido": "FUNDAMENTADA", "confere": i <= rag_t08["numerador"],
              "fontes_exigidas_citadas": True, "fontes_exigidas": ["DOC-0" + str(i)], "documentos_citados": ["DOC-0" + str(i)],
              "codigo_motivo": "FUNDAMENTADA", "afirmacoes_do_modelo": 2, "afirmacoes_com_citacao": 2,
              "afirmacoes_com_numeros_no_trecho_citado": 2} for i in range(1, 6)]
    itens += [{"id": "RAG-06", "tipo": "sem_resposta", "status_obtido": "SEM_EVIDENCIA_SUFICIENTE", "confere": True},
              {"id": "RAG-08", "tipo": "contraditoria", "status_obtido": "CONFLITO_DE_FONTES", "confere": True,
               "documentos_nas_divergencias": ["DOC-04", "DOC-05"], "afirmacoes_do_modelo": 2, "afirmacoes_com_citacao": 1,
               "afirmacoes_com_numeros_no_trecho_citado": 1}]
    escrever(raiz, f"resultados/metricas/avaliacao_rag_rf19_{PRINCIPAL}.json", {
        "gerado_em": "2026-10-30T11:00:00", "itens": itens,
        "agregados": {"T08_respondiveis_conferem": rag_t08, "T08_status_fundamentada": fr(5, 5),
                      "T08_afirmacoes_essenciais_presentes": fr(10, 10), "T08_referencias_essenciais_citadas": fr(8, 8),
                      "T09_abstencao_correta": fr(2, 2), "T10_conflito_tratado": fr(1, 1)},
        "controle_t14": {"status_obtido": "SEM_EVIDENCIA_SUFICIENTE", "confere": True}})
    escrever(raiz, "resultados/metricas/conferencia_sustentacao_rag.json", {"revisado_por": None, "casos": [
        {"id": "RAG-01", "status": "FUNDAMENTADA", "afirmacoes": [{"sustentada": sustentada}, {"sustentada": sustentada}]},
        {"id": "RAG-06", "status": "SEM_EVIDENCIA_SUFICIENTE", "afirmacoes": []}]})
    escrever(raiz, avaliacao.ARQ_DECISOES_D02, [
        {"caso_id": f"ATD-{n}", "estado": e, "registrado_em": f"2026-10-30T12:0{n}:00", "envio_automatico_bloqueado": True}
        for n, e in enumerate(decisoes)])
    escrever(raiz, "resultados/metricas/comparativo_geracao_rf21.json", {
        "gerado_em": "2026-10-30T12:00:00", "modelos": [PRINCIPAL, "gpt-5.6-terra"], "confere_t12": True,
        "indice": {"preservado": True, "antes": {"vetores": 59}},
        "falha_simulada": {"status": "SEM_EVIDENCIA_SUFICIENTE", "codigo_motivo": "FALHA_NA_GERACAO", "auditoria": {"sucesso": False}}})
    escrever(raiz, "resultados/indice/exclusao_t14.json", {
        "doc_id": "DOC-99", "confere": True, "exclusao": {"vetores_removidos_por_colecao": {"acervo_principal": 4}},
        "depois": {"trechos_do_documento_no_top_k": 0}, "reindexacao_automatica": {"ignorados_por_exclusao": ["DOC-99"]}})
    escrever(raiz, "indice/manifesto_indice.json", {"colecoes": {"acervo_principal": {"exclusoes": [{"doc_id": "DOC-99"}]}}})
    escrever(raiz, "resultados/metricas/regressao_t15.json", {
        "gerado_em": "2026-10-30T13:00:00", "decisoes_simuladas": regressao_simulada, "confere": True,
        "pasta_de_evidencias": "resultados/regressao/x",
        "texto": {"chegou_a_minuta": True, "revisao": {"decisao": "APROVADO"}, "acerto_extracao_gabarito": fr(24, 26)},
        "ocr": {"acerto_leitura_gabarito": fr(21, 26), "etapa_final": "MINUTA_GERADA", "estado_na_fila": "PENDENTE"}})
    escrever(raiz, "resultados/metricas/avaliacao_sentimentos_rf22.json", {
        "agregados": {"acuracia_polaridade": fr(11, 12), "revisao_esperada_sinalizada": fr(3, 4)},
        "itens": [{"id": "AV-12", "ambiguidade_esperada": "limitrofe", "polaridade_confere": False, "polaridade_esperada": "indeterminada",
                   "polaridade_obtida": "positiva", "justificativa_gabarito": "R4"}]})


@pytest.fixture
def raiz(tmp_path, monkeypatch):
    monkeypatch.setattr(avaliacao, "RAIZ_PROJETO", tmp_path)
    caminho_csv, _ = persistir_rotulos(registros_do_gabarito(), tmp_path / "resultados" / "sentimentos")
    monkeypatch.setattr(src.sentiment, "arquivo_de_rotulos_mais_recente", lambda *_: caminho_csv)
    return tmp_path


def situacoes(linhas):
    return {l["id"]: l["situacao"] for l in linhas}


def test_sem_evidencia_tudo_fica_pendente_sem_quebrar(tmp_path, monkeypatch):
    monkeypatch.setattr(avaliacao, "RAIZ_PROJETO", tmp_path)
    monkeypatch.setattr(src.sentiment, "arquivo_de_rotulos_mais_recente", lambda *_: None)
    linhas, metricas = avaliacao.montar_matriz(CONFIG)
    assert [l["id"] for l in linhas] == [f"T{n:02d}" for n in range(1, 16)]
    assert set(situacoes(linhas).values()) == {avaliacao.PENDENTE}
    assert all(l["obtido"] == "não localizado" or l["id"] == "T11" for l in linhas)
    assert metricas["acuracia_de_categorias"] is None and metricas["sentimentos"] is None


def test_situacoes_saem_das_evidencias(raiz):
    evidencias(raiz)
    s = situacoes(avaliacao.montar_matriz(CONFIG)[0])
    assert s["T03"] == avaliacao.RESSALVA  # campos exatos 41/42
    assert all(s[t] == avaliacao.CONFERE for t in ("T01", "T02", "T04", "T05", "T06", "T07", "T08", "T09", "T10", "T11",
                                                     "T12", "T13", "T14", "T15"))


def test_falha_parcial_vira_ressalva_e_regressao_simulada_tambem(raiz):
    evidencias(raiz, rag_t08=fr(4, 5), regressao_simulada=True)
    linhas, _ = avaliacao.montar_matriz(CONFIG)
    s = situacoes(linhas)
    assert s["T08"] == avaliacao.RESSALVA and s["T15"] == avaliacao.RESSALVA
    t15 = next(l for l in linhas if l["id"] == "T15")
    assert "simulada" in t15["observacao"]


@pytest.mark.parametrize("decisoes", [(), ("APROVADA",), ("REJEITADA", "REVISAR")])
def test_t11_exige_aprovacao_e_rejeicao_ou_revisao_reais(raiz, decisoes):
    evidencias(raiz, decisoes=decisoes)
    linha = next(l for l in avaliacao.montar_matriz(CONFIG)[0] if l["id"] == "T11")
    assert linha["situacao"] == avaliacao.PENDENTE and "Ação humana pendente" in linha["observacao"]


def test_metricas_do_rf23_e_sustentacao_humana(raiz):
    evidencias(raiz)
    m = avaliacao.montar_matriz(CONFIG)[1]
    assert m["acuracia_de_categorias"] == fr(6, 6) and m["acerto_de_recuperacao"] == fr(5, 5)
    sustentacao = m["respostas_institucionais_sustentadas"]
    assert sustentacao["verificacao_automatica"] == fr(5, 6)  # RAG-08 tem afirmação sem citação
    assert sustentacao["conferencia_humana"] is None and sustentacao["conferencia_humana_situacao"].startswith("PENDENTE: 0 de 2")
    assert m["abstencao_correta_sem_resposta"] == fr(2, 2) and m["caso_contraditorio"]["documentos"] == ["DOC-04", "DOC-05"]
    assert m["sentimentos"]["acuracia_polaridade"] == fr(11, 12) and m["t13_agregacao"] is True
    evidencias(raiz, sustentada=True)
    assert avaliacao.montar_matriz(CONFIG)[1]["respostas_institucionais_sustentadas"]["conferencia_humana"] == fr(1, 1)


def test_relatorio_tem_a_nota_da_numeracao_e_as_quinze_linhas(raiz):
    evidencias(raiz)
    linhas, metricas = avaliacao.montar_matriz(CONFIG)
    texto = avaliacao.relatorio_matriz_md(linhas, metricas, "2026-10-30T14:00:00")
    assert "RF15, RF15, RF16 e RF17" in texto and "RF14, RF14, RF15 e RF16" in texto
    assert all(f"| T{n:02d} |" in texto for n in range(1, 16))
    assert "Acurácia de categorias (6 solicitações): **6/6**" in texto


def test_t13_sobre_os_rotulos_gravados(raiz):
    t13 = avaliacao.executar_t13()
    assert t13["confere"] and t13["filtro"]["canal"] == "presencial" and not t13["filtro"]["percentual_exibido"]
    assert t13["duplicata"] == {"duplicatas_removidas": 1, "denominador": 12} and t13["vazio"]["denominador"] == 0


# ------------------------------------------------------------------------------
# OCR no fluxo integrado (correção da regressão T15)
# ------------------------------------------------------------------------------
def test_alertas_de_leitura_ocr():
    alertas = alertas_de_leitura_ocr({"trechos_incertos": [{"rotulo": "CPF", "situacao": "INCERTO"}]})
    assert alertas[0] == ALERTA_OCR_NAO_CONFIRMADO and alertas[1] == "CAMPO_INCERTO_NA_LEITURA: CPF (INCERTO)"
    assert alertas_de_leitura_ocr({}) == [ALERTA_OCR_NAO_CONFIRMADO]


def test_atendimento_de_ocr_vai_a_revisao_prioritaria(indice, tmp_path):  # noqa: F811
    audit = AuditManager(dir_logs=tmp_path / "logs")
    guardrails, _, _ = guardrails_offline()
    texto = (raiz_projeto / "dados" / "originais" / "entrada_texto.txt").read_text(encoding="utf-8")
    resultado = processar_atendimento(texto, CONFIG_RAG, indice, cliente(responder_sol01), guardrails, audit, dir_base=tmp_path,
                                      alertas_da_origem=alertas_de_leitura_ocr({}))
    assert resultado.alertas_da_origem == [ALERTA_OCR_NAO_CONFIRMADO]
    assert ALERTA_OCR_NAO_CONFIRMADO in resultado.rag["alertas"] and resultado.rag["encaminhamento"] == "REVISAO_HUMANA_PRIORITARIA"


def test_relatorios_da_regressao_e_do_comparativo_renderizam():
    regressao = {"gerado_em": "x", "provedor": "openai", "modelo": PRINCIPAL, "decisoes_simuladas": True, "pasta_de_evidencias": "p",
                 "confere": False, "pendencias": ["OCR: não chegou à minuta"],
                 "texto": {"fluxo": "f", "pipeline_concluido": True, "acerto_extracao_gabarito": None, "minuta": None,
                           "revisao": {"decisao": None, "operador": None, "arquivo": "a"}},
                 "ocr": {"fluxo": "f", "leitura_ok": False, "erro_leitura": "INDISPONIVEL"}}
    texto = avaliacao.relatorio_regressao_md(regressao)
    assert "NÃO CONFERE" in texto and "Leitura falhou: INDISPONIVEL" in texto and "Pendência: OCR" in texto
