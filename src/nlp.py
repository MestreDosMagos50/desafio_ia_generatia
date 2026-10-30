#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
==============================================================================
EXTRAÇÃO ESTRUTURADA, REGRAS DE NEGÓCIO E FICHA DE COMPREENSÃO (RF14, RF15)
==============================================================================
- extrair: converte a solicitação no ContratoSolicitacaoV2. Com esquema nativo
  (Structured Outputs da OpenAI) a saída já vem restrita; nos demais
  provedores é validada localmente, com no máximo 1 tentativa de correção.
  Saída ainda inválida é rejeitada antes da minuta.
- classificar_erros_contrato: distingue JSON inválido, chave extra, tipo
  incorreto, campo obrigatório ausente e valor fora do domínio (T01).
- conferir_regras_negocio: datas reais de calendário, formato do protocolo,
  ancoragem dos valores e das entidades no texto original e coerência
  interna do contrato (T02). Violação grave bloqueia a minuta.
- gerar_ficha: resumo de até 100 palavras (contado em código), entidades
  literais conferidas no texto e informações inferidas, separadas (RF15).
- avaliar_contra_gabarito: acurácia da categoria, omissões, entidades
  incorretas e fatos sem suporte, com numerador e denominador (T03).
Entrada, erro e decisão de cada caso ficam em resultados/nlp/ e cada chamada
ao modelo vai para a auditoria (RF21).
==============================================================================
"""

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple, Union

from pydantic import ValidationError

from src.conferencia import normalizar
from src.llm_client import LLMClient, LLMResponse
from src.prompts import (
    PROMPT_CORRECAO_ESQUEMA,
    PROMPT_EXTRACAO_JSON_GENERICO,
    PROMPT_EXTRACAO_V2_SISTEMA,
    PROMPT_EXTRACAO_V2_USUARIO,
    PROMPT_FICHA_NLP_SISTEMA,
    PROMPT_FICHA_NLP_USUARIO,
    VERSOES_PROMPTS,
    delimitar_dados_externos,
)
from src.schemas import (
    TIPOS_ENTIDADE,
    VERSAO_ESQUEMA,
    ContratoSolicitacaoV2,
    EntidadesLiterais,
    FichaCompreensaoNLP,
    ResumoNLP,
)

RAIZ_PROJETO = Path(__file__).resolve().parent.parent
LIMITE_PALAVRAS_RESUMO = 100
PROVEDORES_ESQUEMA_NATIVO = ("openai",)
PADRAO_PROTOCOLO = re.compile(r"^\d{4}-\d{6}$")  # formato institucional AAAA-NNNNNN
MESES = {"janeiro": 1, "fevereiro": 2, "marco": 3, "abril": 4, "maio": 5, "junho": 6, "julho": 7,
         "agosto": 8, "setembro": 9, "outubro": 10, "novembro": 11, "dezembro": 12}
DATA_NUMERICA = re.compile(r"(?<![\d/])(\d{1,2})/(\d{1,2})/(\d{4})(?![\d/])")
DATA_EXTENSO = re.compile(r"\b(\d{1,2}) de (" + "|".join(MESES) + r") de (\d{4})\b")
NUMERO = re.compile(r"\d+(?:[.,/-]\d+)*")  # inclui decimais com vírgula (R$ 150,00) como um único número

# Decisões: o mesmo vocabulário dos gabaritos
GERAR_MINUTA = "GERAR_MINUTA_PARA_REVISAO"
ENCAMINHAR_REVISAO = "ENCAMINHAR_REVISAO_HUMANA"
BLOQUEAR_REGRA = "BLOQUEAR_MINUTA_E_REVISAR"
REJEITAR_SAIDA = "REJEITAR_SAIDA_SEM_MINUTA"

# Tipo de erro do Pydantic -> código do RF14; os demais (string_type, bool_type, list_type...) são tipo incorreto
CODIGOS_ERRO_PYDANTIC = {
    "extra_forbidden": "CHAVE_EXTRA",
    "missing": "CAMPO_OBRIGATORIO_AUSENTE",
    "literal_error": "VALOR_FORA_DO_DOMINIO",
    "json_invalid": "JSON_INVALIDO",
}


# ------------------------------------------------------------------------------
# Validação do contrato (T01)
# ------------------------------------------------------------------------------
def classificar_erros_contrato(conteudo: Union[str, Dict[str, Any]]) -> List[Dict[str, str]]:
    """Valida contra o ContratoSolicitacaoV2 e classifica cada erro. Lista vazia significa contrato válido."""
    try:
        if isinstance(conteudo, str):
            ContratoSolicitacaoV2.model_validate_json(conteudo)
        else:
            ContratoSolicitacaoV2.model_validate(conteudo)
        return []
    except ValidationError as e:
        return [{
            "codigo": CODIGOS_ERRO_PYDANTIC.get(erro["type"], "TIPO_INCORRETO"),
            "campo": ".".join(str(parte) for parte in erro["loc"]) or "(raiz)",
            "detalhe": erro["msg"],
        } for erro in e.errors()]


def classificar_erros_resumo(conteudo: str) -> List[str]:
    try:
        ResumoNLP.model_validate_json(conteudo)
        return []
    except ValidationError as e:
        return [erro["type"] for erro in e.errors()]


# ------------------------------------------------------------------------------
# Regras de negócio (T02)
# ------------------------------------------------------------------------------
@dataclass
class AlertaRegra:
    codigo: str
    campo: str
    mensagem: str
    bloqueia_minuta: bool


def _data_canonica(dia: str, mes: Union[str, int], ano: str) -> Optional[str]:
    """DD/MM/AAAA se a data existe no calendário; None se for impossível (ex.: 31/02)."""
    try:
        return datetime(int(ano), int(mes), int(dia)).strftime("%d/%m/%Y")
    except ValueError:
        return None


def datas_do_texto(texto: str) -> Tuple[Set[str], List[str]]:
    """Datas reais citadas no texto, em DD/MM/AAAA (numéricas e por extenso), e as datas impossíveis encontradas."""
    normalizado = normalizar(texto)
    validas, impossiveis = set(), []
    candidatas = [(d, m, a, f"{d}/{m}/{a}") for d, m, a in DATA_NUMERICA.findall(normalizado)]
    candidatas += [(d, MESES[mes], a, f"{d} de {mes} de {a}") for d, mes, a in DATA_EXTENSO.findall(normalizado)]
    for dia, mes, ano, literal in candidatas:
        canonica = _data_canonica(dia, mes, ano)
        if canonica:
            validas.add(canonica)
        else:
            impossiveis.append(literal)
    return validas, impossiveis


def _chave_de_data(valor: str) -> Optional[str]:
    """Forma canônica de uma data escrita como DD/MM/AAAA ou por extenso; None se não for data."""
    normalizado = normalizar(valor)
    numerica = DATA_NUMERICA.fullmatch(normalizado)
    if numerica:
        return _data_canonica(*numerica.groups())
    extenso = DATA_EXTENSO.fullmatch(normalizado)
    if extenso:
        dia, mes, ano = extenso.groups()
        return _data_canonica(dia, MESES[mes], ano)
    return None


def ancorado(valor: str, texto: str, datas_validas: Optional[Set[str]] = None) -> bool:
    """O valor aparece no texto original (sem diferenciar maiúsculas, acentos e espaços); datas valem em qualquer formato."""
    if normalizar(valor) in normalizar(texto):
        return True
    chave = _chave_de_data(valor)
    return chave is not None and chave in (datas_validas if datas_validas is not None else datas_do_texto(texto)[0])


def separar_entidades(entidades: EntidadesLiterais, texto: str) -> Tuple[EntidadesLiterais, Dict[str, List[str]]]:
    """Entidades com apoio literal no texto e as que não aparecem nele (fatos sem suporte)."""
    datas_validas = datas_do_texto(texto)[0]
    literais, sem_apoio = {}, {}
    for tipo in TIPOS_ENTIDADE:
        valores = getattr(entidades, tipo)
        literais[tipo] = [v for v in valores if ancorado(v, texto, datas_validas)]
        faltantes = [v for v in valores if v not in literais[tipo]]
        if faltantes:
            sem_apoio[tipo] = faltantes
    return EntidadesLiterais(**literais), sem_apoio


def conferir_regras_negocio(contrato: ContratoSolicitacaoV2, texto_original: str) -> List[AlertaRegra]:
    """Regras que dependem do domínio, e não do formato (Aula 08 §7). Devolve alertas em vez de lançar exceção."""
    alertas: List[AlertaRegra] = []
    datas_validas, impossiveis = datas_do_texto(texto_original)

    # 1. Datas reais de calendário: no texto original e nos valores extraídos
    for literal in impossiveis:
        alertas.append(AlertaRegra("DATA_INVALIDA", "texto_original",
                                   f"O texto original contém data inexistente no calendário: {literal}.", True))
    datas_extraidas = [("data_solicitacao", contrato.data_solicitacao)] + [("entidades.datas", d) for d in contrato.entidades.datas]
    for campo, valor in datas_extraidas:
        if valor is None:
            continue
        numerica = DATA_NUMERICA.fullmatch(normalizar(valor))
        if campo == "data_solicitacao" and not numerica:
            alertas.append(AlertaRegra("DATA_INVALIDA", campo, f"Data fora do formato DD/MM/AAAA: {valor}.", True))
        elif numerica and _data_canonica(*numerica.groups()) is None:
            alertas.append(AlertaRegra("DATA_INVALIDA", campo, f"Data inexistente no calendário: {valor}.", True))
        elif campo == "data_solicitacao" and not ancorado(valor, texto_original, datas_validas):
            alertas.append(AlertaRegra("NAO_ANCORADO", campo, f"A data {valor} não aparece no texto original.", True))

    # 2. Formato do protocolo
    if contrato.protocolo is not None and not PADRAO_PROTOCOLO.match(contrato.protocolo.strip()):
        alertas.append(AlertaRegra("PROTOCOLO_FORMATO", "protocolo",
                                   f"Protocolo fora do formato AAAA-NNNNNN: {contrato.protocolo}.", True))

    # 3. Ancoragem: valores copiados do texto precisam estar nele; entidade sem apoio exige revisão
    for campo in ("protocolo", "solicitante_ficticio", "curso"):
        valor = getattr(contrato, campo)
        if valor is not None and not ancorado(valor, texto_original, datas_validas):
            alertas.append(AlertaRegra("NAO_ANCORADO", campo, f"'{valor}' não aparece no texto original.", True))
    for tipo, valores in separar_entidades(contrato.entidades, texto_original)[1].items():
        alertas.append(AlertaRegra("ENTIDADE_SEM_APOIO", f"entidades.{tipo}",
                                   f"Entidades que não aparecem no texto original: {', '.join(valores)}.", False))

    # 4. Coerência interna do contrato
    if sorted(contrato.campos_ausentes) != sorted(contrato.campos_nulos()):
        alertas.append(AlertaRegra("CAMPOS_AUSENTES_INCOERENTES", "campos_ausentes",
                                   f"campos_ausentes={contrato.campos_ausentes}, mas os campos null são {contrato.campos_nulos()}.", True))
    if contrato.categoria == "REVISAO" and not contrato.necessita_revisao:
        alertas.append(AlertaRegra("REVISAO_SEM_MARCACAO", "necessita_revisao",
                                   "Categoria REVISAO exige necessita_revisao = true.", True))
    if contrato.pedido is None and not contrato.necessita_revisao:
        alertas.append(AlertaRegra("PEDIDO_AUSENTE_SEM_REVISAO", "necessita_revisao",
                                   "Solicitação sem pedido escrito exige necessita_revisao = true.", True))
    return alertas


def decidir(contrato: ContratoSolicitacaoV2, alertas: List[AlertaRegra]) -> Tuple[str, str]:
    """Decisão antes da minuta. Mesmo quando segue, a minuta só vale após aprovação humana (RF24)."""
    bloqueios = [a for a in alertas if a.bloqueia_minuta]
    if bloqueios:
        return BLOQUEAR_REGRA, "; ".join(a.mensagem for a in bloqueios)
    motivos = [a.mensagem for a in alertas]
    if contrato.pedido is None:
        motivos.append("Nenhum pedido escrito.")
    if contrato.categoria == "REVISAO":
        motivos.append("Sem assunto predominante (categoria REVISAO).")
    if contrato.necessita_revisao and not motivos:
        motivos.append("O extrator marcou necessita_revisao.")
    if motivos or contrato.necessita_revisao:
        return ENCAMINHAR_REVISAO, "; ".join(motivos)
    return GERAR_MINUTA, "Contrato válido e coerente com o texto original; a minuta segue para aprovação humana."


def numeros_sem_lastro(resumo: str, texto: str) -> List[str]:
    """Números e datas do resumo que não aparecem no texto original (verificação da Aula 12 §4.3)."""
    datas_validas = datas_do_texto(texto)[0]
    original = normalizar(texto)
    orfaos = []
    for bruto in NUMERO.findall(normalizar(resumo)):
        chave = _chave_de_data(bruto)
        if (chave and chave in datas_validas) or re.search(rf"(?<!\d){re.escape(bruto)}(?!\d)", original):
            continue
        if bruto not in orfaos:
            orfaos.append(bruto)
    return orfaos


# ------------------------------------------------------------------------------
# Extração e ficha de compreensão
# ------------------------------------------------------------------------------
@dataclass
class ResultadoExtracao:
    """Registro do caso: preserva entrada, erro e decisão (critério de aceite do RF14)."""
    id_caso: str
    canal: str
    arquivo_origem: str
    sha256_entrada: str
    texto_entrada: str
    versao_esquema: str
    prompt: Dict[str, str]
    modo_esquema: str
    contrato: Optional[Dict[str, Any]]
    erros_validacao: List[Dict[str, str]]
    alertas: List[Dict[str, Any]]
    decisao: str
    motivo: str
    chamadas: List[Dict[str, Any]] = field(default_factory=list)
    registrado_em: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))


def _telemetria(etapa: str, resposta: LLMResponse) -> Dict[str, Any]:
    return {
        "etapa": etapa,
        "provedor": resposta.provedor,
        "modelo": resposta.modelo,
        "sucesso": resposta.sucesso,
        "codigo_erro": resposta.codigo_erro,
        "tentativas": resposta.tentativas,
        "latencia_ms": round(resposta.latencia_ms, 1),
        "tokens_total": resposta.tokens_total,
        "custo_estimado_usd": resposta.custo_estimado_usd,
    }


def _formatar_erros(erros: List[Dict[str, str]]) -> str:
    return "\n".join(f"- {e['codigo']} em {e['campo']}: {e['detalhe']}" for e in erros)


class ExtratorSolicitacoes:
    """Extração do contrato (RF14) e ficha de compreensão (RF15) de cada solicitação."""

    def __init__(self, llm_client: Optional[LLMClient] = None, audit: Any = None,
                 config_path: str = "config.json", dir_saida: Optional[Path] = None):
        self.llm = llm_client or LLMClient(config_path)
        self.audit = audit  # AuditManager; os testes offline usam None para não gravar no log real
        caminho = Path(config_path) if Path(config_path).is_absolute() else RAIZ_PROJETO / config_path
        config = json.loads(caminho.read_text(encoding="utf-8"))
        self.categorias: Dict[str, str] = config["classificacao"]["categorias_desafio02"]
        self.dir_saida = dir_saida or RAIZ_PROJETO / "resultados" / "nlp"

    @property
    def esquema_nativo(self) -> bool:
        return self.llm.provedor in PROVEDORES_ESQUEMA_NATIVO

    def prompt_sistema_extracao(self) -> str:
        definicoes = "\n".join(f"   - {nome}: {descricao}" for nome, descricao in self.categorias.items())
        return PROMPT_EXTRACAO_V2_SISTEMA.format(categorias=definicoes)

    def _gerar(self, etapa: str, prompt_id: str, id_caso: str, canal: str, arquivo_origem: str,
               prompt: str, sistema: Optional[str] = None, **kwargs) -> LLMResponse:
        resposta = self.llm.gerar(prompt, system_instruction=sistema, **kwargs)
        resposta.parametros["versao_esquema"] = VERSAO_ESQUEMA
        if self.audit is not None:
            self.audit.registrar_execucao(
                caso_id=id_caso, etapa=etapa, modalidade=canal, arquivo_origem=arquivo_origem, resposta=resposta,
                prompt_id=prompt_id, prompt_versao=VERSOES_PROMPTS[prompt_id],
                prompt_texto=(sistema or "") + prompt
            )
        return resposta

    def _salvar(self, subpasta: str, id_caso: str, dados: Dict[str, Any]) -> Path:
        destino = self.dir_saida / subpasta / f"{id_caso}.json"
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_text(json.dumps(dados, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        return destino

    def extrair(self, id_caso: str, texto: str, canal: str, arquivo_origem: str) -> ResultadoExtracao:
        sistema = self.prompt_sistema_extracao()
        usuario = PROMPT_EXTRACAO_V2_USUARIO.format(canal=canal, conteudo_delimitado=delimitar_dados_externos(texto))
        parametros = {"schema": ContratoSolicitacaoV2, "reasoning_effort": "none", "max_completion_tokens": 4000}

        resposta = self._gerar("extracao_contrato_v2", "PROMPT_EXTRACAO_V2", id_caso, canal, arquivo_origem,
                               usuario, sistema, **parametros)
        chamadas = [_telemetria("extracao_contrato_v2", resposta)]
        erros = classificar_erros_contrato(resposta.conteudo) if resposta.sucesso else []
        if resposta.sucesso and erros and not self.esquema_nativo:
            # Sem esquema nativo: validação local com no máximo 1 tentativa de correção (RF14)
            correcao = PROMPT_CORRECAO_ESQUEMA.format(erros=_formatar_erros(erros), resposta_anterior=resposta.conteudo[:4000])
            resposta = self._gerar("correcao_contrato_v2", "PROMPT_CORRECAO_ESQUEMA", id_caso, canal, arquivo_origem,
                                   f"{usuario}\n{correcao}", sistema, **parametros)
            chamadas.append(_telemetria("correcao_contrato_v2", resposta))
            erros = classificar_erros_contrato(resposta.conteudo) if resposta.sucesso else erros

        contrato, alertas = None, []
        if not resposta.sucesso:
            decisao, motivo = REJEITAR_SAIDA, f"Falha do provedor ({resposta.codigo_erro}): {resposta.erro}"
        elif erros:
            decisao, motivo = REJEITAR_SAIDA, f"Saída fora do contrato ({len(erros)} erro(s)); nenhuma minuta é gerada."
        else:
            contrato = ContratoSolicitacaoV2.model_validate_json(resposta.conteudo)
            alertas = conferir_regras_negocio(contrato, texto)
            decisao, motivo = decidir(contrato, alertas)

        resultado = ResultadoExtracao(
            id_caso=id_caso, canal=canal, arquivo_origem=arquivo_origem,
            sha256_entrada=hashlib.sha256(texto.encode("utf-8")).hexdigest(),
            texto_entrada=texto, versao_esquema=VERSAO_ESQUEMA,
            prompt={"id": "PROMPT_EXTRACAO_V2", "versao": VERSOES_PROMPTS["PROMPT_EXTRACAO_V2"]},
            modo_esquema="Structured Outputs (esquema nativo)" if self.esquema_nativo else "validação local com até 1 correção",
            contrato=contrato.model_dump() if contrato else None,
            erros_validacao=erros, alertas=[asdict(a) for a in alertas],
            decisao=decisao, motivo=motivo, chamadas=chamadas,
        )
        self._salvar("extracoes", id_caso, asdict(resultado))
        return resultado

    def gerar_ficha(self, id_caso: str, texto: str, canal: str, arquivo_origem: str,
                    contrato: ContratoSolicitacaoV2) -> Tuple[Optional[FichaCompreensaoNLP], List[Dict[str, Any]]]:
        """Ficha de compreensão (RF15): resumo pelo modelo; categoria e entidades vêm do contrato validado."""
        usuario = PROMPT_FICHA_NLP_USUARIO.format(conteudo_delimitado=delimitar_dados_externos(texto))
        parametros = {"schema": ResumoNLP, "reasoning_effort": "low", "max_completion_tokens": 4000}
        resposta = self._gerar("ficha_nlp", "PROMPT_FICHA_NLP", id_caso, canal, arquivo_origem,
                               usuario, PROMPT_FICHA_NLP_SISTEMA, **parametros)
        chamadas = [_telemetria("ficha_nlp", resposta)]
        if not resposta.sucesso or classificar_erros_resumo(resposta.conteudo):
            return None, chamadas
        saida = ResumoNLP.model_validate_json(resposta.conteudo)

        palavras = len(saida.resumo.split())
        if palavras > LIMITE_PALAVRAS_RESUMO:
            pedido = (f"{usuario}\nO resumo anterior tinha {palavras} palavras. Reescreva com no máximo "
                      f"{LIMITE_PALAVRAS_RESUMO} palavras, mantendo os fatos e sem acrescentar dados.")
            nova = self._gerar("ficha_nlp_reducao", "PROMPT_FICHA_NLP", id_caso, canal, arquivo_origem,
                               pedido, PROMPT_FICHA_NLP_SISTEMA, **parametros)
            chamadas.append(_telemetria("ficha_nlp_reducao", nova))
            if nova.sucesso and not classificar_erros_resumo(nova.conteudo):
                saida = ResumoNLP.model_validate_json(nova.conteudo)
                palavras = len(saida.resumo.split())

        literais, sem_apoio = separar_entidades(contrato.entidades, texto)
        alertas = []
        if palavras > LIMITE_PALAVRAS_RESUMO:
            alertas.append(f"RESUMO_EXCEDE_LIMITE: {palavras} palavras (limite {LIMITE_PALAVRAS_RESUMO}).")
        orfaos = numeros_sem_lastro(saida.resumo, texto)
        if orfaos:
            alertas.append(f"NUMERO_SEM_LASTRO_NO_RESUMO: {', '.join(orfaos)}.")
        sem_base = [i.informacao for i in saida.informacoes_inferidas if normalizar(i.base) not in normalizar(texto)]
        if sem_base:
            alertas.append(f"INFERENCIA_SEM_BASE_LITERAL: {'; '.join(sem_base)}.")

        ficha = FichaCompreensaoNLP(
            id_caso=id_caso, resumo=saida.resumo, palavras_resumo=palavras, categoria=contrato.categoria,
            entidades_literais=literais, entidades_sem_apoio=sem_apoio,
            informacoes_inferidas=saida.informacoes_inferidas, alertas=alertas,
        )
        self._salvar("fichas", id_caso, {**ficha.model_dump(), "chamadas": chamadas})
        return ficha, chamadas

    def comparar_json_sintatico_e_esquema(self, id_caso: str, texto: str, canal: str, arquivo_origem: str) -> Dict[str, Any]:
        """
        Comparativo do RF14 (T01) no mesmo caso: JSON Mode com instrução genérica, JSON Mode com as instruções
        do contrato (sem esquema) e Structured Outputs com o contrato. Cada saída é validada contra o contrato.
        """
        delimitado = delimitar_dados_externos(texto)
        sistema = self.prompt_sistema_extracao()
        usuario = PROMPT_EXTRACAO_V2_USUARIO.format(canal=canal, conteudo_delimitado=delimitado)
        variantes = [
            ("json_object_instrucao_generica", "PROMPT_EXTRACAO_JSON_GENERICO",
             PROMPT_EXTRACAO_JSON_GENERICO.format(conteudo_delimitado=delimitado), None, {"modo_json": True}),
            ("json_object_instrucoes_do_contrato", "PROMPT_EXTRACAO_V2", usuario, sistema, {"modo_json": True}),
            ("structured_outputs_contrato", "PROMPT_EXTRACAO_V2", usuario, sistema, {"schema": ContratoSolicitacaoV2}),
        ]
        resultados = []
        for nome, prompt_id, prompt, sist, extra in variantes:
            resposta = self._gerar(f"comparativo_{nome}", prompt_id, id_caso, canal, arquivo_origem, prompt, sist,
                                   reasoning_effort="none", max_completion_tokens=4000, **extra)
            sintaxe_ok, chaves = False, []
            if resposta.sucesso:
                try:
                    dados = json.loads(resposta.conteudo)
                    sintaxe_ok, chaves = True, sorted(dados) if isinstance(dados, dict) else []
                except json.JSONDecodeError:
                    pass
            erros = classificar_erros_contrato(resposta.conteudo) if resposta.sucesso else []
            resultados.append({
                "variante": nome,
                "garantia_da_api": "esquema (sintaxe, tipos e estrutura)" if "schema" in extra else "apenas sintaxe JSON",
                "sucesso_chamada": resposta.sucesso,
                "codigo_erro_chamada": resposta.codigo_erro,
                "json_sintaticamente_valido": sintaxe_ok,
                "chaves_devolvidas": chaves,
                "valido_no_contrato": resposta.sucesso and sintaxe_ok and not erros,
                "erros_por_codigo": {c: sum(1 for e in erros if e["codigo"] == c) for c in sorted({e["codigo"] for e in erros})},
                "erros": erros,
                "saida": resposta.conteudo,
                "chamada": _telemetria(nome, resposta),
            })
        return {"caso": id_caso, "versao_esquema": VERSAO_ESQUEMA, "variantes": resultados}


# ------------------------------------------------------------------------------
# Avaliação contra o gabarito (T03) e relatórios
# ------------------------------------------------------------------------------
CAMPOS_EXATOS = ("protocolo", "data_solicitacao", "solicitante_ficticio", "curso", "categoria",
                 "campos_ausentes", "necessita_revisao")
# Redigidos pelo modelo: o sentido é conferido pela equipe, mas preencher o que o gabarito espera null
# (ou deixar null o que ele espera preenchido) é erro objetivo
CAMPOS_SEMANTICOS = ("assunto", "pedido")


def _mesmo_valor(esperado: Any, obtido: Any) -> bool:
    if isinstance(esperado, list) and isinstance(obtido, list):
        return sorted(normalizar(v) for v in esperado) == sorted(normalizar(v) for v in obtido)
    if isinstance(esperado, str) and isinstance(obtido, str):
        return normalizar(esperado) == normalizar(obtido)
    return esperado == obtido


def _chave_entidade(tipo: str, valor: str) -> str:
    """Datas são comparadas pela forma canônica (14/10/2026 == 14 de outubro de 2026); o resto, pelo texto normalizado."""
    return (_chave_de_data(valor) if tipo == "datas" else None) or normalizar(valor)


def _proporcao(numerador: int, denominador: int) -> Dict[str, Any]:
    """Proporção sempre com numerador e denominador visíveis (RF23); sem divisão por zero."""
    return {"numerador": numerador, "denominador": denominador,
            "valor": round(numerador / denominador, 4) if denominador else None}


def avaliar_contra_gabarito(gabarito: Dict[str, Any], resultados: Dict[str, ResultadoExtracao],
                            fichas: Dict[str, FichaCompreensaoNLP]) -> Dict[str, Any]:
    """Compara contrato e ficha de cada solicitação com o gabarito elaborado antes da execução (T03)."""
    casos = []
    for caso in gabarito["casos"]:
        id_caso, esperado = caso["id"], caso["esperado"]
        resultado, ficha = resultados.get(id_caso), fichas.get(id_caso)
        obtido = resultado.contrato if resultado else None
        texto = resultado.texto_entrada if resultado else ""
        item: Dict[str, Any] = {
            "id": id_caso, "tipo_caso": caso["tipo_caso"], "contrato_valido": obtido is not None,
            "decisao_esperada": caso["decisao_esperada"], "decisao_obtida": resultado.decisao if resultado else None,
        }
        item["decisao_correta"] = item["decisao_esperada"] == item["decisao_obtida"]
        if obtido:
            item.update({"categoria_esperada": esperado["categoria"], "categoria_obtida": obtido["categoria"],
                         "categoria_correta": esperado["categoria"] == obtido["categoria"]})
            item["campos_divergentes"] = [{"campo": c, "esperado": esperado[c], "obtido": obtido[c]}
                                          for c in CAMPOS_EXATOS if not _mesmo_valor(esperado[c], obtido[c])]
            item["nulidade_divergente"] = [{"campo": c, "esperado": esperado[c], "obtido": obtido[c]}
                                           for c in CAMPOS_SEMANTICOS if (esperado[c] is None) != (obtido[c] is None)]
            datas_validas = datas_do_texto(texto)[0]
            omitidas, sem_suporte, nao_esperadas = [], [], []
            for tipo in TIPOS_ENTIDADE:
                esperadas = {_chave_entidade(tipo, v): v for v in esperado["entidades"][tipo]}
                opcionais = {_chave_entidade(tipo, v) for v in caso["entidades_aceitas_opcionais"].get(tipo, [])}
                obtidas = {_chave_entidade(tipo, v): v for v in obtido["entidades"][tipo]}
                omitidas += [f"{tipo}: {v}" for chave, v in esperadas.items() if chave not in obtidas]
                for chave, valor in obtidas.items():
                    if not ancorado(valor, texto, datas_validas):
                        sem_suporte.append(f"{tipo}: {valor}")
                    elif chave not in esperadas and chave not in opcionais:
                        nao_esperadas.append(f"{tipo}: {valor}")
            item.update({
                "entidades_esperadas": sum(len(esperado["entidades"][t]) for t in TIPOS_ENTIDADE),
                "entidades_omitidas": omitidas, "entidades_sem_suporte": sem_suporte, "entidades_nao_esperadas": nao_esperadas,
            })
        if ficha:
            resumo = normalizar(ficha.resumo)
            item["resumo"] = {
                "texto": ficha.resumo,
                "palavras": ficha.palavras_resumo,
                "dentro_do_limite": ficha.palavras_resumo <= LIMITE_PALAVRAS_RESUMO,
                "fatos": [{"fato": f["fato"],
                           "preservado": all(any(alt in resumo for alt in m.split("|")) for m in f["marcadores"])}
                          for f in caso["fatos_essenciais"]],
                "termos_proibidos_encontrados": [t for t in caso["termos_proibidos_resumo"] if t in resumo],
                "numeros_sem_lastro": numeros_sem_lastro(ficha.resumo, texto),
                "informacoes_inferidas": [i.model_dump() for i in ficha.informacoes_inferidas],
                "alertas": ficha.alertas,
            }
        casos.append(item)

    total = len(gabarito["casos"])
    validos = [c for c in casos if c["contrato_valido"]]
    com_resumo = [c for c in casos if "resumo" in c]
    agregados = {
        "acuracia_categoria": _proporcao(sum(c.get("categoria_correta", False) for c in casos), total),
        "contratos_validos": _proporcao(len(validos), total),
        "campos_exatos_corretos": _proporcao(sum(len(CAMPOS_EXATOS) - len(c["campos_divergentes"]) for c in validos),
                                             len(CAMPOS_EXATOS) * total),
        "assunto_e_pedido_com_presenca_correta": _proporcao(
            sum(len(CAMPOS_SEMANTICOS) - len(c["nulidade_divergente"]) for c in validos), len(CAMPOS_SEMANTICOS) * total),
        "entidades_omitidas": _proporcao(sum(len(c["entidades_omitidas"]) for c in validos),
                                         sum(c["entidades_esperadas"] for c in validos)),
        "entidades_sem_suporte": sum(len(c["entidades_sem_suporte"]) for c in validos),
        "entidades_nao_esperadas": sum(len(c["entidades_nao_esperadas"]) for c in validos),
        "resumos_no_limite_de_100_palavras": _proporcao(sum(c["resumo"]["dentro_do_limite"] for c in com_resumo), total),
        "fatos_essenciais_preservados": _proporcao(sum(f["preservado"] for c in com_resumo for f in c["resumo"]["fatos"]),
                                                   sum(len(c["fatos_essenciais"]) for c in gabarito["casos"])),
        "resumos_com_termo_proibido": sum(bool(c["resumo"]["termos_proibidos_encontrados"]) for c in com_resumo),
        "resumos_com_numero_sem_lastro": sum(bool(c["resumo"]["numeros_sem_lastro"]) for c in com_resumo),
        "decisoes_corretas": _proporcao(sum(c["decisao_correta"] for c in casos), total),
    }
    return {"versao_gabarito": gabarito["versao_gabarito"], "versao_esquema": VERSAO_ESQUEMA,
            "agregados": agregados, "casos": casos}


def _celula(valor: Any) -> str:
    return str(valor).replace("|", "/").replace("\n", " ")


def relatorio_avaliacao_md(avaliacao: Dict[str, Any], contexto: Dict[str, Any]) -> str:
    linhas = [
        "# Avaliação da extração estruturada e da ficha de compreensão (RF14, RF15, T03)", "",
        f"- Gerado em: {contexto['gerado_em']} | Provedor/modelo: {contexto['provedor']} / {contexto['modelo']}",
        f"- Gabarito: v{avaliacao['versao_gabarito']} (revisão humana: {contexto['revisao_gabarito']}) | "
        f"Esquema: v{avaliacao['versao_esquema']} | Custo estimado da execução: US$ {contexto['custo_total_usd']:.6f}", "",
        "## Indicadores", "", "| Indicador | Numerador | Denominador | Valor |", "|---|---|---|---|",
    ]
    for nome, valor in avaliacao["agregados"].items():
        if isinstance(valor, dict):
            percentual = f"{valor['valor']:.1%}" if valor["valor"] is not None else "sem base"
            linhas.append(f"| {nome} | {valor['numerador']} | {valor['denominador']} | {percentual} |")
        else:
            linhas.append(f"| {nome} | {valor} | - | - |")
    linhas += ["", "## Por solicitação", "",
               "| Caso | Tipo | Categoria (esperada -> obtida) | Decisão (esperada -> obtida) | Campos divergentes | "
               "Entidades omitidas / sem suporte / não esperadas | Palavras | Fatos preservados |",
               "|---|---|---|---|---|---|---|---|"]
    for c in avaliacao["casos"]:
        divergentes = ", ".join(d["campo"] for d in c.get("campos_divergentes", [])) or "-"
        entidades = (f"{len(c.get('entidades_omitidas', []))} / {len(c.get('entidades_sem_suporte', []))} / "
                     f"{len(c.get('entidades_nao_esperadas', []))}")
        resumo = c.get("resumo", {})
        fatos = f"{sum(f['preservado'] for f in resumo.get('fatos', []))}/{len(resumo.get('fatos', []))}" if resumo else "-"
        linhas.append(f"| {c['id']} | {c['tipo_caso']} | {c.get('categoria_esperada', '-')} -> {c.get('categoria_obtida', '-')} | "
                      f"{c['decisao_esperada']} -> {c['decisao_obtida']} | {_celula(divergentes)} | {entidades} | "
                      f"{resumo.get('palavras', '-')} | {fatos} |")
    linhas += ["", "## Erros registrados", ""]
    for c in avaliacao["casos"]:
        detalhes = [f"campo {d['campo']}: esperado {d['esperado']!r}, obtido {d['obtido']!r}" for d in c.get("campos_divergentes", [])]
        detalhes += [f"campo {d['campo']}: esperado {'null' if d['esperado'] is None else 'preenchido'}, obtido {d['obtido']!r}"
                     + (" (valor deduzido, não escrito no texto)" if d["esperado"] is None else " (omitido)")
                     for d in c.get("nulidade_divergente", [])]
        detalhes += [f"entidade omitida - {e}" for e in c.get("entidades_omitidas", [])]
        detalhes += [f"entidade sem suporte no texto - {e}" for e in c.get("entidades_sem_suporte", [])]
        detalhes += [f"entidade não esperada - {e}" for e in c.get("entidades_nao_esperadas", [])]
        resumo = c.get("resumo", {})
        detalhes += [f"fato não preservado no resumo - {f['fato']}" for f in resumo.get("fatos", []) if not f["preservado"]]
        detalhes += [f"termo proibido no resumo - {t}" for t in resumo.get("termos_proibidos_encontrados", [])]
        detalhes += [f"número sem lastro no resumo - {n}" for n in resumo.get("numeros_sem_lastro", [])]
        linhas.append(f"- **{c['id']}**: " + ("; ".join(_celula(d) for d in detalhes) if detalhes else "nenhum erro automático"))
    linhas += ["", "## Limitações", "",
               "- A preservação dos fatos é conferida por marcadores definidos no gabarito antes da execução: é indicativa e "
               "não substitui a leitura do resumo, registrada em resultados/nlp/conferencia_humana_rf15.json.",
               "- Seis solicitações formam um conjunto pequeno: os números servem para detectar regressões, não para "
               "certificar o extrator (Aula 09 §5.2).",
               "- O esquema garante a forma dos dados, não a verdade; a ancoragem confere presença no texto, não a "
               "atribuição correta de cada valor.", ""]
    return "\n".join(linhas)


def relatorio_comparativo_md(comparativo: Dict[str, Any]) -> str:
    linhas = [
        "# Comparativo: JSON apenas sintático x saída validada por esquema (RF14, T01)", "",
        f"Caso: {comparativo['caso']} | Contrato: ContratoSolicitacaoV2 v{comparativo['versao_esquema']}", "",
        "## Mesmo caso nas três formas de saída", "",
        "| Variante | Garantia da API | JSON válido | Válido no contrato | Erros por código | Chaves devolvidas |",
        "|---|---|---|---|---|---|",
    ]
    for v in comparativo["variantes"]:
        erros = ", ".join(f"{c}: {n}" for c, n in v["erros_por_codigo"].items()) or "-"
        linhas.append(f"| {v['variante']} | {v['garantia_da_api']} | {'sim' if v['json_sintaticamente_valido'] else 'não'} | "
                      f"{'sim' if v['valido_no_contrato'] else 'não'} | {erros} | {_celula(', '.join(v['chaves_devolvidas']))} |")
    linhas += ["", "## Payloads de teste (JSON válido fora do contrato)", "",
               "| Caso | Descrição | Erros esperados | Erros obtidos | Confere |", "|---|---|---|---|---|"]
    for p in comparativo["payloads_sinteticos"]:
        linhas.append(f"| {p['id']} | {p['descricao']} | {', '.join(p['erros_esperados'])} | "
                      f"{', '.join(p['erros_obtidos'])} | {'sim' if p['confere'] else 'NÃO'} |")
    linhas += ["", "JSON Mode garante só a sintaxe: as chaves e os tipos ficam a critério do modelo. O esquema estrito "
               "restringe a geração; mesmo assim, toda saída é validada localmente antes de seguir (Aula 08 §4 e §5).", ""]
    return "\n".join(linhas)


def _salvar_json(caminho: Path, dados: Any):
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text(json.dumps(dados, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")


def _registro_de_conferencia(caminho: Path, avaliacao: Dict[str, Any]) -> bool:
    """
    Modelo do registro de conferência humana do RF15 (resumo, categoria, entidades e correções).
    Não sobrescreve um registro que já tenha anotações da equipe. Retorna True se o arquivo foi gravado.
    """
    if caminho.exists():
        atual = json.loads(caminho.read_text(encoding="utf-8"))
        if atual.get("revisado_por") or any(c.get("correcoes") or c.get("resumo_fiel") is not None for c in atual["casos"]):
            return False
    _salvar_json(caminho, {
        "instrucoes": "Para cada solicitação, a equipe lê o resumo e o contrato, preenche resumo_fiel e categoria_correta "
                      "(true/false) e registra em correcoes cada valor corrigido. Os achados automáticos estão em "
                      "verificacao_automatica.",
        "revisado_por": None,
        "data": None,
        "casos": [{
            "id": c["id"],
            "resumo": c.get("resumo", {}).get("texto"),
            "verificacao_automatica": {
                "categoria_correta": c.get("categoria_correta"),
                "campos_divergentes": [d["campo"] for d in c.get("campos_divergentes", []) + c.get("nulidade_divergente", [])],
                "entidades_omitidas": c.get("entidades_omitidas", []),
                "entidades_sem_suporte": c.get("entidades_sem_suporte", []),
                "fatos_nao_preservados": [f["fato"] for f in c.get("resumo", {}).get("fatos", []) if not f["preservado"]],
            },
            "resumo_fiel": None,
            "categoria_correta": None,
            "correcoes": [],
            "observacoes": None,
        } for c in avaliacao["casos"]],
    })
    return True


def executar_avaliacao_nlp(config: Dict[str, Any]) -> bool:
    """
    Modo --modo avaliar-nlp: extrai e resume as 6 solicitações, executa o T02 (regras de negócio) e o
    comparativo do T01, e avalia tudo contra os gabaritos elaborados antes da execução (T03).
    """
    from src.audit import AuditManager

    arquivos = config["desafio02"]

    def carregar(chave: str) -> Dict[str, Any]:
        return json.loads((RAIZ_PROJETO / arquivos[chave]).read_text(encoding="utf-8"))

    def ler(relativo: str) -> str:
        return (RAIZ_PROJETO / relativo).read_text(encoding="utf-8")

    solicitacoes = carregar("solicitacoes")["solicitacoes"]
    gabarito = carregar("gabarito_solicitacoes")
    negativos = carregar("casos_negativos_t01_t02")

    print("=" * 75)
    print("  AVALIAÇÃO DA EXTRAÇÃO ESTRUTURADA E DA FICHA DE COMPREENSÃO (RF14, RF15)")
    print("=" * 75)
    from src.llm_client import OrcamentoExecucao
    llm = LLMClient()
    llm.orcamento = OrcamentoExecucao.do_config(config)  # teto de chamadas e tokens da execução (RF16)
    print(f"• Provedor: {llm.provedor} | Modelo: {llm.modelo} | Gabarito: v{gabarito['versao_gabarito']} "
          f"(revisão humana: {gabarito['revisao_humana']['status']})")
    if not llm.disponivel:
        print(f"[ERRO] {llm.motivo_indisponibilidade}")
        return False

    extrator = ExtratorSolicitacoes(llm_client=llm, audit=AuditManager())
    resultados: Dict[str, ResultadoExtracao] = {}
    fichas: Dict[str, FichaCompreensaoNLP] = {}
    chamadas: List[Dict[str, Any]] = []

    print("\n[1/3] Solicitações: contrato, regras de negócio e ficha de compreensão")
    for solicitacao in solicitacoes:
        id_caso, texto = solicitacao["id"], ler(solicitacao["arquivo"])
        resultado = extrator.extrair(id_caso, texto, solicitacao["canal"], solicitacao["arquivo"])
        resultados[id_caso] = resultado
        chamadas += resultado.chamadas
        detalhe = ""
        if resultado.contrato:
            ficha, chamadas_ficha = extrator.gerar_ficha(id_caso, texto, solicitacao["canal"], solicitacao["arquivo"],
                                                         ContratoSolicitacaoV2.model_validate(resultado.contrato))
            chamadas += chamadas_ficha
            if ficha:
                fichas[id_caso] = ficha
                detalhe = f" | categoria {ficha.categoria} | resumo {ficha.palavras_resumo} palavras"
        print(f"  - {id_caso} ({solicitacao['tipo_caso']}): {resultado.decisao}{detalhe}")

    print("\n[2/3] T02: regras de negócio")
    data_impossivel, nao_ancorado = negativos["t02_casos"]
    resultado_a = extrator.extrair(data_impossivel["id"], ler(data_impossivel["arquivo"]), "texto (e-mail)",
                                   data_impossivel["arquivo"])
    chamadas += resultado_a.chamadas
    candidata = ContratoSolicitacaoV2.model_validate(nao_ancorado["extracao_candidata"])
    alertas_b = conferir_regras_negocio(candidata, ler(nao_ancorado["texto_original"]))
    decisao_b, motivo_b = decidir(candidata, alertas_b)
    t02 = [
        {"id": data_impossivel["id"], "decisao_esperada": data_impossivel["decisao_esperada"],
         "decisao_obtida": resultado_a.decisao, "alertas_esperados": data_impossivel["alertas_esperados"],
         "alertas_obtidos": sorted({a["codigo"] for a in resultado_a.alertas}), "motivo": resultado_a.motivo,
         "registro": "resultados/nlp/extracoes/T02-A.json"},
        {"id": nao_ancorado["id"], "decisao_esperada": nao_ancorado["decisao_esperada"], "decisao_obtida": decisao_b,
         "alertas_esperados": nao_ancorado["alertas_esperados"], "alertas_obtidos": sorted({a.codigo for a in alertas_b}),
         "motivo": motivo_b, "alertas": [asdict(a) for a in alertas_b],
         "observacao": "Regras aplicadas sobre a extração candidata do gabarito; sem chamada ao modelo."},
    ]
    for caso in t02:
        caso["confere"] = (caso["decisao_obtida"] == caso["decisao_esperada"]
                           and set(caso["alertas_esperados"]) <= set(caso["alertas_obtidos"]))
        print(f"  - {caso['id']}: {caso['decisao_obtida']} | alertas {', '.join(caso['alertas_obtidos']) or '-'} | "
              f"{'confere' if caso['confere'] else 'NÃO confere'} com o gabarito")
    _salvar_json(RAIZ_PROJETO / "resultados" / "nlp" / "t02_regras_negocio.json", t02)

    print("\n[3/3] T01: JSON apenas sintático x esquema (SOL-01)")
    sol01 = next(s for s in solicitacoes if s["id"] == "SOL-01")
    comparativo = extrator.comparar_json_sintatico_e_esquema("SOL-01", ler(sol01["arquivo"]), sol01["canal"], sol01["arquivo"])
    chamadas += [v["chamada"] for v in comparativo["variantes"]]
    comparativo["payloads_sinteticos"] = []
    for payload in negativos["t01_payloads"]:
        obtidos = sorted({e["codigo"] for e in classificar_erros_contrato(payload["payload"])})
        comparativo["payloads_sinteticos"].append({
            "id": payload["id"], "descricao": payload["descricao"], "erros_esperados": payload["erros_esperados"],
            "erros_obtidos": obtidos, "confere": obtidos == sorted(payload["erros_esperados"]),
        })
    for variante in comparativo["variantes"]:
        print(f"  - {variante['variante']}: JSON válido={variante['json_sintaticamente_valido']} | "
              f"válido no contrato={variante['valido_no_contrato']} | erros={variante['erros_por_codigo'] or '-'}")

    avaliacao = avaliar_contra_gabarito(gabarito, resultados, fichas)
    contexto = {
        "gerado_em": datetime.now().isoformat(timespec="seconds"), "provedor": llm.provedor, "modelo": llm.modelo,
        "revisao_gabarito": gabarito["revisao_humana"]["status"],
        "custo_total_usd": sum(c["custo_estimado_usd"] or 0.0 for c in chamadas),
        "chamadas_ao_modelo": len(chamadas),
    }
    dir_metricas = RAIZ_PROJETO / "resultados" / "metricas"
    _salvar_json(dir_metricas / "avaliacao_nlp_rf15.json", {**contexto, **avaliacao})
    (dir_metricas / "avaliacao_nlp_rf15.md").write_text(relatorio_avaliacao_md(avaliacao, contexto), encoding="utf-8")
    _salvar_json(dir_metricas / "comparativo_json_esquema_rf14.json", comparativo)
    (dir_metricas / "comparativo_json_esquema_rf14.md").write_text(relatorio_comparativo_md(comparativo), encoding="utf-8")
    conferencia = RAIZ_PROJETO / "resultados" / "nlp" / "conferencia_humana_rf15.json"
    gravou_conferencia = _registro_de_conferencia(conferencia, avaliacao)

    agregados = avaliacao["agregados"]
    print("\n" + "=" * 75)
    for nome in ("acuracia_categoria", "decisoes_corretas", "campos_exatos_corretos", "assunto_e_pedido_com_presenca_correta",
                 "entidades_omitidas", "fatos_essenciais_preservados", "resumos_no_limite_de_100_palavras"):
        valor = agregados[nome]
        print(f"  {nome}: {valor['numerador']}/{valor['denominador']}")
    print(f"  entidades sem suporte: {agregados['entidades_sem_suporte']} | não esperadas: "
          f"{agregados['entidades_nao_esperadas']} | resumos com número sem lastro: {agregados['resumos_com_numero_sem_lastro']}")
    print(f"  Chamadas ao modelo: {contexto['chamadas_ao_modelo']} | custo estimado: US$ {contexto['custo_total_usd']:.6f}")
    print("  Relatórios: resultados/metricas/avaliacao_nlp_rf15.md e comparativo_json_esquema_rf14.md")
    print("  Registros por caso: resultados/nlp/extracoes/ e resultados/nlp/fichas/")
    print(f"  Conferência humana: {conferencia.relative_to(RAIZ_PROJETO).as_posix()}"
          + ("" if gravou_conferencia else " (mantida: já tem anotações da equipe)"))
    print("=" * 75)
    return True
