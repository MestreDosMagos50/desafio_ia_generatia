#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
==============================================================================
CLIENTE DE INTEGRAÇÃO COM MODELO DE LINGUAGEM (LLM) E TRATAMENTO DE FALHAS
Atende aos requisitos RF03, RF04, RF11 e RF21.
==============================================================================
Características:
- Provedor escolhido por LLM_PROVIDER: openai (padrão do Desafio 02) e
  simulado ficam isolados em adaptadores (src/adaptadores.py, RF21); google
  (Gemini, Desafio 01) segue no caminho abaixo, com modelo e parâmetros
  vindos do config.json / .env;
- Timeout aplicado a cada requisição e retentativas com espera exponencial;
- Modelos alternativos (config.json) quando o principal responde 429 ou 5xx;
- Tratamento explícito de chave ausente, autenticação inválida, limite de
  requisições (429), indisponibilidade (5xx, timeout, rede) e resposta vazia;
- Em caso de falha retorna sucesso=False com mensagem compreensível — a
  resposta do modelo nunca é substituída por texto pronto;
- Sanitização de credenciais em mensagens de erro e logs;
- Telemetria de latência, tokens (entrada, saída e raciocínio) e custo estimado.
==============================================================================
"""

import os
import re
import time
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Tuple

import httpx

try:
    from google import genai
    from google.genai import errors as genai_errors
    from google.genai import types as genai_types
except ImportError:  # tratado como provedor indisponível em _inicializar_provedor
    genai = None
    genai_errors = None
    genai_types = None

logger = logging.getLogger("LLMClient")

try:
    from dotenv import load_dotenv
    # Variáveis já definidas no ambiente têm precedência sobre o arquivo .env
    load_dotenv(dotenv_path=Path(__file__).resolve().parent.parent / ".env")
except ImportError:
    pass


@dataclass
class LLMResponse:
    """Estrutura padronizada de retorno de chamadas ao modelo."""
    conteudo: str
    modelo: str
    provedor: str
    sucesso: bool
    latencia_ms: float
    tentativas: int = 0
    tokens_prompt: Optional[int] = None
    tokens_resposta: Optional[int] = None
    tokens_raciocinio: Optional[int] = None
    tokens_total: Optional[int] = None
    custo_estimado_usd: Optional[float] = None
    codigo_erro: Optional[str] = None
    erro: Optional[str] = None
    parametros: Dict[str, Any] = field(default_factory=dict)
    timestamp: str = ""
    # Saída binária (geração de imagem); não entra em to_dict nem nos logs
    dados_binarios: Optional[bytes] = field(default=None, repr=False)
    mime_type: Optional[str] = None

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now().isoformat()

    def marcar_falha(self, codigo: str, mensagem: str) -> "LLMResponse":
        """Marca como falha uma resposta recebida mas inutilizável (ex.: fora do esquema JSON)."""
        self.sucesso = False
        self.codigo_erro = codigo
        self.erro = mensagem
        return self

    def to_dict(self) -> Dict[str, Any]:
        return {
            "conteudo": self.conteudo,
            "modelo": self.modelo,
            "provedor": self.provedor,
            "sucesso": self.sucesso,
            "latencia_ms": round(self.latencia_ms, 2),
            "tentativas": self.tentativas,
            "tokens_prompt": self.tokens_prompt,
            "tokens_resposta": self.tokens_resposta,
            "tokens_raciocinio": self.tokens_raciocinio,
            "tokens_total": self.tokens_total,
            "custo_estimado_usd": round(self.custo_estimado_usd, 6) if self.custo_estimado_usd is not None else None,
            "codigo_erro": self.codigo_erro,
            "erro": self.erro,
            "parametros": self.parametros,
            "timestamp": self.timestamp
        }


class OrcamentoExecucao:
    """
    Teto de chamadas e de tokens de uma execução (RF16 / T05). Antes de cada chamada o LLMClient confere o saldo;
    depois, registra as tentativas efetivamente feitas (inclusive a repetição por falha transitória) e os tokens.
    """

    def __init__(self, max_chamadas: int, max_tokens: int):
        self.max_chamadas = max_chamadas
        self.max_tokens = max_tokens
        self.chamadas = 0
        self.tokens = 0
        self.bloqueios = 0

    @classmethod
    def do_config(cls, config: dict) -> "OrcamentoExecucao":
        guardrails = config.get("guardrails", {})
        return cls(int(guardrails.get("max_chamadas_por_execucao", 150)), int(guardrails.get("max_tokens_por_execucao", 400000)))

    def motivo_bloqueio(self) -> Optional[Tuple[str, str]]:
        if self.chamadas >= self.max_chamadas:
            return ("LIMITE_DE_CHAMADAS", f"Teto de {self.max_chamadas} chamadas por execução atingido; nenhuma nova chamada foi feita.")
        if self.tokens >= self.max_tokens:
            return ("LIMITE_DE_TOKENS", f"Teto de {self.max_tokens} tokens por execução atingido; nenhuma nova chamada foi feita.")
        return None

    def registrar(self, resposta: LLMResponse):
        self.chamadas += resposta.tentativas
        self.tokens += resposta.tokens_total or 0

    def resumo(self) -> Dict[str, int]:
        return {"chamadas": self.chamadas, "max_chamadas": self.max_chamadas, "tokens": self.tokens,
                "max_tokens": self.max_tokens, "bloqueios": self.bloqueios}


class LLMClient:
    """Cliente resiliente para interação com o modelo de linguagem."""

    PADRAO_CHAVE_SEGREDO = re.compile(r'(AIza[0-9A-Za-z_-]{20,}|AQ\.[0-9A-Za-z_-]{20,}|sk-[A-Za-z0-9_-]{20,}|hf_[A-Za-z0-9]{20,})')
    PLACEHOLDER_CHAVE = "sua_chave_gemini_aqui"
    PROVEDORES_ADAPTADOS = ("openai", "simulado")
    VARIAVEIS_CHAVE = {"openai": "OPENAI_API_KEY", "google": "GEMINI_API_KEY"}

    def __init__(self, config_path: str = "config.json", provedor: Optional[str] = None, modelo: Optional[str] = None):
        """`provedor` e `modelo` sobrepõem LLM_PROVIDER e o modelo do .env/config.json (ex.: segunda configuração do RF21)."""
        self.config = self._carregar_config(config_path)
        self.llm_cfg = self.config.get("llm", {})
        self.provedor = (provedor or os.getenv("LLM_PROVIDER") or self.llm_cfg.get("provider_padrao", "google")).strip().lower()
        self.modelo = (modelo or os.getenv("GEMINI_MODEL", self.llm_cfg.get("modelo_padrao", "gemini-3.8-flash"))).strip()
        self.temperatura = float(self.llm_cfg.get("temperatura", 0.2))
        self.timeout = int(self.llm_cfg.get("timeout_segundos", 90))
        self.max_tentativas = max(1, int(self.llm_cfg.get("max_tentativas", 3)))
        self.espera_inicial = float(self.llm_cfg.get("espera_inicial_segundos", 2.0))
        # Modelos tentados, em ordem, quando o principal responde 429 ou 5xx (cada modelo tem cota própria)
        self.modelos_alternativos = [m for m in self.llm_cfg.get("modelos_alternativos", []) if m and m != self.modelo]

        # Tabela de custo por 1.000 tokens (USD) — fonte registrada no config.json
        custos = self.llm_cfg.get("custo_estimado_por_1k_tokens", {})
        self.custo_input_1k = float(custos.get("input_usd", 0.0))
        self.custo_output_1k = float(custos.get("output_usd", 0.0))
        # A tabela vale só para este modelo; outro modelo (GEMINI_MODEL no .env ou alternativo) fica sem custo estimado
        self.modelo_precificado = custos.get("modelo", self.llm_cfg.get("modelo_padrao"))

        self.gemini_client = None
        self.orcamento: Optional[OrcamentoExecucao] = None  # teto de chamadas e tokens da execução (RF16)
        self.adaptador = None  # OpenAIAdapter ou SimulatedAdapter (provedores do Desafio 02)
        self.indisponibilidade: Optional[Tuple[str, str]] = None  # (código, mensagem)
        if self.provedor in self.PROVEDORES_ADAPTADOS:
            self._inicializar_adaptador(modelo)
        else:
            self._inicializar_provedor()

    @property
    def disponivel(self) -> bool:
        """Indica se o cliente está pronto para chamar o provedor."""
        if self.adaptador is not None:
            return self.adaptador.disponivel
        return self.gemini_client is not None

    @property
    def motivo_indisponibilidade(self) -> Optional[str]:
        if self.adaptador is not None:
            return self.adaptador.motivo_indisponibilidade
        return self.indisponibilidade[1] if self.indisponibilidade else None

    @property
    def variavel_chave(self) -> Optional[str]:
        """Variável de ambiente com a chave do provedor ativo (None no adaptador simulado)."""
        return self.VARIAVEIS_CHAVE.get(self.provedor)

    def _inicializar_adaptador(self, modelo: Optional[str]):
        """Provedores do Desafio 02: a chamada fica isolada no adaptador, com parâmetros do config.json (RF21)."""
        from src.adaptadores import OpenAIAdapter, SimulatedAdapter
        if self.provedor == "openai":
            self.adaptador = OpenAIAdapter(self.llm_cfg.get("openai", {}), modelo=modelo)
        else:
            self.adaptador = SimulatedAdapter(self.llm_cfg.get("simulado", {}), modelo=modelo)
        self.modelo = self.adaptador.modelo
        self.timeout = self.adaptador.timeout
        self.max_tentativas = self.adaptador.max_tentativas
        self.modelos_alternativos = []

    def _carregar_config(self, caminho_config: str) -> dict:
        caminho = Path(caminho_config)
        if not caminho.is_absolute():
            caminho = Path(__file__).resolve().parent.parent / caminho_config
        if caminho.exists():
            with open(caminho, "r", encoding="utf-8") as f:
                return json.load(f)
        return {}

    def _sanitizar_mensagem(self, texto: str) -> str:
        """Remove qualquer padrão de credencial ou chave privada de strings de log."""
        if not texto:
            return ""
        return self.PADRAO_CHAVE_SEGREDO.sub("[CHAVE_OCULTADA_POR_SEGURANCA]", str(texto))

    def _inicializar_provedor(self):
        """Configura a conexão com a API do Google GenAI ou registra o motivo da indisponibilidade."""
        if self.provedor != "google":
            self.indisponibilidade = (
                "PROVEDOR_NAO_SUPORTADO",
                f"O provedor '{self.provedor}' não é suportado. Defina no .env LLM_PROVIDER=openai (padrão do "
                "Desafio 02), google (Gemini legado do Desafio 01) ou simulado."
            )
            return

        if genai is None:
            self.indisponibilidade = (
                "BIBLIOTECA_AUSENTE",
                "A biblioteca google-genai não está instalada. Execute: pip install -r requirements.txt"
            )
            return

        chave = os.getenv("GEMINI_API_KEY", "").strip()
        if not chave or chave == self.PLACEHOLDER_CHAVE:
            self.indisponibilidade = (
                "CHAVE_AUSENTE",
                "A chave GEMINI_API_KEY não está configurada. Copie .env.example para .env "
                "e preencha a chave (README, seção 3)."
            )
            logger.info("GEMINI_API_KEY ausente: chamadas ao modelo ficarão indisponíveis.")
            return

        try:
            self.gemini_client = genai.Client(
                api_key=chave,
                http_options=genai_types.HttpOptions(timeout=self.timeout * 1000)  # milissegundos
            )
            logger.info("Cliente Google GenAI inicializado para o modelo %s (timeout %d s).", self.modelo, self.timeout)
        except Exception as e:
            self.gemini_client = None
            self.indisponibilidade = (
                "ERRO_INICIALIZACAO",
                f"Falha ao inicializar o cliente do provedor: {self._sanitizar_mensagem(str(e))}"
            )
            logger.error(self.indisponibilidade[1])

    def calcular_custo(self, tokens_prompt: int, tokens_resposta: int, tokens_raciocinio: int = 0,
                       modelo: Optional[str] = None) -> Optional[float]:
        """
        Custo estimado em USD com a tabela do config.json. Tokens de raciocínio são cobrados como saída.
        Retorna None se o modelo usado não for o da tabela (preço desconhecido não é estimado).
        """
        if self.adaptador is not None:
            return self.adaptador.calcular_custo(tokens_prompt, tokens_resposta, tokens_raciocinio, modelo)
        if modelo is not None and modelo != self.modelo_precificado:
            return None
        custo_in = (tokens_prompt / 1000.0) * self.custo_input_1k
        custo_out = ((tokens_resposta + tokens_raciocinio) / 1000.0) * self.custo_output_1k
        return custo_in + custo_out

    def gerar(
        self,
        prompt: str,
        system_instruction: Optional[str] = None,
        temperatura: Optional[float] = None,
        schema: Optional[Any] = None,
        seed: Optional[int] = None,
        permitir_alternativos: bool = True,
        modelo: Optional[str] = None,
        reasoning_effort: Optional[str] = None,
        max_completion_tokens: Optional[int] = None,
        modo_json: bool = False
    ) -> LLMResponse:
        """
        Executa uma chamada textual ao modelo.
        Com `schema` (ex.: modelo Pydantic), solicita saída JSON estruturada.
        `seed` fixa a amostragem quando o provedor suporta (usado no experimento RF02).
        `permitir_alternativos=False` impede a troca de modelo (o experimento exige o mesmo modelo).
        Nos provedores do Desafio 02 a chamada vai ao adaptador: `modelo` escolhe a configuração
        (ex.: gpt-5.6-terra), `reasoning_effort` e `max_completion_tokens` seguem a família GPT-5.6 e
        `modo_json` pede JSON apenas sintático (comparativo do RF14). `temperatura` e `seed` não se aplicam ao GPT-5.6.
        """
        def chamar() -> LLMResponse:
            if self.adaptador is not None:
                return self.adaptador.gerar(prompt, system_instruction=system_instruction, schema=schema, modelo=modelo,
                                            reasoning_effort=reasoning_effort, max_completion_tokens=max_completion_tokens,
                                            modo_json=modo_json)
            resposta = self._executar(prompt, system_instruction, temperatura, schema, modelo=modelo,
                                      config_extra={"seed": seed} if seed is not None else None,
                                      permitir_alternativos=permitir_alternativos)
            if seed is not None:
                resposta.parametros["seed"] = seed
            return resposta
        return self._com_orcamento(chamar, modelo)

    def chamar_servico(self, operacao: str, funcao: Callable[[Any], Any], modelo: str) -> Tuple[Any, LLMResponse]:
        """
        Chamada auxiliar (moderação, embeddings) pelo adaptador, sob o mesmo orçamento da execução.
        Retorna (resultado bruto ou None, LLMResponse com a telemetria).
        """
        if self.adaptador is None or not hasattr(self.adaptador, "chamar_servico"):
            return None, self._resposta_falha("NAO_SUPORTADO", f"O provedor '{self.provedor}' não oferece {operacao} nesta versão.",
                                              time.perf_counter(), 0, {"operacao": operacao}, modelo)
        resultado: Dict[str, Any] = {}

        def chamar() -> LLMResponse:
            resultado["valor"], resposta = self.adaptador.chamar_servico(operacao, funcao, modelo)
            return resposta
        resposta = self._com_orcamento(chamar, modelo)
        return resultado.get("valor"), resposta

    def _com_orcamento(self, chamar: Callable[[], LLMResponse], modelo: Optional[str] = None) -> LLMResponse:
        """Confere o teto de chamadas e tokens antes da chamada e registra o consumo depois (RF16)."""
        if self.orcamento is not None:
            bloqueio = self.orcamento.motivo_bloqueio()
            if bloqueio:
                self.orcamento.bloqueios += 1
                logger.warning("[ORÇAMENTO] %s", bloqueio[1])
                return self._resposta_falha(bloqueio[0], bloqueio[1], time.perf_counter(), 0,
                                            {"orcamento": self.orcamento.resumo()}, modelo)
        resposta = chamar()
        if self.orcamento is not None:
            self.orcamento.registrar(resposta)
        return resposta

    def gerar_multimodal(
        self,
        arquivo: Path,
        mime_type: str,
        instrucao: str,
        system_instruction: Optional[str] = None,
        temperatura: Optional[float] = None,
        schema: Optional[Any] = None,
        resolucao: Optional[str] = None
    ) -> LLMResponse:
        """
        Envia um arquivo (áudio, PDF ou imagem) junto com a instrução textual (RF06, RF08).
        Exemplos de mime_type: 'audio/mp3', 'application/pdf', 'image/png'.
        `resolucao` (ex.: 'MEDIA_RESOLUTION_HIGH') controla o detalhe com que imagens são analisadas.
        No provedor openai o PDF é convertido em PNG por página; áudio não é suportado (Gemini legado).
        """
        def chamar() -> LLMResponse:
            if self.adaptador is not None:
                return self.adaptador.gerar_multimodal(arquivo, mime_type, instrucao, system_instruction=system_instruction,
                                                       schema=schema, resolucao=resolucao)
            partes = None
            if genai_types is not None:
                dados = Path(arquivo).read_bytes()
                parte = genai_types.Part.from_bytes(
                    data=dados,
                    mime_type=mime_type,
                    media_resolution=genai_types.PartMediaResolution(level=resolucao) if resolucao else None
                )
                partes = [parte, instrucao]
            resposta = self._executar(partes, system_instruction, temperatura, schema)
            if resolucao:
                resposta.parametros["resolucao_midia"] = resolucao
            return resposta
        return self._com_orcamento(chamar)

    def gerar_imagem(
        self,
        prompt: str,
        modelo: str,
        proporcao: str = "16:9",
        seed: Optional[int] = None,
        max_tentativas: int = 1
    ) -> LLMResponse:
        """
        Gera uma imagem com um modelo de imagem do provedor (RF10).
        A imagem volta em `dados_binarios`; o custo não é estimado (o preço por imagem difere do de texto).
        """
        if self.adaptador is not None:
            return self.adaptador.gerar_imagem(prompt, modelo)
        config_extra: Dict[str, Any] = {"response_modalities": ["IMAGE"], "seed": seed}
        if genai_types is not None:
            config_extra["image_config"] = genai_types.ImageConfig(aspect_ratio=proporcao)
        resposta = self._executar(prompt, None, None, None, modelo=modelo, config_extra=config_extra,
                                  saida_imagem=True, max_tentativas=max_tentativas)
        resposta.parametros.update({"proporcao": proporcao, "seed": seed})
        return resposta

    def _executar(
        self,
        contents: Any,
        system_instruction: Optional[str],
        temperatura: Optional[float],
        schema: Optional[Any],
        modelo: Optional[str] = None,
        config_extra: Optional[Dict[str, Any]] = None,
        saida_imagem: bool = False,
        max_tentativas: Optional[int] = None,
        permitir_alternativos: bool = True
    ) -> LLMResponse:
        """
        Executa a chamada no modelo principal e, se ele responder com limite de requisições (429)
        ou indisponibilidade (5xx), nos modelos alternativos do config.json, em ordem.
        Um modelo passado explicitamente (ex.: modelo de imagem) não tem alternativos.
        """
        temp = self.temperatura if temperatura is None else temperatura
        cadeia = [modelo] if modelo else [self.modelo] + (self.modelos_alternativos if permitir_alternativos else [])
        max_tentativas = max_tentativas or self.max_tentativas
        parametros = {
            "temperatura": temp,
            "timeout_s": self.timeout,
            "max_tentativas": max_tentativas,
            "saida_json": schema is not None
        }
        inicio = time.perf_counter()

        if self.gemini_client is None:
            codigo, mensagem = self.indisponibilidade or ("CLIENTE_NAO_INICIALIZADO", "O cliente do provedor não foi inicializado.")
            return self._resposta_falha(codigo, mensagem, inicio, 0, parametros, cadeia[0])

        config_chamada = genai_types.GenerateContentConfig(
            temperature=temp,
            system_instruction=system_instruction or None,
            response_mime_type="application/json" if schema is not None else None,
            response_schema=schema,
            **(config_extra or {})
        )

        tentados = []
        for indice, modelo_atual in enumerate(cadeia):
            tentados.append(modelo_atual)
            resposta = self._executar_modelo(contents, config_chamada, modelo_atual, max_tentativas, parametros, inicio, saida_imagem)
            ultimo = indice == len(cadeia) - 1
            if resposta.sucesso or resposta.codigo_erro not in ("LIMITE_REQUISICOES", "INDISPONIVEL") or ultimo:
                break
            logger.warning("[MODELO ALTERNATIVO] %s indisponível (%s); tentando %s.",
                           modelo_atual, resposta.codigo_erro, cadeia[indice + 1])

        if len(tentados) > 1:
            resposta.parametros = {**resposta.parametros, "modelo_solicitado": cadeia[0], "modelos_tentados": tentados}
        return resposta

    def _executar_modelo(
        self,
        contents: Any,
        config_chamada: Any,
        modelo: str,
        max_tentativas: int,
        parametros: Dict[str, Any],
        inicio: float,
        saida_imagem: bool
    ) -> LLMResponse:
        """Chamada a um modelo com novas tentativas e espera exponencial."""
        espera = self.espera_inicial
        for tentativa in range(1, max_tentativas + 1):
            try:
                resposta = self.gemini_client.models.generate_content(
                    model=modelo,
                    contents=contents,
                    config=config_chamada
                )
            except Exception as e:
                codigo, mensagem, retentavel = self._classificar_excecao(e, modelo)
                if codigo == "LIMITE_REQUISICOES" and "PerDay" in str(e):
                    # Cota diária esgotada: novas tentativas no mesmo modelo não adiantam
                    retentavel = False
                    mensagem = f"Cota diária do modelo '{modelo}' esgotada no nível gratuito (HTTP 429)."
                logger.warning(
                    "[TENTATIVA %d/%d] %s (%s): %s",
                    tentativa, max_tentativas, codigo, modelo, self._sanitizar_mensagem(str(e))[:300]
                )
                if retentavel and tentativa < max_tentativas:
                    time.sleep(max(espera, self._espera_sugerida(e)))
                    espera *= 2
                    continue
                return self._resposta_falha(codigo, mensagem, inicio, tentativa, dict(parametros), modelo)

            if saida_imagem:
                dados, mime = self._extrair_imagem(resposta)
                if not dados:
                    return self._resposta_falha(
                        "RESPOSTA_VAZIA",
                        f"O provedor não retornou imagem (motivo informado: {self._motivo_termino(resposta)}).",
                        inicio, tentativa, dict(parametros), modelo
                    )
                retorno = self._resposta_sucesso(resposta, "", inicio, tentativa, dict(parametros), modelo)
                retorno.dados_binarios, retorno.mime_type, retorno.custo_estimado_usd = dados, mime, None
                return retorno

            conteudo = self._extrair_texto(resposta)
            if not conteudo.strip():
                return self._resposta_falha(
                    "RESPOSTA_VAZIA",
                    f"O provedor retornou uma resposta vazia (motivo informado: {self._motivo_termino(resposta)}).",
                    inicio, tentativa, dict(parametros), modelo
                )
            return self._resposta_sucesso(resposta, conteudo, inicio, tentativa, dict(parametros), modelo)

    def _classificar_excecao(self, e: Exception, modelo: Optional[str] = None) -> Tuple[str, str, bool]:
        """Traduz a exceção em (código, mensagem compreensível, deve_retentar)."""
        modelo = modelo or self.modelo
        if genai_errors is not None and isinstance(e, genai_errors.ClientError):
            detalhe = str(e)
            if e.code in (401, 403) or "API_KEY_INVALID" in detalhe or "API key not valid" in detalhe:
                return ("AUTENTICACAO",
                        "A chave de API foi recusada pelo provedor (inválida, revogada ou sem permissão). "
                        "Gere uma nova chave e atualize o arquivo .env.", False)
            if e.code == 429:
                return ("LIMITE_REQUISICOES",
                        "Limite de requisições do provedor atingido (HTTP 429). Aguarde alguns minutos e tente novamente.", True)
            if e.code == 404:
                return ("MODELO_NAO_ENCONTRADO",
                        f"O modelo '{modelo}' não foi encontrado no provedor. "
                        "Verifique GEMINI_MODEL no .env ou llm.modelo_padrao no config.json.", False)
            return ("REQUISICAO_INVALIDA",
                    f"O provedor recusou a requisição (HTTP {e.code}). Verifique o modelo e os parâmetros enviados.", False)

        if genai_errors is not None and isinstance(e, genai_errors.ServerError):
            return ("INDISPONIVEL",
                    f"O serviço do provedor está indisponível no momento (HTTP {e.code}). Tente novamente mais tarde.", True)

        if isinstance(e, httpx.TimeoutException):
            return ("TIMEOUT", f"O provedor não respondeu dentro do tempo limite de {self.timeout} s.", True)

        if isinstance(e, (httpx.TransportError, ConnectionError)):
            return ("SEM_CONEXAO", "Não foi possível conectar ao provedor. Verifique a conexão com a internet.", True)

        return ("ERRO_INESPERADO", f"Falha inesperada ao chamar o provedor ({type(e).__name__}).", False)

    @staticmethod
    def _espera_sugerida(e: Exception, limite_segundos: float = 60.0) -> float:
        """Tempo de espera indicado pelo provedor no erro 429 (RetryInfo.retryDelay), limitado a 60 s."""
        detalhes = getattr(e, "details", None)
        erro = detalhes.get("error", {}) if isinstance(detalhes, dict) else {}
        for item in erro.get("details", []) if isinstance(erro, dict) else []:
            atraso = item.get("retryDelay") if isinstance(item, dict) else None
            if isinstance(atraso, str) and atraso.endswith("s"):
                try:
                    return min(float(atraso[:-1]), limite_segundos)
                except ValueError:
                    pass
        return 0.0

    @staticmethod
    def _extrair_texto(resposta: Any) -> str:
        try:
            return (getattr(resposta, "text", None) or "") if resposta is not None else ""
        except Exception:
            return ""

    @staticmethod
    def _extrair_imagem(resposta: Any) -> Tuple[Optional[bytes], Optional[str]]:
        """Primeira imagem (inline_data) das partes da resposta."""
        try:
            for parte in resposta.candidates[0].content.parts or []:
                dados = getattr(parte, "inline_data", None)
                if dados is not None and dados.data:
                    return dados.data, dados.mime_type
        except (AttributeError, IndexError, TypeError):
            pass
        return None, None

    @staticmethod
    def _motivo_termino(resposta: Any) -> str:
        """Obtém o motivo de término ou bloqueio informado pelo provedor, quando existir."""
        try:
            if getattr(resposta, "candidates", None):
                motivo = resposta.candidates[0].finish_reason
                if motivo:
                    return str(motivo)
            feedback = getattr(resposta, "prompt_feedback", None)
            if feedback is not None and getattr(feedback, "block_reason", None):
                return f"bloqueio: {feedback.block_reason}"
        except Exception:
            pass
        return "não informado"

    def _resposta_sucesso(self, resposta: Any, conteudo: str, inicio: float, tentativas: int, parametros: Dict[str, Any], modelo: Optional[str] = None) -> LLMResponse:
        tokens_prompt = tokens_resposta = tokens_raciocinio = tokens_total = None
        custo = None
        uso = getattr(resposta, "usage_metadata", None)
        if uso is not None:
            tokens_prompt = getattr(uso, "prompt_token_count", None) or 0
            tokens_resposta = getattr(uso, "candidates_token_count", None) or 0
            tokens_raciocinio = getattr(uso, "thoughts_token_count", None) or 0
            tokens_total = getattr(uso, "total_token_count", None) or (tokens_prompt + tokens_resposta + tokens_raciocinio)
            custo = self.calcular_custo(tokens_prompt, tokens_resposta, tokens_raciocinio, modelo or self.modelo)
            if custo is None:
                parametros["observacao_custo"] = f"sem tabela de preço para '{modelo or self.modelo}'; custo não estimado"

        versao = getattr(resposta, "model_version", None)
        if isinstance(versao, str) and versao:
            parametros["versao_modelo"] = versao
        return LLMResponse(
            conteudo=conteudo,
            modelo=modelo or self.modelo,
            provedor=self.provedor,
            sucesso=True,
            latencia_ms=(time.perf_counter() - inicio) * 1000.0,
            tentativas=tentativas,
            tokens_prompt=tokens_prompt,
            tokens_resposta=tokens_resposta,
            tokens_raciocinio=tokens_raciocinio,
            tokens_total=tokens_total,
            custo_estimado_usd=custo,
            parametros=parametros
        )

    def _resposta_falha(self, codigo: str, mensagem: str, inicio: float, tentativas: int, parametros: Dict[str, Any], modelo: Optional[str] = None) -> LLMResponse:
        return LLMResponse(
            conteudo="",
            modelo=modelo or self.modelo,
            provedor=self.provedor,
            sucesso=False,
            latencia_ms=(time.perf_counter() - inicio) * 1000.0,
            tentativas=tentativas,
            codigo_erro=codigo,
            erro=self._sanitizar_mensagem(mensagem),
            parametros=parametros
        )
