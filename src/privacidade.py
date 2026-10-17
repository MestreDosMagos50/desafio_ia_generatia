#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
==============================================================================
PRIVACIDADE E MINIMIZAÇÃO DE DADOS PESSOAIS (RF12 / LGPD)
==============================================================================
- minimizar(): payload enviado ao modelo para redigir a minuta. Leva só o que a
  redação precisa; CPF, RG e e-mail seguem mascarados e filiação, telefones e
  data de nascimento são omitidos.
- mascarar_cpf / mascarar_rg / mascarar_email: máscaras de identificadores.
- mascarar_texto(): aplica as máscaras em texto livre; usado na auditoria para
  que logs e registros de decisão não guardem CPF ou e-mail completos.

Limite conhecido: a EXTRAÇÃO (RF05), a transcrição (RF06) e a leitura da ficha
(RF08) precisam enviar o documento inteiro ao provedor, porque o objetivo delas
é justamente ler esses dados. A minimização vale para as etapas seguintes.
==============================================================================
"""

import re
from typing import Any, Dict

from src.conferencia import NAO_LOCALIZADO, eh_ausente, obter

PADRAO_CPF = re.compile(r"\b(\d{3})\.?(\d{3})\.?(\d{3})-?(\d{2})\b")
PADRAO_EMAIL = re.compile(r"\b([\w.+-])([\w.+-]*)@([\w-]+(?:\.[\w-]+)+)\b")

# Rótulos legíveis dos campos ausentes enviados ao modelo
ROTULOS_AUSENTES = {
    "protocolo": "Número de protocolo",
    "data_solicitacao": "Data da solicitação",
    "nome_completo": "Nome completo",
    "data_nascimento": "Data de nascimento",
    "cpf": "CPF",
    "rg": "RG",
    "orgao_expedidor": "Órgão expedidor do RG",
    "uf": "UF de expedição do RG",
    "nome_mae": "Nome da mãe",
    "nome_pai": "Nome do pai",
    "email": "E-mail",
    "telefone_celular": "Telefone celular",
    "telefone_residencial": "Telefone residencial",
    "nome": "Curso pretendido",
    "turno": "Turno",
    "data_inicio": "Data de início do curso",
    "documentos_comprobatorios_anexos": "Documentos comprobatórios anexados",
}


def mascarar_cpf(valor: Any) -> str:
    """'123.456.789-00' -> '***.456.789-**' (formato usado em comunicações oficiais)."""
    if eh_ausente(valor):
        return NAO_LOCALIZADO
    digitos = re.sub(r"\D", "", str(valor))
    if len(digitos) != 11:
        return "***"
    return f"***.{digitos[3:6]}.{digitos[6:9]}-**"


def mascarar_rg(valor: Any) -> str:
    """'1234567-8' -> '****567-8' (mantém só os últimos caracteres)."""
    if eh_ausente(valor):
        return NAO_LOCALIZADO
    texto = str(valor).strip()
    visiveis = 5 if len(texto) > 6 else 2
    return "*" * (len(texto) - visiveis) + texto[-visiveis:]


def mascarar_email(valor: Any) -> str:
    """'marcos.almeida@exemplo.com' -> 'm***@exemplo.com'."""
    if eh_ausente(valor):
        return NAO_LOCALIZADO
    return PADRAO_EMAIL.sub(lambda m: f"{m.group(1)}***@{m.group(3)}", str(valor))


def mascarar_texto(texto: str) -> str:
    """Mascara CPFs e e-mails em texto livre (logs, justificativas, resumos, campos livres da minuta)."""
    if not isinstance(texto, str) or not texto:
        return texto
    texto = PADRAO_CPF.sub(lambda m: f"***.{m.group(2)}.{m.group(3)}-**", texto)
    return PADRAO_EMAIL.sub(lambda m: f"{m.group(1)}***@{m.group(3)}", texto)


def minimizar(registro: Dict[str, Any]) -> Dict[str, Any]:
    """
    Payload minimizado para a redação da minuta (RF09 / RF12).
    - mantém: nome (saudação), curso, pedido, declaração de faltas, lacunas e alertas de segurança;
    - mascara: CPF, RG e e-mail (identificação do registro sem expor o número completo), inclusive quando
      aparecem dentro dos campos de texto livre (assunto, pedido, declaração, trechos suspeitos);
    - omite: nome da mãe e do pai, telefones, data de nascimento, naturalidade e o texto original.
    """
    solicitante = registro.get("solicitante", {}) or {}
    return {
        "data_solicitacao": registro.get("data_solicitacao"),
        "canal_origem": registro.get("canal_origem"),
        "nome_solicitante": obter(registro, "solicitante.nome_completo", NAO_LOCALIZADO),
        "cpf_mascarado": mascarar_cpf(solicitante.get("cpf")),
        "rg_mascarado": mascarar_rg(solicitante.get("rg")),
        "email_mascarado": mascarar_email(solicitante.get("email")),
        "curso": registro.get("curso"),
        # Campos de texto livre podem conter identificadores digitados pelo cidadão: aplica as máscaras
        "assunto": mascarar_texto(registro.get("assunto")),
        "pedido_detalhado": mascarar_texto(registro.get("pedido_detalhado")),
        "declarou_ciencia_faltas": registro.get("declarou_ciencia_faltas"),
        "texto_ciencia_faltas": mascarar_texto(registro.get("texto_ciencia_faltas")),
        "documentos_anexados": [mascarar_texto(d) for d in registro.get("documentos_anexados") or []],
        "campos_ausentes": [ROTULOS_AUSENTES.get(c, c) for c in registro.get("campos_ausentes", [])],
        "suspeita_prompt_injection": registro.get("suspeita_prompt_injection"),
        "trechos_suspeitos": [mascarar_texto(t) for t in registro.get("trechos_suspeitos") or []],
        # Os valores corrigidos pelo revisor prevalecem sobre o texto do cidadão
        "correcoes_do_revisor": [mascarar_texto(c) for c in registro.get("correcoes_revisor") or []],
    }


# Campos do registro que NÃO vão ao modelo na geração da minuta (documentação e testes)
CAMPOS_OMITIDOS_NA_MINUTA = (
    "solicitante.nome_mae", "solicitante.nome_pai", "solicitante.telefone_celular",
    "solicitante.telefone_residencial", "solicitante.data_nascimento", "solicitante.naturalidade",
    "texto_original",
)
