#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
==============================================================================
ADAPTADORES DE GERAÇÃO DO DESAFIO 02: OPENAI E SIMULADO (RF16, RF21)
==============================================================================
O LLMClient escolhe o adaptador pelo provedor configurado (LLM_PROVIDER):
- openai:   gpt-5.6-luna (principal) e gpt-5.6-terra (segunda configuração
            real), seguindo a família GPT-5.6 (Aula 08 §3): max_completion_tokens,
            sem temperature/top_p, reasoning_effort, e conferência de
            finish_reason e refusal antes de usar a resposta;
- simulado: resposta determinística local, sem rede, identificada como
            simulada e sem equivalência de qualidade (RF21 / T12), com falha
            injetável.
Limites do RF16: timeout explícito e no máximo 1 repetição por falha
transitória. O SDK da OpenAI repete 2 vezes por padrão; aqui max_retries=0 e
a repetição fica sob controle do adaptador.
O caminho Gemini do Desafio 01 continua dentro do LLMClient, sem alteração.
==============================================================================
"""

import base64
import hashlib
import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from pydantic import ValidationError

from src.llm_client import LLMClient, LLMResponse

try:
    import openai
except ImportError:  # tratado como provedor indisponível em OpenAIAdapter._criar_cliente
    openai = None

logger = logging.getLogger("LLMClient")

# Valores aceitos pelo gpt-5.6-luna; "minimal", herdado do GPT-5, foi descontinuado e gera erro (Aula 08 §3.3)
ESFORCOS_RACIOCINIO = ("none", "low", "medium", "high", "xhigh")
MIME_IMAGEM = ("image/png", "image/jpeg")
MENSAGEM_TRUNCADA = ("A resposta foi truncada pelo limite de tokens (finish_reason=length); os tokens de raciocínio "
                     "saem do mesmo orçamento. Aumente max_completion_tokens ou reduza reasoning_effort.")


def sanitizar(texto: Optional[str]) -> str:
    """Remove padrões de chave de API de mensagens de erro e logs (mesmo padrão do LLMClient)."""
    return LLMClient.PADRAO_CHAVE_SEGREDO.sub("[CHAVE_OCULTADA_POR_SEGURANCA]", str(texto)) if texto else ""


def _menciona_json(mensagens: List[Dict[str, Any]]) -> bool:
    """A API só aceita response_format json_object se alguma mensagem contiver a palavra 'json' (Aula 08 §4.1)."""
    for mensagem in mensagens:
        conteudo = mensagem["content"]
        partes = [conteudo] if isinstance(conteudo, str) else [p.get("text", "") for p in conteudo]
        if any("json" in parte.lower() for parte in partes):
            return True
    return False


class OpenAIAdapter:
    """Geração pela API da OpenAI (Chat Completions), com a mesma interface de retorno do LLMClient."""

    provedor = "openai"
    VARIAVEL_CHAVE = "OPENAI_API_KEY"
    PLACEHOLDER_CHAVE = "sua_chave_openai_aqui"

    def __init__(self, cfg: Dict[str, Any], modelo: Optional[str] = None, cliente: Any = None):
        """`cfg` é o bloco llm.openai do config.json; `cliente` substitui o SDK (testes offline)."""
        self.cfg = cfg
        # Precedência: argumento explícito > .env > config.json
        self.modelo = (modelo or os.getenv("OPENAI_MODEL") or cfg.get("modelo_padrao", "gpt-5.6-luna")).strip()
        self.modelo_alternativo = (os.getenv("OPENAI_ALT_MODEL") or cfg.get("modelo_alternativo", "gpt-5.6-terra")).strip()
        self.modelo_embedding = (os.getenv("OPENAI_EMBEDDING_MODEL") or cfg.get("modelo_embedding", "text-embedding-3-small")).strip()
        self.modelo_moderacao = (os.getenv("OPENAI_MODERATION_MODEL") or cfg.get("modelo_moderacao", "omni-moderation-latest")).strip()
        self.timeout = int(cfg.get("timeout_segundos", 60))
        self.max_tentativas = max(1, int(cfg.get("max_tentativas", 2)))
        self.espera_inicial = float(cfg.get("espera_inicial_segundos", 2.0))
        self.reasoning_effort = cfg.get("reasoning_effort_padrao", "low")
        self.max_completion_tokens = int(cfg.get("max_completion_tokens_padrao", 4000))
        self.visao_dpi = int(cfg.get("visao_dpi", 150))
        self.visao_max_paginas = int(cfg.get("visao_max_paginas", 5))
        self.precos = cfg.get("precos_por_1m_tokens_usd", {})
        self.indisponibilidade: Optional[Tuple[str, str]] = None  # (código, mensagem)
        self.cliente = cliente if cliente is not None else self._criar_cliente()

    @property
    def disponivel(self) -> bool:
        return self.cliente is not None

    @property
    def motivo_indisponibilidade(self) -> Optional[str]:
        return self.indisponibilidade[1] if self.indisponibilidade else None

    def _criar_cliente(self) -> Any:
        """Cria o cliente do SDK ou registra o motivo da indisponibilidade (a chave nunca é exibida)."""
        if openai is None:
            self.indisponibilidade = ("BIBLIOTECA_AUSENTE",
                                      "A biblioteca openai não está instalada. Execute: pip install -r requirements.txt")
            return None
        chave = os.getenv(self.VARIAVEL_CHAVE, "").strip()
        if not chave or chave == self.PLACEHOLDER_CHAVE:
            self.indisponibilidade = ("CHAVE_AUSENTE",
                                      "A chave OPENAI_API_KEY não está configurada. Abra o arquivo .env na raiz do "
                                      "projeto e cole a chave em OPENAI_API_KEY.")
            logger.info("OPENAI_API_KEY ausente: chamadas ao modelo ficarão indisponíveis.")
            return None
        try:
            # max_retries=0: a repetição por falha transitória é feita pelo adaptador (RF16: no máximo 1)
            return openai.OpenAI(api_key=chave, timeout=self.timeout, max_retries=0)
        except Exception as e:
            self.indisponibilidade = ("ERRO_INICIALIZACAO", f"Falha ao inicializar o cliente da OpenAI: {sanitizar(str(e))}")
            logger.error(self.indisponibilidade[1])
            return None

    def calcular_custo(self, tokens_prompt: int, tokens_resposta: int, tokens_raciocinio: int = 0,
                       modelo: Optional[str] = None) -> Optional[float]:
        """
        Custo estimado em USD pela tabela do config.json (faixa de contexto curto). O raciocínio é cobrado
        como saída. Retorna None se o modelo não estiver na tabela (preço desconhecido não é estimado).
        """
        preco = self.precos.get(modelo or self.modelo)
        if not preco:
            return None
        return (tokens_prompt / 1e6) * float(preco.get("entrada", 0.0)) + \
               ((tokens_resposta + tokens_raciocinio) / 1e6) * float(preco.get("saida", 0.0))

    # --------------------------------------------------------------------------
    # Geração
    # --------------------------------------------------------------------------
    def gerar(
        self,
        prompt: str,
        system_instruction: Optional[str] = None,
        schema: Optional[Any] = None,
        modelo: Optional[str] = None,
        reasoning_effort: Optional[str] = None,
        max_completion_tokens: Optional[int] = None,
        modo_json: bool = False
    ) -> LLMResponse:
        """
        Chamada textual. Com `schema` (classe Pydantic) usa Structured Outputs (chat.completions.parse);
        com `modo_json=True`, apenas JSON sintaticamente válido (json_object), para o comparativo do RF14.
        """
        return self._executar(prompt, system_instruction, schema, modelo, reasoning_effort,
                              max_completion_tokens, modo_json)

    def gerar_multimodal(
        self,
        arquivo: Path,
        mime_type: str,
        instrucao: str,
        system_instruction: Optional[str] = None,
        schema: Optional[Any] = None,
        resolucao: Optional[str] = None,
        modelo: Optional[str] = None,
        reasoning_effort: Optional[str] = None,
        max_completion_tokens: Optional[int] = None
    ) -> LLMResponse:
        """
        Imagem (PNG/JPEG) ou PDF convertido em PNG página a página com pymupdf (T15: OCR com o gpt-5.6-luna).
        Áudio não é suportado: a transcrição do Desafio 01 depende do Gemini legado.
        `resolucao` com HIGH (ex.: 'MEDIA_RESOLUTION_HIGH', usado pelo Desafio 01) vira detail='high'.
        """
        inicio = time.perf_counter()
        modelo_usado = modelo or self.modelo
        parametros: Dict[str, Any] = {"mime_type": mime_type}
        if mime_type.startswith("audio/"):
            return self._resposta(False, inicio, 0, parametros, modelo_usado, codigo="NAO_SUPORTADO",
                                  erro="Transcrição de áudio não é suportada pelo provedor openai nesta versão; o modo "
                                       "de áudio do Desafio 01 exige LLM_PROVIDER=google (Gemini legado).")
        try:
            imagens = self._imagens_do_arquivo(Path(arquivo), mime_type)
        except (ValueError, RuntimeError) as e:
            return self._resposta(False, inicio, 0, parametros, modelo_usado, codigo="ARQUIVO_INVALIDO", erro=str(e))

        detalhe = "high" if resolucao and "HIGH" in resolucao.upper() else "auto"
        partes = [{"type": "text", "text": instrucao}] + [
            {"type": "image_url", "image_url": {"url": url, "detail": detalhe}} for url in imagens
        ]
        resposta = self._executar(partes, system_instruction, schema, modelo, reasoning_effort,
                                  max_completion_tokens, False)
        resposta.parametros.update({"mime_type": mime_type, "paginas_enviadas": len(imagens), "detalhe_imagem": detalhe})
        return resposta

    def gerar_imagem(self, prompt: str, modelo: str, **_ignorados) -> LLMResponse:
        """Geração de imagem não faz parte do Desafio 02; o cartaz do Desafio 01 usa o Gemini legado ou o modelo aberto."""
        return self._resposta(False, time.perf_counter(), 0, {}, modelo, codigo="NAO_SUPORTADO",
                              erro="Geração de imagem não está implementada no provedor openai.")

    def chamar_servico(self, operacao: str, funcao: Callable[[Any], Any], modelo: str) -> Tuple[Any, LLMResponse]:
        """
        Chamada auxiliar da OpenAI (embeddings, moderação) com o mesmo timeout, repetição única por
        falha transitória e classificação de erros da geração (RF16). `funcao` recebe o cliente do SDK.
        Retorna (resultado bruto ou None, LLMResponse com telemetria para a auditoria).
        """
        inicio = time.perf_counter()
        parametros: Dict[str, Any] = {"operacao": operacao, "timeout_s": self.timeout, "max_tentativas": self.max_tentativas}
        if self.cliente is None:
            codigo, mensagem = self.indisponibilidade or ("CLIENTE_NAO_INICIALIZADO", "O cliente da OpenAI não foi inicializado.")
            return None, self._resposta(False, inicio, 0, parametros, modelo, codigo=codigo, erro=mensagem)
        resultado, tentativas, falha = self._chamar_com_repeticao(lambda: funcao(self.cliente), modelo, parametros, inicio)
        if falha is not None:
            return None, falha
        return resultado, self._resposta(True, inicio, tentativas, parametros, modelo,
                                         uso=self._telemetria(resultado, modelo, parametros))

    def _executar(
        self,
        conteudo_usuario: Any,
        system_instruction: Optional[str],
        schema: Optional[Any],
        modelo: Optional[str],
        reasoning_effort: Optional[str],
        max_completion_tokens: Optional[int],
        modo_json: bool
    ) -> LLMResponse:
        modelo = modelo or self.modelo
        esforco = reasoning_effort or self.reasoning_effort
        limite = int(max_completion_tokens or self.max_completion_tokens)
        modo_saida = "json_schema_estrito" if schema is not None else ("json_object" if modo_json else "texto")
        parametros: Dict[str, Any] = {
            "reasoning_effort": esforco,
            "max_completion_tokens": limite,
            "timeout_s": self.timeout,
            "max_tentativas": self.max_tentativas,
            "saida_json": modo_saida != "texto",
            "modo_saida": modo_saida,
            "temperatura": "padrão do modelo (não ajustável no GPT-5.6)"
        }
        inicio = time.perf_counter()

        if self.cliente is None:
            codigo, mensagem = self.indisponibilidade or ("CLIENTE_NAO_INICIALIZADO", "O cliente da OpenAI não foi inicializado.")
            return self._resposta(False, inicio, 0, parametros, modelo, codigo=codigo, erro=mensagem)
        if esforco not in ESFORCOS_RACIOCINIO:
            return self._resposta(False, inicio, 0, parametros, modelo, codigo="PARAMETRO_INVALIDO",
                                  erro=f"reasoning_effort '{esforco}' inválido; use um de: {', '.join(ESFORCOS_RACIOCINIO)}.")

        mensagens: List[Dict[str, Any]] = []
        if system_instruction:
            mensagens.append({"role": "system", "content": system_instruction})
        mensagens.append({"role": "user", "content": conteudo_usuario})
        if modo_saida == "json_object" and not _menciona_json(mensagens):
            mensagens.insert(0, {"role": "system", "content": "Responda somente com um objeto JSON válido."})
            parametros["instrucao_json_acrescentada"] = True

        argumentos: Dict[str, Any] = {"model": modelo, "messages": mensagens,
                                      "max_completion_tokens": limite, "reasoning_effort": esforco}
        if schema is not None:
            argumentos["response_format"] = schema
            chamada = self.cliente.chat.completions.parse
        else:
            if modo_json:
                argumentos["response_format"] = {"type": "json_object"}
            chamada = self.cliente.chat.completions.create

        resposta, tentativas, falha = self._chamar_com_repeticao(lambda: chamada(**argumentos), modelo, parametros, inicio)
        if falha is not None:
            return falha

        uso = self._telemetria(resposta, modelo, parametros)
        escolha = resposta.choices[0]
        recusa = getattr(escolha.message, "refusal", None)
        if recusa:
            return self._resposta(False, inicio, tentativas, parametros, modelo, codigo="RECUSA_MODELO",
                                  erro=f"O modelo recusou o pedido: {recusa}", uso=uso)
        if escolha.finish_reason != "stop":
            codigo, mensagem = {
                "length": ("RESPOSTA_TRUNCADA", MENSAGEM_TRUNCADA),
                "content_filter": ("BLOQUEIO_CONTEUDO", "A resposta foi bloqueada pelo filtro de conteúdo do provedor."),
            }.get(escolha.finish_reason, ("RESPOSTA_INCOMPLETA", f"Resposta incompleta (finish_reason={escolha.finish_reason})."))
            return self._resposta(False, inicio, tentativas, parametros, modelo, codigo=codigo, erro=mensagem, uso=uso)
        conteudo = escolha.message.content or ""
        if not conteudo.strip():
            return self._resposta(False, inicio, tentativas, parametros, modelo, codigo="RESPOSTA_VAZIA",
                                  erro="O provedor retornou uma resposta vazia.", uso=uso)
        return self._resposta(True, inicio, tentativas, parametros, modelo, conteudo=conteudo, uso=uso)

    def _chamar_com_repeticao(self, funcao: Callable[[], Any], modelo: str, parametros: Dict[str, Any],
                              inicio: float) -> Tuple[Any, int, Optional[LLMResponse]]:
        """Executa `funcao` com no máximo 1 repetição por falha transitória (RF16). Retorna (resultado, tentativas, falha)."""
        espera = self.espera_inicial
        for tentativa in range(1, self.max_tentativas + 1):
            try:
                return funcao(), tentativa, None
            except Exception as e:
                codigo, mensagem, retentavel = self.classificar_excecao(e, modelo)
                logger.warning("[TENTATIVA %d/%d] %s (%s): %s",
                               tentativa, self.max_tentativas, codigo, modelo, sanitizar(str(e))[:300])
                if retentavel and tentativa < self.max_tentativas:
                    time.sleep(espera)
                    espera *= 2
                    continue
                # LengthFinishReasonError traz a resposta truncada: os tokens consumidos entram na auditoria
                completion = getattr(e, "completion", None)
                uso = self._telemetria(completion, modelo, parametros) if completion is not None else None
                return None, tentativa, self._resposta(False, inicio, tentativa, parametros, modelo,
                                                       codigo=codigo, erro=mensagem, uso=uso)
        raise AssertionError("max_tentativas deve ser >= 1")  # inalcançável

    def classificar_excecao(self, e: Exception, modelo: Optional[str] = None) -> Tuple[str, str, bool]:
        """Traduz a exceção do SDK em (código, mensagem compreensível, deve_repetir)."""
        modelo = modelo or self.modelo
        if openai is None:
            return ("ERRO_INESPERADO", f"Falha inesperada ao chamar a OpenAI ({type(e).__name__}).", False)
        if isinstance(e, openai.LengthFinishReasonError):
            return ("RESPOSTA_TRUNCADA", MENSAGEM_TRUNCADA, False)
        if isinstance(e, openai.ContentFilterFinishReasonError):
            return ("BLOQUEIO_CONTEUDO", "A resposta foi bloqueada pelo filtro de conteúdo do provedor.", False)
        if isinstance(e, (openai.AuthenticationError, openai.PermissionDeniedError)):
            return ("AUTENTICACAO",
                    "A chave OPENAI_API_KEY foi recusada pela OpenAI (inválida, revogada ou sem permissão para este "
                    "modelo). Confira a chave no arquivo .env.", False)
        if isinstance(e, openai.RateLimitError):
            if getattr(e, "code", None) == "insufficient_quota":
                return ("COTA_INSUFICIENTE",
                        "A conta da OpenAI está sem crédito ou cota disponível (HTTP 429 insufficient_quota). "
                        "Verifique o faturamento da conta; repetir a chamada não resolve.", False)
            return ("LIMITE_REQUISICOES",
                    "Limite de requisições da OpenAI atingido (HTTP 429). Aguarde alguns instantes e tente novamente.", True)
        if isinstance(e, openai.NotFoundError):
            return ("MODELO_NAO_ENCONTRADO",
                    f"O modelo '{modelo}' não foi encontrado ou não está liberado para esta chave. "
                    "Verifique llm.openai no config.json ou as variáveis OPENAI_*_MODEL no .env.", False)
        if isinstance(e, openai.APITimeoutError):  # antes de APIConnectionError, da qual é subclasse
            return ("TIMEOUT", f"A OpenAI não respondeu dentro do tempo limite de {self.timeout} s.", True)
        if isinstance(e, openai.APIConnectionError):
            return ("SEM_CONEXAO", "Não foi possível conectar à OpenAI. Verifique a conexão com a internet.", True)
        if isinstance(e, openai.APIStatusError):
            if e.status_code >= 500:
                return ("INDISPONIVEL",
                        f"O serviço da OpenAI está indisponível no momento (HTTP {e.status_code}). Tente novamente mais tarde.", True)
            detalhe = sanitizar(getattr(e, "message", "") or str(e))[:300]
            return ("REQUISICAO_INVALIDA", f"A OpenAI recusou a requisição (HTTP {e.status_code}): {detalhe}", False)
        return ("ERRO_INESPERADO", f"Falha inesperada ao chamar a OpenAI ({type(e).__name__}).", False)

    def _telemetria(self, resposta: Any, modelo: str, parametros: Dict[str, Any]) -> Dict[str, Any]:
        """Tokens e custo da resposta. Na OpenAI, completion_tokens já inclui o raciocínio; aqui ele é separado."""
        versao = getattr(resposta, "model", None)
        if isinstance(versao, str) and versao:
            parametros["versao_modelo"] = versao
        uso = getattr(resposta, "usage", None)
        if uso is None:
            return {}
        tokens_prompt = getattr(uso, "prompt_tokens", 0) or 0
        tokens_saida = getattr(uso, "completion_tokens", 0) or 0
        detalhes = getattr(uso, "completion_tokens_details", None)
        tokens_raciocinio = (getattr(detalhes, "reasoning_tokens", 0) or 0) if detalhes is not None else 0
        tokens_resposta = max(tokens_saida - tokens_raciocinio, 0)
        custo = self.calcular_custo(tokens_prompt, tokens_resposta, tokens_raciocinio, modelo)
        if custo is None:
            parametros["observacao_custo"] = f"sem tabela de preço para '{modelo}'; custo não estimado"
        return {
            "tokens_prompt": tokens_prompt,
            "tokens_resposta": tokens_resposta,
            "tokens_raciocinio": tokens_raciocinio,
            "tokens_total": getattr(uso, "total_tokens", None) or tokens_prompt + tokens_saida,
            "custo_estimado_usd": custo
        }

    def _imagens_do_arquivo(self, caminho: Path, mime_type: str) -> List[str]:
        """Data URLs a enviar: PDF vira PNG por página (pymupdf); PNG e JPEG vão como estão."""
        if mime_type in MIME_IMAGEM:
            return [f"data:{mime_type};base64,{base64.b64encode(caminho.read_bytes()).decode('ascii')}"]
        if mime_type != "application/pdf":
            raise ValueError(f"Tipo de arquivo '{mime_type}' não suportado pelo provedor openai.")
        try:
            import pymupdf
        except ImportError:
            raise RuntimeError("A biblioteca pymupdf não está instalada. Execute: pip install -r requirements.txt")
        with pymupdf.open(caminho) as documento:
            if len(documento) > self.visao_max_paginas:
                raise ValueError(f"O PDF tem {len(documento)} páginas; o limite para leitura por visão é "
                                 f"{self.visao_max_paginas} (llm.openai.visao_max_paginas).")
            return ["data:image/png;base64," + base64.b64encode(pagina.get_pixmap(dpi=self.visao_dpi).tobytes("png")).decode("ascii")
                    for pagina in documento]

    def _resposta(self, sucesso: bool, inicio: float, tentativas: int, parametros: Dict[str, Any], modelo: str,
                  conteudo: str = "", codigo: Optional[str] = None, erro: Optional[str] = None,
                  uso: Optional[Dict[str, Any]] = None) -> LLMResponse:
        return LLMResponse(
            conteudo=conteudo,
            modelo=modelo,
            provedor=self.provedor,
            sucesso=sucesso,
            latencia_ms=(time.perf_counter() - inicio) * 1000.0,
            tentativas=tentativas,
            codigo_erro=codigo,
            erro=sanitizar(erro) if erro else None,
            parametros=parametros,
            **(uso or {})
        )


class SimulatedAdapter:
    """
    Adaptador simulado (RF21 / T12): responde localmente, sem rede e de forma determinística.
    Serve para testes offline e para demonstrar a troca da configuração de geração sem reconstruir
    o índice. Não tem equivalência de qualidade com um modelo real e não pode ser apresentado como tal.
    """

    provedor = "simulado"
    OBSERVACAO = "Adaptador simulado para teste operacional — sem equivalência de qualidade com um modelo real."

    def __init__(self, cfg: Dict[str, Any], modelo: Optional[str] = None,
                 responder: Optional[Callable[[str, Optional[Any]], str]] = None, falha: Optional[str] = None):
        """`responder(prompt, schema)` define o conteúdo; `falha` (ex.: 'INDISPONIVEL') simula erro do serviço (T12)."""
        self.modelo = modelo or cfg.get("modelo", "simulado-deterministico")
        self.responder = responder
        self.falha = falha
        self.timeout = 0
        self.max_tentativas = 1
        self.indisponibilidade = None
        self.disponivel = True
        self.motivo_indisponibilidade = None

    def calcular_custo(self, *_args, **_kwargs) -> Optional[float]:
        return None

    def gerar(self, prompt: str, system_instruction: Optional[str] = None, schema: Optional[Any] = None,
              modelo: Optional[str] = None, modo_json: bool = False, **_ignorados) -> LLMResponse:
        inicio = time.perf_counter()
        modelo = modelo or self.modelo
        parametros = {
            "modo_saida": "json_schema_estrito" if schema is not None else ("json_object" if modo_json else "texto"),
            "simulado": True,
            "observacao": self.OBSERVACAO,
            "observacao_custo": "adaptador simulado: tokens e custo indisponíveis; apenas a latência local foi medida"
        }
        if self.falha:
            return self._resposta(False, inicio, parametros, modelo, codigo=self.falha,
                                  erro=f"Falha simulada do serviço de geração ({self.falha}), injetada para o teste "
                                       "de troca de provedor (T12).")
        try:
            conteudo = self.responder(prompt, schema) if self.responder else self._resposta_padrao(prompt, schema, modo_json)
        except ValidationError as e:
            return self._resposta(False, inicio, parametros, modelo, codigo="SIMULADO_SEM_RESPOSTA",
                                  erro=f"O adaptador simulado não monta resposta padrão para {schema.__name__} "
                                       f"({e.error_count()} campo(s) obrigatório(s)); informe um `responder`.")
        return self._resposta(True, inicio, parametros, modelo, conteudo=conteudo)

    def gerar_multimodal(self, arquivo: Path, mime_type: str, instrucao: str, system_instruction: Optional[str] = None,
                         schema: Optional[Any] = None, **_ignorados) -> LLMResponse:
        resposta = self.gerar(instrucao, system_instruction, schema)
        resposta.parametros["mime_type"] = mime_type
        return resposta

    def gerar_imagem(self, prompt: str, modelo: str, **_ignorados) -> LLMResponse:
        return self._resposta(False, time.perf_counter(), {"simulado": True}, modelo, codigo="NAO_SUPORTADO",
                              erro="O adaptador simulado não gera imagens.")

    @staticmethod
    def _resposta_padrao(prompt: str, schema: Optional[Any], modo_json: bool) -> str:
        """Conteúdo determinístico que não inventa dados: valores padrão do esquema ou eco da assinatura do prompt."""
        if schema is not None:
            return schema().model_dump_json()
        assinatura = hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:12]
        if modo_json:
            return json.dumps({"simulado": True, "assinatura_prompt": assinatura})
        return (f"[RESPOSTA SIMULADA — sem equivalência de qualidade] Prompt recebido com {len(prompt)} "
                f"caracteres (sha256 {assinatura}).")

    def _resposta(self, sucesso: bool, inicio: float, parametros: Dict[str, Any], modelo: str, conteudo: str = "",
                  codigo: Optional[str] = None, erro: Optional[str] = None) -> LLMResponse:
        return LLMResponse(
            conteudo=conteudo,
            modelo=modelo,
            provedor=self.provedor,
            sucesso=sucesso,
            latencia_ms=(time.perf_counter() - inicio) * 1000.0,
            tentativas=1,
            codigo_erro=codigo,
            erro=erro,
            parametros=parametros
        )
