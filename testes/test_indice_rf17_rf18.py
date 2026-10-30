#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
==============================================================================
TESTES DA INGESTÃO, DO ÍNDICE VETORIAL E DO CHUNKING (RF17, RF18, RF24)
==============================================================================
Sem rede (gerador de embeddings falso, determinístico; SDK falso da OpenAI):
- leitura por página, PDF sem texto, linhas e seções reconstruídas como na
  fonte e referências do gabarito na página e seção certas;
- trechos dentro do tamanho, sem cruzar página ou seção, com cabeçalho
  contextual e IDs determinísticos;
- T06: reinício reutiliza o índice sem novo embedding e reindexar não duplica;
  documento alterado substitui os trechos antigos; modelo ou chunking
  diferente exige reindexação;
- cosseno, similaridade = 1 - distância e filtro com $and;
- T14: exclusão remove os vetores, registra e não volta sozinha;
- embeddings em lotes, na ordem certa, sob o orçamento da execução;
- T07: experimento de chunking com as mesmas perguntas e o mesmo vetor.
==============================================================================
"""

import hashlib
import importlib.util
import json
import math
import re
import shutil
import sys
from pathlib import Path
from types import SimpleNamespace

import pymupdf
import pytest

raiz_projeto = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(raiz_projeto))

from src.conferencia import normalizar
from src.embeddings import EmbeddingsOpenAI, ErroEmbeddings, IndiceVetorial, comparar_configuracoes
from src.ingestion import (
    PREAMBULO, clausulas_preservadas, dividir_em_trechos, gerar_trechos, ler_documento, reconstruir_linhas, segmentar,
)
from src.llm_client import LLMClient, OrcamentoExecucao
from test_adaptadores_openai import CFG_OPENAI, SDKFalso
from src.adaptadores import OpenAIAdapter

CONFIG = json.loads((raiz_projeto / "config.json").read_text(encoding="utf-8"))
MANIFESTO = json.loads((raiz_projeto / CONFIG["desafio02"]["manifesto_acervo"]).read_text(encoding="utf-8"))
DOCS = {d["doc_id"]: d for d in MANIFESTO["documentos"]}
GABARITO_RAG = json.loads((raiz_projeto / CONFIG["desafio02"]["gabarito_rag"]).read_text(encoding="utf-8"))
CHUNK_A = {"rotulo": "A", **CONFIG["chunking"]["configuracoes"]["A"]}
CHUNK_B = {"rotulo": "B", **CONFIG["chunking"]["configuracoes"]["B"]}


class EmbedderFalso:
    """Bag-of-words com hashing: determinístico, sem rede; textos com palavras em comum ficam próximos."""

    def __init__(self, modelo="embedding-falso-teste", dimensao=128):
        self.modelo, self.dimensao, self.chamadas = modelo, dimensao, []

    def embedar(self, textos, etapa="teste"):
        self.chamadas.append({"etapa": etapa, "textos": len(textos), "tokens": 0, "custo_estimado_usd": 0.0})
        vetores = []
        for texto in textos:
            vetor = [0.0] * self.dimensao
            for palavra in re.findall(r"[a-z0-9]+", normalizar(texto)):
                vetor[int(hashlib.md5(palavra.encode()).hexdigest(), 16) % self.dimensao] += 1.0
            norma = math.sqrt(sum(x * x for x in vetor)) or 1.0
            vetores.append([x / norma for x in vetor])
        return vetores


def novo_indice(diretorio, embedder=None) -> IndiceVetorial:
    return IndiceVetorial(CONFIG, embedder or EmbedderFalso(), diretorio_base=diretorio)


def docs(*ids):
    return [DOCS[i] for i in ids]


def fonte_do_gerador():
    spec = importlib.util.spec_from_file_location("gerador", raiz_projeto / CONFIG["desafio02"]["gerador_acervo"])
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


# ------------------------------------------------------------------------------
# Ingestão
# ------------------------------------------------------------------------------
def test_pdf_lido_por_pagina_e_txt_sem_paginacao():
    assert [p.numero for p in ler_documento(raiz_projeto / DOCS["DOC-01"]["arquivo"])] == [1, 2, 3]
    assert [p.numero for p in ler_documento(raiz_projeto / DOCS["DOC-03"]["arquivo"])] == [None]


def test_pdf_sem_texto_gera_erro_que_orienta_ocr(tmp_path):
    vazio = tmp_path / "digitalizado.pdf"
    with pymupdf.open() as pdf:
        pdf.new_page()
        pdf.save(vazio)
    with pytest.raises(ValueError, match="OCR"):
        ler_documento(vazio)
    with pytest.raises(ValueError, match="não suportado"):
        ler_documento(tmp_path / "planilha.xlsx")


def test_linhas_reconstruidas_preservam_cada_linha_da_fonte():
    """A diagramação do PDF quebra frases; a reconstrução precisa devolver cada linha da fonte inteira."""
    gerador = fonte_do_gerador()
    for doc in gerador.DOCUMENTOS:
        if doc["formato"] != "pdf":
            continue
        paginas = ler_documento(raiz_projeto / DOCS[doc["doc_id"]]["arquivo"])
        for pagina, fonte in zip(paginas, gerador.paginas_finais(doc)):
            reconstruidas = reconstruir_linhas(pagina.texto)
            for linha in filter(None, (" ".join(l.split()) for l in fonte.splitlines())):
                assert any(linha in r for r in reconstruidas), f"{doc['doc_id']} p.{pagina.numero}: {linha[:60]}"


def test_referencias_do_gabarito_caem_na_pagina_e_secao_certas():
    referencias = [r for p in GABARITO_RAG["perguntas"] for r in p["trechos_referencia"]]
    referencias += GABARITO_RAG["pergunta_controle_exclusao_t14"]["antes_da_exclusao"]["trechos_referencia"]
    for ref in referencias:
        segmentos = segmentar(ler_documento(raiz_projeto / DOCS[ref["doc_id"]]["arquivo"]))
        assert any(s.pagina == ref["pagina"] and s.secao == ref["secao"] and normalizar(ref["trecho_gabarito"]) in normalizar(s.texto)
                   for s in segmentos), f"{ref['doc_id']} p.{ref['pagina']} {ref['secao']}"


def test_secao_continua_e_preambulo():
    segmentos = segmentar(ler_documento(raiz_projeto / DOCS["DOC-02"]["arquivo"]))
    assert segmentos[0].secao == PREAMBULO
    assert [s.secao for s in segmentos if s.pagina == 2][0] == "Art. 3º"


@pytest.mark.parametrize("chunking", [CHUNK_A, CHUNK_B])
def test_trechos_respeitam_tamanho_pagina_e_secao(chunking):
    for doc in MANIFESTO["documentos"]:
        caminho = raiz_projeto / doc["arquivo"]
        trechos, segmentos = gerar_trechos(doc, caminho, chunking["tamanho"], chunking["sobreposicao"], chunking["rotulo"])
        textos_por_local = {(s.pagina, s.secao): normalizar(s.texto) for s in segmentos}
        for trecho in trechos:
            meta = trecho.metadados
            assert len(trecho.conteudo) <= chunking["tamanho"]
            assert normalizar(trecho.conteudo) in textos_por_local[(meta.get("pagina"), meta["secao"])], "trecho cruzou página ou seção"
            assert trecho.texto.startswith(f"[{doc['doc_id']} | {doc['titulo']} | versão {doc['versao']} | {meta['secao']}")
            assert ("pagina" in meta) is (doc["formato"] == "pdf")
            assert meta["hash_sha256"] == doc["hash_sha256"] and meta["chunk_id"] == trecho.chunk_id


def test_ids_sao_deterministicos_e_carregam_a_configuracao():
    doc = DOCS["DOC-05"]
    primeiro, _ = gerar_trechos(doc, raiz_projeto / doc["arquivo"], 350, 50, "A")
    segundo, _ = gerar_trechos(doc, raiz_projeto / doc["arquivo"], 350, 50, "A")
    assert [t.chunk_id for t in primeiro] == [t.chunk_id for t in segundo]
    assert primeiro[0].chunk_id.startswith("DOC-05::A::p1::t")


def test_sobreposicao_e_corte_em_fim_de_frase():
    texto = " ".join(f"Frase número {i} do manual, com algumas palavras a mais." for i in range(40))
    trechos = dividir_em_trechos(texto, 200, 50)

    assert all(len(c) <= 200 for _, c in trechos)
    assert all(c.endswith(".") for _, c in trechos[:-1]), "corte preferencial em fim de frase"
    for (inicio_a, conteudo_a), (inicio_b, _) in zip(trechos, trechos[1:]):
        assert inicio_b < inicio_a + len(conteudo_a), "trechos vizinhos se sobrepõem"
        assert texto[inicio_b - 1].isspace(), "a sobreposição começa no início de uma palavra"
    assert dividir_em_trechos("curto", 200, 50) == [(0, "curto")]
    with pytest.raises(ValueError):
        dividir_em_trechos(texto, 100, 100)


def test_clausulas_inteiras_com_trecho_grande():
    doc = DOCS["DOC-01"]
    trechos, segmentos = gerar_trechos(doc, raiz_projeto / doc["arquivo"], 5000, 0, "G")
    inteiras, total = clausulas_preservadas(segmentos, trechos)
    assert inteiras == total > 10


# ------------------------------------------------------------------------------
# Índice (T06)
# ------------------------------------------------------------------------------
def test_t06_reinicio_reutiliza_o_indice_sem_novo_embedding(tmp_path):
    primeiro = novo_indice(tmp_path)
    relatorio = primeiro.indexar("acervo_teste", docs("DOC-03", "DOC-05", "DOC-06"), CHUNK_A)
    assert relatorio["indexados"] == ["DOC-03", "DOC-05", "DOC-06"]

    reiniciado = novo_indice(tmp_path, EmbedderFalso())
    assert reiniciado.situacao("acervo_teste", CHUNK_A)[0] == "COMPATIVEL"
    segundo = reiniciado.indexar("acervo_teste", docs("DOC-03", "DOC-05", "DOC-06"), CHUNK_A)

    assert segundo["reutilizados"] == ["DOC-03", "DOC-05", "DOC-06"] and segundo["indexados"] == []
    assert segundo["chamadas_de_embedding"] == 0
    assert segundo["vetores_na_colecao"] == relatorio["vetores_na_colecao"] == segundo["vetores_no_manifesto"]


def test_reindexar_sem_manifesto_nao_duplica(tmp_path):
    indice = novo_indice(tmp_path)
    total = indice.indexar("acervo_teste", docs("DOC-04", "DOC-06"), CHUNK_A)["vetores_na_colecao"]
    (tmp_path / "manifesto_indice.json").unlink()

    relatorio = novo_indice(tmp_path).indexar("acervo_teste", docs("DOC-04", "DOC-06"), CHUNK_A)

    assert relatorio["vetores_na_colecao"] == total, "IDs determinísticos: o mesmo acervo não cria vetores novos"


def test_documento_alterado_substitui_os_trechos_antigos(tmp_path):
    copia = tmp_path / "DOC-06.txt"
    shutil.copy(raiz_projeto / DOCS["DOC-06"]["arquivo"], copia)
    doc = {**DOCS["DOC-06"], "arquivo": str(copia)}
    indice = novo_indice(tmp_path / "indice")
    antes = indice.indexar("acervo_teste", [doc], CHUNK_A)["vetores_na_colecao"]

    with open(copia, "a", encoding="utf-8") as arquivo:
        arquivo.write("\n4. TRANSPORTE NOTURNO\n4.1. Existe ônibus escolar no turno noturno?\nNão. O acervo fictício não prevê ônibus escolar.\n")
    relatorio = indice.indexar("acervo_teste", [doc], CHUNK_A)
    colecao = indice._colecao("acervo_teste")

    assert relatorio["indexados"] == ["DOC-06"] and relatorio["removidos_por_mudanca"] == antes
    assert relatorio["vetores_na_colecao"] == relatorio["vetores_no_manifesto"] > antes
    hashes = {m["hash_sha256"] for m in colecao.get(include=["metadatas"])["metadatas"]}
    assert hashes == {indice.manifesto["colecoes"]["acervo_teste"]["documentos"]["DOC-06"]["hash_sha256"]}


def test_modelo_ou_chunking_diferente_exige_reindexacao(tmp_path):
    indice = novo_indice(tmp_path)
    indice.indexar("acervo_teste", docs("DOC-04"), CHUNK_A)

    assert indice.situacao("acervo_teste", CHUNK_B)[0] == "INCOMPATIVEL"
    assert novo_indice(tmp_path, EmbedderFalso(modelo="outro-modelo")).situacao("acervo_teste", CHUNK_A)[0] == "INCOMPATIVEL"
    relatorio = indice.indexar("acervo_teste", docs("DOC-04"), CHUNK_B)
    assert relatorio["situacao_inicial"] == "INCOMPATIVEL" and relatorio["indexados"] == ["DOC-04"]
    assert relatorio["assinatura"]["chunking"]["rotulo"] == "B"


# ------------------------------------------------------------------------------
# Busca
# ------------------------------------------------------------------------------
def test_busca_em_cosseno_com_metadados_rastreaveis(tmp_path):
    indice = novo_indice(tmp_path)
    indice.indexar("acervo_teste", docs("DOC-05", "DOC-06"), CHUNK_A)
    alvo = indice._colecao("acervo_teste").get(where={"doc_id": "DOC-05"}, include=["documents"])
    resultados = indice.buscar("acervo_teste", alvo["documents"][0], top_k=3)

    assert indice._colecao("acervo_teste").configuration["hnsw"]["space"] == "cosine"
    primeiro = resultados[0]
    assert primeiro["chunk_id"] == alvo["ids"][0]
    assert primeiro["similaridade_cosseno"] == pytest.approx(1.0, abs=1e-3)
    assert all(r["similaridade_cosseno"] == pytest.approx(1 - r["distancia_cosseno"], abs=1e-4) for r in resultados)
    assert {"doc_id", "versao", "pagina", "secao", "chunk_id", "texto"} <= set(primeiro)


def test_filtro_com_dois_campos_vira_and(tmp_path):
    indice = novo_indice(tmp_path)
    indice.indexar("acervo_teste", docs("DOC-05", "DOC-06"), CHUNK_A)
    resultados = indice.buscar("acervo_teste", "termo de compromisso", top_k=5, filtros={"doc_id": "DOC-05", "pagina": 2})
    assert resultados and all((r["doc_id"], r["pagina"]) == ("DOC-05", 2) for r in resultados)


# ------------------------------------------------------------------------------
# Exclusão (T14)
# ------------------------------------------------------------------------------
class AuditoriaFalsa:
    def __init__(self):
        self.registros = []

    def registrar_execucao(self, **kwargs):
        self.registros.append(kwargs)


def test_t14_exclusao_remove_os_vetores_e_nao_volta_sozinha(tmp_path):
    auditoria = AuditoriaFalsa()
    indice = IndiceVetorial(CONFIG, EmbedderFalso(), diretorio_base=tmp_path, audit=auditoria)
    acervo = docs("DOC-03", "DOC-06", "DOC-99")
    indice.indexar("acervo_teste", acervo, CHUNK_A)
    indice.indexar("outra_colecao", docs("DOC-99"), CHUNK_B)
    pergunta = GABARITO_RAG["pergunta_controle_exclusao_t14"]["pergunta"]
    assert "DOC-99" in {r["doc_id"] for r in indice.buscar("acervo_teste", pergunta, top_k=3)}

    relatorio = indice.excluir_documento("DOC-99", "teste")

    assert relatorio["vetores_restantes"] == 0 and set(relatorio["vetores_removidos_por_colecao"]) == {"acervo_teste", "outra_colecao"}
    assert "DOC-99" not in {r["doc_id"] for r in indice.buscar("acervo_teste", pergunta, top_k=5)}
    assert auditoria.registros[-1]["etapa"] == "exclusao_documento"
    reindexacao = novo_indice(tmp_path).indexar("acervo_teste", acervo, CHUNK_A)
    assert reindexacao["ignorados_por_exclusao"] == ["DOC-99"], "documento excluído não volta numa reindexação automática"
    assert novo_indice(tmp_path).indexar("acervo_teste", acervo, CHUNK_A, reincluir_excluidos=True)["indexados"] == ["DOC-99"]


def test_t14_exclusao_sobrevive_a_reconstrucao_do_indice(tmp_path):
    """Instalação nova: o manifesto vem no pacote e indice/chroma não; a reconstrução não traz o excluído de volta."""
    acervo = docs("DOC-03", "DOC-99")
    indice = novo_indice(tmp_path / "original")
    indice.indexar("acervo_teste", acervo, CHUNK_A)
    indice.excluir_documento("DOC-99", "teste")
    (tmp_path / "pacote").mkdir()
    shutil.copy(tmp_path / "original" / "manifesto_indice.json", tmp_path / "pacote" / "manifesto_indice.json")
    reconstruido = novo_indice(tmp_path / "pacote")
    assert reconstruido.situacao("acervo_teste", CHUNK_A)[0] == "INCONSISTENTE"
    relatorio = reconstruido.indexar("acervo_teste", acervo, CHUNK_A)
    assert relatorio["indexados"] == ["DOC-03"] and relatorio["ignorados_por_exclusao"] == ["DOC-99"]
    assert reconstruido.manifesto["colecoes"]["acervo_teste"]["exclusoes"][0]["doc_id"] == "DOC-99"


class ColecaoInstavel:
    """Repassa para a coleção real, mas a leitura falha nas `falhas` primeiras vezes (erro interno do Chroma)."""

    def __init__(self, colecao, falhas):
        self.colecao, self.falhas, self.tentativas = colecao, falhas, 0

    def _talvez_falhar(self):
        from chromadb.errors import InternalError
        self.tentativas += 1
        if self.tentativas <= self.falhas:
            raise InternalError("Error creating hnsw segment reader: Nothing found on disk")

    def query(self, **kwargs):
        self._talvez_falhar()
        return self.colecao.query(**kwargs)

    def get(self, **kwargs):
        self._talvez_falhar()
        return self.colecao.get(**kwargs)


def indice_instavel(tmp_path, monkeypatch, falhas):
    import src.embeddings
    monkeypatch.setattr(src.embeddings.time, "sleep", lambda _s: None)
    indice = novo_indice(tmp_path)
    indice.indexar("acervo_teste", docs("DOC-03"), CHUNK_A)
    instavel = ColecaoInstavel(indice._colecao("acervo_teste"), falhas)
    monkeypatch.setattr(indice, "_colecao", lambda _nome: instavel)
    return indice, instavel


def test_leitura_do_indice_repete_uma_vez_em_falha_interna_do_chroma(tmp_path, monkeypatch):
    indice, instavel = indice_instavel(tmp_path, monkeypatch, falhas=1)
    assert indice.buscar("acervo_teste", "faltas nos primeiros dias letivos", top_k=2)
    assert instavel.tentativas == 2
    instavel.tentativas = 0
    assert indice.trechos_da_secao("acervo_teste", "DOC-03", indice.buscar("acervo_teste", "faltas", 1)[0]["secao"])


def test_falha_que_persiste_no_indice_sobe_para_quem_chamou(tmp_path, monkeypatch):
    from chromadb.errors import InternalError
    indice, instavel = indice_instavel(tmp_path, monkeypatch, falhas=2)
    with pytest.raises(InternalError):
        indice.buscar("acervo_teste", "faltas", top_k=2)
    assert instavel.tentativas == 2, "no máximo uma nova tentativa"


# ------------------------------------------------------------------------------
# Embeddings da OpenAI (SDK falso)
# ------------------------------------------------------------------------------
def lote_de_embeddings(*indices, dimensao=4):
    return SimpleNamespace(model="text-embedding-3-small", usage=SimpleNamespace(prompt_tokens=10 * len(indices), total_tokens=10 * len(indices)),
                           data=[SimpleNamespace(index=i, embedding=[float(i + 1)] * dimensao) for i in indices])


def test_embeddings_em_lotes_na_ordem_e_sob_o_orcamento():
    cliente = LLMClient(provedor="simulado")
    cliente.adaptador, cliente.provedor = OpenAIAdapter(CFG_OPENAI, cliente=SDKFalso(lote_de_embeddings(1, 0), lote_de_embeddings(0))), "openai"
    cliente.orcamento = OrcamentoExecucao(10, 10 ** 6)
    embedder = EmbeddingsOpenAI(cliente, "text-embedding-3-small", dimensao=4, tamanho_lote=2)

    vetores = embedder.embedar(["a", "b", "c"])

    assert vetores == [[1.0] * 4, [2.0] * 4, [1.0] * 4], "a ordem segue o campo index, não a ordem de chegada"
    assert [c["textos"] for c in embedder.chamadas] == [2, 1] and cliente.orcamento.chamadas == 2
    metodo, argumentos = cliente.adaptador.cliente.chamadas[0]
    assert metodo == "embeddings" and argumentos["model"] == "text-embedding-3-small"


def test_embeddings_recusam_texto_longo_e_dimensao_errada():
    cliente = LLMClient(provedor="simulado")
    cliente.adaptador, cliente.provedor = OpenAIAdapter(CFG_OPENAI, cliente=SDKFalso(lote_de_embeddings(0, dimensao=3))), "openai"
    embedder = EmbeddingsOpenAI(cliente, "text-embedding-3-small", dimensao=4)

    with pytest.raises(ValueError, match="excede o limite"):
        embedder.embedar(["x" * 30000])
    assert cliente.adaptador.cliente.chamadas == [], "texto longo é recusado antes de chamar a API"
    with pytest.raises(ErroEmbeddings) as erro:
        embedder.embedar(["texto"])
    assert erro.value.codigo == "DIMENSAO_INESPERADA"


def test_falha_de_embedding_vira_erro_com_codigo():
    embedder = EmbeddingsOpenAI(LLMClient(provedor="simulado"), "text-embedding-3-small", dimensao=4)
    with pytest.raises(ErroEmbeddings) as erro:
        embedder.embedar(["texto"])
    assert erro.value.codigo == "NAO_SUPORTADO"


def test_diagnostico_do_indice_sem_rede(tmp_path):
    from src.embeddings import diagnosticar_indice
    config = {**CONFIG, "indice": {**CONFIG["indice"], "diretorio_base": str(tmp_path)}}
    assert diagnosticar_indice(config)[0] == "AUSENTE"

    modelo = CONFIG["llm"]["openai"]["modelo_embedding"]
    indice = novo_indice(tmp_path, EmbedderFalso(modelo=modelo, dimensao=CONFIG["llm"]["openai"]["dimensao_embedding"]))
    indice.indexar(CONFIG["indice"]["colecao_principal"], docs("DOC-04"), {"rotulo": CONFIG["chunking"]["configuracao_principal"],
                   **CONFIG["chunking"]["configuracoes"][CONFIG["chunking"]["configuracao_principal"]]})
    assert diagnosticar_indice(config)[0] == "COMPATIVEL"

    outro_chunking = {**config, "chunking": {**CONFIG["chunking"], "configuracao_principal": "B"}}
    assert diagnosticar_indice(outro_chunking)[0] == "INCOMPATIVEL", "índice desatualizado em relação ao config"


# ------------------------------------------------------------------------------
# Experimento de chunking (T07)
# ------------------------------------------------------------------------------
def test_t07_experimento_compara_as_configuracoes_com_as_mesmas_perguntas(tmp_path):
    embedder = EmbedderFalso()
    resultado = comparar_configuracoes(CONFIG, novo_indice(tmp_path, embedder))

    assert set(resultado["configuracoes"]) == {"A", "B"}
    assert resultado["configuracao_recomendada"] in {"A", "B"}
    assert [c["etapa"] for c in embedder.chamadas].count("experimento_chunking_perguntas") == 1, "um vetor por pergunta para as duas"
    for configuracao in resultado["configuracoes"].values():
        assert configuracao["acerto_recuperacao"]["denominador"] == 5
        assert len(configuracao["perguntas"]) == 8
        assert configuracao["parametros"]["unidade"] == "caracteres"
        assert configuracao["clausulas_inteiras"]["numerador"] <= configuracao["clausulas_inteiras"]["denominador"]
