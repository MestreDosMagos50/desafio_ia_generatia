#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
==============================================================================
VALIDAÇÃO DOS DADOS FICTÍCIOS E GABARITOS DO DESAFIO 02 (Seção 6)
==============================================================================
Sem rede e sem modelo, confere que os dados preparados antes da execução:
- cumprem as quantidades mínimas (6 documentos em 2 temas e 2 formatos,
  6 solicitações, 8 perguntas do RAG, 12 avaliações, 3 ataques);
- são reproduzíveis (o gerador recria o acervo com o mesmo SHA-256) e têm
  PDFs textuais com identificação visível e metadados limpos;
- têm gabaritos coerentes (trechos de referência presentes na página e na
  seção indicadas, entidades presentes no texto original, rótulos dentro
  das listas documentadas, erros esperados do T01 consistentes);
- não contêm dados reais (domínios oficiais, telefones, CPFs, chaves e os
  nomes e o endereço reais dos editais de contexto/, conferidos por hash).
==============================================================================
"""

import hashlib
import importlib.util
import json
import re
import sys
import unicodedata
from collections import Counter
from datetime import datetime
from pathlib import Path

import pymupdf
import pytest

raiz_projeto = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(raiz_projeto))

CONFIG = json.loads((raiz_projeto / "config.json").read_text(encoding="utf-8"))
ARQUIVOS = CONFIG["desafio02"]


def carregar(chave: str) -> dict:
    return json.loads((raiz_projeto / ARQUIVOS[chave]).read_text(encoding="utf-8"))


MANIFESTO = carregar("manifesto_acervo")
DOCS = {doc["doc_id"]: doc for doc in MANIFESTO["documentos"]}
CAMPOS_CONTRATO = ["protocolo", "data_solicitacao", "solicitante_ficticio", "curso", "assunto", "pedido",
                   "categoria", "entidades", "campos_ausentes", "necessita_revisao"]
CAMPOS_ANULAVEIS = ["protocolo", "data_solicitacao", "solicitante_ficticio", "curso", "assunto", "pedido"]
TIPOS_ENTIDADE = ["pessoas_ficticias", "orgaos", "locais", "datas", "protocolos"]


def normalizar(texto: str) -> str:
    """Sem acentos, minúsculo e com espaços colapsados (critério de comparação dos gabaritos)."""
    texto = unicodedata.normalize("NFKD", texto)
    return " ".join("".join(c for c in texto if not unicodedata.combining(c)).casefold().split())


def paginas_do_documento(doc_id: str) -> list:
    """Texto por página (PDF) ou o texto inteiro como página única (TXT)."""
    caminho = raiz_projeto / DOCS[doc_id]["arquivo"]
    if DOCS[doc_id]["formato"] == "pdf":
        with pymupdf.open(caminho) as pdf:
            return [pagina.get_text() for pagina in pdf]
    return [caminho.read_text(encoding="utf-8")]


def texto_do_documento(doc_id: str) -> str:
    return "\n".join(paginas_do_documento(doc_id))


def conferir_trecho(referencia: dict):
    paginas = paginas_do_documento(referencia["doc_id"])
    alvo = paginas[referencia["pagina"] - 1] if referencia["pagina"] else paginas[0]
    assert normalizar(referencia["trecho_gabarito"]) in normalizar(alvo), \
        f"{referencia['doc_id']} p.{referencia['pagina']}: trecho de referência não encontrado: {referencia['trecho_gabarito']!r}"
    assert normalizar(referencia["secao"]) in normalizar(alvo), f"seção {referencia['secao']!r} fora da página indicada"
    # Precisa caber inteiro num trecho da menor configuração de chunking (350 caracteres com cabeçalho)
    assert len(referencia["trecho_gabarito"]) <= 120


# ------------------------------------------------------------------------------
# Acervo
# ------------------------------------------------------------------------------
def test_acervo_cumpre_os_minimos_da_secao6():
    principais = [d for d in MANIFESTO["documentos"] if d["uso"] == "acervo_principal"]
    assert len(principais) == 6
    assert {d["tema"] for d in principais} == set(MANIFESTO["temas"]) and len(MANIFESTO["temas"]) == 2
    assert Counter(d["formato"] for d in principais) == {"pdf": 3, "txt": 3}
    for doc in principais:
        assert doc["doc_id"] and doc["titulo"] and doc["versao"] and doc["data_publicacao"]
    assert DOCS["DOC-99"]["uso"] == "teste_exclusao_T14"


def test_arquivos_conferem_com_o_manifesto_e_mostram_identificacao():
    for doc_id, doc in DOCS.items():
        caminho = raiz_projeto / doc["arquivo"]
        assert hashlib.sha256(caminho.read_bytes()).hexdigest() == doc["hash_sha256"], f"{doc_id}: hash divergente"
        primeira = normalizar(paginas_do_documento(doc_id)[0])
        assert normalizar(f"Identificador: {doc_id} | Versão: {doc['versao']}") in primeira
        assert "documento ficticio" in primeira


def test_pdfs_sao_textuais_e_tem_metadados_limpos():
    for doc_id, doc in DOCS.items():
        if doc["formato"] != "pdf":
            continue
        with pymupdf.open(raiz_projeto / doc["arquivo"]) as pdf:
            assert len(pdf) == doc["paginas"] >= 2
            assert all(len(pagina.get_text().strip()) > 200 for pagina in pdf), f"{doc_id}: página sem texto extraível"
            metadados = pdf.metadata
        assert "fictício" in metadados["author"]
        assert metadados["creator"] == "scripts/gerar_acervo_ficticio.py"


def test_gerador_recria_o_acervo_com_os_mesmos_bytes(tmp_path):
    """Índice reproduzível: o mesmo conteúdo gera os mesmos arquivos e hashes (base do T06)."""
    spec = importlib.util.spec_from_file_location("gerar_acervo_ficticio", raiz_projeto / ARQUIVOS["gerador_acervo"])
    gerador = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gerador)

    recriado = gerador.gerar_acervo(tmp_path / "acervo")
    hashes = gerador.gerar_solicitacoes_reaproveitadas(tmp_path / "solicitacoes")

    assert recriado == MANIFESTO
    for nome, valor in hashes.items():
        assert hashlib.sha256((raiz_projeto / "dados" / "solicitacoes" / nome).read_bytes()).hexdigest() == valor


def test_retificacao_explicita_e_conflito_sem_regra_de_prevalencia():
    assert DOCS["DOC-02"]["retifica"] == "DOC-01" and "DOC-02" in DOCS["DOC-01"]["retificado_por"]
    retificador = normalizar(texto_do_documento("DOC-02"))
    assert "onde se le" in retificador and "leia-se" in retificador and "prevalece" in retificador

    comunicado, regulamento = DOCS["DOC-04"], DOCS["DOC-05"]
    assert (comunicado["data_publicacao"], comunicado["versao"]) == (regulamento["data_publicacao"], regulamento["versao"])
    assert comunicado["regra_de_prevalencia"] is None and regulamento["regra_de_prevalencia"] is None
    for doc_id in ("DOC-04", "DOC-05"):
        assert "prevalece" not in normalizar(texto_do_documento(doc_id))


# ------------------------------------------------------------------------------
# Perguntas do RAG
# ------------------------------------------------------------------------------
def test_oito_perguntas_rag_com_trechos_de_referencia_verificaveis():
    gabarito = carregar("gabarito_rag")
    perguntas = gabarito["perguntas"]
    assert len({p["id"] for p in perguntas}) == len(perguntas) == 8
    assert Counter(p["tipo"] for p in perguntas) == {"respondivel": 5, "sem_resposta": 2, "contraditoria": 1}
    status = {"respondivel": "FUNDAMENTADA", "sem_resposta": "SEM_EVIDENCIA_SUFICIENTE", "contraditoria": "CONFLITO_DE_FONTES"}
    temas = set()

    for pergunta in perguntas:
        assert pergunta["status_esperado"] == status[pergunta["tipo"]]
        assert pergunta["decisao_humana_esperada"] == ("aprovada" if pergunta["tipo"] == "respondivel" else "revisar")
        for referencia in pergunta["trechos_referencia"]:
            assert DOCS[referencia["doc_id"]]["uso"] == "acervo_principal"
            conferir_trecho(referencia)
            # Paráfrase: a pergunta não copia o trecho que deve recuperar (Aula 11, Mini LAB)
            assert normalizar(referencia["trecho_gabarito"]) not in normalizar(pergunta["pergunta"])
            temas.add(DOCS[referencia["doc_id"]]["tema"])
        if pergunta["tipo"] == "respondivel":
            assert any(r["essencial"] for r in pergunta["trechos_referencia"])
        if pergunta["tipo"] == "contraditoria":
            assert {r["doc_id"] for r in pergunta["trechos_referencia"]} == {"DOC-04", "DOC-05"}

    assert temas == set(MANIFESTO["temas"]), "as perguntas respondíveis devem cobrir os dois temas"
    assert any(r["doc_id"] == "DOC-02" for p in perguntas for r in p["trechos_referencia"]), "falta pergunta sobre a retificação"


def test_perguntas_sem_resposta_nao_tem_apoio_no_acervo():
    acervo = " ".join(normalizar(texto_do_documento(doc_id)) for doc_id, doc in DOCS.items())
    for pergunta in carregar("gabarito_rag")["perguntas"]:
        for termo in pergunta.get("termos_ausentes_no_acervo", []):
            assert not re.search(rf"\b{re.escape(normalizar(termo))}\b", acervo), f"{pergunta['id']}: '{termo}' aparece no acervo"


def test_pergunta_de_controle_da_exclusao_recupera_so_o_doc99():
    controle = carregar("gabarito_rag")["pergunta_controle_exclusao_t14"]
    assert controle["documento_excluido"] == "DOC-99"
    for referencia in controle["antes_da_exclusao"]["trechos_referencia"]:
        assert referencia["doc_id"] == "DOC-99"
        conferir_trecho(referencia)
    assert controle["depois_da_exclusao"]["status_esperado"] == "SEM_EVIDENCIA_SUFICIENTE"


# ------------------------------------------------------------------------------
# Solicitações (RF14, RF15) e casos negativos (T01, T02)
# ------------------------------------------------------------------------------
def test_seis_solicitacoes_com_audio_e_ocr_reaproveitados():
    solicitacoes = carregar("solicitacoes")["solicitacoes"]
    assert Counter(s["tipo_caso"] for s in solicitacoes) == {"completa": 4, "incompleta": 1, "ambigua": 1}
    canais_reaproveitados = " ".join(s["canal"] for s in solicitacoes if s["reaproveitada_desafio01"])
    assert "áudio" in canais_reaproveitados and "OCR" in canais_reaproveitados
    for solicitacao in solicitacoes:
        assert (raiz_projeto / solicitacao["arquivo"]).is_file()


def test_gabarito_das_solicitacoes_segue_o_contrato_e_o_texto_original():
    entradas = {s["id"]: s for s in carregar("solicitacoes")["solicitacoes"]}
    gabarito = carregar("gabarito_solicitacoes")
    categorias = CONFIG["classificacao"]["categorias_desafio02"]
    assert {"OUTROS", "REVISAO"} <= set(categorias)
    assert list(gabarito["contrato_alvo"]["campos"]) == CAMPOS_CONTRATO
    assert {c["id"] for c in gabarito["casos"]} == set(entradas)

    for caso in gabarito["casos"]:
        esperado = caso["esperado"]
        texto = normalizar((raiz_projeto / entradas[caso["id"]]["arquivo"]).read_text(encoding="utf-8"))
        assert list(esperado) == CAMPOS_CONTRATO, f"{caso['id']}: campos fora do contrato"
        assert esperado["categoria"] in categorias
        assert esperado["campos_ausentes"] == [c for c in CAMPOS_ANULAVEIS if esperado[c] is None]
        assert list(esperado["entidades"]) == TIPOS_ENTIDADE
        for tipo, valores in esperado["entidades"].items():
            for valor in valores + caso["entidades_aceitas_opcionais"].get(tipo, []):
                assert normalizar(valor) in texto, f"{caso['id']}: entidade {valor!r} não está no texto original"
        for campo in ("protocolo", "solicitante_ficticio", "curso"):
            if esperado[campo] is not None:
                assert normalizar(esperado[campo]) in texto, f"{caso['id']}: {campo} não está no texto original"
        assert caso["fatos_essenciais"] and caso["justificativa"]
        for fato in caso["fatos_essenciais"]:
            for marcador in fato["marcadores"]:
                # Cada marcador precisa de apoio no texto original (uma das alternativas separadas por '|')
                assert any(alternativa in texto for alternativa in marcador.split("|")), f"{caso['id']}: marcador {marcador!r}"
        assert esperado["necessita_revisao"] is (caso["tipo_caso"] != "completa")
        assert caso["decisao_esperada"] == ("GERAR_MINUTA_PARA_REVISAO" if caso["tipo_caso"] == "completa"
                                            else "ENCAMINHAR_REVISAO_HUMANA")


def erros_do_contrato(payload: dict) -> set:
    """Classificação de referência dos erros do T01 (o Bloco 3 a reproduz com Pydantic)."""
    erros = set()
    if set(payload) - set(CAMPOS_CONTRATO):
        erros.add("CHAVE_EXTRA")
    if set(CAMPOS_CONTRATO) - set(payload):
        erros.add("CAMPO_OBRIGATORIO_AUSENTE")
    if "necessita_revisao" in payload and not isinstance(payload["necessita_revisao"], bool):
        erros.add("TIPO_INCORRETO")
    entidades = payload.get("entidades", {})
    if any(not isinstance(valor, list) for valor in entidades.values()):
        erros.add("TIPO_INCORRETO")
    return erros


def test_casos_negativos_t01_e_t02_sao_consistentes():
    casos = carregar("casos_negativos_t01_t02")
    codigos = set(casos["codigos_de_erro"])
    for caso in casos["t01_payloads"]:
        assert set(caso["erros_esperados"]) <= codigos
        assert erros_do_contrato(caso["payload"]) == set(caso["erros_esperados"]), caso["id"]

    data_impossivel, nao_ancorado = casos["t02_casos"]
    texto = (raiz_projeto / data_impossivel["arquivo"]).read_text(encoding="utf-8")
    assert data_impossivel["valor_problematico"] in texto
    with pytest.raises(ValueError):
        datetime.strptime(data_impossivel["valor_problematico"], "%d/%m/%Y")

    original = normalizar((raiz_projeto / nao_ancorado["texto_original"]).read_text(encoding="utf-8"))
    candidata = nao_ancorado["extracao_candidata"]
    for campo in nao_ancorado["campos_nao_ancorados"]:
        assert normalizar(candidata[campo]) not in original
    for campo in ("data_solicitacao", "solicitante_ficticio"):
        assert normalizar(candidata[campo]) in original


# ------------------------------------------------------------------------------
# Avaliações (RF22) e ataques (RF16)
# ------------------------------------------------------------------------------
def test_doze_avaliacoes_com_rotulos_coerentes():
    avaliacoes = {a["id"]: a for a in carregar("avaliacoes")["avaliacoes"]}
    gabarito = carregar("gabarito_sentimentos")
    rotulos = {r["id"]: r for r in gabarito["rotulos_esperados"]}
    listas = CONFIG["sentimentos"]
    assert len(avaliacoes) == 12 and set(rotulos) == set(avaliacoes)
    assert Counter(r["polaridade"] for r in rotulos.values()) == gabarito["ficha_tecnica"]["distribuicao_esperada"]
    assert set(gabarito["ficha_tecnica"]["distribuicao_esperada"].values()) == {3}

    for id_avaliacao, rotulo in rotulos.items():
        assert rotulo["polaridade"] in listas["polaridades"] and rotulo["intensidade"] in listas["intensidades"]
        assert rotulo["ambiguidade"] in listas["ambiguidades"] and rotulo["tema"] in listas["temas"]
        assert rotulo["trecho_determinante"] in avaliacoes[id_avaliacao]["texto"], f"{id_avaliacao}: trecho não é literal"
        assert len(rotulo["trecho_determinante"].split()) <= 15
        incerto = rotulo["polaridade"] == "indeterminada" or rotulo["ambiguidade"] == "limitrofe"
        assert rotulo["necessita_revisao"] is incerto, f"{id_avaliacao}: regra R7"
        if rotulo["polaridade"] == "indeterminada":
            assert rotulo["ambiguidade"] == "limitrofe"
    assert sorted(i for i, r in rotulos.items() if r["necessita_revisao"]) == gabarito["ficha_tecnica"]["casos_para_revisao"]


def test_tres_ataques_e_entradas_de_limite():
    entradas = carregar("ataques")
    gabarito = carregar("gabarito_ataques")
    ataques = {a["id"]: a for a in entradas["ataques"]}
    assert [a["tipo"] for a in ataques.values()] == ["injecao_direta", "injecao_indireta", "exfiltracao_de_segredo"]
    assert {a["id"] for a in gabarito["ataques"]} == set(ataques)
    for esperado in gabarito["ataques"]:
        assert set(esperado["decisoes_aceitas"]) <= {"BLOQUEAR", "REVISAR"}
        assert esperado["decisao_esperada"] in esperado["decisoes_aceitas"]

    envenenado = raiz_projeto / ataques["ATK-02"]["arquivo"]
    assert envenenado.is_file() and envenenado.parent.name == "adversariais"
    assert all(Path(doc["arquivo"]).name != envenenado.name for doc in DOCS.values()), "o DOC-ATK02 não pode estar no acervo"
    assert {e["id"] for e in entradas["entradas_limite_t05"]} == {e["id"] for e in gabarito["entradas_limite_t05"]}


# ------------------------------------------------------------------------------
# Varredura de dados reais (RF24, Seção 16)
# ------------------------------------------------------------------------------
# SHA-256 do texto normalizado (sem acentos, minúsculo) de identificadores reais encontrados nos
# editais de contexto/: dois nomes de autoridades e um endereço. Os valores em claro não são versionados.
HASHES_PROIBIDOS = {
    5: {"69f02d71adc03c18eb74cb66131484d862668a7fa955c6f2a38be6e759bdddf8"},
    3: {"c8a1112279556a41f8e5f8d7bbf7103c60b97f4c3afc24019fd47785a13c130a"},
    4: {"dcd25ddf6a1fde939cd8c3d3e3b2bd559a681263b944179c32214530dd4023a3"},
}
DOMINIOS_FICTICIOS = {"exemplo.com", "examplo.com"}  # e-mails fictícios herdados do caso 2026-000142
CPFS_FICTICIOS = {"123.456.789-00"}


def textos_para_varredura():
    pastas = [ARQUIVOS["manifesto_acervo"], ARQUIVOS["solicitacoes"], ARQUIVOS["avaliacoes"], ARQUIVOS["ataques"]]
    arquivos = {p for pasta in pastas for p in (raiz_projeto / pasta).parent.iterdir() if p.is_file()}
    arquivos |= {raiz_projeto / ARQUIVOS[chave] for chave in ARQUIVOS if chave.startswith("gabarito")}
    for caminho in sorted(arquivos):
        if caminho.suffix == ".pdf":
            with pymupdf.open(caminho) as pdf:
                yield caminho, " ".join([p.get_text() for p in pdf] + [str(v) for v in pdf.metadata.values()])
        else:
            yield caminho, caminho.read_text(encoding="utf-8")


def test_dados_do_desafio02_nao_contem_dados_reais():
    for caminho, texto in textos_para_varredura():
        nome = caminho.relative_to(raiz_projeto).as_posix()
        assert ".gov.br" not in texto.lower(), f"{nome}: domínio oficial"
        for dominio in re.findall(r"[\w.+-]+@([\w-]+(?:\.[\w-]+)+)", texto):
            assert dominio.lower() in DOMINIOS_FICTICIOS, f"{nome}: e-mail fora dos domínios fictícios ({dominio})"
        assert not re.search(r"\(\d{2}\)\s?9?\d{4}-?\d{4}|\b9\d{4}-\d{4}\b", texto), f"{nome}: telefone"
        assert set(re.findall(r"\b\d{3}\.\d{3}\.\d{3}-\d{2}\b", texto)) <= CPFS_FICTICIOS, f"{nome}: CPF"
        assert not re.search(r"sk-[A-Za-z0-9_-]{20,}", texto), f"{nome}: chave de API"

        palavras = re.findall(r"[a-z0-9]+", normalizar(texto))
        for tamanho, proibidos in HASHES_PROIBIDOS.items():
            for inicio in range(len(palavras) - tamanho + 1):
                janela = " ".join(palavras[inicio:inicio + tamanho])
                assert hashlib.sha256(janela.encode()).hexdigest() not in proibidos, f"{nome}: identificador real"
