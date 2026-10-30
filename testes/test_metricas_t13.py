#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
==============================================================================
TESTES DA AGREGAÇÃO DETERMINÍSTICA (RF22, RF23 — T13)
==============================================================================
T13: filtro, duplicata e conjunto vazio com totais corretos, denominador
visível e sem divisão por zero. Também: percentual omitido abaixo do mínimo
de 10 casos, censo sem intervalo de confiança e fila de revisão.
Os rótulos de entrada são os do gabarito (sem modelo).
==============================================================================
"""

import json
import sys
from pathlib import Path

raiz_projeto = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(raiz_projeto))

from src import metrics

CONFIG = json.loads((raiz_projeto / "config.json").read_text(encoding="utf-8"))
AVALIACOES = json.loads((raiz_projeto / CONFIG["desafio02"]["avaliacoes"]).read_text(encoding="utf-8"))["avaliacoes"]
GABARITO = json.loads((raiz_projeto / CONFIG["desafio02"]["gabarito_sentimentos"]).read_text(encoding="utf-8"))


def registros(**alteracoes_por_id):
    rotulos = {r["id"]: r for r in GABARITO["rotulos_esperados"]}
    linhas = []
    for a in AVALIACOES:
        r = rotulos[a["id"]]
        linhas.append({"id": a["id"], "atendimento_id": a["atendimento_id"], "data": a["data"], "canal": a["canal"],
                       "polaridade": r["polaridade"], "intensidade": r["intensidade"], "ambiguidade": r["ambiguidade"],
                       "tema": r["tema"], "trecho_determinante": r["trecho_determinante"],
                       "justificativa_curta": r["justificativa"], "necessita_revisao": r["necessita_revisao"],
                       "classificacao_valida": True, "alertas": "", "modelo": "gabarito", "classificado_em": "2026-10-30T10:00:00",
                       **alteracoes_por_id.get(a["id"], {})})
    return linhas


def contagem(distribuicao):
    return {c["categoria"]: c["n"] for c in distribuicao["categorias"]}


def test_constantes_coincidem_com_o_config():
    assert metrics.MINIMO_PARA_PERCENTUAL == CONFIG["sentimentos"]["minimo_para_percentual"] == 10
    assert metrics.E_AMOSTRA is CONFIG["sentimentos"]["e_amostra"] is False


def test_percentual_com_base_suficiente_vazia_ou_pequena():
    assert metrics.percentual(3, 12) == 25.0
    assert metrics.percentual(0, 0) is None and metrics.percentual(1, 0) is None
    assert metrics.percentual(1, 9) is None and metrics.percentual(1, 10) == 10.0
    assert metrics.formatar(metrics.proporcao(3, 12)) == "3/12 (25,0%)"
    assert metrics.formatar(metrics.proporcao(2, 5)) == "2/5"


def test_lote_completo_tem_totais_e_denominador():
    df = metrics.de_registros(registros())
    distribuicao = metrics.distribuicao(df)
    assert distribuicao["denominador"] == 12 and sum(c["n"] for c in distribuicao["categorias"]) == 12
    assert contagem(distribuicao) == {"positiva": 3, "negativa": 3, "neutra": 3, "indeterminada": 3}
    assert all(c["percentual"] == 25.0 and c["denominador"] == 12 for c in distribuicao["categorias"])
    ficha = metrics.ficha_tecnica(df)
    assert ficha["n_avaliacoes"] == 12 and not ficha["e_amostra"] and "não se aplica" in ficha["intervalo_de_confianca"]
    assert ficha["limitrofes"] == {"n": 4, "denominador": 12, "percentual": 33.3}
    assert ficha["periodo"] == {"inicio": "2026-10-05", "fim": "2026-10-21"} and ficha["modelos"] == ["gabarito"]


def test_filtro_abaixo_do_minimo_mostra_so_a_contagem():
    df = metrics.filtrar(metrics.de_registros(registros()), canais=["presencial"])
    distribuicao = metrics.distribuicao(df)
    assert distribuicao["denominador"] == 5 and sum(c["n"] for c in distribuicao["categorias"]) == 5
    assert all(c["percentual"] is None for c in distribuicao["categorias"]) and not distribuicao["percentual_exibido"]
    assert "abaixo do mínimo de 10" in distribuicao["motivo_sem_percentual"]
    assert contagem(distribuicao) == {"positiva": 2, "negativa": 1, "neutra": 1, "indeterminada": 1}


def test_filtro_por_periodo_e_inclusivo_e_combina_com_outros():
    df = metrics.de_registros(registros())
    assert len(metrics.filtrar(df, data_inicial="2026-10-13", data_final="2026-10-16")) == 4
    assert len(metrics.filtrar(df, data_inicial="2026-10-13", data_final="2026-10-16", polaridades=["neutra"])) == 3
    assert len(metrics.filtrar(df, apenas_revisao=True)) == 4


def test_conjunto_vazio_nao_divide_por_zero():
    df = metrics.filtrar(metrics.de_registros(registros()), canais=["canal-inexistente"])
    distribuicao = metrics.distribuicao(df)
    assert distribuicao["denominador"] == 0 and all(c["n"] == 0 and c["percentual"] is None for c in distribuicao["categorias"])
    assert distribuicao["motivo_sem_percentual"] == "nenhuma avaliação no recorte"
    resultado = metrics.indicadores(metrics.de_registros(registros()), canais=["canal-inexistente"])
    assert resultado["ficha_tecnica"]["n_avaliacoes"] == 0 and resultado["ficha_tecnica"]["limitrofes"]["percentual"] is None
    assert resultado["por_canal"] == [] and resultado["fila_de_revisao"] == []
    assert metrics.indicadores(metrics.de_registros([]))["polaridade"]["denominador"] == 0


def test_duplicata_conta_uma_vez_pela_classificacao_mais_recente():
    linhas = registros()
    repetida = {**linhas[0], "polaridade": "neutra", "classificado_em": "2026-10-30T11:00:00"}
    df, removidas = metrics.remover_duplicatas(metrics.de_registros(linhas + [repetida]))
    assert removidas == 1 and len(df) == 12
    assert df.loc[df["id"] == "AV-01", "polaridade"].item() == "neutra"
    resultado = metrics.indicadores(metrics.de_registros(linhas + [repetida]))
    assert resultado["ficha_tecnica"]["duplicatas_removidas"] == 1 and resultado["polaridade"]["denominador"] == 12
    assert contagem(resultado["polaridade"]) == {"positiva": 2, "negativa": 3, "neutra": 4, "indeterminada": 3}


def test_recorte_por_grupo_omite_percentual_dos_grupos_pequenos():
    grupos = {g["grupo"]: g for g in metrics.recorte(metrics.de_registros(registros()), "canal")}
    assert sum(g["n"] for g in grupos.values()) == 12
    assert all(c["percentual"] is None for g in grupos.values() for c in g["categorias"])
    assert grupos["presencial"]["n"] == 5 and grupos["aplicativo"]["n"] == 2


def test_rotulo_ausente_por_falha_aparece_na_contagem_e_na_fila():
    linhas = registros(**{"AV-03": {"polaridade": None, "ambiguidade": None, "classificacao_valida": False,
                                    "necessita_revisao": True, "alertas": "FALHA_NA_CLASSIFICACAO: INDISPONIVEL"}})
    df = metrics.de_registros(linhas)
    distribuicao = metrics.distribuicao(df)
    assert contagem(distribuicao)["sem rótulo"] == 1 and contagem(distribuicao)["positiva"] == 2
    assert sum(c["n"] for c in distribuicao["categorias"]) == 12
    fila = metrics.fila_de_revisao(df)
    assert "AV-03" in fila["id"].tolist() and set(fila["id"]) == {"AV-03", "AV-06", "AV-10", "AV-11", "AV-12"}
    assert metrics.ficha_tecnica(df)["sem_rotulo_valido"]["n"] == 1


def test_indicadores_viram_json_valido():
    texto = json.dumps(metrics.indicadores(metrics.de_registros(registros(**{"AV-03": {"trecho_determinante": None}}))),
                       allow_nan=False, default=str)
    assert '"denominador": 12' in texto
