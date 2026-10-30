#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
==============================================================================
GERAÇÃO FUNDAMENTADA COM RAG (RF19) — Aulas 12 e 13
==============================================================================
Pergunta -> recuperação -> três guardas -> minuta com citações verificáveis.
- Recuperação: top-k no índice principal (cosseno). Cada trecho leva os
  vizinhos da mesma seção e, havendo retificação declarada, entram trechos do
  documento relacionado, buscados com o mesmo vetor (sem novo embedding).
- Guarda 1 (limiar): top-1 abaixo do limiar calibrado recusa sem chamar o
  modelo. Margem estreita entre o 1º e o último trecho gera alerta.
- Guarda 2 (contrato): fatos do cidadão e orientações do acervo em blocos
  separados, regras explícitas e Structured Outputs com status, afirmações e
  citações por número de trecho; a recusa é a FRASE_ABSTENCAO_PADRAO, fixa e
  reconhecível por comparação de string.
- Guarda 3 (ancoragem): número, data ou prazo sem lastro nos trechos, no
  quadro de vigência ou na mensagem converte a saída na recusa padronizada;
  citação a trecho inexistente também.
- Camadas 2 e 3 dos guardrails (src/guardrails.py): trecho com instrução ao
  sistema é neutralizado; dado pessoal é mascarado e segredo descarta a saída.
- Documento, versão, página e seção de cada citação são escritos pelo código
  a partir dos metadados do índice, nunca pelo modelo.
- Vigência e conflito: prevalece só o que está escrito (retificação do DOC-02
  sobre o DOC-01). Fontes divergentes sem regra escrita resultam em
  CONFLITO_DE_FONTES, com os dois trechos expostos.
A entrada chega aqui depois da camada 1 dos guardrails (no fluxo integrado e
no --modo responder). Toda resposta, inclusive a recusa, segue como minuta
PENDENTE_REVISAO_HUMANA, com envio automático bloqueado e trechos visíveis.
==============================================================================
"""

import json
import re
import statistics
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from chromadb.errors import ChromaError
from pydantic import ValidationError

from src.conferencia import NAO_LOCALIZADO, normalizar
from src.embeddings import (
    EXPLICACAO_SIMILARIDADE, ErroEmbeddings, IndiceVetorial, _carregar, _salvar, chunking_principal, preparar_indice,
)
from src.guardrails import BLOQUEAR, Guardrails, delimitar_trechos_do_acervo, remover_citacoes
from src.ingestion import PREAMBULO
from src.llm_client import LLMClient, LLMResponse
from src.nlp import _telemetria, numeros_sem_lastro
from src.prompts import (
    FRASE_ABSTENCAO_PADRAO, PROMPT_RAG_SISTEMA, PROMPT_RAG_USUARIO, VERSOES_PROMPTS, delimitar_fatos_da_solicitacao,
)
from src.schemas import VERSAO_ESQUEMA_RAG, SaidaGeracaoRAG

RAIZ_PROJETO = Path(__file__).resolve().parent.parent
FUNDAMENTADA, SEM_EVIDENCIA, CONFLITO = "FUNDAMENTADA", "SEM_EVIDENCIA_SUFICIENTE", "CONFLITO_DE_FONTES"
STATUS_REVISAO = "PENDENTE_REVISAO_HUMANA"
CONFERENCIA_E_APROVACAO = "CONFERENCIA_E_APROVACAO_HUMANA"
REVISAO_PRIORITARIA = "REVISAO_HUMANA_PRIORITARIA"
MARCA_CITACAO = re.compile(r"\[(\d+(?:\s*[,;]\s*\d+)*)\]")
SEQUENCIA_DE_CITACOES = re.compile(r"\[\d+\](?:\s*\[\d+\])*")
GRADE_LIMIAR = [round(0.20 + 0.05 * i, 2) for i in range(11)]
REFERENCIAS_LIMIAR = {0.25: "Aula 13", 0.5: "Aula 12"}


# ------------------------------------------------------------------------------
# Citações
# ------------------------------------------------------------------------------
def normalizar_marcas(texto: str) -> str:
    """[1, 3] e [1;3] viram [1][3], para que cada número de trecho seja conferido e formatado sozinho."""
    return MARCA_CITACAO.sub(lambda m: "".join(f"[{n}]" for n in re.split(r"\s*[,;]\s*", m.group(1))), texto)


def numeros_de_trecho(texto: str) -> List[int]:
    return [int(n) for n in re.findall(r"\[(\d+)\]", texto)]


def rotulo_citacao(trecho: Dict[str, Any]) -> str:
    """(DOC-02, v1.0, p. 1, Art. 1º) nos PDFs; (DOC-03, v1.0, seção 2) nos TXT, que não têm página."""
    partes = [trecho["doc_id"], f"v{trecho['versao']}"]
    if trecho.get("pagina"):
        partes.append(f"p. {trecho['pagina']}")
    secao = trecho.get("secao") or ""
    numero = re.match(r"^(\d+)\.\s", secao)
    if numero:
        partes.append(f"seção {numero.group(1)}")
    elif secao == PREAMBULO:
        partes.append("preâmbulo")
    elif secao:
        partes.append(secao)
    return ", ".join(partes)


def conteudo_do_trecho(trecho: Dict[str, Any]) -> str:
    """Texto do trecho sem o cabeçalho contextual que a ingestão prefixa."""
    texto = trecho["texto"]
    return texto.split("\n", 1)[-1] if texto.startswith("[") else texto


def formatar_citacoes(texto: str, fontes: List[Dict[str, Any]]) -> str:
    """Troca [n] pelo rótulo do trecho n; citações seguidas viram um parêntese só, sem rótulos repetidos."""
    por_numero = {f["n"]: f["rotulo"] for f in fontes}

    def trocar(marca: re.Match) -> str:
        rotulos = list(dict.fromkeys(por_numero[n] for n in numeros_de_trecho(marca.group(0)) if n in por_numero))
        return f"({'; '.join(rotulos)})" if rotulos else ""

    return SEQUENCIA_DE_CITACOES.sub(trocar, texto)


def alertas_de_vigencia(citados: List[Dict[str, Any]], contexto: List[Dict[str, Any]]) -> List[str]:
    """
    Confere em código a regra 4 do prompt: resposta que cita um documento de um par com retificação declarada sem
    citar o outro vai à revisão prioritária. Não muda o status; o operador confere qual redação foi aplicada.
    """
    docs_citados = {t["doc_id"] for t in citados}
    docs_no_contexto = {t["doc_id"] for t in contexto}
    alertas = []
    for trecho in {t["doc_id"]: t for t in citados}.values():
        for original in [trecho["retifica"]] if trecho.get("retifica") else []:
            if original in docs_no_contexto and original not in docs_citados:
                alertas.append(f"CITACAO_DE_VIGENCIA_INCOMPLETA: a resposta cita o {trecho['doc_id']}, que retifica o "
                               f"{original}, sem citar o trecho do {original} que está no contexto.")
        for retificador in trecho.get("retificado_por", []):
            if retificador not in docs_citados:
                alertas.append(f"VIGENCIA_A_CONFERIR: a resposta cita o {trecho['doc_id']}, que tem itens retificados pelo "
                               f"{retificador}, sem citar o {retificador}; confira se o item usado não foi alterado.")
    return alertas


# ------------------------------------------------------------------------------
# Resultado
# ------------------------------------------------------------------------------
@dataclass
class RespostaRAG:
    """Registro completo de uma resposta: o que foi recuperado, o que cada guarda decidiu e o que segue ao operador."""
    id_caso: str
    pergunta: str
    status: str
    resposta: str
    codigo_motivo: str
    motivo: str
    encaminhamento: str
    fontes: List[Dict[str, Any]]
    afirmacoes: List[Dict[str, Any]]
    divergencias: List[Dict[str, Any]]
    alertas: List[str]
    guardas: Dict[str, Any]
    recuperacao: Dict[str, Any]
    saida_modelo: Optional[Dict[str, Any]]
    provedor: Optional[str]
    modelo: Optional[str]
    prompt: Dict[str, str]
    versao_esquema: str
    versao_indice: str
    colecao: str
    configuracao_chunking: Optional[str]
    chamadas: List[Dict[str, Any]] = field(default_factory=list)
    minuta: str = ""
    id_execucao: Optional[str] = None
    status_revisao: str = STATUS_REVISAO
    envio_automatico_bloqueado: bool = True
    registrado_em: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def montar_minuta(r: RespostaRAG) -> str:
    """Minuta para o operador: resposta, divergências e trechos consultados, inclusive na recusa (Aula 13 §7)."""
    linhas = ["MINUTA PARA REVISÃO HUMANA - envio automático bloqueado", f"Status: {r.status}",
              f"Encaminhamento: {r.encaminhamento}", "", "Resposta proposta:", r.resposta]
    if r.divergencias:
        linhas += ["", "Divergência entre as fontes (sem regra escrita de prevalência):"]
        for d in r.divergencias:
            linhas.append(f"- {d['assunto']}")
            linhas += [f"  ({p['rotulo']}) \"{p['trecho']}\"" for p in d["passagens"]]
    if r.alertas:
        linhas += ["", "Alertas para o operador:"] + [f"- {a}" for a in r.alertas]
    linhas += ["", "Trechos consultados:" if r.fontes else "Trechos consultados: nenhum."]
    for f in r.fontes:
        marca = "citado" if f["citado"] else "não citado"
        linhas.append(f"[{f['n']}] ({f['rotulo']}) {f['titulo'] or NAO_LOCALIZADO} | {marca} | origem: {f['origem']}")
    autoria = f"{r.provedor}/{r.modelo}" if r.modelo else "sem chamada ao modelo"
    linhas += ["", f"Conteúdo gerado com apoio de IA ({autoria}; {r.prompt['id']} v{r.prompt['versao']}). "
                   "Confira cada citação na passagem original antes de aprovar."]
    return "\n".join(linhas)


# ------------------------------------------------------------------------------
# Assistente
# ------------------------------------------------------------------------------
class AssistenteRAG:
    """Responde com fonte ou recusa (Aula 13 §5): recuperação, guardas, citações e registro auditável."""

    def __init__(self, indice: IndiceVetorial, llm: LLMClient, config: Dict[str, Any], guardrails: Optional[Guardrails] = None,
                 audit: Any = None, colecao: Optional[str] = None, modelo: Optional[str] = None,
                 dir_saida: Optional[Path] = None):
        self.cfg = config["rag"]
        self.limiar = self.cfg.get("limiar_similaridade")
        if self.limiar is None:
            raise ValueError("rag.limiar_similaridade não definido em config.json: execute "
                             "python -m src.main --modo calibrar-limiar e registre o valor.")
        self.indice, self.llm, self.audit, self.modelo = indice, llm, audit, modelo
        self.guardrails = guardrails or Guardrails(llm_client=llm)  # camadas 2 e 3 são locais, sem chamada de rede
        self.colecao = colecao or config["indice"].get("colecao_principal", "acervo_principal")
        self.top_k = int(self.cfg.get("top_k") or config["chunking"].get("top_k", 4))
        self.margem_minima = float(self.cfg.get("margem_minima_top1_topk", 0.02))
        self.vizinhos = int(self.cfg.get("vizinhos_por_trecho", 1))
        self.de_vigencia = int(self.cfg.get("trechos_de_vigencia_por_documento", 2))
        self.max_trechos = int(self.cfg.get("max_trechos_contexto", 12))
        chunking = chunking_principal(config)
        self.rotulo_chunking = chunking["rotulo"] if chunking else None
        self.documentos = {d["doc_id"]: d for d in _carregar(config, "manifesto_acervo")["documentos"]}
        self.dir_saida = dir_saida

    # --------------------------------------------------------------------------
    # Recuperação e contexto
    # --------------------------------------------------------------------------
    def montar_contexto(self, recuperados: List[Dict[str, Any]], vetor: List[float]) -> List[Dict[str, Any]]:
        """Top-k, depois os trechos de vigência do documento relacionado, depois os vizinhos; no máximo max_trechos."""
        contexto: Dict[str, Dict[str, Any]] = {}

        def incluir(trecho: Dict[str, Any], origem: str):
            if trecho["chunk_id"] not in contexto and len(contexto) < self.max_trechos:
                contexto[trecho["chunk_id"]] = {**trecho, "origem": origem}

        for trecho in recuperados:
            incluir(trecho, "busca")
        if self.de_vigencia:
            relacionados: List[str] = []
            for trecho in recuperados:
                for doc_id in ([trecho["retifica"]] if trecho.get("retifica") else []) + trecho.get("retificado_por", []):
                    if doc_id not in relacionados:
                        relacionados.append(doc_id)
            for doc_id in relacionados:
                for trecho in self.indice.buscar(self.colecao, top_k=self.de_vigencia, vetor=vetor, filtros={"doc_id": doc_id}):
                    incluir(trecho, "vigencia")
        if self.vizinhos:
            for central in list(contexto.values()):
                for trecho in self.indice.trechos_da_secao(self.colecao, central["doc_id"], central["secao"]):
                    if 0 < abs(trecho["numero"] - central["numero"]) <= self.vizinhos:
                        incluir(trecho, "vizinho")
        ordem: Dict[str, int] = {}
        for trecho in contexto.values():
            ordem.setdefault(trecho["doc_id"], len(ordem))
        return sorted(contexto.values(), key=lambda t: (ordem[t["doc_id"]], t["numero"]))

    def quadro_vigencia(self, contexto: List[Dict[str, Any]]) -> str:
        """Metadados de vigência de cada documento do contexto (manifesto do acervo e metadados do índice)."""
        linhas, vistos = [], set()
        for trecho in contexto:
            doc_id = trecho["doc_id"]
            if doc_id in vistos:
                continue
            vistos.add(doc_id)
            doc = self.documentos.get(doc_id, {})
            partes = [doc_id, trecho.get("titulo") or NAO_LOCALIZADO, f"versão {trecho.get('versao')}",
                      f"publicado em {doc.get('data_publicacao') or NAO_LOCALIZADO}"]
            if doc.get("emissor"):
                partes.append(f"emissor: {doc['emissor']}")
            if trecho.get("retifica"):
                partes.append(f"retifica {trecho['retifica']}")
            if trecho.get("retificado_por"):
                partes.append(f"retificado por {', '.join(trecho['retificado_por'])}")
            partes.append(f"vigência: {trecho.get('vigencia') or doc.get('vigencia') or NAO_LOCALIZADO}")
            partes.append(f"prevalência declarada: {doc.get('regra_de_prevalencia') or 'nenhuma'}")
            linhas.append("- " + " | ".join(partes))
        return "\n".join(linhas)

    def _fontes(self, contexto: List[Dict[str, Any]], citados: Set[int]) -> List[Dict[str, Any]]:
        return [{
            "n": n, "rotulo": rotulo_citacao(t), "citado": n in citados, "origem": t.get("origem", "busca"),
            "chunk_id": t["chunk_id"], "doc_id": t["doc_id"], "titulo": t.get("titulo"), "versao": t.get("versao"),
            "pagina": t.get("pagina"), "secao": t.get("secao"), "similaridade_cosseno": t.get("similaridade_cosseno"),
            "retifica": t.get("retifica"), "retificado_por": t.get("retificado_por", []),
            "neutralizado": bool(t.get("neutralizado")), "trecho": conteudo_do_trecho(t),
        } for n, t in enumerate(contexto, start=1)]

    # --------------------------------------------------------------------------
    # Resposta
    # --------------------------------------------------------------------------
    def responder(self, pergunta: str, id_caso: str = "CONSULTA", vetor: Optional[List[float]] = None,
                  alertas_entrada: Optional[List[str]] = None, arquivo_origem: str = "(consulta)",
                  texto_busca: Optional[str] = None) -> RespostaRAG:
        """
        `pergunta` vai ao modelo como fatos da solicitação; `texto_busca`, se informado, é o que se vetoriza para a
        busca (no atendimento, assunto e pedido do contrato em vez do texto com dados pessoais).
        """
        inicio = time.perf_counter()
        estado = {"id_caso": id_caso, "pergunta": pergunta, "alertas": list(alertas_entrada or []), "guardas": {},
                  "recuperacao": {"top_k": self.top_k, "limiar": self.limiar, "explicacao": EXPLICACAO_SIMILARIDADE},
                  "contexto": [], "resposta_llm": None, "prompt_texto": None, "arquivo_origem": arquivo_origem}

        try:
            if vetor is None:
                vetor = self.indice.embedder.embedar([texto_busca or pergunta], etapa="consulta_rag")[0]
            recuperados = self.indice.buscar(self.colecao, top_k=self.top_k, vetor=vetor)
        except (ErroEmbeddings, RuntimeError, ChromaError) as e:
            return self._recusar(estado, "FALHA_NA_RECUPERACAO", f"A recuperação falhou ({type(e).__name__}: {e}); nada é "
                                 "respondido sem trechos.", inicio)
        if not recuperados:
            return self._recusar(estado, "INDICE_VAZIO", "Nenhum trecho no índice.", inicio)

        top1, topk = recuperados[0]["similaridade_cosseno"], recuperados[-1]["similaridade_cosseno"]
        margem = round(top1 - topk, 4)
        estado["recuperacao"].update({"similaridade_top1": top1, "similaridade_topk": topk, "margem_top1_topk": margem,
                                      "margem_minima": self.margem_minima, "margem_estreita": margem < self.margem_minima,
                                      "ids_top_k": [r["chunk_id"] for r in recuperados]})
        if margem < self.margem_minima:
            estado["alertas"].append(f"MARGEM_ESTREITA: o 1º e o último trecho do top-{self.top_k} têm similaridade "
                                     f"quase igual (margem {margem:.4f} < {self.margem_minima}); confira se a fonte é a certa.")

        # Guarda 1: limiar de similaridade, antes de qualquer chamada ao modelo
        if top1 < self.limiar:
            estado["guardas"]["1_limiar"] = {"decisao": "RECUSA", "detalhe": f"top-1 {top1:.4f} < limiar {self.limiar}"}
            estado["contexto"] = [{**r, "origem": "busca"} for r in recuperados]
            return self._recusar(estado, "LIMIAR_DE_SIMILARIDADE",
                                 f"O trecho mais próximo tem similaridade {top1:.4f}, abaixo do limiar {self.limiar}.", inicio)
        estado["guardas"]["1_limiar"] = {"decisao": "SEGUE", "detalhe": f"top-1 {top1:.4f} >= limiar {self.limiar}"}

        try:
            contexto = self.montar_contexto(recuperados, vetor)
        except (RuntimeError, ChromaError) as e:
            estado["contexto"] = [{**r, "origem": "busca"} for r in recuperados]
            return self._recusar(estado, "FALHA_NA_RECUPERACAO", f"A leitura dos trechos vizinhos ou de vigência falhou "
                                 f"({type(e).__name__}: {e}); nada é respondido com contexto incompleto.", inicio)
        contexto, camada2 = self.guardrails.inspecionar_trechos(contexto)
        estado["contexto"] = contexto
        estado["guardas"]["camada2_conteudo_recuperado"] = {"decisao": camada2.decisao, "detalhe": camada2.detalhe}
        if camada2.motivos:
            estado["alertas"].append(camada2.detalhe)

        # Guarda 2: contrato de saída
        quadro = self.quadro_vigencia(contexto)
        sistema = PROMPT_RAG_SISTEMA.format(recusa=FRASE_ABSTENCAO_PADRAO, max_palavras=self.cfg.get("max_palavras_resposta", 150))
        usuario = PROMPT_RAG_USUARIO.format(fatos_delimitados=delimitar_fatos_da_solicitacao(pergunta), quadro_vigencia=quadro,
                                            trechos_delimitados=delimitar_trechos_do_acervo(contexto))
        estado["prompt_texto"] = sistema + usuario
        resposta_llm = self.llm.gerar(usuario, system_instruction=sistema, schema=SaidaGeracaoRAG, modelo=self.modelo,
                                      reasoning_effort=self.cfg.get("reasoning_effort", "low"),
                                      max_completion_tokens=int(self.cfg.get("max_completion_tokens", 3000)))
        resposta_llm.parametros.update({"versao_esquema": VERSAO_ESQUEMA_RAG, "versao_indice": self.indice.versao_indice,
                                        "colecao": self.colecao, "ids_recuperados": [t["chunk_id"] for t in contexto]})
        estado["resposta_llm"] = resposta_llm
        if not resposta_llm.sucesso:
            estado["guardas"]["2_contrato"] = {"decisao": "RECUSA", "detalhe": f"falha do provedor ({resposta_llm.codigo_erro})"}
            return self._recusar(estado, "FALHA_NA_GERACAO", f"Falha do serviço de geração ({resposta_llm.codigo_erro}): "
                                 f"{resposta_llm.erro}", inicio)
        try:
            saida = SaidaGeracaoRAG.model_validate_json(resposta_llm.conteudo)
        except ValidationError as e:
            estado["guardas"]["2_contrato"] = {"decisao": "RECUSA", "detalhe": f"{e.error_count()} erro(s) de esquema"}
            return self._recusar(estado, "SAIDA_FORA_DO_ESQUEMA", "A saída do modelo não seguiu o contrato.", inicio)
        estado["saida"] = saida
        if saida.alerta:
            estado["alertas"].append(f"ALERTA DO MODELO: {saida.alerta}")

        resposta = normalizar_marcas(saida.resposta)
        recusa = self._conferir_contrato(saida, resposta, contexto, estado)
        if recusa:
            estado["guardas"]["2_contrato"] = {"decisao": "RECUSA", "detalhe": recusa[1]}
            return self._recusar(estado, *recusa, inicio)
        estado["guardas"]["2_contrato"] = {"decisao": "SEGUE", "detalhe": f"status {saida.status} com citações válidas"}

        # Guarda 3: ancoragem numérica e camada 3 dos guardrails (segredo, dados pessoais, citação)
        lastro = "\n".join([t["texto"] for t in contexto] + [quadro, pergunta])
        citados = sorted(set(numeros_de_trecho(resposta)) | {n for a in saida.afirmacoes for n in a.trechos}
                         | {n for d in saida.divergencias for n in d.trechos})
        resposta, camada3 = self.guardrails.filtrar_saida(
            resposta, ids_citados=[contexto[n - 1]["chunk_id"] for n in citados],
            ids_recuperados=[t["chunk_id"] for t in contexto], contexto=lastro)
        textos_extras = [a.texto for a in saida.afirmacoes] + [d.assunto for d in saida.divergencias]
        filtrados_extras = [self.guardrails.filtrar_saida(normalizar_marcas(t)) for t in textos_extras]
        orfaos = numeros_sem_lastro(remover_citacoes(" ".join(textos_extras)), lastro)
        estado["guardas"]["camada3_saida"] = {"decisao": camada3.decisao, "detalhe": camada3.detalhe}
        if camada3.decisao == BLOQUEAR or any(c.decisao == BLOQUEAR for _, c in filtrados_extras):
            estado["guardas"]["3_ancoragem"] = {"decisao": "RECUSA", "detalhe": "segredo na saída"}
            return self._recusar(estado, "SEGREDO_NA_SAIDA", "A saída continha padrão de credencial e foi descartada.", inicio)
        if "NUMERO_SEM_LASTRO" in camada3.motivos or orfaos:
            detalhe = "; ".join(filter(None, [camada3.detalhe if "NUMERO_SEM_LASTRO" in camada3.motivos else "",
                                              f"nas afirmações: {', '.join(orfaos)}" if orfaos else ""]))
            estado["guardas"]["3_ancoragem"] = {"decisao": "RECUSA", "detalhe": detalhe}
            return self._recusar(estado, "NUMERO_SEM_LASTRO", f"Número sem lastro nos trechos recuperados ({detalhe}).", inicio)
        estado["guardas"]["3_ancoragem"] = {"decisao": "SEGUE", "detalhe": "todos os números constam dos trechos ou da mensagem"}
        if "DADO_PESSOAL_MASCARADO" in camada3.motivos:
            estado["alertas"].append("DADO_PESSOAL_MASCARADO: CPF, e-mail ou telefone mascarado na resposta.")

        fontes = self._fontes(contexto, set(citados))
        afirmacoes = []
        for afirmacao, (texto_filtrado, _) in zip(saida.afirmacoes, filtrados_extras):
            passagens = [fontes[n - 1] for n in dict.fromkeys(afirmacao.trechos)]
            fora = numeros_sem_lastro(remover_citacoes(afirmacao.texto), "\n".join([p["trecho"] for p in passagens] + [pergunta]))
            afirmacoes.append({
                "texto": formatar_citacoes(texto_filtrado, fontes), "trechos": list(dict.fromkeys(afirmacao.trechos)),
                "citacoes": [{k: p[k] for k in ("rotulo", "chunk_id", "doc_id", "versao", "pagina", "secao", "trecho")}
                             for p in passagens],
                "numeros_fora_do_trecho_citado": fora,
            })
            if not afirmacao.trechos:
                estado["alertas"].append(f"AFIRMACAO_SEM_CITACAO: \"{afirmacao.texto}\"")
            elif fora:
                estado["alertas"].append(f"NUMERO_FORA_DO_TRECHO_CITADO: {', '.join(fora)} em \"{afirmacao.texto}\" está em outro "
                                         "trecho do contexto, não no citado.")
        estado["alertas"] += alertas_de_vigencia([contexto[n - 1] for n in citados], contexto)
        divergencias = [{"assunto": d.assunto, "trechos": list(dict.fromkeys(d.trechos)),
                         "passagens": [{k: fontes[n - 1][k] for k in ("rotulo", "chunk_id", "doc_id", "trecho")}
                                       for n in dict.fromkeys(d.trechos)]} for d in saida.divergencias]
        if saida.status == CONFLITO:
            motivo = "As fontes divergem e nenhuma regra escrita no acervo indica qual prevalece; o operador decide."
            codigo = "CONFLITO_SEM_REGRA_DE_PREVALENCIA"
        else:
            codigo, motivo = "FUNDAMENTADA", "Resposta sustentada pelos trechos citados; o operador confere e aprova."
        return self._concluir(estado, saida.status, formatar_citacoes(resposta, fontes), codigo, motivo, fontes, afirmacoes,
                              divergencias, inicio)

    def _conferir_contrato(self, saida: SaidaGeracaoRAG, resposta: str, contexto: List[Dict[str, Any]],
                           estado: Dict[str, Any]) -> Optional[Tuple[str, str]]:
        """(código, motivo) da recusa, ou None se a saída cumpre o contrato."""
        if saida.status == SEM_EVIDENCIA or normalizar(FRASE_ABSTENCAO_PADRAO) in normalizar(resposta) \
                or SEM_EVIDENCIA in resposta:
            return "MODELO_DECLAROU_SEM_EVIDENCIA", "O modelo declarou que os trechos não sustentam a resposta."
        todos = numeros_de_trecho(resposta) + [n for a in saida.afirmacoes for n in a.trechos] \
            + [n for d in saida.divergencias for n in d.trechos]
        invalidos = sorted({n for n in todos if not 1 <= n <= len(contexto)})
        if invalidos:
            return "CITACAO_INVALIDA", f"Citação a trecho inexistente: {invalidos} (o contexto tem {len(contexto)} trechos)."
        if not numeros_de_trecho(resposta):
            return "RESPOSTA_SEM_CITACAO", "A resposta não cita nenhum trecho do acervo."
        if saida.status == CONFLITO:
            divergentes = [d for d in saida.divergencias if len(set(d.trechos)) >= 2]
            if not divergentes:
                return "CONFLITO_SEM_TRECHOS_DIVERGENTES", "Conflito declarado sem dois trechos divergentes citados."
            for d in divergentes:
                docs = {contexto[n - 1]["doc_id"] for n in d.trechos}
                relacionados = {contexto[n - 1].get("retifica") for n in d.trechos} | \
                    {r for n in d.trechos for r in contexto[n - 1].get("retificado_por", [])}
                if docs & relacionados:
                    estado["alertas"].append(f"CONFLITO_COM_RETIFICACAO_DECLARADA: {', '.join(sorted(docs))} têm retificação "
                                             "escrita; a divergência pode ser só a redação revogada.")
        return None

    # --------------------------------------------------------------------------
    # Conclusão, registro e auditoria
    # --------------------------------------------------------------------------
    def _recusar(self, estado: Dict[str, Any], codigo: str, motivo: str, inicio: float) -> RespostaRAG:
        fontes = self._fontes(estado["contexto"], set())
        return self._concluir(estado, SEM_EVIDENCIA, FRASE_ABSTENCAO_PADRAO, codigo, motivo, fontes, [], [], inicio)

    def _concluir(self, estado: Dict[str, Any], status: str, resposta: str, codigo: str, motivo: str,
                  fontes: List[Dict[str, Any]], afirmacoes: List[Dict[str, Any]], divergencias: List[Dict[str, Any]],
                  inicio: float) -> RespostaRAG:
        resposta_llm: Optional[LLMResponse] = estado["resposta_llm"]
        saida = estado.get("saida")
        encaminhamento = CONFERENCIA_E_APROVACAO if status == FUNDAMENTADA and not estado["alertas"] else REVISAO_PRIORITARIA
        resultado = RespostaRAG(
            id_caso=estado["id_caso"], pergunta=estado["pergunta"], status=status, resposta=resposta, codigo_motivo=codigo,
            motivo=motivo, encaminhamento=encaminhamento, fontes=fontes, afirmacoes=afirmacoes, divergencias=divergencias,
            alertas=estado["alertas"], guardas=estado["guardas"], recuperacao=estado["recuperacao"],
            saida_modelo=saida.model_dump() if saida is not None else None,
            provedor=resposta_llm.provedor if resposta_llm else None, modelo=resposta_llm.modelo if resposta_llm else None,
            prompt={"id": "PROMPT_RAG", "versao": VERSOES_PROMPTS["PROMPT_RAG"]}, versao_esquema=VERSAO_ESQUEMA_RAG,
            versao_indice=self.indice.versao_indice, colecao=self.colecao, configuracao_chunking=self.rotulo_chunking,
            chamadas=[_telemetria("rag_geracao", resposta_llm)] if resposta_llm else [],
        )
        resultado.recuperacao["duracao_total_ms"] = round((time.perf_counter() - inicio) * 1000, 1)
        resultado.minuta = montar_minuta(resultado)
        self._registrar(resultado, estado)
        return resultado

    def _registrar(self, resultado: RespostaRAG, estado: Dict[str, Any]):
        arquivo_saida = None
        if self.dir_saida is not None:
            destino = Path(self.dir_saida) / f"{resultado.id_caso}.json"
            destino.parent.mkdir(parents=True, exist_ok=True)
            destino.write_text(json.dumps(resultado.to_dict(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            arquivo_saida = destino
        if self.audit is None:
            return
        resumo = (f"status={resultado.status}; motivo={resultado.codigo_motivo}; "
                  f"citados={[f['chunk_id'] for f in resultado.fontes if f['citado']]}")
        parametros = None if estado["resposta_llm"] else {
            "versao_esquema": VERSAO_ESQUEMA_RAG, "versao_indice": self.indice.versao_indice, "colecao": self.colecao,
            "ids_recuperados": [f["chunk_id"] for f in resultado.fontes], "limiar": self.limiar}
        resultado.id_execucao = self.audit.registrar_execucao(
            caso_id=resultado.id_caso, etapa="rag_resposta", modalidade="consulta_rag", arquivo_origem=estado["arquivo_origem"],
            resposta=estado["resposta_llm"], prompt_id="PROMPT_RAG", prompt_versao=VERSOES_PROMPTS["PROMPT_RAG"],
            prompt_texto=estado["prompt_texto"], arquivo_saida=arquivo_saida, resumo_saida=resumo,
            duracao_ms=resultado.recuperacao["duracao_total_ms"], parametros=parametros, observacao=resultado.motivo,
            consulta=resultado.pergunta)
        if arquivo_saida is not None:
            arquivo_saida.write_text(json.dumps(resultado.to_dict(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


# ------------------------------------------------------------------------------
# Calibração do limiar (guarda 1)
# ------------------------------------------------------------------------------
def _tem_resposta(tipo: str) -> bool:
    return tipo in ("respondivel", "contraditoria")


def calibrar_limiar(medicoes: List[Dict[str, Any]], folga: float) -> Dict[str, Any]:
    """
    `medicoes`: [{"id", "tipo", "similaridades": [top-1..top-k]}]. Distribuição do top-1 por grupo, cortes de cada
    limiar da grade e o limiar sugerido pela regra registrada no config.json antes da medição.
    """
    com = [m["similaridades"][0] for m in medicoes if _tem_resposta(m["tipo"])]
    sem = [m["similaridades"][0] for m in medicoes if not _tem_resposta(m["tipo"])]

    def resumo(valores: List[float]) -> Dict[str, Any]:
        return {"n": len(valores), "minimo": min(valores), "mediana": round(statistics.median(valores), 4),
                "maximo": max(valores)} if valores else {"n": 0}

    grade = [{"limiar": g, "corta_com_resposta": sum(v < g for v in com), "corta_sem_resposta": sum(v < g for v in sem),
              "referencia": REFERENCIAS_LIMIAR.get(g)} for g in GRADE_LIMIAR]
    candidatos = [g for g in GRADE_LIMIAR if com and g <= round(min(com) - folga, 4)]
    return {
        "top1_com_resposta": resumo(com), "top1_sem_resposta": resumo(sem),
        "sobreposicao": bool(com and sem and max(sem) >= min(com)),
        "distancia_entre_grupos": round(min(com) - max(sem), 4) if com and sem else None,
        "grade": grade, "folga": folga, "limiar_sugerido": max(candidatos) if candidatos else 0.0,
        "margens": [{"id": m["id"], "tipo": m["tipo"], "margem_top1_topk": round(m["similaridades"][0] - m["similaridades"][-1], 4)}
                    for m in medicoes],
    }


def relatorio_calibracao_md(c: Dict[str, Any]) -> str:
    com, sem = c["top1_com_resposta"], c["top1_sem_resposta"]
    linhas = [
        "# Calibração do limiar de similaridade do RAG (RF19, guarda 1)", "",
        f"- Gerado em: {c['gerado_em']} | índice `{c['colecao']}` (chunking {c['configuracao_chunking']}, top-{c['top_k']}) | "
        f"modelo de embedding `{c['modelo_embedding']}`",
        f"- {EXPLICACAO_SIMILARIDADE}",
        f"- Regra registrada antes da medição: {c['regra']}", "",
        "## Similaridade do 1º trecho por pergunta", "",
        "| Pergunta | Tipo | Top-1 | Top-k | Margem top-1 − top-k | Documento do top-1 |", "|---|---|---:|---:|---:|---|",
    ]
    for m in c["medicoes"]:
        linhas.append(f"| {m['id']} | {m['tipo']} | {m['similaridades'][0]:.4f} | {m['similaridades'][-1]:.4f} | "
                      f"{m['similaridades'][0] - m['similaridades'][-1]:.4f} | {m['docs'][0]} |")
    linhas += [
        "", "## Distribuição", "",
        f"- Com resposta no acervo (respondíveis e contraditória, n={com['n']}): mínimo {com['minimo']:.4f} | "
        f"mediana {com['mediana']:.4f} | máximo {com['maximo']:.4f}",
        f"- Sem resposta no acervo (n={sem['n']}): mínimo {sem['minimo']:.4f} | mediana {sem['mediana']:.4f} | "
        f"máximo {sem['maximo']:.4f}" if sem["n"] else "- Sem resposta no acervo: nenhuma pergunta.",
        f"- Sobreposição entre os grupos: {'sim' if c['sobreposicao'] else 'não'}; distância entre o menor top-1 com resposta "
        f"e o maior sem resposta: {c['distancia_entre_grupos']}", "",
        "| Limiar | Corta perguntas com resposta | Corta perguntas sem resposta | Referência |", "|---:|---:|---:|---|",
    ]
    linhas += [f"| {g['limiar']:.2f} | {g['corta_com_resposta']} | {g['corta_sem_resposta']} | {g['referencia'] or ''} |"
               for g in c["grade"]]
    linhas += [
        "", "## Decisão", "",
        f"- Limiar sugerido pela regra: **{c['limiar_sugerido']:.2f}** (folga {c['folga']} abaixo do menor top-1 com resposta).",
        f"- Limiar em uso (config.json, rag.limiar_similaridade): {c['limiar_configurado']}",
        f"- Com só {len(c['medicoes'])} perguntas, qualquer separação observada vale para este acervo e este conjunto. "
        "A Aula 12 mostrou "
        "distribuições sobrepostas (respondível com 0,509 e sem resposta com 0,695): o limiar é rede grosseira e a "
        "abstenção fina fica com o contrato do prompt (guarda 2) e a ancoragem numérica (guarda 3).",
        f"- Margem mínima entre o 1º e o último trecho do top-k: {c['margem_minima']} (abaixo disso a minuta recebe "
        "alerta de revisão adicional). Perguntas abaixo da margem nesta medição: "
        + (", ".join(m["id"] for m in c["margens"] if m["margem_top1_topk"] < c["margem_minima"]) or "nenhuma") + ".",
    ]
    return "\n".join(linhas) + "\n"


# ------------------------------------------------------------------------------
# Avaliação contra o gabarito (T08, T09, T10)
# ------------------------------------------------------------------------------
def _presente(marcadores: List[str], texto: str) -> bool:
    return all(any(alternativa in texto for alternativa in m.split("|")) for m in marcadores)


def _contem_referencia(fonte: Dict[str, Any], ref: Dict[str, Any]) -> bool:
    return fonte["doc_id"] == ref["doc_id"] and normalizar(ref["trecho_gabarito"]) in normalizar(fonte["trecho"])


def _proporcao(itens: List[bool]) -> Dict[str, int]:
    return {"numerador": sum(itens), "denominador": len(itens)}


def avaliar_resposta(pergunta: Dict[str, Any], r: RespostaRAG) -> Dict[str, Any]:
    """Conferência determinística de uma resposta contra o gabarito; a sustentação fina fica com a equipe (RF23)."""
    tipo = pergunta["tipo"]
    item = {
        "id": pergunta["id"], "tipo": tipo, "status_esperado": pergunta["status_esperado"], "status_obtido": r.status,
        "status_correto": r.status == pergunta["status_esperado"], "codigo_motivo": r.codigo_motivo,
        "similaridade_top1": r.recuperacao.get("similaridade_top1"), "margem_top1_topk": r.recuperacao.get("margem_top1_topk"),
        "trechos_no_contexto": len(r.fontes),
        "trechos_citados": list(dict.fromkeys(f["rotulo"] for f in r.fontes if f["citado"])),
        "alertas": r.alertas, "decisao_humana_esperada": pergunta.get("decisao_humana_esperada"),
        "encaminhada_a_revisao": r.status_revisao == STATUS_REVISAO and r.envio_automatico_bloqueado,
    }
    if not _tem_resposta(tipo):
        item["recusa_padronizada_exata"] = r.resposta == FRASE_ABSTENCAO_PADRAO
        item["sem_chamada_ao_modelo"] = r.modelo is None
        item["confere"] = item["status_correto"] and item["recusa_padronizada_exata"] and item["encaminhada_a_revisao"]
        return item

    citadas = [f for f in r.fontes if f["citado"]]
    texto = normalizar(r.resposta)
    referencias = [{"doc_id": ref["doc_id"], "trecho_gabarito": ref["trecho_gabarito"], "essencial": ref["essencial"],
                    "no_top_k": any(_contem_referencia(f, ref) for f in r.fontes if f["origem"] == "busca"),
                    "no_contexto": any(_contem_referencia(f, ref) for f in r.fontes),
                    "citada": any(_contem_referencia(f, ref) for f in citadas)} for ref in pergunta["trechos_referencia"]]
    afirmacoes = [{"afirmacao": a["afirmacao"], "fonte": a["fonte"], "presente": _presente(a["marcadores"], texto)}
                  for a in pergunta["afirmacoes_essenciais"]]
    exigidas = pergunta.get("fontes_citadas_exigidas", [])
    docs_citados = sorted({f["doc_id"] for f in citadas})
    item.update({
        "referencias": referencias, "afirmacoes_essenciais": afirmacoes, "fontes_exigidas": exigidas,
        "documentos_citados": docs_citados, "fontes_exigidas_citadas": set(exigidas) <= set(docs_citados),
        "afirmacoes_do_modelo": len(r.afirmacoes),
        "afirmacoes_com_citacao": sum(bool(a["trechos"]) for a in r.afirmacoes),
        "afirmacoes_com_numeros_no_trecho_citado": sum(bool(a["trechos"]) and not a["numeros_fora_do_trecho_citado"]
                                                       for a in r.afirmacoes),
    })
    essenciais_citadas = all(ref["citada"] for ref in referencias if ref["essencial"])
    todas_presentes = all(a["presente"] for a in afirmacoes)
    if tipo == "contraditoria":
        divergentes = {p["doc_id"] for d in r.divergencias for p in d["passagens"]}
        item["documentos_nas_divergencias"] = sorted(divergentes)
        item["divergencia_exposta"] = bool(exigidas) and set(exigidas) <= divergentes
        item["confere"] = item["status_correto"] and item["divergencia_exposta"] and todas_presentes and essenciais_citadas
    else:
        item["confere"] = item["status_correto"] and item["fontes_exigidas_citadas"] and todas_presentes and essenciais_citadas
    return item


def agregar(itens: List[Dict[str, Any]]) -> Dict[str, Any]:
    respondiveis = [i for i in itens if i["tipo"] == "respondivel"]
    sem_resposta = [i for i in itens if i["tipo"] == "sem_resposta"]
    contraditorias = [i for i in itens if i["tipo"] == "contraditoria"]
    institucionais = [i for i in itens if _tem_resposta(i["tipo"]) and i["status_obtido"] != SEM_EVIDENCIA]
    return {
        "T08_respondiveis_conferem": _proporcao([i["confere"] for i in respondiveis]),
        "T08_status_fundamentada": _proporcao([i["status_correto"] for i in respondiveis]),
        "T08_afirmacoes_essenciais_presentes": _proporcao([a["presente"] for i in respondiveis for a in i["afirmacoes_essenciais"]]),
        "T08_referencias_essenciais_citadas": _proporcao([r["citada"] for i in respondiveis for r in i["referencias"] if r["essencial"]]),
        "T08_referencias_essenciais_no_contexto": _proporcao([r["no_contexto"] for i in respondiveis for r in i["referencias"]
                                                              if r["essencial"]]),
        "T08_referencias_essenciais_no_top_k": _proporcao([r["no_top_k"] for i in respondiveis for r in i["referencias"]
                                                           if r["essencial"]]),
        "T08_fontes_exigidas_citadas": _proporcao([i["fontes_exigidas_citadas"] for i in respondiveis]),
        "T09_abstencao_correta": _proporcao([i["confere"] for i in sem_resposta]),
        "T10_conflito_tratado": _proporcao([i["confere"] for i in contraditorias]),
        "recusas_indevidas": _proporcao([i["status_obtido"] == SEM_EVIDENCIA for i in respondiveis + contraditorias]),
        "afirmacoes_do_modelo_com_citacao": {"numerador": sum(i["afirmacoes_com_citacao"] for i in institucionais),
                                             "denominador": sum(i["afirmacoes_do_modelo"] for i in institucionais)},
        "afirmacoes_com_numeros_no_trecho_citado": {
            "numerador": sum(i["afirmacoes_com_numeros_no_trecho_citado"] for i in institucionais),
            "denominador": sum(i["afirmacoes_do_modelo"] for i in institucionais)},
        "respostas_convertidas_em_recusa_pela_ancoragem": sum(i["codigo_motivo"] == "NUMERO_SEM_LASTRO" for i in itens),
    }


def relatorio_avaliacao_md(avaliacao: Dict[str, Any]) -> str:
    a = avaliacao["agregados"]

    def fr(chave: str) -> str:
        return f"{a[chave]['numerador']}/{a[chave]['denominador']}"

    linhas = [
        "# Avaliação do RAG fundamentado (RF19: T08, T09, T10)", "",
        f"- Gerado em: {avaliacao['gerado_em']} | provedor `{avaliacao['provedor']}` | modelo `{avaliacao['modelo']}` | "
        f"prompt PROMPT_RAG v{avaliacao['prompt_versao']} | esquema {avaliacao['versao_esquema']}",
        f"- Índice `{avaliacao['colecao']}` v{avaliacao['versao_indice']} (chunking {avaliacao['configuracao_chunking']}, "
        f"top-{avaliacao['top_k']}, vizinhos {avaliacao['vizinhos_por_trecho']}, limiar {avaliacao['limiar']}, "
        f"margem mínima {avaliacao['margem_minima']})",
        f"- Gabarito v{avaliacao['versao_gabarito']} (revisão humana: {avaliacao['revisao_gabarito']}), elaborado antes da execução.",
        f"- Chamadas ao modelo: {avaliacao['chamadas_ao_modelo']} de geração + {avaliacao['chamadas_de_embedding']} de embedding | "
        f"tokens: {avaliacao['tokens_total']} | custo estimado: US$ {avaliacao['custo_total_usd']:.6f}", "",
        "## Resultado", "",
        "| Teste | Medida | Resultado |", "|---|---|---:|",
        f"| T08 | Respondíveis que conferem com o gabarito (status, fontes, afirmações e referências citadas) | {fr('T08_respondiveis_conferem')} |",
        f"| T08 | Status FUNDAMENTADA | {fr('T08_status_fundamentada')} |",
        f"| T08 | Afirmações essenciais presentes (marcadores) | {fr('T08_afirmacoes_essenciais_presentes')} |",
        f"| T08 | Referências essenciais citadas | {fr('T08_referencias_essenciais_citadas')} |",
        f"| T08 | Referências essenciais no contexto enviado ao modelo | {fr('T08_referencias_essenciais_no_contexto')} |",
        f"| T08 | Referências essenciais já no top-k (sem vizinhos nem vigência) | {fr('T08_referencias_essenciais_no_top_k')} |",
        f"| T08 | Fontes exigidas citadas | {fr('T08_fontes_exigidas_citadas')} |",
        f"| T09 | Abstenção correta (recusa padronizada exata e encaminhamento) | {fr('T09_abstencao_correta')} |",
        f"| T10 | Conflito tratado (status, dois trechos expostos, sem escolher prazo) | {fr('T10_conflito_tratado')} |",
        f"| — | Recusas indevidas (pergunta com resposta recusada) | {fr('recusas_indevidas')} |",
        f"| — | Afirmações do modelo com citação | {fr('afirmacoes_do_modelo_com_citacao')} |",
        f"| — | Afirmações citadas e com os números no próprio trecho citado | {fr('afirmacoes_com_numeros_no_trecho_citado')} |",
        f"| — | Respostas convertidas em recusa pela ancoragem numérica | {a['respostas_convertidas_em_recusa_pela_ancoragem']} |",
        "", "## Por pergunta", "",
        "| Pergunta | Tipo | Esperado | Obtido | Motivo | Top-1 | Citados | Confere |", "|---|---|---|---|---|---:|---|---|",
    ]
    for i in avaliacao["itens"]:
        top1 = f"{i['similaridade_top1']:.4f}" if i["similaridade_top1"] is not None else "-"
        linhas.append(f"| {i['id']} | {i['tipo']} | {i['status_esperado']} | {i['status_obtido']} | {i['codigo_motivo']} | "
                      f"{top1} | {'; '.join(i['trechos_citados']) or '-'} | {'sim' if i['confere'] else 'NÃO'} |")
    falhas = [i for i in avaliacao["itens"] if not i["confere"]]
    linhas += ["", "## Falhas e pontos de atenção", ""]
    if not falhas:
        linhas.append("- Nenhuma pergunta divergiu do gabarito nos critérios automáticos.")
    for i in falhas:
        detalhes = []
        if not i["status_correto"]:
            detalhes.append(f"status {i['status_obtido']} (esperado {i['status_esperado']}, motivo {i['codigo_motivo']})")
        for a in i.get("afirmacoes_essenciais", []):
            if not a["presente"]:
                detalhes.append(f"afirmação ausente: \"{a['afirmacao']}\"")
        for ref in i.get("referencias", []):
            if ref["essencial"] and not ref["citada"]:
                detalhes.append(f"referência essencial não citada: {ref['doc_id']} \"{ref['trecho_gabarito']}\" "
                                f"(no contexto: {'sim' if ref['no_contexto'] else 'não'})")
        if i.get("fontes_exigidas") and not i.get("fontes_exigidas_citadas"):
            detalhes.append(f"fontes exigidas {i['fontes_exigidas']}, citadas {i['documentos_citados']}")
        if "recusa_padronizada_exata" in i and not i["recusa_padronizada_exata"]:
            detalhes.append("a resposta não é a recusa padronizada")
        linhas.append(f"- **{i['id']}**: " + "; ".join(detalhes or ["ver registro da resposta"]))
    alertas = [(i["id"], al) for i in avaliacao["itens"] for al in i["alertas"]]
    if alertas:
        linhas += ["", "Alertas emitidos para o operador:"] + [f"- {pid}: {al}" for pid, al in alertas]
    controle = avaliacao.get("controle_t14")
    if controle:
        linhas += ["", "## Controle do T14 (documento excluído)", "",
                   f"- {controle['id']}: DOC-99 {'excluído' if controle['documento_excluido'] else 'indexado'}; esperado "
                   f"{controle['status_esperado']}, obtido {controle['status_obtido']} ({controle['codigo_motivo']}); "
                   f"DOC-99 nos trechos consultados: {'sim' if controle['doc_excluido_no_contexto'] else 'não'}; "
                   f"{'confere' if controle['confere'] else 'NÃO confere'}."]
    linhas += [
        "", "## Como ler", "",
        "- Afirmações e referências são conferidas por marcadores e trechos literais definidos no gabarito antes da execução: "
        "a conferência é indicativa. A sustentação de cada afirmação contra a passagem citada é feita pela equipe em "
        "resultados/metricas/conferencia_sustentacao_rag.json (RF23), sem LLM-juiz.",
        "- Toda resposta, inclusive as recusas, fica PENDENTE_REVISAO_HUMANA com envio automático bloqueado; a decisão "
        "esperada do operador está no gabarito (aprovada ou revisar).",
        "- Registros completos (trechos consultados, guardas, saída do modelo e minuta): resultados/rag/respostas/.",
    ]
    return "\n".join(linhas) + "\n"


def _registro_de_sustentacao(caminho: Path, respostas: Dict[str, RespostaRAG], gabarito: Dict[str, Any]) -> bool:
    """
    Conferência humana da sustentação de cada afirmação contra a passagem citada (RF23). Não sobrescreve um
    registro que já tenha anotações da equipe. Retorna True se o arquivo foi gravado.
    """
    if caminho.exists():
        atual = json.loads(caminho.read_text(encoding="utf-8"))
        if atual.get("revisado_por") or any(a.get("sustentada") is not None for c in atual["casos"] for a in c["afirmacoes"]):
            return False
    perguntas = {p["id"]: p for p in gabarito["perguntas"]}
    _salvar(caminho.relative_to(RAIZ_PROJETO).as_posix(), {
        "instrucoes": "Para cada afirmação, leia a passagem citada e preencha sustentada (true/false). A proporção de "
                      "respostas institucionais com todas as afirmações sustentadas (RF23) sai deste registro. Registre "
                      "também a decisão do operador (aprovada, rejeitada ou revisar) e a justificativa.",
        "revisado_por": None, "data": None,
        "casos": [{
            "id": id_caso, "status": r.status, "resposta": r.resposta, "modelo": r.modelo,
            "decisao_humana_esperada": perguntas.get(id_caso, {}).get("decisao_humana_esperada"),
            "decisao_humana": None, "justificativa": None,
            "afirmacoes": [{"texto": a["texto"], "citacoes": [{"rotulo": c["rotulo"], "trecho": c["trecho"]} for c in a["citacoes"]],
                            "sustentada": None, "observacao": None} for a in r.afirmacoes],
        } for id_caso, r in respostas.items()],
    })
    return True


# ------------------------------------------------------------------------------
# Execução pela linha de comando
# ------------------------------------------------------------------------------
def _indice_pronto(config: Dict[str, Any]) -> Tuple[Optional[IndiceVetorial], str]:
    indice, motivo = preparar_indice(config)
    if indice is None:
        return None, motivo
    nome = config["indice"].get("colecao_principal", "acervo_principal")
    chunking = chunking_principal(config)
    situacao, detalhe = indice.situacao(nome, chunking) if chunking else ("AUSENTE", "sem configuração de chunking")
    if situacao != "COMPATIVEL":
        return None, f"Índice {situacao}: {detalhe} Execute: python -m src.main --modo indexar"
    return indice, ""


def _perguntas_de_avaliacao(config: Dict[str, Any], indice: IndiceVetorial) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """As 8 perguntas do gabarito e, se o DOC-99 estiver excluído, o controle do T14 (passa a ser sem resposta)."""
    gabarito = _carregar(config, "gabarito_rag")
    perguntas = [dict(p) for p in gabarito["perguntas"]]
    controle = gabarito.get("pergunta_controle_exclusao_t14")
    nome = config["indice"].get("colecao_principal", "acervo_principal")
    if controle and controle["documento_excluido"] not in indice.manifesto["colecoes"].get(nome, {}).get("documentos", {}):
        perguntas.append({"id": controle["id"], "tipo": "sem_resposta", "pergunta": controle["pergunta"],
                          "status_esperado": controle["depois_da_exclusao"]["status_esperado"], "controle_t14": True,
                          "documento_excluido": controle["documento_excluido"], "decisao_humana_esperada": "revisar"})
    return gabarito, perguntas


def executar_calibracao_limiar(config: Dict[str, Any]) -> bool:
    """--modo calibrar-limiar: similaridade do top-k nas perguntas do gabarito (uma chamada de embedding) e limiar sugerido."""
    print("=" * 75)
    print("  CALIBRAÇÃO DO LIMIAR DE SIMILARIDADE DO RAG (RF19, guarda 1)")
    print("=" * 75)
    indice, motivo = _indice_pronto(config)
    if indice is None:
        print(f"[ERRO] {motivo}")
        return False
    cfg = config["rag"]
    nome = config["indice"].get("colecao_principal", "acervo_principal")
    top_k = int(cfg.get("top_k") or config["chunking"].get("top_k", 4))
    _, perguntas = _perguntas_de_avaliacao(config, indice)
    vetores = indice.embedder.embedar([p["pergunta"] for p in perguntas], etapa="calibracao_limiar_rag")
    medicoes = []
    for p, vetor in zip(perguntas, vetores):
        recuperados = indice.buscar(nome, top_k=top_k, vetor=vetor)
        medicoes.append({"id": p["id"], "tipo": p["tipo"], "similaridades": [r["similaridade_cosseno"] for r in recuperados],
                         "docs": [r["doc_id"] for r in recuperados], "chunk_ids": [r["chunk_id"] for r in recuperados]})
    calibracao = calibrar_limiar(medicoes, float(cfg.get("folga_calibracao", 0.05)))
    tokens = sum(c["tokens"] or 0 for c in indice.embedder.chamadas)
    calibracao.update({
        "gerado_em": datetime.now().isoformat(timespec="seconds"), "colecao": nome, "top_k": top_k,
        "configuracao_chunking": chunking_principal(config)["rotulo"], "modelo_embedding": indice.embedder.modelo,
        "regra": cfg.get("regra_calibracao_limiar"), "limiar_configurado": cfg.get("limiar_similaridade"),
        "margem_minima": cfg.get("margem_minima_top1_topk"), "medicoes": medicoes, "tokens_embedding": tokens,
        "custo_estimado_usd": sum(c["custo_estimado_usd"] or 0.0 for c in indice.embedder.chamadas),
    })
    _salvar("resultados/metricas/calibracao_limiar_rag.json", calibracao, relatorio_calibracao_md(calibracao))
    for m in medicoes:
        print(f"  - {m['id']} ({m['tipo']}): top-1 {m['similaridades'][0]:.4f} ({m['docs'][0]}) | margem "
              f"{m['similaridades'][0] - m['similaridades'][-1]:.4f}")
    print(f"• Com resposta: {calibracao['top1_com_resposta']} | sem resposta: {calibracao['top1_sem_resposta']}")
    print(f"• Sobreposição: {'sim' if calibracao['sobreposicao'] else 'não'} | limiar sugerido pela regra: "
          f"{calibracao['limiar_sugerido']:.2f} | em uso: {cfg.get('limiar_similaridade')}")
    print(f"• Embedding: {tokens} tokens | US$ {calibracao['custo_estimado_usd']:.6f}")
    print("• Relatório: resultados/metricas/calibracao_limiar_rag.md")
    print("=" * 75)
    return True


def _nome_de_arquivo(modelo: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", modelo)


def executar_avaliacao_rag(config: Dict[str, Any], modelo: Optional[str] = None,
                           indice: Optional[IndiceVetorial] = None) -> bool:
    """
    --modo avaliar-rag: as 8 perguntas do gabarito (T08, T09, T10) e o controle do T14, com o índice como está.
    `modelo` troca só a geração (RF21); `indice` permite reutilizar um índice já aberto.
    """
    from src.audit import AuditManager

    print("=" * 75)
    print("  AVALIAÇÃO DO RAG FUNDAMENTADO (RF19: T08, T09, T10)")
    print("=" * 75)
    motivo = ""
    if indice is None:
        indice, motivo = _indice_pronto(config)
    if indice is None:
        print(f"[ERRO] {motivo}")
        return False
    if config["rag"].get("limiar_similaridade") is None:
        print("[ERRO] rag.limiar_similaridade não definido: execute python -m src.main --modo calibrar-limiar e registre o valor.")
        return False
    llm = indice.embedder.llm
    modelo = modelo or llm.modelo
    gabarito, perguntas = _perguntas_de_avaliacao(config, indice)
    audit = AuditManager()
    pasta = RAIZ_PROJETO / "resultados" / "rag" / "respostas" / _nome_de_arquivo(modelo)
    assistente = AssistenteRAG(indice, llm, config, audit=audit, modelo=modelo, dir_saida=pasta)
    print(f"• Provedor: {llm.provedor} | modelo: {modelo} | limiar {assistente.limiar} | top-{assistente.top_k} | "
          f"gabarito v{gabarito['versao_gabarito']} (revisão humana: {gabarito['revisao_humana']['status']})")

    vetores = indice.embedder.embedar([p["pergunta"] for p in perguntas], etapa="consulta_rag")
    respostas: Dict[str, RespostaRAG] = {}
    itens, controle, chamadas = [], None, []
    origem = config["desafio02"]["gabarito_rag"]
    for p, vetor in zip(perguntas, vetores):
        r = assistente.responder(p["pergunta"], id_caso=p["id"], vetor=vetor, arquivo_origem=origem)
        chamadas += r.chamadas
        if p.get("controle_t14"):
            no_contexto = any(f["doc_id"] == p["documento_excluido"] for f in r.fontes)
            controle = {"id": p["id"], "documento_excluido": True, "status_esperado": p["status_esperado"],
                        "status_obtido": r.status, "codigo_motivo": r.codigo_motivo, "doc_excluido_no_contexto": no_contexto,
                        "confere": r.status == p["status_esperado"] and not no_contexto}
            print(f"  - {p['id']} (controle T14): {r.status} ({r.codigo_motivo}) | DOC-99 no contexto: "
                  f"{'sim' if no_contexto else 'não'}")
            continue
        respostas[p["id"]] = r
        item = avaliar_resposta(p, r)
        itens.append(item)
        print(f"  - {p['id']} ({p['tipo']}): {r.status} ({r.codigo_motivo}) | top-1 "
              f"{r.recuperacao.get('similaridade_top1')} | {'confere' if item['confere'] else 'NÃO confere'}")

    embeddings = indice.embedder.chamadas
    avaliacao = {
        "gerado_em": datetime.now().isoformat(timespec="seconds"), "provedor": llm.provedor, "modelo": modelo,
        "prompt_versao": VERSOES_PROMPTS["PROMPT_RAG"], "versao_esquema": VERSAO_ESQUEMA_RAG,
        "colecao": assistente.colecao, "versao_indice": indice.versao_indice, "configuracao_chunking": assistente.rotulo_chunking,
        "documentos_no_indice": sorted(indice.manifesto["colecoes"].get(assistente.colecao, {}).get("documentos", {})),
        "top_k": assistente.top_k, "vizinhos_por_trecho": assistente.vizinhos, "limiar": assistente.limiar,
        "margem_minima": assistente.margem_minima, "versao_gabarito": gabarito["versao_gabarito"],
        "revisao_gabarito": gabarito["revisao_humana"]["status"], "chamadas_ao_modelo": len(chamadas),
        "chamadas_de_embedding": len(embeddings),
        "tokens_total": sum(c["tokens_total"] or 0 for c in chamadas) + sum(c["tokens"] or 0 for c in embeddings),
        "custo_total_usd": sum(c["custo_estimado_usd"] or 0.0 for c in chamadas)
        + sum(c["custo_estimado_usd"] or 0.0 for c in embeddings),
        "agregados": agregar(itens), "itens": itens, "controle_t14": controle,
    }
    destino = f"resultados/metricas/avaliacao_rag_rf19_{_nome_de_arquivo(modelo)}.json"
    _salvar(destino, avaliacao, relatorio_avaliacao_md(avaliacao))
    conferencia = RAIZ_PROJETO / "resultados" / "metricas" / "conferencia_sustentacao_rag.json"
    gravou = modelo == llm.modelo and _registro_de_sustentacao(conferencia, respostas, gabarito)

    a = avaliacao["agregados"]
    print("\n" + "=" * 75)
    for chave in ("T08_respondiveis_conferem", "T08_afirmacoes_essenciais_presentes", "T08_referencias_essenciais_citadas",
                  "T09_abstencao_correta", "T10_conflito_tratado", "recusas_indevidas"):
        print(f"  {chave}: {a[chave]['numerador']}/{a[chave]['denominador']}")
    print(f"  Chamadas: {avaliacao['chamadas_ao_modelo']} de geração + {avaliacao['chamadas_de_embedding']} de embedding | "
          f"custo estimado: US$ {avaliacao['custo_total_usd']:.6f}")
    print(f"  Relatório: {Path(destino).with_suffix('.md').as_posix()}")
    print(f"  Respostas e minutas: {pasta.relative_to(RAIZ_PROJETO).as_posix()}/")
    if modelo == llm.modelo:
        print(f"  Conferência humana: {conferencia.relative_to(RAIZ_PROJETO).as_posix()}"
              + ("" if gravou else " (mantida: já tem anotações da equipe)"))
    print("=" * 75)
    return True


def executar_consulta_rag(config: Dict[str, Any], consulta: str) -> bool:
    """--modo responder: camada 1 dos guardrails na pergunta, depois o RAG; mostra a minuta e os trechos consultados."""
    from src.audit import AuditManager

    indice, motivo = _indice_pronto(config)
    if indice is None:
        print(f"[ERRO] {motivo}")
        return False
    if config["rag"].get("limiar_similaridade") is None:
        print("[ERRO] rag.limiar_similaridade não definido: execute python -m src.main --modo calibrar-limiar.")
        return False
    llm, audit = indice.embedder.llm, AuditManager()
    guardrails = Guardrails(llm_client=llm, audit=audit)
    id_caso = f"CONSULTA-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    veredito = guardrails.avaliar_entrada(id_caso, consulta)
    print(f"Guardrails de entrada: {veredito.decisao} ({', '.join(veredito.motivos) or 'sem achados'})")
    if veredito.decisao == BLOQUEAR:
        print("A pergunta foi bloqueada e não segue para o RAG; o caso vai à revisão humana.")
        return True
    alertas = [f"ENTRADA_EM_REVISAO: {', '.join(veredito.motivos)}"] if veredito.decisao != "PERMITIR" else []
    assistente = AssistenteRAG(indice, llm, config, guardrails=guardrails, audit=audit,
                               dir_saida=RAIZ_PROJETO / "resultados" / "rag" / "respostas" / "consultas")
    r = assistente.responder(consulta, id_caso=id_caso, alertas_entrada=alertas)
    print()
    print(r.minuta)
    print()
    for f in r.fontes:
        similaridade = f" | similaridade {f['similaridade_cosseno']:.4f}" if f["similaridade_cosseno"] is not None else ""
        print(f"[{f['n']}] {f['rotulo']} | {f['chunk_id']} | {f['origem']}{similaridade}")
        print("    " + " ".join(f["trecho"].split())[:240])
    print(f"\nRegistro: resultados/rag/respostas/consultas/{id_caso}.json")
    return True
