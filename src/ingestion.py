#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
==============================================================================
INGESTÃO DO ACERVO: LEITURA POR PÁGINA, SEÇÕES E TRECHOS (RF17, RF18)
==============================================================================
- ler_documento: PDF textual com pymupdf, página a página (página = índice + 1),
  e TXT como texto sem paginação. PDF sem texto extraível gera erro claro:
  documento digitalizado exige OCR antes da indexação (Aula 13 §3.2).
- reconstruir_linhas: junta as quebras de linha da diagramação do PDF,
  preservando itens numerados, alíneas, artigos e títulos.
- segmentar: divide cada página em seções ("4. DA MATRÍCULA...", "Art. 1º")
  sem cruzar a fronteira de página; a seção continua na página seguinte.
- dividir_em_trechos: tamanho e sobreposição em CARACTERES do conteúdo,
  terminando de preferência em fim de linha ou de frase na segunda metade da
  janela (Aula 13 §3.3). O cabeçalho contextual com documento, título,
  versão, seção e página é prefixado ao texto indexado (Aula 12 §3.2: a busca
  só enxerga o texto do trecho) e não entra na conta do tamanho.
- clausulas_preservadas: proporção de cláusulas que ficaram inteiras em algum
  trecho, a medida mais direta do dano de um corte (Aula 12 §3.2).
==============================================================================
"""

import hashlib
import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from src.conferencia import normalizar

PREAMBULO = "Preâmbulo"
INICIO_DE_ITEM = re.compile(r"^(\d+(\.\d+)*\.\s|[a-z]\)\s|Art\.\s*\d+|Onde se lê|Leia-se|Cuiabá,|Identificador:|DOCUMENTO FICTÍCIO)")
TITULO_DE_SECAO = re.compile(r"^\d{1,2}\.\s+[^a-z]+$")   # "4. DA MATRÍCULA E DOS DOCUMENTOS EXIGIDOS"
ARTIGO = re.compile(r"^(Art\.\s*\d+º)")
CARACTERES_POR_TOKEN = 4  # estimativa para português; os tokens reais da indexação vêm da API


@dataclass
class PaginaLida:
    numero: Optional[int]  # None em documento sem paginação (TXT)
    texto: str


@dataclass
class Segmento:
    pagina: Optional[int]
    secao: str
    linhas: List[str]

    @property
    def texto(self) -> str:
        return "\n".join(self.linhas)


@dataclass
class Trecho:
    chunk_id: str
    texto: str        # cabeçalho contextual + conteúdo: é o que vai para o embedding
    conteudo: str     # só o texto do documento
    metadados: Dict[str, Any] = field(default_factory=dict)


def sha256_arquivo(caminho: Path) -> str:
    return hashlib.sha256(Path(caminho).read_bytes()).hexdigest()


def estimar_tokens(texto: str) -> int:
    return math.ceil(len(texto) / CARACTERES_POR_TOKEN)


def ler_documento(caminho: Path) -> List[PaginaLida]:
    caminho = Path(caminho)
    if caminho.suffix.lower() == ".txt":
        return [PaginaLida(None, caminho.read_text(encoding="utf-8"))]
    if caminho.suffix.lower() != ".pdf":
        raise ValueError(f"Formato '{caminho.suffix}' não suportado na indexação: use .txt ou .pdf textual.")
    import pymupdf
    with pymupdf.open(caminho) as pdf:
        paginas = [PaginaLida(indice + 1, pagina.get_text()) for indice, pagina in enumerate(pdf)]
    if not any(p.texto.strip() for p in paginas):
        raise ValueError(f"{caminho.name}: nenhum texto extraído. O arquivo provavelmente é digitalizado e precisa "
                         "passar por OCR antes de ser indexado.")
    return [p for p in paginas if p.texto.strip()]


def _maiuscula(linha: str) -> bool:
    letras = [c for c in linha if c.isalpha()]
    return len(letras) >= 4 and sum(c.isupper() for c in letras) / len(letras) >= 0.8


def reconstruir_linhas(texto: str) -> List[str]:
    """Junta a linha à anterior quando ela é só continuação da diagramação (sem marcador de item nem pontuação final)."""
    linhas: List[str] = []
    for bruta in texto.splitlines():
        linha = " ".join(bruta.split())
        if not linha:
            if linhas and linhas[-1]:
                linhas.append("")  # parágrafo em branco impede a junção
            continue
        anterior = linhas[-1] if linhas else ""
        continuacao = (anterior and not INICIO_DE_ITEM.match(linha)
                       and not anterior.endswith((".", ";", ":", "!", "?"))
                       and _maiuscula(anterior) == _maiuscula(linha))
        if continuacao:
            linhas[-1] = f"{anterior} {linha}"
        else:
            linhas.append(linha)
    return [linha for linha in linhas if linha]


def secao_da_linha(linha: str) -> Optional[str]:
    if TITULO_DE_SECAO.match(linha) and _maiuscula(linha):
        return linha
    artigo = ARTIGO.match(linha)
    return artigo.group(1) if artigo else None


def segmentar(paginas: List[PaginaLida]) -> List[Segmento]:
    """Seções por página: nenhum segmento atravessa duas páginas, e a seção corrente segue na página seguinte."""
    segmentos: List[Segmento] = []
    secao = PREAMBULO
    for pagina in paginas:
        atual: Optional[Segmento] = None
        for linha in reconstruir_linhas(pagina.texto):
            nova = secao_da_linha(linha)
            if nova or atual is None:
                secao = nova or secao
                atual = Segmento(pagina.numero, secao, [])
                segmentos.append(atual)
            atual.linhas.append(linha)
    return segmentos


def dividir_em_trechos(texto: str, tamanho: int, sobreposicao: int) -> List[Tuple[int, str]]:
    """(posição, conteúdo) de cada trecho com até `tamanho` caracteres; o seguinte começa `sobreposicao` antes do fim."""
    if sobreposicao >= tamanho:
        raise ValueError("A sobreposição precisa ser menor que o tamanho do trecho.")
    if len(texto) <= tamanho:
        return [(0, texto.strip())] if texto.strip() else []
    trechos, inicio = [], 0
    while inicio < len(texto):
        fim = min(inicio + tamanho, len(texto))
        if fim < len(texto):
            metade = inicio + tamanho // 2
            corte = max(texto.rfind("\n", metade, fim), texto.rfind(". ", metade, fim), texto.rfind("; ", metade, fim))
            if corte != -1:
                fim = corte + 1
        conteudo = texto[inicio:fim].strip()
        if conteudo:
            trechos.append((inicio, conteudo))
        if fim >= len(texto):
            break
        proximo = max(inicio + 1, fim - sobreposicao)
        # A sobreposição não começa no meio de uma palavra
        while 0 < proximo < fim and not texto[proximo - 1].isspace():
            proximo += 1
        inicio = proximo if proximo < fim else fim
    return trechos


def cabecalho_contextual(doc: Dict[str, Any], secao: str, pagina: Optional[int]) -> str:
    partes = [doc["doc_id"], doc["titulo"], f"versão {doc['versao']}", secao] + ([f"p. {pagina}"] if pagina else [])
    return "[" + " | ".join(partes) + "]"


def gerar_trechos(doc: Dict[str, Any], caminho: Path, tamanho: int, sobreposicao: int,
                  rotulo: str) -> Tuple[List[Trecho], List[Segmento]]:
    """Trechos de um documento com metadados rastreáveis (RF17) e os segmentos usados para medir as cláusulas."""
    segmentos = segmentar(ler_documento(caminho))
    hash_documento = sha256_arquivo(caminho)
    trechos: List[Trecho] = []
    for segmento in segmentos:
        for posicao, conteudo in dividir_em_trechos(segmento.texto, tamanho, sobreposicao):
            local = f"p{segmento.pagina}" if segmento.pagina else "txt"
            chunk_id = f"{doc['doc_id']}::{rotulo}::{local}::t{len(trechos):03d}"
            metadados = {
                "doc_id": doc["doc_id"], "titulo": doc["titulo"], "versao": doc["versao"], "hash_sha256": hash_documento,
                "secao": segmento.secao, "chunk_id": chunk_id, "vigencia": doc.get("vigencia") or "",
                "formato": doc.get("formato", Path(caminho).suffix.lstrip(".")), "tema": doc.get("tema") or "",
                "uso": doc.get("uso") or "", "configuracao_chunking": rotulo, "caracteres": len(conteudo), "posicao": posicao,
            }
            if segmento.pagina:
                metadados["pagina"] = segmento.pagina
            if doc.get("retifica"):
                metadados["retifica"] = doc["retifica"]
            if doc.get("retificado_por"):
                metadados["retificado_por"] = ",".join(doc["retificado_por"])
            texto = f"{cabecalho_contextual(doc, segmento.secao, segmento.pagina)}\n{conteudo}"
            trechos.append(Trecho(chunk_id, texto, conteudo, metadados))
    return trechos, segmentos


def clausulas(segmentos: List[Segmento], minimo_caracteres: int = 40) -> List[str]:
    """Cláusulas do documento: linhas reconstruídas com conteúdo (títulos curtos ficam de fora)."""
    return [linha for segmento in segmentos for linha in segmento.linhas
            if len(linha) >= minimo_caracteres and not secao_da_linha(linha)]


def clausulas_preservadas(segmentos: List[Segmento], trechos: List[Trecho]) -> Tuple[int, int]:
    """(cláusulas inteiras em algum trecho, total de cláusulas)."""
    conteudos = [normalizar(t.conteudo) for t in trechos]
    todas = clausulas(segmentos)
    inteiras = sum(any(normalizar(c) in conteudo for conteudo in conteudos) for c in todas)
    return inteiras, len(todas)
