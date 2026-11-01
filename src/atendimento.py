#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
==============================================================================
FLUXO INTEGRADO DE ATENDIMENTO E SERVIÇOS DA INTERFACE (RF20, RF21, RF24)
==============================================================================
A interface (src/app.py) só apresenta; a lógica fica aqui, testável sem ela.
- processar_atendimento: guardrails de entrada -> contrato e ficha ->
  RAG com fatos minimizados -> minuta PENDENTE_REVISAO_HUMANA. Entrada
  bloqueada ou contrato rejeitado param o fluxo sem minuta, e o caso segue
  para o operador do mesmo jeito.
- Troca da configuração de geração (RF21, T12): luna, terra, simulado
  conservador ou simulado com falha. O índice e os embeddings não mudam; os
  guardrails de entrada continuam no cliente principal, porque a troca de
  geração não pode enfraquecer a camada de segurança.
- O simulado conservador não lê o texto: devolve contrato vazio, recusa do
  RAG e polaridade indeterminada, tudo marcado para revisão. Serve para
  operar sem rede e nunca é apresentado como equivalente a um modelo real.
- Inclusão de documento pela interface: arquivo temporário removido no
  finally (Aula 13 §7.3); o manifesto registra o nome original e o hash.
- Fila de minutas e decisão do operador (T11): estado PENDENTE, APROVADA,
  REJEITADA ou REVISAR, com justificativa; o envio continua manual.
==============================================================================
"""

import hashlib
import json
import os
import re
import tempfile
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.conferencia import NAO_LOCALIZADO
from src.embeddings import IndiceVetorial, chunking_principal, documentos_do_indice_principal
from src.guardrails import BLOQUEAR, PERMITIR, Guardrails
from src.ingestion import sha256_arquivo
from src.llm_client import LLMClient, OrcamentoExecucao
from src.nlp import BLOQUEAR_REGRA, GERAR_MINUTA, ExtratorSolicitacoes
from src.privacidade import mascarar_texto
from src.prompts import FRASE_ABSTENCAO_PADRAO, TAG_DADOS_EXTERNOS
from src.rag import SEM_EVIDENCIA, AssistenteRAG
from src.schemas import (
    CAMPOS_ANULAVEIS, ClassificacaoSentimento, ContratoSolicitacaoV2, EntidadesLiterais, ResumoNLP, SaidaGeracaoRAG,
    VereditoPolitica,
)

RAIZ_PROJETO = Path(__file__).resolve().parent.parent
DIR_ATENDIMENTOS = RAIZ_PROJETO / "resultados" / "atendimentos"
STATUS_REVISAO = "PENDENTE_REVISAO_HUMANA"
MARCA_SIMULADO = "[SIMULADO — sem equivalência de qualidade]"
ALERTA_OCR_NAO_CONFIRMADO = (
    "ENTRADA_OCR_SEM_CONFIRMACAO_HUMANA: leitura de manuscrito ainda não conferida na imagem. Confira código, documentos e "
    "datas antes de qualquer uso; a leitura pode errar sem marcar o campo como incerto (no Desafio 01 a ficha só entra "
    "depois da confirmação humana dos campos críticos)."
)


def alertas_de_leitura_ocr(leitura_revisada: Dict[str, Any]) -> List[str]:
    """Alerta obrigatório de toda entrada vinda de OCR e um alerta por campo que a leitura marcou como incerto ou ilegível."""
    return [ALERTA_OCR_NAO_CONFIRMADO] + [f"CAMPO_INCERTO_NA_LEITURA: {t['rotulo']} ({t['situacao']})"
                                          for t in leitura_revisada.get("trechos_incertos", [])]


# ------------------------------------------------------------------------------
# Configurações de geração (RF21, T12)
# ------------------------------------------------------------------------------
def configuracoes_de_geracao(config: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    openai_cfg = config["llm"]["openai"]
    return {
        "principal": {"rotulo": f"OpenAI {openai_cfg['modelo_padrao']} (principal)", "provedor": "openai",
                      "modelo": openai_cfg["modelo_padrao"]},
        "alternativa": {"rotulo": f"OpenAI {openai_cfg['modelo_alternativo']} (2ª configuração real)", "provedor": "openai",
                        "modelo": openai_cfg["modelo_alternativo"]},
        "simulado": {"rotulo": "Simulado conservador (sem rede; sem equivalência de qualidade)", "provedor": "simulado"},
        "simulado_falha": {"rotulo": "Simulado com falha do serviço de geração (T12)", "provedor": "simulado",
                           "falha": "INDISPONIVEL"},
    }


def cliente_de_geracao(chave: str, config: Dict[str, Any]) -> LLMClient:
    """Cliente da configuração escolhida, sob o teto de chamadas da execução; não toca no índice."""
    cfg = configuracoes_de_geracao(config)[chave]
    llm = LLMClient(provedor=cfg["provedor"], modelo=cfg.get("modelo"))
    llm.orcamento = OrcamentoExecucao.do_config(config)
    if cfg["provedor"] == "simulado":
        llm.adaptador.responder = responder_simulado_conservador
        llm.adaptador.falha = cfg.get("falha")
    return llm


def responder_simulado_conservador(prompt: str, schema: Optional[Any]) -> str:
    """Saídas que não inventam nada: tudo ausente, recusa ou indeterminado, e tudo para revisão humana."""
    if schema is ContratoSolicitacaoV2:
        vazio = EntidadesLiterais(pessoas_ficticias=[], orgaos=[], locais=[], datas=[], protocolos=[])
        return ContratoSolicitacaoV2(**{c: None for c in CAMPOS_ANULAVEIS}, categoria="REVISAO", entidades=vazio,
                                     campos_ausentes=list(CAMPOS_ANULAVEIS), necessita_revisao=True).model_dump_json()
    if schema is ResumoNLP:
        return ResumoNLP(resumo=f"{MARCA_SIMULADO} Resumo indisponível: o adaptador simulado não lê a solicitação.",
                         informacoes_inferidas=[]).model_dump_json()
    if schema is SaidaGeracaoRAG:
        return SaidaGeracaoRAG(status=SEM_EVIDENCIA, resposta=FRASE_ABSTENCAO_PADRAO, afirmacoes=[], divergencias=[],
                               alerta=None).model_dump_json()
    if schema is VereditoPolitica:
        return VereditoPolitica(violacao=False, regra=None, decisao="REVISAR",
                                motivo="Adaptador simulado: sem classificação real.").model_dump_json()
    if schema is ClassificacaoSentimento:
        texto = re.search(rf"<{TAG_DADOS_EXTERNOS}>\s*(.*?)\s*</{TAG_DADOS_EXTERNOS}>", prompt, re.S)
        trecho = " ".join((texto.group(1) if texto else "").split()[:8])
        return ClassificacaoSentimento(polaridade="indeterminada", intensidade="leve", ambiguidade="limitrofe", tema="outro",
                                       trecho_determinante=trecho, justificativa_curta=f"{MARCA_SIMULADO} sem classificação real.",
                                       necessita_revisao=True).model_dump_json()
    return f"{MARCA_SIMULADO} Prompt com {len(prompt)} caracteres."


# ------------------------------------------------------------------------------
# Atendimento integrado
# ------------------------------------------------------------------------------
@dataclass
class ResultadoAtendimento:
    id_atendimento: str
    id_solicitacao: Optional[str]
    canal: str
    arquivo_origem: str
    configuracao_geracao: Dict[str, Any]
    etapa_final: str
    motivo: str
    entrada: Dict[str, Any]
    extracao: Optional[Dict[str, Any]] = None
    contrato_exibicao: Optional[Dict[str, Any]] = None
    ficha: Optional[Dict[str, Any]] = None
    rag: Optional[Dict[str, Any]] = None
    fatos_enviados_ao_rag: Optional[str] = None
    alertas_da_origem: List[str] = field(default_factory=list)
    status_revisao: str = STATUS_REVISAO
    envio_automatico_bloqueado: bool = True
    registrado_em: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def novo_id_atendimento() -> str:
    return f"ATD-{datetime.now():%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:4].upper()}"


def fatos_minimizados(contrato: ContratoSolicitacaoV2) -> str:
    """O que o RAG precisa saber da solicitação, sem nome, CPF ou contatos (RF24: minimizar o enviado ao provedor)."""
    exibicao = contrato.para_exibicao_interface()
    campos = (("assunto", "Assunto"), ("pedido", "Pedido"), ("curso", "Curso"), ("data_solicitacao", "Data da solicitação"))
    return "\n".join(f"{rotulo}: {mascarar_texto(str(exibicao[campo]))}" for campo, rotulo in campos)


def texto_de_busca(contrato: ContratoSolicitacaoV2, texto: str) -> str:
    partes = [p for p in (contrato.assunto, contrato.pedido, contrato.curso) if p]
    return " ".join(partes) if partes else mascarar_texto(texto[:500])


def processar_atendimento(texto: str, config: Dict[str, Any], indice: Optional[IndiceVetorial], llm_geracao: LLMClient,
                          guardrails: Guardrails, audit: Any = None, canal: str = "texto", arquivo_origem: str = "(mensagem)",
                          id_solicitacao: Optional[str] = None, configuracao: Optional[Dict[str, Any]] = None,
                          dir_base: Optional[Path] = None, alertas_da_origem: Optional[List[str]] = None) -> ResultadoAtendimento:
    """
    Fluxo mínimo da Seção 9 do enunciado para uma solicitação; o resultado e cada etapa ficam gravados.
    `alertas_da_origem` (ex.: leitura de manuscrito não confirmada) acompanham a minuta e a levam à revisão prioritária.
    """
    id_atendimento = novo_id_atendimento()
    pasta = Path(dir_base or DIR_ATENDIMENTOS) / id_atendimento
    resultado = ResultadoAtendimento(
        id_atendimento=id_atendimento, id_solicitacao=id_solicitacao, canal=canal, arquivo_origem=arquivo_origem,
        configuracao_geracao=configuracao or {"provedor": llm_geracao.provedor, "modelo": llm_geracao.modelo},
        etapa_final="", motivo="", entrada={}, alertas_da_origem=list(alertas_da_origem or []))

    veredito = guardrails.avaliar_entrada(id_atendimento, texto, arquivo_origem)
    resultado.entrada = veredito.to_dict()
    if veredito.decisao == BLOQUEAR:
        resultado.etapa_final, resultado.motivo = "BLOQUEADA_NA_ENTRADA", f"Guardrails: {', '.join(veredito.motivos)}"
        return _gravar(resultado, pasta)
    alertas = list(resultado.alertas_da_origem)
    if veredito.decisao != PERMITIR:
        alertas.append(f"ENTRADA_EM_REVISAO: {', '.join(veredito.motivos) or veredito.decisao}")

    extrator = ExtratorSolicitacoes(llm_client=llm_geracao, audit=audit, dir_saida=pasta)
    extracao = extrator.extrair(id_atendimento, texto, canal, arquivo_origem)
    resultado.extracao = asdict(extracao)
    if extracao.contrato is None:
        resultado.etapa_final, resultado.motivo = "EXTRACAO_REJEITADA", extracao.motivo
        return _gravar(resultado, pasta)
    contrato = ContratoSolicitacaoV2.model_validate(extracao.contrato)
    resultado.contrato_exibicao = contrato.para_exibicao_interface()
    if extracao.decisao == BLOQUEAR_REGRA:
        resultado.etapa_final, resultado.motivo = "EXTRACAO_BLOQUEADA", extracao.motivo
        return _gravar(resultado, pasta)
    ficha, _ = extrator.gerar_ficha(id_atendimento, texto, canal, arquivo_origem, contrato)
    resultado.ficha = ficha.model_dump() if ficha else None
    alertas += [f"{a['codigo']}: {a['mensagem']}" for a in extracao.alertas]
    if extracao.decisao != GERAR_MINUTA:
        alertas.append(f"DECISAO_DA_EXTRACAO: {extracao.decisao} ({extracao.motivo})")

    if indice is None:
        resultado.etapa_final, resultado.motivo = "RECUPERACAO_INDISPONIVEL", "Índice indisponível: a minuta não foi gerada."
        return _gravar(resultado, pasta)
    resultado.fatos_enviados_ao_rag = fatos_minimizados(contrato)
    assistente = AssistenteRAG(indice, llm_geracao, config, guardrails=guardrails, audit=audit, dir_saida=pasta)
    resposta = assistente.responder(resultado.fatos_enviados_ao_rag, id_caso=id_atendimento, alertas_entrada=alertas,
                                    arquivo_origem=arquivo_origem, texto_busca=texto_de_busca(contrato, texto))
    resultado.rag = resposta.to_dict()
    resultado.etapa_final, resultado.motivo = "MINUTA_GERADA", resposta.motivo
    return _gravar(resultado, pasta)


def _gravar(resultado: ResultadoAtendimento, pasta: Path) -> ResultadoAtendimento:
    pasta.mkdir(parents=True, exist_ok=True)
    (pasta / "atendimento.json").write_text(json.dumps(resultado.to_dict(), indent=2, ensure_ascii=False, default=str) + "\n",
                                            encoding="utf-8")
    return resultado


# ------------------------------------------------------------------------------
# Fila de minutas e decisão do operador (T11)
# ------------------------------------------------------------------------------
def _ler_json(caminho: Path) -> Optional[Dict[str, Any]]:
    try:
        return json.loads(caminho.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def minutas_para_revisao(audit: Any, dir_atendimentos: Path = DIR_ATENDIMENTOS,
                         dir_respostas_rag: Path = RAIZ_PROJETO / "resultados" / "rag" / "respostas") -> List[Dict[str, Any]]:
    """Atendimentos e respostas do RAG gravados, com o estado atual da decisão do operador (PENDENTE se não houver)."""
    estados = audit.estado_das_minutas()
    itens = []
    for caminho in sorted(Path(dir_atendimentos).glob("*/atendimento.json")):
        dados = _ler_json(caminho)
        if not dados:
            continue
        rag = dados.get("rag") or {}
        itens.append({"caso_id": dados["id_atendimento"], "origem": f"atendimento ({dados.get('id_solicitacao') or 'mensagem digitada'})",
                      "etapa": dados["etapa_final"], "status": rag.get("status") or dados["etapa_final"],
                      "minuta": rag.get("minuta") or f"Sem minuta: {dados['motivo']}", "provedor": rag.get("provedor"),
                      "modelo": rag.get("modelo"), "prompt": rag.get("prompt"), "id_execucao": rag.get("id_execucao"),
                      "registrado_em": dados["registrado_em"], "arquivo": caminho, "dados": dados})
    for caminho in sorted(Path(dir_respostas_rag).glob("*/*.json")):
        dados = _ler_json(caminho)
        if not dados or "minuta" not in dados:
            continue
        itens.append({"caso_id": dados["id_caso"], "origem": f"RAG ({caminho.parent.name})", "etapa": "MINUTA_GERADA",
                      "status": dados["status"], "minuta": dados["minuta"], "provedor": dados.get("provedor"),
                      "modelo": dados.get("modelo"), "prompt": dados.get("prompt"), "id_execucao": dados.get("id_execucao"),
                      "registrado_em": dados.get("registrado_em"), "arquivo": caminho, "dados": {"rag": dados}})
    for item in itens:
        decisao = estados.get(item["caso_id"])
        item["estado"] = decisao["estado"] if decisao else "PENDENTE"
        item["ultima_decisao"] = decisao
    return itens


def registrar_decisao(audit: Any, item: Dict[str, Any], estado: str, operador: str, justificativa: str) -> Dict[str, Any]:
    """Grava a decisão do operador sobre a minuta do item; valida estado, operador e justificativa."""
    minuta = {"minuta": item["minuta"], "provedor": item["provedor"], "modelo": item["modelo"], "prompt": item["prompt"],
              "status": item["status"]}
    return audit.registrar_decisao_minuta(item["caso_id"], estado, operador, justificativa, item.get("id_execucao"), minuta)


# ------------------------------------------------------------------------------
# Acervo e índice
# ------------------------------------------------------------------------------
def ler_manifesto_do_indice(config: Dict[str, Any]) -> Dict[str, Any]:
    caminho = RAIZ_PROJETO / config.get("indice", {}).get("diretorio_base", "indice") / "manifesto_indice.json"
    return _ler_json(caminho) or {"colecoes": {}}


def situacao_do_acervo(config: Dict[str, Any], manifesto: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """
    Cada documento do acervo e cada documento enviado pela interface, com a situação no índice (sem rede):
    INDEXADO, DESATUALIZADO (arquivo mudou desde a indexação), NAO_INDEXADO ou EXCLUIDO (RF24).
    """
    manifesto = manifesto or ler_manifesto_do_indice(config)
    registro = manifesto["colecoes"].get(config["indice"].get("colecao_principal", "acervo_principal"),
                                         {"documentos": {}, "exclusoes": []})
    excluidos = {e["doc_id"]: e for e in registro.get("exclusoes", []) if not e.get("reincluido_em")}
    linhas = []
    acervo = documentos_do_indice_principal(config)
    for doc in acervo:
        indexado = registro["documentos"].get(doc["doc_id"])
        caminho = RAIZ_PROJETO / doc["arquivo"]
        if doc["doc_id"] in excluidos:
            situacao = "EXCLUIDO"
        elif indexado is None:
            situacao = "NAO_INDEXADO"
        else:
            situacao = "INDEXADO" if indexado["hash_sha256"] == sha256_arquivo(caminho) else "DESATUALIZADO"
        linhas.append({"doc_id": doc["doc_id"], "titulo": doc["titulo"], "versao": doc["versao"], "formato": doc["formato"],
                       "origem": "acervo fictício", "situacao": situacao, "trechos": indexado["trechos"] if indexado else 0,
                       "excluido_em": excluidos.get(doc["doc_id"], {}).get("em"), "arquivo": doc["arquivo"]})
    conhecidos = {d["doc_id"] for d in acervo}
    for doc_id, indexado in registro["documentos"].items():
        if doc_id not in conhecidos:
            linhas.append({"doc_id": doc_id, "titulo": indexado.get("titulo") or NAO_LOCALIZADO, "versao": indexado.get("versao"),
                           "formato": Path(indexado["arquivo"]).suffix.lstrip("."), "origem": "enviado pela interface",
                           "situacao": "INDEXADO", "trechos": indexado["trechos"], "excluido_em": None,
                           "arquivo": indexado["arquivo"]})
    return linhas


def indexar_documento_enviado(indice: IndiceVetorial, config: Dict[str, Any], guardrails: Guardrails, nome_arquivo: str,
                              conteudo: bytes, titulo: str, versao: str = "1.0") -> Dict[str, Any]:
    """
    Indexa um .txt ou .pdf enviado pela interface. O conteúdo vai a um arquivo temporário apagado no finally, inclusive
    em falha (Aula 13 §7.3). O manifesto registra o nome original; o identificador vem do hash do conteúdo.
    """
    extensao = Path(nome_arquivo).suffix.lower()
    if extensao not in (".txt", ".pdf"):
        raise ValueError(f"Formato '{extensao or 'sem extensão'}' não indexável: envie .txt ou .pdf textual.")
    if not (titulo or "").strip():
        raise ValueError("Informe o título do documento.")
    doc_id = f"UP-{hashlib.sha256(conteudo).hexdigest()[:8].upper()}"
    with tempfile.NamedTemporaryFile(delete=False, suffix=extensao) as temporario:
        temporario.write(conteudo)
        caminho = Path(temporario.name)
    try:
        limites = guardrails.validar_arquivo(caminho)
        if limites.decisao == BLOQUEAR:
            raise ValueError(limites.detalhe)
        doc = {"doc_id": doc_id, "titulo": titulo.strip(), "versao": (versao or "1.0").strip(), "formato": extensao.lstrip("."),
               "arquivo": str(caminho), "arquivo_registrado": f"(enviado pela interface) {Path(nome_arquivo).name}",
               "tema": "", "uso": "enviado_pela_interface", "retifica": None, "retificado_por": [],
               "vigencia": f"Enviado pela interface em {datetime.now():%d/%m/%Y}; vigência não declarada."}
        try:
            relatorio = indice.indexar(config["indice"].get("colecao_principal", "acervo_principal"), [doc],
                                       chunking_principal(config))
        except UnicodeDecodeError:
            raise ValueError("O .txt precisa estar em UTF-8.")
        registro = indice.manifesto["colecoes"][config["indice"].get("colecao_principal", "acervo_principal")]
        if doc_id in registro["documentos"]:
            registro["documentos"][doc_id].update({"titulo": doc["titulo"], "versao": doc["versao"]})
            indice._gravar_manifesto()
        return {"doc_id": doc_id, **relatorio}
    finally:
        os.unlink(caminho)


# ------------------------------------------------------------------------------
# Auditoria na interface (RF21)
# ------------------------------------------------------------------------------
CAMPOS_DO_LOG = ("timestamp", "id_execucao", "caso_id", "etapa", "provedor", "modelo", "sucesso", "codigo_erro",
                 "duracao_ms", "tokens_total", "custo_estimado_usd", "resumo_saida")


def registros_de_auditoria(audit: Any, limite: int = 200) -> List[Dict[str, Any]]:
    """Últimas linhas do auditoria.jsonl, sanitizadas de novo na leitura (credenciais, CPF e e-mail)."""
    caminho = Path(audit.arquivo_log_jsonl)
    if not caminho.exists():
        return []
    linhas = caminho.read_text(encoding="utf-8").splitlines()[-limite:]
    registros = []
    for linha in reversed(linhas):
        try:
            dados = json.loads(linha)
        except json.JSONDecodeError:
            continue
        registros.append(audit._sanitizar({c: dados.get(c) for c in CAMPOS_DO_LOG}))
    return registros


def resumo_de_uso(registros: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Chamadas, falhas, tokens e custo por provedor e modelo; custo do simulado é indisponível, não zero."""
    grupos: Dict[tuple, Dict[str, Any]] = {}
    for r in registros:
        if r.get("provedor") in (None, "nenhum"):
            continue
        g = grupos.setdefault((r["provedor"], r.get("modelo")), {"provedor": r["provedor"], "modelo": r.get("modelo"),
                                                                  "chamadas": 0, "falhas": 0, "tokens": 0, "custo_usd": 0.0,
                                                                  "chamadas_sem_custo": 0})
        g["chamadas"] += 1
        g["falhas"] += 0 if r.get("sucesso") else 1
        g["tokens"] += r.get("tokens_total") or 0
        if r.get("custo_estimado_usd") is None:
            g["chamadas_sem_custo"] += 1
        else:
            g["custo_usd"] += r["custo_estimado_usd"]
    return [{**g, "custo_usd": None if g["chamadas_sem_custo"] == g["chamadas"] else round(g["custo_usd"], 6)}
            for g in grupos.values()]
