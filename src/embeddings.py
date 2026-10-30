#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
==============================================================================
EMBEDDINGS E ÍNDICE VETORIAL PERSISTENTE (RF17, RF18, RF24)
==============================================================================
- Embeddings gerados no próprio código com text-embedding-3-small (1536
  dimensões) pelo LLMClient: mesmo timeout, repetição única e teto de chamadas
  da execução. A OpenAIEmbeddingFunction do Chroma não é usada (o padrão dela
  ainda é o ada-002, Aula 11 §4.2) e nenhuma coleção tem função de embedding
  própria: um vetor de modelo diferente nunca entra no índice por engano.
- ChromaDB 1.5.9 persistente (indice/chroma), coleções em distância de
  cosseno; similaridade = 1 - distância. Filtro com mais de um campo usa $and.
- Manifesto (indice/manifesto_indice.json) com modelo, dimensão, chunking,
  versão do índice e hash de cada documento:
  * reinício reutiliza o índice sem recalcular embeddings;
  * documento com o mesmo hash não é reenviado; hash diferente remove os
    trechos antigos antes de inserir os novos; IDs determinísticos tornam o
    upsert idempotente (reindexar não duplica, T06);
  * modelo, dimensão, chunking ou versão diferentes marcam o índice como
    incompatível e exigem reindexação completa;
  * documento excluído (RF24, T14) não volta numa reindexação automática.
A similaridade mede proximidade de sentido entre a pergunta e o trecho, não
veracidade nem vigência (Seção 16 do enunciado).
==============================================================================
"""

import json
import math
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from src.ingestion import estimar_tokens, gerar_trechos, sha256_arquivo
from src.llm_client import LLMClient, LLMResponse

RAIZ_PROJETO = Path(__file__).resolve().parent.parent
EXPLICACAO_SIMILARIDADE = (
    "Similaridade de cosseno entre o vetor da pergunta e o do trecho (1 - distância de cosseno do Chroma): perto de 1, "
    "sentidos próximos; perto de 0, sem relação. Mede proximidade de sentido, não veracidade nem vigência do trecho."
)


class ErroEmbeddings(RuntimeError):
    def __init__(self, codigo: str, mensagem: str):
        super().__init__(f"{codigo}: {mensagem}")
        self.codigo = codigo


class EmbeddingsOpenAI:
    """Gera vetores pelo adaptador da OpenAI, em lotes, conferindo limite de tokens por texto e dimensão."""

    def __init__(self, llm: LLMClient, modelo: str, dimensao: int, limite_tokens_por_texto: int = 8192,
                 tamanho_lote: int = 128, audit: Any = None):
        self.llm, self.modelo, self.dimensao = llm, modelo, dimensao
        self.limite_tokens_por_texto, self.tamanho_lote, self.audit = limite_tokens_por_texto, tamanho_lote, audit
        self.chamadas: List[Dict[str, Any]] = []

    def embedar(self, textos: List[str], etapa: str = "embeddings") -> List[List[float]]:
        for texto in textos:
            # Estimativa conservadora (3 caracteres por token) antes de enviar: texto longo demais é recusado aqui
            if math.ceil(len(texto) / 3) > self.limite_tokens_por_texto:
                raise ValueError(f"Trecho com cerca de {math.ceil(len(texto) / 3)} tokens excede o limite de "
                                 f"{self.limite_tokens_por_texto} do modelo de embedding; divida o texto antes de indexar.")
        vetores: List[List[float]] = []
        for inicio in range(0, len(textos), self.tamanho_lote):
            lote = textos[inicio:inicio + self.tamanho_lote]
            resultado, resposta = self.llm.chamar_servico(
                "embeddings", lambda c, lote=lote: c.embeddings.create(model=self.modelo, input=lote), self.modelo)
            self._registrar(etapa, resposta, len(lote))
            if resultado is None:
                raise ErroEmbeddings(resposta.codigo_erro or "FALHA_EMBEDDINGS", resposta.erro or "falha sem mensagem")
            ordenados = [item.embedding for item in sorted(resultado.data, key=lambda item: item.index)]
            if any(len(v) != self.dimensao for v in ordenados):
                raise ErroEmbeddings("DIMENSAO_INESPERADA", f"o modelo devolveu vetores fora da dimensão {self.dimensao}")
            vetores.extend(ordenados)
        return vetores

    def _registrar(self, etapa: str, resposta: LLMResponse, quantidade: int):
        self.chamadas.append({"etapa": etapa, "textos": quantidade, "sucesso": resposta.sucesso,
                              "codigo_erro": resposta.codigo_erro, "tokens": resposta.tokens_prompt,
                              "custo_estimado_usd": resposta.custo_estimado_usd, "latencia_ms": round(resposta.latencia_ms, 1)})
        if self.audit is not None:
            self.audit.registrar_execucao(caso_id="RF17_INDICE", etapa=etapa, modalidade="acervo",
                                          arquivo_origem="dados/acervo/manifesto_acervo.json", resposta=resposta,
                                          resumo_saida=f"{quantidade} texto(s) vetorizado(s)")


class IndiceVetorial:
    """Coleções Chroma persistentes com manifesto de compatibilidade, reuso e exclusão auditada."""

    def __init__(self, config: Dict[str, Any], embedder: Any, diretorio_base: Optional[Path] = None, audit: Any = None):
        import chromadb
        from chromadb.config import Settings

        self.cfg = config.get("indice", {})
        self.embedder = embedder
        self.audit = audit
        self.diretorio_base = Path(diretorio_base or RAIZ_PROJETO / self.cfg.get("diretorio_base", "indice"))
        self.diretorio_base.mkdir(parents=True, exist_ok=True)
        self.caminho_manifesto = self.diretorio_base / "manifesto_indice.json"
        self.versao_indice = self.cfg.get("versao_indice", "1.0.0")
        self.cliente = chromadb.PersistentClient(path=str(self.diretorio_base / "chroma"),
                                                 settings=Settings(anonymized_telemetry=False))
        self.manifesto = self._ler_manifesto()

    # --------------------------------------------------------------------------
    # Manifesto e compatibilidade
    # --------------------------------------------------------------------------
    def _ler_manifesto(self) -> Dict[str, Any]:
        if self.caminho_manifesto.exists():
            return json.loads(self.caminho_manifesto.read_text(encoding="utf-8"))
        return {"versao_manifesto": "1.0", "colecoes": {}}

    def _gravar_manifesto(self):
        self.caminho_manifesto.write_text(json.dumps(self.manifesto, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    def assinatura(self, chunking: Dict[str, Any]) -> Dict[str, Any]:
        """O que precisa ser igual para os vetores da coleção serem comparáveis com uma consulta nova."""
        return {"modelo_embedding": self.embedder.modelo, "dimensao": self.embedder.dimensao, "distancia": "cosine",
                "versao_indice": self.versao_indice, "chunking": {"unidade": "caracteres", **chunking}}

    def situacao(self, nome: str, chunking: Dict[str, Any]) -> Tuple[str, str]:
        """AUSENTE, COMPATIVEL, INCOMPATIVEL (modelo, dimensão, chunking ou versão mudaram) ou INCONSISTENTE."""
        registro = self.manifesto["colecoes"].get(nome)
        if registro is None:
            return "AUSENTE", "Coleção ainda não indexada."
        diferencas = [chave for chave, valor in self.assinatura(chunking).items() if registro["assinatura"].get(chave) != valor]
        if diferencas:
            return "INCOMPATIVEL", f"Mudou {', '.join(diferencas)}: é preciso reindexar a coleção inteira."
        esperado = sum(d["trechos"] for d in registro["documentos"].values())
        atual = self._colecao(nome).count()
        if atual != esperado:
            return "INCONSISTENTE", f"A coleção tem {atual} vetores e o manifesto registra {esperado}."
        return "COMPATIVEL", f"{atual} vetores de {len(registro['documentos'])} documento(s)."

    def _colecao(self, nome: str):
        colecao = self.cliente.get_or_create_collection(name=nome, embedding_function=None,
                                                        configuration={"hnsw": {"space": "cosine"}})
        espaco = (colecao.configuration or {}).get("hnsw", {}).get("space")
        if espaco != "cosine":
            raise RuntimeError(f"A coleção {nome} usa distância '{espaco}', não cosseno: reindexe a coleção.")
        return colecao

    def nomes_colecoes(self) -> List[str]:
        return [c if isinstance(c, str) else c.name for c in self.cliente.list_collections()]

    def _apagar_colecao(self, nome: str):
        if nome in self.nomes_colecoes():
            self.cliente.delete_collection(nome)
        self.manifesto["colecoes"].pop(nome, None)

    # --------------------------------------------------------------------------
    # Indexação (T06)
    # --------------------------------------------------------------------------
    def indexar(self, nome: str, documentos: List[Dict[str, Any]], chunking: Dict[str, Any],
                reconstruir: bool = False, reincluir_excluidos: bool = False) -> Dict[str, Any]:
        """
        Indexa os documentos na coleção. `chunking` = {"rotulo", "tamanho", "sobreposicao"}. Documentos já indexados
        com o mesmo hash são reutilizados sem nova chamada de embedding.
        """
        situacao, motivo = self.situacao(nome, chunking)
        # Exclusão é decisão de governança, não propriedade dos vetores: sobrevive à reconstrução da coleção (RF24)
        exclusoes = (self.manifesto["colecoes"].get(nome) or {}).get("exclusoes", [])
        if reconstruir or situacao in ("INCOMPATIVEL", "INCONSISTENTE"):
            self._apagar_colecao(nome)
        agora = datetime.now().isoformat(timespec="seconds")
        registro = self.manifesto["colecoes"].setdefault(nome, {
            "assinatura": self.assinatura(chunking), "criada_em": agora, "documentos": {}, "exclusoes": exclusoes})
        colecao = self._colecao(nome)
        chamadas_antes = len(self.embedder.chamadas) if hasattr(self.embedder, "chamadas") else 0
        excluidos = {e["doc_id"] for e in registro["exclusoes"] if not e.get("reincluido_em")}
        relatorio = {"colecao": nome, "situacao_inicial": situacao, "motivo": motivo, "reutilizados": [], "indexados": [],
                     "ignorados_por_exclusao": [], "removidos_por_mudanca": 0}

        for doc in documentos:
            doc_id, caminho = doc["doc_id"], Path(doc["arquivo"])
            caminho = caminho if caminho.is_absolute() else RAIZ_PROJETO / caminho
            if doc_id in excluidos and not reincluir_excluidos:
                relatorio["ignorados_por_exclusao"].append(doc_id)
                continue
            hash_atual = sha256_arquivo(caminho)
            anterior = registro["documentos"].get(doc_id)
            if anterior and anterior["hash_sha256"] == hash_atual:
                relatorio["reutilizados"].append(doc_id)
                continue
            # Versão anterior do documento (ou vetores sem registro no manifesto) sai antes da nova entrar
            antigos = colecao.get(where={"doc_id": doc_id}, include=[])["ids"]
            if antigos:
                colecao.delete(ids=antigos)
                relatorio["removidos_por_mudanca"] += len(antigos)
            trechos, _ = gerar_trechos(doc, caminho, chunking["tamanho"], chunking["sobreposicao"], chunking["rotulo"])
            vetores = self.embedder.embedar([t.texto for t in trechos], etapa=f"indexacao_{nome}")
            colecao.upsert(ids=[t.chunk_id for t in trechos], embeddings=vetores, documents=[t.texto for t in trechos],
                           metadatas=[t.metadados for t in trechos])
            registro["documentos"][doc_id] = {"hash_sha256": hash_atual, "trechos": len(trechos),
                                              "arquivo": doc.get("arquivo_registrado", doc["arquivo"]), "indexado_em": agora}
            if doc_id in excluidos:
                for exclusao in registro["exclusoes"]:
                    if exclusao["doc_id"] == doc_id and not exclusao.get("reincluido_em"):
                        exclusao["reincluido_em"] = agora
            relatorio["indexados"].append(doc_id)

        registro["atualizada_em"] = agora
        self._gravar_manifesto()
        relatorio.update({
            "vetores_na_colecao": colecao.count(),
            "vetores_no_manifesto": sum(d["trechos"] for d in registro["documentos"].values()),
            "chamadas_de_embedding": (len(self.embedder.chamadas) - chamadas_antes) if hasattr(self.embedder, "chamadas") else None,
            "assinatura": registro["assinatura"],
        })
        return relatorio

    # --------------------------------------------------------------------------
    # Busca
    # --------------------------------------------------------------------------
    def buscar(self, nome: str, pergunta: Optional[str] = None, top_k: int = 4, vetor: Optional[List[float]] = None,
               filtros: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """Top-k por similaridade de cosseno. `filtros` com mais de um campo vira um $and (Chroma 1.5)."""
        if vetor is None:
            vetor = self.embedder.embedar([pergunta], etapa="consulta")[0]
        where = None
        if filtros:
            condicoes = [{campo: valor} for campo, valor in filtros.items()]
            where = condicoes[0] if len(condicoes) == 1 else {"$and": condicoes}
        resultado = self._ler(lambda: self._colecao(nome).query(query_embeddings=[vetor], n_results=top_k, where=where,
                                                                include=["documents", "metadatas", "distances"]))
        return [{
            "posicao": posicao, **_como_trecho(chunk_id, documento, meta),
            "distancia_cosseno": round(distancia, 4), "similaridade_cosseno": round(1 - distancia, 4),
        } for posicao, (chunk_id, documento, meta, distancia) in enumerate(zip(
            resultado["ids"][0], resultado["documents"][0], resultado["metadatas"][0], resultado["distances"][0]), start=1)]

    def trechos_da_secao(self, nome: str, doc_id: str, secao: str) -> List[Dict[str, Any]]:
        """Todos os trechos de uma seção na ordem do documento, para trazer os vizinhos de um trecho recuperado (RF19)."""
        resultado = self._ler(lambda: self._colecao(nome).get(where={"$and": [{"doc_id": doc_id}, {"secao": secao}]},
                                                              include=["documents", "metadatas"]))
        trechos = [_como_trecho(chunk_id, documento, meta) for chunk_id, documento, meta in
                   zip(resultado["ids"], resultado["documents"], resultado["metadatas"])]
        return sorted(trechos, key=lambda t: t["numero"])

    @staticmethod
    def _ler(operacao: Callable[[], Any]) -> Any:
        """
        Leitura do Chroma com no máximo uma nova tentativa em falha interna (mesma política do RF16 para a API). No
        Windows, o arquivo HNSW recém-gravado pode estar momentaneamente ilegível ("Nothing found on disk"); uma falha
        que persiste sobe para quem chamou.
        """
        from chromadb.errors import InternalError
        try:
            return operacao()
        except InternalError:
            time.sleep(0.5)
            return operacao()

    # --------------------------------------------------------------------------
    # Exclusão (RF24, T14)
    # --------------------------------------------------------------------------
    def excluir_documento(self, doc_id: str, motivo: str, arquivo_origem: str = "") -> Dict[str, Any]:
        """
        Remove os vetores do documento de todas as coleções do índice, retira-o do manifesto e registra a exclusão.
        O documento não volta numa reindexação automática; só com reincluir_excluidos=True.
        """
        agora = datetime.now().isoformat(timespec="seconds")
        removidos: Dict[str, int] = {}
        for nome in self.nomes_colecoes():
            alvo = self.cliente.get_collection(nome)
            ids = alvo.get(where={"doc_id": doc_id}, include=[])["ids"]
            if ids:
                alvo.delete(ids=ids)
            removidos[nome] = len(ids)
            registro = self.manifesto["colecoes"].get(nome)
            if registro is not None:
                registro["documentos"].pop(doc_id, None)
                registro["exclusoes"].append({"doc_id": doc_id, "em": agora, "vetores_removidos": len(ids), "motivo": motivo})
        self._gravar_manifesto()
        restantes = sum(len(self.cliente.get_collection(nome).get(where={"doc_id": doc_id}, include=[])["ids"])
                        for nome in self.nomes_colecoes())
        relatorio = {"doc_id": doc_id, "motivo": motivo, "excluido_em": agora, "vetores_removidos_por_colecao": removidos,
                     "vetores_restantes": restantes}
        if self.audit is not None:
            self.audit.registrar_execucao(
                caso_id="RF24_EXCLUSAO", etapa="exclusao_documento", modalidade="acervo",
                arquivo_origem=arquivo_origem or "indice/manifesto_indice.json",
                resumo_saida=f"doc_id={doc_id}; vetores_removidos={sum(removidos.values())}; restantes={restantes}",
                observacao=motivo)
        return relatorio


def _como_trecho(chunk_id: str, documento: str, meta: Dict[str, Any]) -> Dict[str, Any]:
    """Trecho com os metadados de rastreio (RF17) e de vigência; `numero` é a ordem do trecho no documento."""
    numero = re.search(r"::t(\d+)$", chunk_id)
    return {
        "chunk_id": chunk_id, "numero": int(numero.group(1)) if numero else 0, "doc_id": meta.get("doc_id"),
        "titulo": meta.get("titulo"), "versao": meta.get("versao"), "pagina": meta.get("pagina"),
        "secao": meta.get("secao"), "vigencia": meta.get("vigencia"), "retifica": meta.get("retifica"),
        "retificado_por": [d for d in (meta.get("retificado_por") or "").split(",") if d], "texto": documento,
    }


# ------------------------------------------------------------------------------
# Execução pela linha de comando: indexar, buscar, experimento RF18 e exclusão T14
# ------------------------------------------------------------------------------
def _carregar(config: Dict[str, Any], chave: str) -> Dict[str, Any]:
    return json.loads((RAIZ_PROJETO / config["desafio02"][chave]).read_text(encoding="utf-8"))


def _salvar(relativo: str, dados: Any, markdown: Optional[str] = None):
    destino = RAIZ_PROJETO / relativo
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(json.dumps(dados, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
    if markdown is not None:
        destino.with_suffix(".md").write_text(markdown, encoding="utf-8")


def diagnosticar_indice(config: Dict[str, Any]) -> Tuple[str, str]:
    """Situação do índice principal sem chamada de rede (--check-env e interface): compara manifesto, coleção e config."""
    from types import SimpleNamespace

    chunking = chunking_principal(config)
    if chunking is None:
        return "SEM_CONFIGURACAO", "chunking.configuracao_principal não definida (execute o experimento-chunking)."
    base = RAIZ_PROJETO / config.get("indice", {}).get("diretorio_base", "indice")
    if not (base / "manifesto_indice.json").exists():
        return "AUSENTE", "Índice ainda não criado (python -m src.main --modo indexar)."
    openai_cfg = config["llm"]["openai"]
    assinatura = SimpleNamespace(modelo=openai_cfg.get("modelo_embedding"), dimensao=int(openai_cfg.get("dimensao_embedding", 1536)),
                                 chamadas=[])
    indice = IndiceVetorial(config, assinatura, diretorio_base=base)
    return indice.situacao(config["indice"].get("colecao_principal", "acervo_principal"), chunking)


def chunking_principal(config: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    cfg = config["chunking"]
    rotulo = cfg.get("configuracao_principal")
    return {"rotulo": rotulo, **cfg["configuracoes"][rotulo]} if rotulo else None


def documentos_do_indice_principal(config: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Acervo principal e o DOC-99 (informativo temporário usado na demonstração de exclusão)."""
    return [d for d in _carregar(config, "manifesto_acervo")["documentos"] if d["uso"] in ("acervo_principal", "teste_exclusao_T14")]


def preparar_indice(config: Dict[str, Any]) -> Tuple[Optional[IndiceVetorial], str]:
    """Índice com embeddings da OpenAI sob o teto de chamadas da execução; (None, motivo) se indisponível."""
    from src.audit import AuditManager
    from src.llm_client import OrcamentoExecucao

    # O índice foi vetorizado com o modelo da OpenAI: a consulta usa o mesmo modelo, qualquer que seja o provedor de geração
    llm = LLMClient(provedor="openai")
    llm.orcamento = OrcamentoExecucao.do_config(config)
    if not llm.disponivel:
        return None, f"Embeddings do índice exigem a chave da OpenAI: {llm.motivo_indisponibilidade}"
    audit = AuditManager()
    cfg_indice = config.get("indice", {})
    embedder = EmbeddingsOpenAI(llm, llm.adaptador.modelo_embedding,
                                int(config["llm"]["openai"].get("dimensao_embedding", 1536)),
                                int(cfg_indice.get("limite_tokens_por_texto", 8192)),
                                int(cfg_indice.get("tamanho_lote_embeddings", 128)), audit)
    return IndiceVetorial(config, embedder, audit=audit), ""


def _custo(chamadas: List[Dict[str, Any]]) -> Tuple[int, float]:
    return sum(c["tokens"] or 0 for c in chamadas), sum(c["custo_estimado_usd"] or 0.0 for c in chamadas)


def executar_indexacao(config: Dict[str, Any]) -> bool:
    """--modo indexar: cria ou atualiza o índice principal. Rodar duas vezes demonstra o reuso sem duplicação (T06)."""
    print("=" * 75)
    print("  INDEXAÇÃO DO ACERVO NO ÍNDICE VETORIAL PERSISTENTE (RF17, T06)")
    print("=" * 75)
    chunking = chunking_principal(config)
    if chunking is None:
        print("[ERRO] Nenhuma configuração de chunking escolhida em config.json (chunking.configuracao_principal).")
        print("       Execute antes: python -m src.main --modo experimento-chunking")
        return False
    indice, motivo = preparar_indice(config)
    if indice is None:
        print(f"[ERRO] {motivo}")
        return False
    nome = config["indice"].get("colecao_principal", "acervo_principal")
    relatorio = indice.indexar(nome, documentos_do_indice_principal(config), chunking)
    tokens, custo = _custo(indice.embedder.chamadas)
    relatorio.update({"executado_em": datetime.now().isoformat(timespec="seconds"), "tokens_embedding": tokens,
                      "custo_estimado_usd": custo})
    assinatura = relatorio["assinatura"]
    print(f"• Coleção: {nome} | modelo {assinatura['modelo_embedding']} ({assinatura['dimensao']} dimensões) | "
          f"chunking {chunking['rotulo']} ({chunking['tamanho']}/{chunking['sobreposicao']} caracteres) | cosseno")
    print(f"• Situação ao abrir: {relatorio['situacao_inicial']} - {relatorio['motivo']}")
    print(f"• Reutilizados sem novo embedding: {len(relatorio['reutilizados'])} {relatorio['reutilizados'] or ''}")
    print(f"• Indexados agora: {len(relatorio['indexados'])} {relatorio['indexados'] or ''}")
    if relatorio["ignorados_por_exclusao"]:
        print(f"• Fora do índice por exclusão registrada (RF24): {relatorio['ignorados_por_exclusao']}")
    print(f"• Vetores na coleção: {relatorio['vetores_na_colecao']} | no manifesto: {relatorio['vetores_no_manifesto']} | "
          f"removidos por mudança de versão: {relatorio['removidos_por_mudanca']}")
    print(f"• Chamadas de embedding: {relatorio['chamadas_de_embedding']} | tokens: {tokens} | custo: US$ {custo:.6f}")
    # Histórico de execuções: duas linhas seguidas com reuso e o mesmo total de vetores evidenciam o T06
    historico = RAIZ_PROJETO / "resultados" / "indice" / "indexacoes.jsonl"
    historico.parent.mkdir(parents=True, exist_ok=True)
    with open(historico, "a", encoding="utf-8") as arquivo:
        arquivo.write(json.dumps({k: v for k, v in relatorio.items() if k != "assinatura"}, ensure_ascii=False) + "\n")
    print("• Registro: resultados/indice/indexacoes.jsonl")
    print("=" * 75)
    return relatorio["vetores_na_colecao"] == relatorio["vetores_no_manifesto"]


def executar_busca(config: Dict[str, Any], consulta: str, top_k: Optional[int] = None) -> bool:
    """--modo buscar: busca exploratória no índice principal, com a similaridade de cada trecho."""
    indice, motivo = preparar_indice(config)
    if indice is None:
        print(f"[ERRO] {motivo}")
        return False
    nome = config["indice"].get("colecao_principal", "acervo_principal")
    chunking = chunking_principal(config)
    situacao, detalhe = indice.situacao(nome, chunking) if chunking else ("AUSENTE", "sem configuração de chunking")
    if situacao != "COMPATIVEL":
        print(f"[ÍNDICE {situacao}] {detalhe} Execute: python -m src.main --modo indexar")
        return False
    resultados = indice.buscar(nome, consulta, top_k or int(config["chunking"].get("top_k", 4)))
    print(f"Consulta: {consulta}\n{EXPLICACAO_SIMILARIDADE}\n")
    for r in resultados:
        local = f"p. {r['pagina']}" if r["pagina"] else "sem paginação"
        print(f"[{r['posicao']}] similaridade {r['similaridade_cosseno']:.4f} (distância {r['distancia_cosseno']:.4f}) | "
              f"{r['doc_id']} v{r['versao']} | {local} | {r['secao']} | {r['chunk_id']}")
        print("    " + " ".join(r["texto"].split("\n", 1)[-1].split())[:240])
    return True


def _acertou(recuperado: Dict[str, Any], referencias: List[Dict[str, Any]]) -> bool:
    from src.conferencia import normalizar
    return any(recuperado["doc_id"] == ref["doc_id"] and normalizar(ref["trecho_gabarito"]) in normalizar(recuperado["texto"])
               for ref in referencias)


def comparar_configuracoes(config: Dict[str, Any], indice: IndiceVetorial) -> Dict[str, Any]:
    """
    Experimento do RF18 (T07): as mesmas perguntas, o mesmo embedding e o mesmo top-k nas configurações de chunking.
    Acerto = perguntas respondíveis com ao menos um trecho de referência no top-k / 5.
    """
    from src.ingestion import clausulas_preservadas

    gabarito = _carregar(config, "gabarito_rag")
    perguntas = gabarito["perguntas"]
    documentos = [d for d in _carregar(config, "manifesto_acervo")["documentos"] if d["uso"] == "acervo_principal"]
    top_k = int(config["chunking"].get("top_k", 4))
    # Um único vetor por pergunta, reaproveitado nas duas configurações: o embedding da consulta é idêntico
    vetores = indice.embedder.embedar([p["pergunta"] for p in perguntas], etapa="experimento_chunking_perguntas")
    configuracoes = {}
    for rotulo, parametros in config["chunking"]["configuracoes"].items():
        chunking = {"rotulo": rotulo, **parametros}
        nome = f"experimento_chunking_{rotulo}"
        indexacao = indice.indexar(nome, documentos, chunking)
        inteiras = total_clausulas = 0
        tamanhos: List[int] = []
        for doc in documentos:
            trechos, segmentos = gerar_trechos(doc, RAIZ_PROJETO / doc["arquivo"], chunking["tamanho"], chunking["sobreposicao"], rotulo)
            preservadas, total = clausulas_preservadas(segmentos, trechos)
            inteiras, total_clausulas = inteiras + preservadas, total_clausulas + total
            tamanhos += [len(t.conteudo) for t in trechos]
        resultados = []
        for pergunta, vetor in zip(perguntas, vetores):
            recuperados = indice.buscar(nome, vetor=vetor, top_k=top_k)
            item = {"id": pergunta["id"], "tipo": pergunta["tipo"],
                    "similaridade_top1": recuperados[0]["similaridade_cosseno"] if recuperados else None,
                    "recuperados": [{k: r[k] for k in ("posicao", "chunk_id", "doc_id", "pagina", "secao", "similaridade_cosseno")}
                                    for r in recuperados],
                    "tokens_contexto_estimados": sum(estimar_tokens(r["texto"]) for r in recuperados)}
            if pergunta["tipo"] == "respondivel":
                posicoes = [r["posicao"] for r in recuperados if _acertou(r, pergunta["trechos_referencia"])]
                essenciais = [ref for ref in pergunta["trechos_referencia"] if ref["essencial"]]
                item.update({"acerto": bool(posicoes), "posicao_primeiro_acerto": posicoes[0] if posicoes else None,
                             "essenciais_recuperados": sum(any(_acertou(r, [ref]) for r in recuperados) for ref in essenciais),
                             "essenciais_total": len(essenciais)})
            resultados.append(item)
        respondiveis = [r for r in resultados if r["tipo"] == "respondivel"]
        sem_resposta = [r for r in resultados if r["tipo"] == "sem_resposta"]
        configuracoes[rotulo] = {
            "parametros": {"unidade": "caracteres", **parametros},
            "trechos": len(tamanhos), "tamanho_medio_caracteres": round(sum(tamanhos) / len(tamanhos), 1),
            "maior_trecho_caracteres": max(tamanhos),
            "acerto_recuperacao": {"numerador": sum(r["acerto"] for r in respondiveis), "denominador": len(respondiveis)},
            "mrr": round(sum(1 / r["posicao_primeiro_acerto"] for r in respondiveis if r["posicao_primeiro_acerto"]) / len(respondiveis), 4),
            "referencias_essenciais_recuperadas": {"numerador": sum(r["essenciais_recuperados"] for r in respondiveis),
                                                   "denominador": sum(r["essenciais_total"] for r in respondiveis)},
            "clausulas_inteiras": {"numerador": inteiras, "denominador": total_clausulas},
            "tokens_contexto_medio_estimado": round(sum(r["tokens_contexto_estimados"] for r in respondiveis) / len(respondiveis), 1),
            "similaridade_top1_media_respondiveis": round(sum(r["similaridade_top1"] for r in respondiveis) / len(respondiveis), 4),
            "similaridade_top1_media_sem_resposta": round(sum(r["similaridade_top1"] for r in sem_resposta) / len(sem_resposta), 4) if sem_resposta else None,
            "falhas": [{"id": r["id"], "recuperados": r["recuperados"]} for r in respondiveis if not r["acerto"]],
            "indexacao": {k: indexacao[k] for k in ("situacao_inicial", "reutilizados", "indexados", "vetores_na_colecao", "chamadas_de_embedding")},
            "perguntas": resultados,
        }

    def chave(rotulo: str):
        c = configuracoes[rotulo]
        return (c["acerto_recuperacao"]["numerador"], c["referencias_essenciais_recuperadas"]["numerador"], c["mrr"],
                c["clausulas_inteiras"]["numerador"] / max(c["clausulas_inteiras"]["denominador"], 1),
                -c["tokens_contexto_medio_estimado"])
    escolhida = max(configuracoes, key=chave)
    criterio = ("1) maior acerto de recuperação; 2) mais referências essenciais no top-k; 3) maior MRR; "
                "4) mais cláusulas inteiras; 5) menor contexto enviado ao modelo (custo)")
    return {"gerado_em": datetime.now().isoformat(timespec="seconds"), "modelo_embedding": indice.embedder.modelo,
            "top_k": top_k, "perguntas_respondiveis": 5, "criterio_de_escolha": criterio,
            "configuracao_recomendada": escolhida, "configuracoes": configuracoes}


def relatorio_chunking_md(resultado: Dict[str, Any]) -> str:
    rotulos = list(resultado["configuracoes"])
    c = resultado["configuracoes"]
    linhas = ["# Comparação de chunking e recuperação (RF18, T07)", "",
              f"- Gerado em: {resultado['gerado_em']} | Embedding: {resultado['modelo_embedding']} | top-k: {resultado['top_k']} | "
              "mesmo vetor de consulta nas duas configurações",
              "- Unidade: caracteres do conteúdo do trecho (o cabeçalho contextual não entra na conta); trechos não cruzam "
              "páginas nem seções; corte preferencial em fim de linha ou de frase.", "",
              "| Indicador | " + " | ".join(f"Config. {r}" for r in rotulos) + " |", "|---|" + "---|" * len(rotulos)]
    linhas.append("| Tamanho / sobreposição | " + " | ".join(f"{c[r]['parametros']['tamanho']} / {c[r]['parametros']['sobreposicao']}" for r in rotulos) + " |")
    linhas.append("| Trechos (tamanho médio) | " + " | ".join(f"{c[r]['trechos']} ({c[r]['tamanho_medio_caracteres']})" for r in rotulos) + " |")
    for nome, chave in [("Acerto de recuperação", "acerto_recuperacao"), ("Referências essenciais no top-k", "referencias_essenciais_recuperadas"),
                        ("Cláusulas inteiras", "clausulas_inteiras")]:
        linhas.append(f"| {nome} | " + " | ".join(f"{c[r][chave]['numerador']}/{c[r][chave]['denominador']}" for r in rotulos) + " |")
    linhas.append("| MRR | " + " | ".join(str(c[r]["mrr"]) for r in rotulos) + " |")
    linhas.append("| Contexto médio no top-k (tokens, estimativa) | " + " | ".join(str(c[r]["tokens_contexto_medio_estimado"]) for r in rotulos) + " |")
    linhas.append("| Similaridade top-1 média: respondíveis / sem resposta | " + " | ".join(
        f"{c[r]['similaridade_top1_media_respondiveis']} / {c[r]['similaridade_top1_media_sem_resposta']}" for r in rotulos) + " |")
    linhas += ["", "## Resultado por pergunta", "",
               "| Pergunta | Tipo | " + " | ".join(f"Config. {r}: posição do acerto (sim. top-1)" for r in rotulos) + " |",
               "|---|---|" + "---|" * len(rotulos)]
    for indice_pergunta, pergunta in enumerate(c[rotulos[0]]["perguntas"]):
        celulas = []
        for r in rotulos:
            item = c[r]["perguntas"][indice_pergunta]
            posicao = item.get("posicao_primeiro_acerto") if item["tipo"] == "respondivel" else None
            marca = (f"{posicao}" if posicao else "não recuperou") if item["tipo"] == "respondivel" else "-"
            celulas.append(f"{marca} ({item['similaridade_top1']})")
        linhas.append(f"| {pergunta['id']} | {pergunta['tipo']} | " + " | ".join(celulas) + " |")
    linhas += ["", "## Falhas de recuperação", "",
               "Uma pergunta conta como acerto com qualquer trecho de referência no top-k (critério do RF18); a referência "
               "essencial é a que sustenta a resposta correta (ex.: a redação retificada, e não a original).", ""]
    for r in rotulos:
        falhas = c[r]["falhas"]
        parciais = [p for p in c[r]["perguntas"] if p["tipo"] == "respondivel" and p["essenciais_recuperados"] < p["essenciais_total"]]
        linhas.append(f"- Config. {r}, sem nenhuma referência no top-k: " + ("nenhuma" if not falhas else "; ".join(
            f"{f['id']} (top-k: {', '.join(x['chunk_id'] for x in f['recuperados'])})" for f in falhas)))
        linhas.append(f"- Config. {r}, referência essencial fora do top-k: " + ("nenhuma" if not parciais else "; ".join(
            f"{p['id']} ({p['essenciais_recuperados']}/{p['essenciais_total']}; top-k: "
            f"{', '.join(f'{x['doc_id']} {x['secao']}' for x in p['recuperados'])})" for p in parciais)))
    linhas += ["", "## Escolha", "", f"- Critério: {resultado['criterio_de_escolha']}.",
               f"- Recomendada pelo experimento: **configuração {resultado['configuracao_recomendada']}**. A escolha final e "
               "sua justificativa ficam registradas em config.json (chunking.configuracao_principal).",
               "- A similaridade top-1 das perguntas sem resposta serve de referência para calibrar o limiar de abstenção "
               "do RAG (Bloco 6); similaridade alta não significa que o trecho responde à pergunta.", ""]
    return "\n".join(linhas)


def executar_experimento_chunking(config: Dict[str, Any]) -> bool:
    print("=" * 75)
    print("  EXPERIMENTO DE CHUNKING E RECUPERAÇÃO (RF18, T07)")
    print("=" * 75)
    indice, motivo = preparar_indice(config)
    if indice is None:
        print(f"[ERRO] {motivo}")
        return False
    resultado = comparar_configuracoes(config, indice)
    tokens, custo = _custo(indice.embedder.chamadas)
    resultado.update({"tokens_embedding": tokens, "custo_estimado_usd": custo})
    _salvar("resultados/metricas/comparacao_chunking_rf18.json", resultado, relatorio_chunking_md(resultado))
    for rotulo, c in resultado["configuracoes"].items():
        print(f"  Config. {rotulo} ({c['parametros']['tamanho']}/{c['parametros']['sobreposicao']}): "
              f"acerto {c['acerto_recuperacao']['numerador']}/{c['acerto_recuperacao']['denominador']} | "
              f"essenciais {c['referencias_essenciais_recuperadas']['numerador']}/{c['referencias_essenciais_recuperadas']['denominador']} | "
              f"MRR {c['mrr']} | {c['trechos']} trechos | contexto ~{c['tokens_contexto_medio_estimado']} tokens")
    print(f"  Recomendada: {resultado['configuracao_recomendada']} | embeddings: {tokens} tokens, US$ {custo:.6f}")
    print("  Relatório: resultados/metricas/comparacao_chunking_rf18.md")
    print("=" * 75)
    return True


def demonstrar_exclusao(config: Dict[str, Any]) -> bool:
    """
    --modo demonstrar-exclusao (RF24, T14): reinclui o DOC-99 se preciso, mostra que a pergunta de controle o recupera,
    exclui documento e vetores e mostra que ele deixa de ser recuperado e não volta numa reindexação automática.
    """
    print("=" * 75)
    print("  EXCLUSÃO DE DOCUMENTO E DERIVADOS (RF24, T14)")
    print("=" * 75)
    chunking = chunking_principal(config)
    indice, motivo = (None, "Nenhuma configuração de chunking escolhida.") if chunking is None else preparar_indice(config)
    if indice is None:
        print(f"[ERRO] {motivo}")
        return False
    nome = config["indice"].get("colecao_principal", "acervo_principal")
    controle = _carregar(config, "gabarito_rag")["pergunta_controle_exclusao_t14"]
    doc_id = controle["documento_excluido"]
    documento = next(d for d in documentos_do_indice_principal(config) if d["doc_id"] == doc_id)
    top_k = int(config["chunking"].get("top_k", 4))

    indice.indexar(nome, [documento], chunking, reincluir_excluidos=True)
    vetor = indice.embedder.embedar([controle["pergunta"]], etapa="consulta_t14")[0]
    referencias = controle["antes_da_exclusao"]["trechos_referencia"]
    antes = indice.buscar(nome, vetor=vetor, top_k=top_k)
    exclusao = indice.excluir_documento(doc_id, "Demonstração do RF24/T14: informativo temporário retirado do acervo",
                                        documento["arquivo"])
    depois = indice.buscar(nome, vetor=vetor, top_k=top_k)
    reindexacao = indice.indexar(nome, documentos_do_indice_principal(config), chunking)

    resultado = {
        "pergunta": controle["pergunta"], "doc_id": doc_id,
        "antes": {"recuperou_o_documento": any(_acertou(r, referencias) for r in antes),
                  "top_k": [{k: r[k] for k in ("posicao", "chunk_id", "doc_id", "similaridade_cosseno")} for r in antes]},
        "exclusao": exclusao,
        "depois": {"trechos_do_documento_no_top_k": sum(r["doc_id"] == doc_id for r in depois),
                   "top_k": [{k: r[k] for k in ("posicao", "chunk_id", "doc_id", "similaridade_cosseno")} for r in depois]},
        "reindexacao_automatica": {"ignorados_por_exclusao": reindexacao["ignorados_por_exclusao"],
                                   "vetores_na_colecao": reindexacao["vetores_na_colecao"]},
        "politica_de_retencao": [
            "Vetores e entrada do manifesto do documento excluído são apagados de todas as coleções do índice.",
            "A exclusão fica registrada no manifesto e na auditoria (data, motivo, vetores removidos).",
            "O documento não volta ao índice numa reindexação automática; só por reinclusão explícita.",
            "Resultados derivados que citem o documento (respostas e minutas do RAG) devem ser apagados ou marcados no "
            "mesmo ato; até o Bloco 5 não há resultado derivado gravado por documento.",
            "O arquivo-fonte do acervo fictício continua versionado porque é recriado pelo gerador; num acervo real, o "
            "arquivo de origem seria removido no mesmo ato, conforme a tabela de temporalidade do órgão.",
        ],
    }
    resultado["confere"] = (resultado["antes"]["recuperou_o_documento"] and resultado["depois"]["trechos_do_documento_no_top_k"] == 0
                            and exclusao["vetores_restantes"] == 0 and doc_id in reindexacao["ignorados_por_exclusao"])
    linhas = ["# Exclusão de documento e derivados (RF24, T14)", "", f"- Pergunta de controle: {controle['pergunta']}",
              f"- Antes da exclusão: o {doc_id} {'foi' if resultado['antes']['recuperou_o_documento'] else 'NÃO foi'} recuperado no top-{top_k}.",
              f"- Exclusão: {sum(exclusao['vetores_removidos_por_colecao'].values())} vetor(es) removido(s) "
              f"({', '.join(f'{c}: {n}' for c, n in exclusao['vetores_removidos_por_colecao'].items())}); restantes: {exclusao['vetores_restantes']}.",
              f"- Depois da exclusão: {resultado['depois']['trechos_do_documento_no_top_k']} trecho(s) do {doc_id} no top-{top_k}.",
              f"- Reindexação automática do acervo: {doc_id} ignorado por exclusão registrada: "
              f"{'sim' if doc_id in reindexacao['ignorados_por_exclusao'] else 'NÃO'}.",
              f"- Situação: {'confere com o T14' if resultado['confere'] else 'NÃO confere'}", "", "## Política de retenção e exclusão", ""]
    linhas += [f"- {item}" for item in resultado["politica_de_retencao"]]
    _salvar("resultados/indice/exclusao_t14.json", resultado, "\n".join(linhas) + "\n")
    for linha in linhas[2:8]:
        print(" " + linha)
    print("  Relatório: resultados/indice/exclusao_t14.md")
    print("=" * 75)
    return resultado["confere"]
