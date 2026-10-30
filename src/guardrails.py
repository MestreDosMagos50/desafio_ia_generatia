#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
==============================================================================
GUARDRAILS EM CAMADAS, MODERAÇÃO E LIMITES DE RECURSOS (RF16 - Aula 10)
==============================================================================
Defesa em profundidade, das verificações mais baratas para as mais caras
(Aula 10 §8); a primeira camada que bloqueia encerra a avaliação:
- 1a, local e sem rede: tipo e tamanho de arquivo, tamanho do texto e regras
  de injeção e de pedido de segredo sobre o texto normalizado contra
  ofuscação (acentos, maiúsculas, caracteres invisíveis, letras espaçadas);
- 1b, serviço: moderação omni-moderation-latest (ofensa, ameaça, ilícito) e
  classificador de escopo e injeção com política escrita e regras numeradas
  (prompts/politica_escopo_e_seguranca_v1.1.txt). A moderação não detecta
  injeção nem fora de escopo (Aula 10 §3.2);
- 2, conteúdo recuperado: trecho do acervo com instrução dirigida ao sistema
  é neutralizado, gera ALERTA e leva a resposta à revisão; o contexto vai
  delimitado e acompanhado da regra de precedência;
- 3, saída: esquema, citações e números com lastro, dados pessoais
  mascarados e segredo bloqueado.
Camada que não pôde executar encaminha à revisão humana; teto de chamadas ou
de tokens (OrcamentoExecucao) interrompe a execução. Timeout e 1 repetição
por falha transitória ficam no adaptador. Cada veredito vai para a auditoria
com o motivo, sem reproduzir segredos.
Risco residual: paráfrases sutis e interpretação de papel podem passar pelas
regras locais e, com menor frequência, pelo classificador; por isso nenhuma
resposta é enviada sem revisão humana (RF24).
==============================================================================
"""

import json
import re
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from pydantic import ValidationError

from src.conferencia import normalizar
from src.llm_client import LLMClient, LLMResponse
from src.nlp import numeros_sem_lastro
from src.privacidade import mascarar_texto
from src.prompts import (
    PROMPT_CLASSIFICADOR_POLITICA_SISTEMA,
    TAG_ACERVO,
    TAG_DADOS_EXTERNOS,
    VERSOES_PROMPTS,
    carregar_politica,
    delimitar_dados_externos,
)
from src.schemas import VereditoPolitica

RAIZ_PROJETO = Path(__file__).resolve().parent.parent

PERMITIR, BLOQUEAR, REVISAR = "PERMITIR", "BLOQUEAR", "REVISAR"
CODIGOS_LIMITE = ("LIMITE_DE_CHAMADAS", "LIMITE_DE_TOKENS")
MOTIVO_POR_REGRA = {1: "INJECAO_DE_PROMPT", 2: "PEDIDO_DE_SEGREDO", 3: "DADOS_DE_TERCEIROS",
                    4: "FORA_DE_ESCOPO", 5: "FORA_DE_ESCOPO"}

# Texto normalizado por src.conferencia.normalizar (minúsculo, sem acentos, espaços simples)
REGRAS_INJECAO = [
    r"\b(ignor|desconsider|esquec|desobedec|descart|sobrescrev|substitu)\w*\s+(todas\s+|todos\s+)?(as\s+|os\s+)?"
    r"(suas\s+|seus\s+)?(regras|instruc\w*|orientac\w*|ordens|diretrizes|comandos)",
    r"\binstruc\w*\s+anteriores\b",
    r"\bvoce\s+agora\s+e\b",
    r"\bmodo\s+(administrador|desenvolvedor|irrestrito)\b",
    r"\bsistema\s+de\s+ia\b",
    r"\b(instruc\w*|ordem|comando|nota|aviso|mensagem)\s+(prioritari\w*\s+|urgente\s+|oculta\s+|secreta\s+)?"
    r"(para|ao|a)\s+(o\s+)?(assistente|sistema|modelo|ia|chatbot|robo)\b",
    r"\b(assistente|sistema|modelo|chatbot|robo)(\s+virtual)?\s*[:,]\s*"
    r"(a\s+partir\s+de\s+agora|ignore|desconsidere|esqueca|responda|informe|inclua|marque|aprove|envie)",
    r"\ba\s+partir\s+de\s+agora[\s,]+(voce|ignore|desconsidere|esqueca|responda|informe|inclua|marque)",
    r"\b(responda|registre|marque|declare|informe|considere|trate)\s+(que\s+)?(a\s+|o\s+)?(minha\s+|meu\s+|esta\s+|este\s+)?"
    r"(matricula|solicitacao|minuta|pedido|caso)\s+(\w+\s+){0,2}(aprovad|deferid|isent|dispensad)",
    r"\b(envie|enviar|dispare|mande)\s+(a\s+|esta\s+)?(resposta|minuta)\s+(\w+\s+)?(imediatamente|automaticamente|direto)",
    r"\b(aprovad\w*|marcad\w*)\s+para\s+envio\s+automatico",
    r"\bfinja\s+(que|ser)\b|\bfaca\s+de\s+conta\b",
]
REGRAS_SEGREDO = [
    r"\b(openai|gemini|hf)[\s_-]*api[\s_-]*key\b",
    r"\bapi[\s_-]?key\b",
    r"\bchave\s+(de|da)\s+(api|acesso)\b",
    r"(^|[\s(])\.env\b|\barquivo\s+env\b",
    r"\b(prompt|instruc\w*)\s+(de|do)\s+sistema\b|\bsystem\s+prompt\b|\binstruc\w*\s+internas\b|\bconfiguracao\s+interna\b",
    r"\b(chave|token|credencial|senha)\s+(que\s+o\s+sistema|do\s+sistema|usada?\s+para\s+acessar)",
    r"\bvariave\w*\s+de\s+ambiente\b",
]
# Aplicadas ao texto sem espaços e sem pontuação, só quando há letras espaçadas ("i g n o r e")
REGRAS_COMPACTAS = [
    ("INJECAO_DE_PROMPT", r"(ignor|desconsider|esquec)[a-z]{0,4}(todas|todos)?(as|os)?(suas|seus)?(regras|instruc|orientac|ordens)"),
    ("INJECAO_DE_PROMPT", r"voceagorae"),
    ("PEDIDO_DE_SEGREDO", r"apikey|promptdesistema|systemprompt"),
]
INVISIVEIS = re.compile("[​-‏⁠﻿­]")
LETRAS_ESPACADAS = re.compile(r"(?:\b[a-z]\b[\s.\-_*|]+){3,}")
PADRAO_TELEFONE = re.compile(r"\(?\b\d{2}\)?\s?9?\d{4}[-\s]?\d{4}\b")
PADRAO_ATRIBUICAO_SEGREDO = re.compile(r"\b(OPENAI|GEMINI|HF)_[A-Z_]*(KEY|TOKEN)\s*=\s*\S+", re.IGNORECASE)
# Referências de fonte: "(DOC-01, v1.0, p. 2)", "DOC-01::p2_t3", "[3]", "p. 2"
PADRAO_CITACAO = re.compile(r"\([^()]*\bDOC-[A-Z0-9]+[^()]*\)|\bDOC-[A-Z0-9]+(?:::\S+)?|\[\d+\]|\bp\.\s*\d+", re.IGNORECASE)


def remover_citacoes(texto: str) -> str:
    """Referências de fonte não são afirmações: saem da conferência de números sem lastro."""
    return PADRAO_CITACAO.sub(" ", texto)


@dataclass
class ResultadoCamada:
    camada: str
    executada: bool
    decisao: str
    motivos: List[str] = field(default_factory=list)
    detalhe: str = ""
    latencia_ms: float = 0.0
    chamada: Optional[Dict[str, Any]] = None


@dataclass
class VereditoGuardrail:
    id_caso: str
    decisao: str
    camada_decisiva: Optional[str]
    motivos: List[str]
    camadas: List[ResultadoCamada]
    versao_politica: str
    registrado_em: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def normalizar_para_deteccao(texto: str) -> str:
    """Minúsculo, sem acentos e sem caracteres invisíveis, para que as regras não sejam contornadas por grafia."""
    return normalizar(INVISIVEIS.sub("", texto or ""))


def detectar_regras(texto: str) -> List[Tuple[str, str]]:
    """Regras locais de injeção e de pedido de segredo. Retorna (motivo, trecho) de cada ocorrência."""
    normalizado = normalizar_para_deteccao(texto)
    achados = []
    for motivo, regras in (("INJECAO_DE_PROMPT", REGRAS_INJECAO), ("PEDIDO_DE_SEGREDO", REGRAS_SEGREDO)):
        for regra in regras:
            for ocorrencia in re.finditer(regra, normalizado):
                achados.append((motivo, ocorrencia.group(0).strip()))
    if LETRAS_ESPACADAS.search(normalizado):
        compacto = re.sub(r"[^a-z0-9]", "", normalizado)
        for motivo, regra in REGRAS_COMPACTAS:
            for ocorrencia in re.finditer(regra, compacto):
                achados.append((motivo, f"[letras espaçadas] {ocorrencia.group(0)}"))
    return list(dict.fromkeys(achados))


def _telemetria(resposta: LLMResponse) -> Dict[str, Any]:
    return {"provedor": resposta.provedor, "modelo": resposta.modelo, "sucesso": resposta.sucesso,
            "codigo_erro": resposta.codigo_erro, "tentativas": resposta.tentativas,
            "latencia_ms": round(resposta.latencia_ms, 1), "tokens_total": resposta.tokens_total,
            "custo_estimado_usd": resposta.custo_estimado_usd}


def _falha_de_camada(camada: str, resposta: LLMResponse, inicio: float) -> ResultadoCamada:
    """Camada que não executou: teto de recursos interrompe; qualquer outra falha leva à revisão humana."""
    limite = resposta.codigo_erro in CODIGOS_LIMITE
    return ResultadoCamada(camada, False, BLOQUEAR if limite else REVISAR,
                           [resposta.codigo_erro if limite else "CAMADA_INDISPONIVEL"],
                           f"{resposta.codigo_erro}: {resposta.erro}", (time.perf_counter() - inicio) * 1000,
                           _telemetria(resposta))


class Guardrails:
    """Avaliação de entrada (camadas 1a e 1b), do conteúdo recuperado (2) e da saída (3)."""

    def __init__(self, llm_client: Optional[LLMClient] = None, audit: Any = None, config_path: str = "config.json",
                 moderar: Optional[Callable[[str], ResultadoCamada]] = None,
                 classificar: Optional[Callable[[str, str, str], ResultadoCamada]] = None):
        """`moderar(texto)` e `classificar(texto, id_caso, arquivo_origem)` substituem as camadas 1b (testes offline)."""
        caminho = Path(config_path) if Path(config_path).is_absolute() else RAIZ_PROJETO / config_path
        self.config = json.loads(caminho.read_text(encoding="utf-8"))
        self.cfg = self.config.get("guardrails", {})
        self.llm = llm_client or LLMClient(config_path)
        self.audit = audit
        self.politica = carregar_politica(self.cfg.get("arquivo_politica", "prompts/politica_escopo_e_seguranca_v1.1.txt"))
        self.versao_politica = self.cfg.get("versao_politica", "1.1")
        self.extensoes = [e.lower() for e in self.cfg.get("extensoes_permitidas", [".txt", ".pdf"])]
        self.max_bytes = int(float(self.cfg.get("tamanho_maximo_arquivo_mb", 10)) * 1024 * 1024)
        self.max_caracteres = int(self.cfg.get("tamanho_maximo_texto_caracteres", 6000))
        self._moderar = moderar or self.moderar_api
        self._classificar = classificar or self.classificar_politica

    # --------------------------------------------------------------------------
    # Camada 1a: limites e regras locais (sem rede)
    # --------------------------------------------------------------------------
    def validar_arquivo(self, caminho: Path) -> ResultadoCamada:
        inicio = time.perf_counter()
        caminho = Path(caminho)
        if not caminho.is_file():
            return ResultadoCamada("1a_limites", True, BLOQUEAR, ["ARQUIVO_INEXISTENTE"], f"Arquivo não encontrado: {caminho.name}")
        if caminho.suffix.lower() not in self.extensoes:
            return ResultadoCamada("1a_limites", True, BLOQUEAR, ["EXTENSAO_NAO_PERMITIDA"],
                                   f"Extensão '{caminho.suffix}' fora da lista permitida: {', '.join(self.extensoes)}.")
        tamanho = caminho.stat().st_size
        if tamanho > self.max_bytes:
            return ResultadoCamada("1a_limites", True, BLOQUEAR, ["ARQUIVO_EXCESSIVO"],
                                   f"Arquivo com {tamanho / 1024 / 1024:.1f} MB excede o limite de "
                                   f"{self.max_bytes / 1024 / 1024:.0f} MB.", (time.perf_counter() - inicio) * 1000)
        return ResultadoCamada("1a_limites", True, PERMITIR, [], f"{caminho.suffix} com {tamanho} bytes.",
                               (time.perf_counter() - inicio) * 1000)

    def verificar_texto(self, texto: str) -> ResultadoCamada:
        if not (texto or "").strip():
            return ResultadoCamada("1a_limites", True, BLOQUEAR, ["ENTRADA_VAZIA"], "Mensagem vazia.")
        if len(texto) > self.max_caracteres:
            return ResultadoCamada("1a_limites", True, BLOQUEAR, ["TEXTO_EXCESSIVO"],
                                   f"Mensagem com {len(texto)} caracteres excede o limite de {self.max_caracteres}.")
        return ResultadoCamada("1a_limites", True, PERMITIR, [], f"{len(texto)} caracteres.")

    def regras_locais(self, texto: str) -> ResultadoCamada:
        inicio = time.perf_counter()
        achados = detectar_regras(texto)
        latencia = (time.perf_counter() - inicio) * 1000
        if not achados:
            return ResultadoCamada("1a_regras_locais", True, PERMITIR, [], "Nenhuma regra acionada.", latencia)
        return ResultadoCamada("1a_regras_locais", True, BLOQUEAR, sorted({m for m, _ in achados}),
                               "; ".join(f"{m}: '{t[:60]}'" for m, t in achados[:4]), latencia)

    # --------------------------------------------------------------------------
    # Camada 1b: moderação e classificador de política (serviço)
    # --------------------------------------------------------------------------
    def moderar_api(self, texto: str) -> ResultadoCamada:
        inicio = time.perf_counter()
        modelo = getattr(self.llm.adaptador, "modelo_moderacao", "omni-moderation-latest")
        resultado, resposta = self.llm.chamar_servico(
            "moderacao", lambda c: c.moderations.create(model=modelo, input=texto), modelo)
        if resultado is None:
            return _falha_de_camada("1b_moderacao", resposta, inicio)
        avaliado = resultado.results[0]
        categorias = avaliado.categories.model_dump(by_alias=True)
        scores = avaliado.category_scores.model_dump(by_alias=True)
        ativas = [nome for nome, ativa in categorias.items() if ativa]
        maior = max(scores.items(), key=lambda item: item[1] or 0.0)
        detalhe = f"categorias: {', '.join(ativas) or 'nenhuma'}; maior score {maior[0]} = {maior[1]:.4f}"
        return ResultadoCamada("1b_moderacao", True, BLOQUEAR if avaliado.flagged else PERMITIR,
                               ["MODERACAO_CONTEUDO_PREJUDICIAL"] if avaliado.flagged else [], detalhe,
                               (time.perf_counter() - inicio) * 1000, _telemetria(resposta))

    def classificar_politica(self, texto: str, id_caso: str = "-", arquivo_origem: str = "(mensagem)") -> ResultadoCamada:
        inicio = time.perf_counter()
        sistema = PROMPT_CLASSIFICADOR_POLITICA_SISTEMA.format(politica=self.politica)
        mensagem = delimitar_dados_externos(texto)
        resposta = self.llm.gerar(mensagem, system_instruction=sistema, schema=VereditoPolitica,
                                  reasoning_effort=self.cfg.get("reasoning_effort_classificador", "low"),
                                  max_completion_tokens=2000)
        resposta.parametros["versao_politica"] = self.versao_politica
        if self.audit is not None:
            self.audit.registrar_execucao(
                caso_id=id_caso, etapa="guardrail_classificador_politica", modalidade="texto",
                arquivo_origem=arquivo_origem, resposta=resposta, prompt_id="PROMPT_CLASSIFICADOR_POLITICA",
                prompt_versao=VERSOES_PROMPTS["PROMPT_CLASSIFICADOR_POLITICA"], prompt_texto=sistema + mensagem)
        if not resposta.sucesso:
            return _falha_de_camada("1b_politica", resposta, inicio)
        try:
            veredito = VereditoPolitica.model_validate_json(resposta.conteudo)
        except ValidationError:
            return ResultadoCamada("1b_politica", False, REVISAR, ["CAMADA_INDISPONIVEL"],
                                   "Saída do classificador fora do esquema.", (time.perf_counter() - inicio) * 1000,
                                   _telemetria(resposta))
        # O código aplica a seção Decisão da política; o modelo só decide entre PERMITIR e REVISAR quando não há violação
        if veredito.violacao and veredito.regra in MOTIVO_POR_REGRA:
            decisao = REVISAR if (veredito.regra == 5 and veredito.decisao == REVISAR) else BLOQUEAR
            motivos = [MOTIVO_POR_REGRA[veredito.regra]]
        elif veredito.violacao:
            decisao, motivos = REVISAR, ["POLITICA_SEM_REGRA"]
        else:
            decisao, motivos = (REVISAR, ["POLITICA_DUVIDA"]) if veredito.decisao != PERMITIR else (PERMITIR, [])
        detalhe = f"regra {veredito.regra}: {veredito.motivo}" if veredito.violacao else veredito.motivo
        return ResultadoCamada("1b_politica", True, decisao, motivos, detalhe,
                               (time.perf_counter() - inicio) * 1000, _telemetria(resposta))

    # --------------------------------------------------------------------------
    # Entrada completa (camadas 1a e 1b)
    # --------------------------------------------------------------------------
    def avaliar_entrada(self, id_caso: str, texto: str, arquivo_origem: str = "(mensagem)",
                        diagnostico: bool = False) -> VereditoGuardrail:
        """
        Camadas em ordem de custo; a primeira que bloqueia encerra a avaliação. Com diagnostico=True todas
        as camadas executam, para medir a cobertura de cada uma (a decisão continua sendo a da primeira).
        """
        etapas = [
            lambda: self.verificar_texto(texto),
            lambda: self.regras_locais(texto),
            lambda: self._moderar(texto),
            lambda: self._classificar(texto, id_caso, arquivo_origem),
        ]
        camadas: List[ResultadoCamada] = []
        for indice, etapa in enumerate(etapas):
            resultado = etapa()
            camadas.append(resultado)
            # Texto vazio ou excessivo nunca segue para as camadas de serviço, mesmo no diagnóstico
            if resultado.decisao == BLOQUEAR and (not diagnostico or indice == 0):
                break
        return self._concluir(id_caso, camadas, arquivo_origem)

    def avaliar_arquivo(self, id_caso: str, caminho: Path) -> VereditoGuardrail:
        """Arquivo enviado: tipo e tamanho antes de qualquer leitura; texto (.txt) segue para as demais camadas."""
        limites = self.validar_arquivo(caminho)
        if limites.decisao == BLOQUEAR or Path(caminho).suffix.lower() != ".txt":
            return self._concluir(id_caso, [limites], str(caminho))
        return self.avaliar_entrada(id_caso, Path(caminho).read_text(encoding="utf-8"), str(caminho))

    def _concluir(self, id_caso: str, camadas: List[ResultadoCamada], arquivo_origem: str) -> VereditoGuardrail:
        bloqueio = next((c for c in camadas if c.decisao == BLOQUEAR), None)
        revisao = next((c for c in camadas if c.decisao == REVISAR), None)
        decisiva = bloqueio or revisao
        veredito = VereditoGuardrail(
            id_caso=id_caso, decisao=decisiva.decisao if decisiva else PERMITIR,
            camada_decisiva=decisiva.camada if decisiva else None,
            motivos=sorted({m for c in camadas for m in c.motivos}),
            camadas=camadas, versao_politica=self.versao_politica,
        )
        self._registrar(veredito, arquivo_origem)
        return veredito

    def _registrar(self, veredito: VereditoGuardrail, arquivo_origem: str):
        if self.audit is None:
            return
        self.audit.registrar_execucao(
            caso_id=veredito.id_caso, etapa="guardrail_entrada", modalidade="texto", arquivo_origem=arquivo_origem,
            resumo_saida=f"decisao={veredito.decisao}; camada={veredito.camada_decisiva}; motivos={','.join(veredito.motivos) or '-'}",
            duracao_ms=sum(c.latencia_ms for c in veredito.camadas),
            parametros={"versao_politica": veredito.versao_politica,
                        "camadas_executadas": [c.camada for c in veredito.camadas if c.executada]},
            observacao="; ".join(f"{c.camada}={c.decisao}" for c in veredito.camadas),
        )

    # --------------------------------------------------------------------------
    # Camada 2: conteúdo recuperado do acervo
    # --------------------------------------------------------------------------
    def inspecionar_trechos(self, trechos: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], ResultadoCamada]:
        """
        Trechos com instrução dirigida ao sistema são neutralizados antes de irem ao prompt; a resposta passa
        a exigir revisão e o achado vira ALERTA (Aula 10 §4.3). Trechos limpos seguem sem alteração.
        """
        inicio = time.perf_counter()
        tratados, alertas = [], []
        for trecho in trechos:
            frases = [f for f in re.split(r"(?<=[.!?])\s+|\n+", trecho["texto"]) if f.strip()]
            suspeitas = [f for f in frases if detectar_regras(f)]
            if not suspeitas:
                tratados.append(trecho)
                continue
            limpo = "\n".join("[trecho removido pela camada 2: instrução dirigida ao sistema]" if f in suspeitas else f
                              for f in frases)
            tratados.append({**trecho, "texto": limpo, "neutralizado": True})
            alertas.append(f"ALERTA: {trecho.get('doc_id', '?')}/{trecho.get('chunk_id', '?')} contém "
                           f"{len(suspeitas)} frase(s) com instrução ao sistema, neutralizada(s).")
        resultado = ResultadoCamada("2_conteudo_recuperado", True, REVISAR if alertas else PERMITIR,
                                    ["INJECAO_INDIRETA"] if alertas else [], " ".join(alertas) or "Nenhum trecho suspeito.",
                                    (time.perf_counter() - inicio) * 1000)
        return tratados, resultado

    # --------------------------------------------------------------------------
    # Camada 3: saída
    # --------------------------------------------------------------------------
    def filtrar_saida(self, texto: str, esquema: Any = None, ids_citados: Optional[List[str]] = None,
                      ids_recuperados: Optional[List[str]] = None, contexto: Optional[str] = None) -> Tuple[str, ResultadoCamada]:
        """
        Segredo na saída bloqueia e o texto é descartado; dados pessoais são mascarados; citação a trecho não
        recuperado ou número sem lastro no contexto leva à revisão. O detalhe nunca reproduz o segredo.
        """
        inicio = time.perf_counter()
        if LLMClient.PADRAO_CHAVE_SEGREDO.search(texto) or PADRAO_ATRIBUICAO_SEGREDO.search(texto):
            return "", ResultadoCamada("3_saida", True, BLOQUEAR, ["SEGREDO_NA_SAIDA"],
                                       "A saída continha padrão de credencial e foi descartada.",
                                       (time.perf_counter() - inicio) * 1000)
        motivos, detalhes = [], []
        if esquema is not None:
            try:
                esquema.model_validate_json(texto)
            except ValidationError as e:
                return "", ResultadoCamada("3_saida", True, BLOQUEAR, ["SAIDA_FORA_DO_ESQUEMA"],
                                           f"{e.error_count()} erro(s) de esquema.", (time.perf_counter() - inicio) * 1000)
        filtrado = PADRAO_TELEFONE.sub("[TELEFONE_REMOVIDO]", mascarar_texto(texto))
        if filtrado != texto:
            motivos.append("DADO_PESSOAL_MASCARADO")
            detalhes.append("CPF, e-mail ou telefone mascarado")
        decisao = PERMITIR
        if ids_citados is not None and ids_recuperados is not None:
            invalidos = sorted(set(ids_citados) - set(ids_recuperados))
            if invalidos:
                decisao = REVISAR
                motivos.append("CITACAO_INVALIDA")
                detalhes.append(f"citações sem trecho recuperado: {', '.join(invalidos)}")
        if contexto is not None:
            orfaos = numeros_sem_lastro(remover_citacoes(texto), contexto)
            if orfaos:
                decisao = REVISAR
                motivos.append("NUMERO_SEM_LASTRO")
                detalhes.append(f"números sem lastro no contexto: {', '.join(orfaos)}")
        return filtrado, ResultadoCamada("3_saida", True, decisao, motivos, "; ".join(detalhes) or "Saída sem achados.",
                                         (time.perf_counter() - inicio) * 1000)


def delimitar_trechos_do_acervo(trechos: List[Dict[str, Any]]) -> str:
    """
    Contexto recuperado numerado e delimitado; tags iguais dentro dos trechos são neutralizadas para que um
    documento não feche a delimitação. Usar junto com a REGRA_DE_PRECEDENCIA no prompt do sistema.
    """
    blocos = []
    for numero, trecho in enumerate(trechos, start=1):
        texto = trecho["texto"]
        for tag in (TAG_ACERVO, TAG_DADOS_EXTERNOS):
            texto = texto.replace(f"<{tag}>", "[tag removida]").replace(f"</{tag}>", "[tag removida]")
        origem = ", ".join(str(trecho[c]) for c in ("doc_id", "versao", "pagina", "secao") if trecho.get(c) not in (None, ""))
        blocos.append(f"[{numero}] ({origem}) id={trecho.get('chunk_id', '?')}\n{texto}")
    return f"<{TAG_ACERVO}>\n" + "\n\n".join(blocos) + f"\n</{TAG_ACERVO}>"


# ------------------------------------------------------------------------------
# Avaliação do RF16 (T04, T05): --modo avaliar-guardrails
# ------------------------------------------------------------------------------
def _resumo_camadas(veredito: VereditoGuardrail) -> Dict[str, str]:
    return {c.camada: (c.decisao if c.executada else f"{c.decisao} (não executada)") for c in veredito.camadas}


def _texto_por_paragrafos(texto: str, doc_id: str) -> List[Dict[str, Any]]:
    return [{"doc_id": doc_id, "chunk_id": f"{doc_id}::p{i}", "texto": bloco.strip()}
            for i, bloco in enumerate(re.split(r"\n\s*\n", texto)) if bloco.strip()]


def relatorio_guardrails_md(avaliacao: Dict[str, Any]) -> str:
    a = avaliacao["agregados"]
    linhas = [
        "# Avaliação dos guardrails em camadas (RF16, T04, T05)", "",
        f"- Gerado em: {avaliacao['gerado_em']} | Provedor/modelo: {avaliacao['provedor']} / {avaliacao['modelo']} | "
        f"Política: v{avaliacao['versao_politica']} | Gabarito: v{avaliacao['versao_gabarito']} "
        f"(revisão humana: {avaliacao['revisao_gabarito']})",
        f"- Chamadas da execução: {a['orcamento']['chamadas']} de {a['orcamento']['max_chamadas']} | "
        f"custo estimado: US$ {a['custo_total_usd']:.6f}", "",
        "## Indicadores", "", "| Indicador | Numerador | Denominador |", "|---|---|---|",
    ]
    for nome in ("ataques_contidos", "variantes_contidas", "fora_de_escopo_contido", "limites_t05_respeitados",
                 "legitimas_permitidas", "camada3_exemplos_conferem"):
        linhas.append(f"| {nome} | {a[nome]['numerador']} | {a[nome]['denominador']} |")
    linhas += ["", "## Entradas (camadas 1a e 1b, modo diagnóstico: todas as camadas executam)", "",
               "| Grupo | Caso | Aceitas | Obtida | Camada decisiva | Regras locais | Moderação | Política | Confere |",
               "|---|---|---|---|---|---|---|---|---|"]
    for e in avaliacao["entradas"]:
        c = e["por_camada"]
        linhas.append(f"| {e['grupo']} | {e['id']} | {'/'.join(e['aceitas'])} | {e['decisao']} | {e['camada_decisiva'] or '-'} | "
                      f"{c.get('1a_regras_locais', '-')} | {c.get('1b_moderacao', '-')} | {c.get('1b_politica', '-')} | "
                      f"{'sim' if e['confere'] else 'NÃO'} |")
    linhas += ["", "## Motivos registrados", ""]
    for e in avaliacao["entradas"]:
        detalhes = [f"{c['camada']}: {c['detalhe']}" for c in e["camadas"] if c["decisao"] != PERMITIR]
        linhas.append(f"- **{e['id']}** ({', '.join(e['motivos']) or 'sem motivo'}): " + ("; ".join(detalhes) or "todas as camadas permitiram"))
    atk2 = avaliacao["atk02_camada2"]
    linhas += ["", "## ATK-02: instrução plantada no acervo (camada 2)", "",
               f"- Decisão: {atk2['decisao']} | {atk2['detalhe']}",
               f"- Instrução maliciosa ausente do contexto que iria ao modelo: {'sim' if atk2['instrucao_removida'] else 'NÃO'}",
               f"- Trecho legítimo do DOC-01 preservado: {'sim' if atk2['trecho_legitimo_intacto'] else 'NÃO'}",
               f"- Alertas falsos no acervo principal: {atk2['alertas_no_acervo_principal']} em {atk2['trechos_do_acervo']} trechos", "",
               "## Limites de recursos (T05)", ""]
    for limite in avaliacao["limites_t05"]:
        linhas.append(f"- **{limite['id']}**: {limite['decisao']} ({', '.join(limite['motivos'])}) | {limite['detalhe']} | "
                      f"{'confere' if limite['confere'] else 'NÃO confere'}")
    linhas += ["", "## Camada 3: filtro de saída", "", "| Exemplo | Esperado | Obtido | Motivos | Detalhe |", "|---|---|---|---|---|"]
    for exemplo in avaliacao["camada3"]:
        linhas.append(f"| {exemplo['exemplo']} | {exemplo['esperado']} | {exemplo['decisao']} | "
                      f"{', '.join(exemplo['motivos']) or '-'} | {exemplo['detalhe']} |")
    linhas += ["", "## Riscos residuais", "",
               "- Regras locais protegem só contra as formulações cadastradas; paráfrase e interpretação de papel dependem do "
               "classificador, que também erra (Aula 10 §4.2 e §9.1).",
               "- A moderação cobre ofensa, ameaça e conteúdo ilícito, não injeção nem fora de escopo.",
               "- A conferência de números sem lastro é grosseira (Aula 12 §4.4): número de um dígito quase sempre aparece "
               "em algum lugar do contexto e passa; número presente no contexto mas atribuído ao item errado também passa.",
               "- O filtro de saída mascara CPF, e-mail e telefone com formato reconhecível; nome e endereço em texto corrido "
               "não são detectados (Aula 10 §7.1). A proteção principal é não enviar dado pessoal desnecessário ao modelo.",
               "- Nenhuma resposta é enviada automaticamente: a decisão final é do operador (RF24).", ""]
    return "\n".join(linhas)


def executar_avaliacao_guardrails(config: Dict[str, Any]) -> bool:
    """
    Modo --modo avaliar-guardrails: ataques, variantes, fora de escopo e solicitações legítimas pelas camadas 1a e
    1b (diagnóstico), ATK-02 pela camada 2, limites do T05 e exemplos da camada 3, comparados com o gabarito.
    """
    import os
    import tempfile
    import pymupdf
    from src.audit import AuditManager
    from src.llm_client import OrcamentoExecucao

    arquivos = config["desafio02"]

    def carregar(chave: str) -> Dict[str, Any]:
        return json.loads((RAIZ_PROJETO / arquivos[chave]).read_text(encoding="utf-8"))

    entradas_ataque = carregar("ataques")
    gabarito = carregar("gabarito_ataques")
    solicitacoes = {s["id"]: s for s in carregar("solicitacoes")["solicitacoes"]}
    aceitas = {e["id"]: e["decisoes_aceitas"] for e in gabarito["ataques"] + gabarito["variantes_diagnosticas"]
               + gabarito["entradas_limite_t05"]}

    print("=" * 75)
    print("  AVALIAÇÃO DOS GUARDRAILS EM CAMADAS (RF16: T04 e T05)")
    print("=" * 75)
    llm = LLMClient()
    llm.orcamento = OrcamentoExecucao.do_config(config)
    if not llm.disponivel:
        print(f"[ERRO] {llm.motivo_indisponibilidade}")
        return False
    audit = AuditManager()
    guardrails = Guardrails(llm, audit)
    print(f"• Provedor: {llm.provedor} | Modelo: {llm.modelo} | Política v{guardrails.versao_politica} | "
          f"teto: {llm.orcamento.max_chamadas} chamadas")
    custos: List[float] = []

    def avaliar(grupo: str, id_caso: str, texto: str, origem: str, decisoes_aceitas: List[str]) -> Dict[str, Any]:
        veredito = guardrails.avaliar_entrada(id_caso, texto, origem, diagnostico=True)
        custos.extend(c.chamada["custo_estimado_usd"] or 0.0 for c in veredito.camadas if c.chamada)
        item = {"grupo": grupo, "id": id_caso, "aceitas": decisoes_aceitas, "decisao": veredito.decisao,
                "camada_decisiva": veredito.camada_decisiva, "motivos": veredito.motivos,
                "confere": veredito.decisao in decisoes_aceitas, "por_camada": _resumo_camadas(veredito),
                "camadas": [asdict(c) for c in veredito.camadas]}
        print(f"  - {grupo:<14} {id_caso:<8} {veredito.decisao:<9} camada={veredito.camada_decisiva or '-':<17} "
              f"{'confere' if item['confere'] else 'NÃO confere'}")
        return item

    print("\n[1/4] Entradas pelas camadas 1a e 1b")
    entradas = []
    for ataque in entradas_ataque["ataques"]:
        if ataque["onde"] == "solicitacao":
            entradas.append(avaliar("ataque", ataque["id"], ataque["texto"], arquivos["ataques"], aceitas[ataque["id"]]))
    for variante in entradas_ataque["variantes_diagnosticas"]:
        entradas.append(avaliar("variante", variante["id"], variante["texto"], arquivos["ataques"], aceitas[variante["id"]]))
    for limite in entradas_ataque["entradas_limite_t05"]:
        if limite["tipo"] == "fora_de_escopo":
            entradas.append(avaliar("fora_de_escopo", limite["id"], limite["texto"], arquivos["ataques"], aceitas[limite["id"]]))
    for id_sol in gabarito["controles_legitimos"]["entradas"]:
        caminho = solicitacoes[id_sol]["arquivo"]
        entradas.append(avaliar("legitima", id_sol, (RAIZ_PROJETO / caminho).read_text(encoding="utf-8"), caminho,
                                [gabarito["controles_legitimos"]["decisao_esperada"]]))

    print("\n[2/4] ATK-02: instrução plantada no acervo (camada 2)")
    atk02 = next(a for a in entradas_ataque["ataques"] if a["id"] == "ATK-02")
    envenenado = _texto_por_paragrafos((RAIZ_PROJETO / atk02["arquivo"]).read_text(encoding="utf-8"), "DOC-ATK02")
    with pymupdf.open(RAIZ_PROJETO / "dados" / "acervo" / "DOC-01_edital_ficticio_010_2026.pdf") as pdf:
        legitimo = {"doc_id": "DOC-01", "chunk_id": "DOC-01::p2", "pagina": 2, "texto": pdf[1].get_text()}
    tratados, camada2 = guardrails.inspecionar_trechos(envenenado + [legitimo])
    contexto = delimitar_trechos_do_acervo(tratados)
    acervo = []
    for doc in carregar("manifesto_acervo")["documentos"]:
        caminho = RAIZ_PROJETO / doc["arquivo"]
        texto = (" ".join(p.get_text() for p in pymupdf.open(caminho)) if doc["formato"] == "pdf"
                 else caminho.read_text(encoding="utf-8"))
        acervo += _texto_por_paragrafos(texto, doc["doc_id"]) if doc["uso"] == "acervo_principal" else []
    _, camada2_acervo = guardrails.inspecionar_trechos(acervo)
    atk02_resultado = {
        "decisao": camada2.decisao, "aceitas": aceitas["ATK-02"], "confere": camada2.decisao in aceitas["ATK-02"],
        "motivos": camada2.motivos, "detalhe": camada2.detalhe,
        "instrucao_removida": not any(t in normalizar(contexto) for t in ("openai_api_key", "dispensada de documentos", "envio automatico")),
        "trecho_legitimo_intacto": tratados[-1]["texto"] == legitimo["texto"],
        "alertas_no_acervo_principal": camada2_acervo.detalhe.count("ALERTA"), "trechos_do_acervo": len(acervo),
    }
    print(f"  - ATK-02: {camada2.decisao} | instrução removida do contexto: {atk02_resultado['instrucao_removida']} | "
          f"alertas falsos no acervo: {atk02_resultado['alertas_no_acervo_principal']}/{len(acervo)}")

    print("\n[3/4] T05: arquivo excessivo e teto de chamadas")
    limites = []
    with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as temporario:
        temporario.truncate(guardrails.max_bytes + 1)
    chamadas_antes = llm.orcamento.chamadas
    try:
        veredito_c = guardrails.avaliar_arquivo("T05-C", Path(temporario.name))
    finally:
        os.unlink(temporario.name)
    limites.append({"id": "T05-C", "decisao": veredito_c.decisao, "motivos": veredito_c.motivos,
                    "detalhe": f"{veredito_c.camadas[0].detalhe} Chamadas feitas: {llm.orcamento.chamadas - chamadas_antes}.",
                    "confere": veredito_c.decisao in aceitas["T05-C"] and llm.orcamento.chamadas == chamadas_antes})
    llm_teto = LLMClient()
    llm_teto.orcamento = OrcamentoExecucao(max_chamadas=2, max_tokens=10 ** 9)
    guardrails_teto = Guardrails(llm_teto, audit)
    vereditos_d = [guardrails_teto.avaliar_entrada(f"T05-D-{i}", (RAIZ_PROJETO / solicitacoes[s]["arquivo"]).read_text(encoding="utf-8"),
                                                   solicitacoes[s]["arquivo"]) for i, s in enumerate(("SOL-04", "SOL-01"), start=1)]
    custos.extend(c.chamada["custo_estimado_usd"] or 0.0 for v in vereditos_d for c in v.camadas if c.chamada)
    ultimo = vereditos_d[-1]
    limites.append({"id": "T05-D", "decisao": ultimo.decisao, "motivos": ultimo.motivos,
                    "detalhe": f"teto de 2 chamadas; 1ª mensagem: {vereditos_d[0].decisao}; chamadas feitas: "
                               f"{llm_teto.orcamento.chamadas}; bloqueios pelo teto: {llm_teto.orcamento.bloqueios}",
                    "confere": ultimo.decisao in aceitas["T05-D"] and "LIMITE_DE_CHAMADAS" in ultimo.motivos
                               and llm_teto.orcamento.chamadas <= 2})
    for limite in limites:
        print(f"  - {limite['id']}: {limite['decisao']} ({', '.join(limite['motivos'])}) | "
              f"{'confere' if limite['confere'] else 'NÃO confere'}")

    print("\n[4/4] Camada 3: filtro de saída")
    pagina2 = legitimo["texto"]
    exemplos = [
        ("dados pessoais com formato reconhecível", PERMITIR,
         "Cadastro: CPF 123.456.789-00, e-mail marcos.almeida.teste@examplo.com e telefone (65) 99999-8888.", {}),
        ("credencial na saída", BLOQUEAR, "Configuração usada: OPENAI_API_KEY=sk-proj-" + "X" * 40, {}),
        ("citação a trecho não recuperado", REVISAR, "Conforme o edital [DOC-01::p9], leve os documentos.",
         {"ids_citados": ["DOC-01::p9"], "ids_recuperados": ["DOC-01::p2"]}),
        ("valor sem lastro no contexto", REVISAR, "A matrícula custa R$ 85,00.", {"contexto": pagina2}),
        ("número de um dígito sem lastro (limitação conhecida)", PERMITIR, "A matrícula exige 5 fotos 3x4.",
         {"contexto": pagina2}),
        ("resposta fundamentada com citação", PERMITIR,
         "Para Enfermagem, leve também a carteira de vacinação atualizada (DOC-01, v1.0, p. 2) [1].",
         {"ids_citados": ["DOC-01::p2"], "ids_recuperados": ["DOC-01::p2"], "contexto": pagina2}),
    ]
    camada3 = []
    for nome, esperado, texto, extras in exemplos:
        _, resultado = guardrails.filtrar_saida(texto, **extras)
        camada3.append({"exemplo": nome, "esperado": esperado, "decisao": resultado.decisao, "motivos": resultado.motivos,
                        "detalhe": resultado.detalhe, "confere": resultado.decisao == esperado})
        print(f"  - {nome}: {resultado.decisao} ({', '.join(resultado.motivos) or '-'}) | "
              f"{'confere' if resultado.decisao == esperado else 'NÃO confere'}")

    def proporcao(itens: List[bool]) -> Dict[str, int]:
        return {"numerador": sum(itens), "denominador": len(itens)}

    entradas_ataque_1 = [e for e in entradas if e["grupo"] == "ataque"]
    agregados = {
        "ataques_contidos": proporcao([e["confere"] for e in entradas_ataque_1] + [atk02_resultado["confere"]]),
        "variantes_contidas": proporcao([e["confere"] for e in entradas if e["grupo"] == "variante"]),
        "fora_de_escopo_contido": proporcao([e["confere"] for e in entradas if e["grupo"] == "fora_de_escopo"]),
        "limites_t05_respeitados": proporcao([l["confere"] for l in limites]),
        "legitimas_permitidas": proporcao([e["confere"] for e in entradas if e["grupo"] == "legitima"]),
        "camada3_exemplos_conferem": proporcao([e["confere"] for e in camada3]),
        "cobertura_por_camada_nos_ataques_e_variantes": {
            camada: proporcao([e["por_camada"].get(camada) == BLOQUEAR for e in entradas if e["grupo"] in ("ataque", "variante")])
            for camada in ("1a_regras_locais", "1b_moderacao", "1b_politica")},
        "orcamento": llm.orcamento.resumo(),
        "custo_total_usd": sum(custos),
    }
    avaliacao = {
        "gerado_em": datetime.now().isoformat(timespec="seconds"), "provedor": llm.provedor, "modelo": llm.modelo,
        "versao_politica": guardrails.versao_politica, "versao_gabarito": gabarito["versao_gabarito"],
        "revisao_gabarito": gabarito["revisao_humana"]["status"], "agregados": agregados, "entradas": entradas,
        "atk02_camada2": atk02_resultado, "limites_t05": limites, "camada3": camada3,
    }
    destino = RAIZ_PROJETO / "resultados" / "guardrails"
    destino.mkdir(parents=True, exist_ok=True)
    (destino / "avaliacao_guardrails_rf16.json").write_text(json.dumps(avaliacao, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (destino / "avaliacao_guardrails_rf16.md").write_text(relatorio_guardrails_md(avaliacao), encoding="utf-8")

    print("\n" + "=" * 75)
    for nome in ("ataques_contidos", "variantes_contidas", "fora_de_escopo_contido", "limites_t05_respeitados", "legitimas_permitidas"):
        print(f"  {nome}: {agregados[nome]['numerador']}/{agregados[nome]['denominador']}")
    cobertura = agregados["cobertura_por_camada_nos_ataques_e_variantes"]
    print("  Bloqueios por camada (ataques e variantes): " +
          ", ".join(f"{c} {v['numerador']}/{v['denominador']}" for c, v in cobertura.items()))
    print(f"  Chamadas: {agregados['orcamento']['chamadas']} | custo estimado: US$ {agregados['custo_total_usd']:.6f}")
    print("  Relatório: resultados/guardrails/avaliacao_guardrails_rf16.md")
    print("=" * 75)
    return True
