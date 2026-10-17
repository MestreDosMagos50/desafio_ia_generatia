#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
==============================================================================
MÓDULO DE VISÃO COMPUTACIONAL E OCR (RF08)
Atende aos requisitos de extração visual e soberania de dados.
==============================================================================
Funcionalidades:
- Validação do documento digitalizado (formato e tamanho);
- Leitura campo a campo por modelo multimodal (documento enviado ao Gemini);
- Preservação do texto bruto (leitura literal) e versão corrigida separada;
- Identificação de campos em branco, ilegíveis ou incertos;
- Confronto campo a campo com o gabarito (gabarito_visao.json);
- Justificativa técnica sobre soberania e privacidade em processamento local.
==============================================================================
"""

import json
from pathlib import Path
from typing import Dict, Any, Tuple, Optional, Literal

from pydantic import BaseModel, Field, ValidationError, create_model

from src.llm_client import LLMClient, LLMResponse
from src.prompts import PROMPT_LEITURA_FICHA
from src.conferencia import NAO_LOCALIZADO, IGNORAR_GABARITO_FICHA, definir, carregar_gabarito, comparar_com_gabarito


JUSTIFICATIVA_SOBERANIA_LOCAL = """
==============================================================================
JUSTIFICATIVA TÉCNICA: PROCESSAMENTO LOCAL (ON-PREMISE / OCR) VS. NUVEM (RF08)
==============================================================================
1. Soberania e Sigilo Institucional:
   Em órgãos públicos e secretarias de estado, formulários de matrícula e fichas
   cadastrais contêm documentos de identidade (RG, CPF) e assinaturas manuscritas.
   O processamento local (via OCR tradicional como Tesseract ou modelos locais
   como TrOCR/Llama-Vision on-premise) garante que imagens biométricas de assinaturas
   nunca deixem a infraestrutura controlada pelo Estado.

2. Conformidade com a LGPD (Arts. 6º, 33 e 46):
   O envio de imagens de formulários com grafotécnica e dados de menores de idade
   a provedores de nuvem estrangeiros (EUA) pode configurar transferência internacional
   de dados pessoais sem consentimento específico. O OCR local elimina esse risco.

3. Resiliência Operacional em Unidades Remotas:
   Escolas técnicas situadas em municípios do interior ou com conectividade intermitente
   mantêm a capacidade de digitalizar e homologar matrículas mesmo sem acesso à internet.
==============================================================================
"""

MIME_DOCUMENTO = {".pdf": "application/pdf", ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}

# Campos do formulário: identificador -> (rótulo impresso na ficha, caminho no registro revisado)
CAMPOS_FICHA = {
    "codigo": ("CÓDIGO", "codigo_matricula"),
    "nome": ("NOME", "solicitante.nome_completo"),
    "data_nascimento": ("DATA DE NASCIMENTO", "solicitante.data_nascimento"),
    "cpf": ("CPF", "solicitante.cpf"),
    "rg": ("RG", "solicitante.rg"),
    "orgao_expedidor": ("ÓRGÃO EXPEDIDOR", "solicitante.orgao_expedidor"),
    "naturalidade": ("NATURALIDADE", "solicitante.naturalidade"),
    "uf": ("UF", "solicitante.uf"),
    "nome_mae": ("NOME DA MÃE", "solicitante.nome_mae"),
    "nome_pai": ("NOME DO PAI", "solicitante.nome_pai"),
    "curso": ("CURSO", "curso.nome"),
    "carga_horaria": ("CH (carga horária)", "curso.carga_horaria"),
    "eixo_tecnologico": ("EIXO TECNOLÓGICO", "curso.eixo_tecnologico"),
    "turma": ("TURMA", "curso.turma"),
    "municipio": ("MUNICÍPIO", "curso.municipio"),
    "turno": ("TURNO", "curso.turno"),
    "inicio_curso": ("INÍCIO DO CURSO", "curso.inicio_curso"),
    "termino_curso": ("TÉRMINO DO CURSO", "curso.termino_curso"),
    "telefone_celular": ("TEL. CELULAR", "solicitante.telefone_celular"),
    "telefone_residencial": ("TELEFONE RESIDENCIAL", "solicitante.telefone_residencial"),
    "email": ("E-MAIL", "solicitante.email"),
    "data_matricula": ("DATA MATRÍCULA", "data_matricula"),
}


class CampoLido(BaseModel):
    valor_lido: str = Field(default="", description="Transcrição literal do que está escrito; vazio se em branco")
    valor_corrigido: str = Field(default=NAO_LOCALIZADO, description="Valor com ajustes de formatação que não mudam o sentido; 'não localizado' se em branco ou ilegível")
    situacao: Literal["LEGIVEL", "INCERTO", "ILEGIVEL", "EM_BRANCO"] = Field(default="ILEGIVEL")
    observacao: str = Field(default="", description="Dúvida e leituras alternativas, para INCERTO ou ILEGIVEL")


# Esquema enviado ao modelo: um CampoLido por campo do formulário
LeituraFicha = create_model(
    "LeituraFicha",
    cabecalho=(str, Field(default="", description="Texto impresso no cabeçalho do formulário")),
    **{
        identificador: (CampoLido, Field(default_factory=CampoLido, description=f"Campo '{rotulo}' do formulário"))
        for identificador, (rotulo, _) in CAMPOS_FICHA.items()
    },
    termo_ciencia_faltas_marcado=(bool, Field(default=False, description="Declaração de ciência das regras de faltas assinalada")),
    assinatura_aluno_presente=(bool, Field(default=False)),
    assinatura_secretaria_presente=(bool, Field(default=False))
)


class VisionProcessor:
    """Processador de documentos digitalizados e formulários manuscritos."""

    def __init__(self, config_path: str = "config.json", llm_client: Optional[LLMClient] = None):
        self.raiz_projeto = Path(__file__).resolve().parent.parent
        self.config = self._carregar_config(config_path)
        self.visao_cfg = self.config.get("visao", {})
        self.llm_client = llm_client or LLMClient(config_path)
        self.dir_processados = self.raiz_projeto / "dados" / "processados"

    def _carregar_config(self, caminho_config: str) -> dict:
        caminho = Path(caminho_config)
        if not caminho.is_absolute():
            caminho = self.raiz_projeto / caminho_config
        if caminho.exists():
            with open(caminho, "r", encoding="utf-8") as f:
                return json.load(f)
        return {}

    def validar_arquivo(self, caminho: Path) -> Tuple[bool, str]:
        """Valida extensão e tamanho do documento digitalizado."""
        if not caminho.exists():
            return False, f"Arquivo não localizado: {caminho}"
        ext = caminho.suffix.lower()
        if ext not in self.visao_cfg.get("extensoes_permitidas", list(MIME_DOCUMENTO)) or ext not in MIME_DOCUMENTO:
            return False, f"Extensão '{ext}' inválida para documentos."
        limite_mb = self.visao_cfg.get("tamanho_maximo_mb", 20)
        tamanho_mb = caminho.stat().st_size / (1024 * 1024)
        if tamanho_mb > limite_mb:
            return False, f"Arquivo com {tamanho_mb:.2f} MB excede o limite de {limite_mb} MB"
        return True, "Arquivo válido"

    def ler_ficha(self, caminho: Path) -> Tuple[Optional[BaseModel], LLMResponse]:
        """Leitura campo a campo do documento pelo modelo multimodal (RF08)."""
        resposta = self.llm_client.gerar_multimodal(
            caminho, MIME_DOCUMENTO[caminho.suffix.lower()], PROMPT_LEITURA_FICHA,
            schema=LeituraFicha, resolucao="MEDIA_RESOLUTION_HIGH"
        )
        if not resposta.sucesso:
            return None, resposta
        try:
            return LeituraFicha.model_validate_json(resposta.conteudo), resposta
        except ValidationError as e:
            resposta.marcar_falha("RESPOSTA_FORA_DO_ESQUEMA", f"A leitura retornada não segue o esquema esperado ({e.error_count()} erro(s)).")
            return None, resposta

    @staticmethod
    def montar_texto_bruto(leitura: BaseModel) -> str:
        """Texto bruto: o que foi lido em cada campo, sem correções, com a situação da leitura."""
        linhas = [f"CABEÇALHO: {leitura.cabecalho}"]
        for identificador, (rotulo, _) in CAMPOS_FICHA.items():
            campo: CampoLido = getattr(leitura, identificador)
            valor = campo.valor_lido if campo.valor_lido else "[EM BRANCO]"
            observacao = f" - {campo.observacao}" if campo.observacao else ""
            linhas.append(f"{rotulo}: {valor}  [{campo.situacao}]{observacao}")
        linhas.append(f"DECLARAÇÃO DE CIÊNCIA DE FALTAS: {'MARCADA' if leitura.termo_ciencia_faltas_marcado else 'NÃO MARCADA'}")
        linhas.append(f"ASSINATURA DO ALUNO OU RESPONSÁVEL: {'PRESENTE' if leitura.assinatura_aluno_presente else 'AUSENTE'}")
        linhas.append(f"ASSINATURA DA SECRETARIA ESCOLAR: {'PRESENTE' if leitura.assinatura_secretaria_presente else 'AUSENTE'}")
        return "\n".join(linhas) + "\n"

    @staticmethod
    def gerar_versao_revisada(leitura: BaseModel) -> Dict[str, Any]:
        """
        Versão corrigida e estruturada (mesma organização do gabarito), sem alterar o sentido:
        campos em branco ou ilegíveis ficam como 'não localizado'; incertos são listados.
        """
        revisada: Dict[str, Any] = {"instituicao": leitura.cabecalho}
        campos_em_branco, trechos_incertos = [], []
        for identificador, (rotulo, caminho) in CAMPOS_FICHA.items():
            campo: CampoLido = getattr(leitura, identificador)
            aproveitavel = campo.situacao in ("LEGIVEL", "INCERTO") and campo.valor_corrigido.strip()
            definir(revisada, caminho, campo.valor_corrigido.strip() if aproveitavel else NAO_LOCALIZADO)
            if campo.situacao == "EM_BRANCO":
                campos_em_branco.append(identificador)
            elif campo.situacao in ("INCERTO", "ILEGIVEL"):
                trechos_incertos.append({
                    "campo": identificador, "rotulo": rotulo, "valor_lido": campo.valor_lido,
                    "situacao": campo.situacao, "observacao": campo.observacao
                })

        revisada["conformidade_e_assinaturas"] = {
            "termo_ciencia_faltas_assinado": leitura.termo_ciencia_faltas_marcado,
            "assinatura_aluno_presente": leitura.assinatura_aluno_presente,
            "assinatura_secretaria_escolar": "presente" if leitura.assinatura_secretaria_presente else NAO_LOCALIZADO
        }
        if not leitura.assinatura_secretaria_presente:
            campos_em_branco.append("assinatura_secretaria_escolar")
        revisada["campos_em_branco_detectados"] = campos_em_branco
        revisada["trechos_incertos"] = trechos_incertos
        return revisada

    def comparar_com_gabarito(self, arquivo_documento: str, dados_extraidos: Dict[str, Any]) -> Dict[str, Any]:
        """Confronta todos os campos da leitura com o gabarito (RF08 / RF13)."""
        gabarito = carregar_gabarito(self.raiz_projeto, self.config, arquivo_documento)
        if not gabarito:
            return {"erro": "Gabarito de visão não encontrado"}
        comparacao = comparar_com_gabarito(
            dados_extraidos, gabarito.get("dados_extraidos_esperados", {}), ignorar=IGNORAR_GABARITO_FICHA
        )
        comparacao["caso_id"] = gabarito.get("caso_id")
        # Campos que o gabarito considera ambíguos: a leitura deve sinalizá-los como INCERTO/ILEGIVEL
        esperados = list(gabarito.get("campos_incertos_esperados", {}))
        sinalizados = {t["campo"] for t in dados_extraidos.get("trechos_incertos", [])}
        comparacao["incertos_esperados"] = {
            "sinalizados": [c for c in esperados if c in sinalizados],
            "nao_sinalizados": [c for c in esperados if c not in sinalizados],
            "sinalizados_fora_do_gabarito": sorted(sinalizados - set(esperados))
        }
        return comparacao

    def processar_caso_visao(self, arquivo_documento: str) -> Dict[str, Any]:
        """Orquestra validação, leitura, versão revisada e comparação. As chamadas vão em 'chamadas'."""
        caminho = self.raiz_projeto / arquivo_documento
        resultado: Dict[str, Any] = {"sucesso": False, "arquivo_origem": arquivo_documento, "chamadas": []}

        valido, msg = self.validar_arquivo(caminho)
        if not valido:
            resultado["erro"] = msg
            return resultado

        leitura, resposta = self.ler_ficha(caminho)
        self.dir_processados.mkdir(parents=True, exist_ok=True)
        caminho_bruto = self.dir_processados / "visao_bruta.txt"
        caminho_revisado = self.dir_processados / "visao_revisada.json"
        resultado["chamadas"].append({
            "etapa": "ocr_visao", "resposta": resposta,
            "prompt_id": "PROMPT_LEITURA_FICHA", "prompt_texto": PROMPT_LEITURA_FICHA,
            "arquivo_saida": caminho_revisado if leitura else None, "resumo": None
        })
        if not leitura:
            resultado["erro"] = resposta.erro
            return resultado

        texto_bruto = self.montar_texto_bruto(leitura)
        revisada = self.gerar_versao_revisada(leitura)
        caminho_bruto.write_text(texto_bruto, encoding="utf-8")
        (self.dir_processados / "visao_bruta.json").write_text(
            json.dumps(leitura.model_dump(), indent=2, ensure_ascii=False), encoding="utf-8"
        )
        caminho_revisado.write_text(json.dumps(revisada, indent=2, ensure_ascii=False), encoding="utf-8")

        comparacao = self.comparar_com_gabarito(arquivo_documento, revisada)
        (self.dir_processados / "comparacao_visao_gabarito.json").write_text(
            json.dumps(comparacao, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        resultado["chamadas"][0]["resumo"] = (
            f"campos_em_branco={len(revisada['campos_em_branco_detectados'])}; "
            f"incertos={len(revisada['trechos_incertos'])}; acerto_gabarito={comparacao.get('taxa_acerto_pct')}%"
        )

        # Justificativa técnica de processamento local (RF08)
        (self.raiz_projeto / "documentacao" / "soberania_e_privacidade_ocr.txt").write_text(
            JUSTIFICATIVA_SOBERANIA_LOCAL, encoding="utf-8"
        )

        resultado.update({
            "sucesso": True,
            "texto_bruto": texto_bruto,
            "dados_revisados": revisada,
            "comparacao_gabarito": comparacao,
            "justificativa_soberania_local": JUSTIFICATIVA_SOBERANIA_LOCAL.strip()
        })
        return resultado
