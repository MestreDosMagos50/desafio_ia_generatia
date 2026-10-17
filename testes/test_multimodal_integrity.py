#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
==============================================================================
TESTES DE INTEGRIDADE MULTIMODAL (ÁUDIO, VISÃO/OCR, IMAGEM E AUDITORIA)
Atende aos requisitos RF06, RF07, RF08, RF10 e RF11.
==============================================================================
"""

import io
import sys
import json
from pathlib import Path
import pytest
from PIL import Image

raiz_projeto = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(raiz_projeto))

from src.audio import AudioProcessor
from src.vision import VisionProcessor, CAMPOS_FICHA
from src.llm_client import LLMResponse
from src.image_generation import ImageGenerator
from src.audit import AuditManager
from src.parsers import SolicitacaoEstruturada


def test_audio_validacao_e_conferencia():
    """Valida requisitos de áudio: extensão, tamanho e conferência de dados críticos (RF06)."""
    ap = AudioProcessor()
    caminho_audio = raiz_projeto / "dados" / "originais" / "entrada_audio.mp3"

    valido, msg = ap.validar_arquivo(caminho_audio)
    assert valido is True

    # Teste com arquivo falso excedendo limites
    caminho_falso = raiz_projeto / "dados" / "originais" / "invalido.xyz"
    valido_falso, msg_falso = ap.validar_arquivo(caminho_falso)
    assert valido_falso is False

    # Metadados
    meta = ap.extrair_metadados(caminho_audio)
    assert meta["duracao_segundos"] > 0
    assert meta["taxa_amostragem_hz"] > 0


class ClienteVisaoFalso:
    """Devolve uma leitura fixa da ficha, simulando a resposta do modelo (sem rede)."""

    def __init__(self, leitura_json: str):
        self.leitura_json = leitura_json

    def gerar_multimodal(self, *args, **kwargs):
        return LLMResponse(conteudo=self.leitura_json, modelo="falso", provedor="teste", sucesso=True, latencia_ms=1.0)


def test_visao_leitura_revisao_e_gabarito(tmp_path):
    """Converte a leitura do modelo em texto bruto, versão revisada e comparação com o gabarito (RF08)."""
    lido = {cid: {"valor_lido": "", "valor_corrigido": "não localizado", "situacao": "EM_BRANCO", "observacao": ""} for cid in CAMPOS_FICHA}
    preenchidos = {
        "codigo": ("2026-000142", "INCERTO", "4 ou 6 no quarto dígito"), "nome": ("MARCOS VINICIUS DE ALMEIDA SANTOS", "LEGIVEL", ""),
        "data_nascimento": ("12/08/2008", "LEGIVEL", ""), "cpf": ("123.456.789-00", "LEGIVEL", ""), "rg": ("1234567-8", "LEGIVEL", ""),
        "naturalidade": ("CUIABA", "LEGIVEL", ""), "nome_mae": ("LUCIA HELENA DE ALMEIDA SANTOS", "LEGIVEL", ""),
        "curso": ("TECNICO EM ENFERMAGEM", "LEGIVEL", ""), "carga_horaria": ("1200 HORAS", "LEGIVEL", ""),
        "eixo_tecnologico": ("SAUDE", "LEGIVEL", ""), "turno": ("NOTURNO", "LEGIVEL", ""), "inicio_curso": ("01/02/2027", "LEGIVEL", ""),
        "email": ("MARCOS.ALMEIDA.TESTE@EXAMPLO.COM", "LEGIVEL", ""), "data_matricula": ("14/10/2026", "LEGIVEL", ""),
    }
    for cid, (valor, situacao, obs) in preenchidos.items():
        lido[cid] = {"valor_lido": valor, "valor_corrigido": valor, "situacao": situacao, "observacao": obs}
    leitura = {"cabecalho": "GOVERNO DE MATO GROSSO", **lido, "termo_ciencia_faltas_marcado": True,
               "assinatura_aluno_presente": True, "assinatura_secretaria_presente": False}

    vp = VisionProcessor(llm_client=ClienteVisaoFalso(json.dumps(leitura, ensure_ascii=False)))
    vp.dir_processados = tmp_path
    res = vp.processar_caso_visao("dados/originais/entrada_pdf-imagem.pdf")

    revisada = res["dados_revisados"]
    assert res["sucesso"] is True
    assert "2026-000142" in res["texto_bruto"] and "[INCERTO]" in res["texto_bruto"]
    assert set(revisada["campos_em_branco_detectados"]) == {
        "orgao_expedidor", "uf", "nome_pai", "turma", "municipio", "termino_curso",
        "telefone_celular", "telefone_residencial", "assinatura_secretaria_escolar"
    }
    assert revisada["trechos_incertos"][0]["campo"] == "codigo"
    assert revisada["solicitante"]["orgao_expedidor"] == "não localizado"
    assert (tmp_path / "visao_bruta.txt").exists() and (tmp_path / "comparacao_visao_gabarito.json").exists()
    # O gabarito registra o e-mail como escrito na ficha (EXAMPLO)
    assert "solicitante.email" not in res["comparacao_gabarito"]["divergentes"]
    incertos = res["comparacao_gabarito"]["incertos_esperados"]
    assert incertos["sinalizados"] == ["codigo"] and incertos["nao_sinalizados"] == ["cpf"]


class ClienteImagemFalso:
    """Simula o modelo de imagem: devolve um PNG gerado localmente ou uma falha (sem rede)."""
    disponivel = True
    timeout = 5

    def __init__(self, falha: str = None):
        self.falha = falha

    def gerar_imagem(self, prompt, modelo, proporcao="16:9", seed=None, max_tentativas=1):
        if self.falha:
            return LLMResponse(conteudo="", modelo=modelo, provedor="google", sucesso=False, latencia_ms=1.0,
                               codigo_erro=self.falha, erro="cota zero para modelos de imagem")
        buffer = io.BytesIO()
        Image.new("RGB", (1344, 768), (200, 225, 215)).save(buffer, format="PNG")
        return LLMResponse(conteudo="", modelo=modelo, provedor="google", sucesso=True, latencia_ms=1.0,
                           parametros={"seed": seed, "proporcao": proporcao}, dados_binarios=buffer.getvalue(), mime_type="image/png")


REGISTRO_CONFIRMADO = {"curso": {"nome": "Técnico em Enfermagem", "eixo_tecnologico": "Saúde", "carga_horaria": "1200 horas",
                                 "turno": "Noturno", "data_inicio": "01/02/2027"}}


def test_cartaz_ilustracao_ia_editada_com_proveniencia(tmp_path):
    """Ilustração do modelo + edição com Pillow: textos medidos, sem glifos ausentes, revisão PENDENTE (RF10)."""
    res = ImageGenerator(llm_client=ClienteImagemFalso(), dir_saida=tmp_path).gerar_cartaz_orientacao(REGISTRO_CONFIRMADO, "2026-000142")

    assert res["sucesso"] is True
    assert Path(res["caminho_imagem"]).exists() and Path(res["caminho_ilustracao"]).exists()
    assert Path(res["caminho_imagem"]).name.startswith("cartaz_orientacao_matricula_")
    meta = json.loads(Path(res["caminho_metadados"]).read_text(encoding="utf-8"))
    # O hash registrado é o do arquivo da ilustração salvo, byte a byte
    import hashlib
    assert meta["ilustracao"]["sha256_original"] == hashlib.sha256(Path(res["caminho_ilustracao"]).read_bytes()).hexdigest()
    # Uma segunda geração não sobrescreve a primeira
    res2 = ImageGenerator(llm_client=ClienteImagemFalso(), dir_saida=tmp_path).gerar_cartaz_orientacao(REGISTRO_CONFIRMADO, "2026-000142")
    assert res2["caminho_imagem"] != res["caminho_imagem"] and Path(res["caminho_imagem"]).exists()
    assert meta["status_revisao"] == "PENDENTE"
    assert all(v is None for v in meta["checklist_revisao_humana"].values())
    assert meta["ilustracao"]["modelo"] == "gemini-3.1-flash-image" and meta["ilustracao"]["seed"] is not None
    assert {"sujeito", "composicao", "estilo", "iluminacao", "proporcao", "restricoes"} <= set(meta["ilustracao"]["prompt_estruturado"])
    assert meta["ilustracao"]["prompt_enviado"] == res["prompt"]
    verificacoes = meta["verificacoes_automaticas"]
    assert verificacoes["textos_dentro_das_areas"] and verificacoes["nota_de_proveniencia_visivel"]
    assert verificacoes["glifos_ausentes_na_fonte"] == []
    # Nada de documentos inventados, "Portaria" ou "prazo improrrogável"
    textos = json.dumps(meta["textos_inseridos"], ensure_ascii=False).lower()
    assert "portaria" not in textos and "improrrog" not in textos and "histórico escolar" not in textos


def test_cartaz_registra_substituicao_quando_modelo_principal_falha(tmp_path, monkeypatch):
    """Cota zero no modelo principal: tenta o modelo aberto e registra a substituição; sem HF_TOKEN, falha clara."""
    monkeypatch.delenv("HF_TOKEN", raising=False)
    res = ImageGenerator(llm_client=ClienteImagemFalso(falha="LIMITE_REQUISICOES"), dir_saida=tmp_path).gerar_cartaz_orientacao()

    assert res["sucesso"] is False
    assert res["resposta"].codigo_erro == "CHAVE_AUSENTE" and "HF_TOKEN" in res["erro"]
    assert res["substituicao"]["modelo_substituto"] == "black-forest-labs/FLUX.1-schnell"
    assert "LIMITE_REQUISICOES" in res["substituicao"]["motivo"]
    assert not list(tmp_path.glob("cartaz_orientacao_matricula*.png"))


def test_glifo_ausente_e_detectado():
    """Caracteres sem glifo na fonte (que sairiam como '□') são apontados."""
    gerador = ImageGenerator(llm_client=None)
    fonte = gerador._fonte(24)
    assert gerador.glifos_ausentes(fonte, "Matrícula à frequência") == []
    assert gerador.glifos_ausentes(fonte, "A\U0001F680") == ["\U0001F680"]


def test_locucao_montada_dos_campos_aprovados():
    """O texto falado vem dos campos aprovados: sem hash nem fontes, com aviso de não localizado e status aprovado (RF07)."""
    ap = AudioProcessor(llm_client=ClienteVisaoFalso("{}"))
    registro = SolicitacaoEstruturada(protocolo="2026-000142", campos_ausentes=["orgao_expedidor", "documentos_comprobatorios_anexos"],
                                      hash_origem_sha256="8bc1318c6b3165a1")
    conteudo = {"assunto": "Efetivação de matrícula", "saudacao": "Prezado Marcos,",
                "paragrafos": ["As aulas começam em 01/02/2027."], "fechamento": "Atenciosamente,", "alertas_para_revisor": ["x"]}
    texto = ap.montar_texto_locucao(registro, conteudo)

    assert "primeiro de fevereiro de 2027" in texto
    assert "não foram localizadas" in texto and "Órgão expedidor do RG" in texto
    assert "aprovada por servidor" in texto and "pendente" not in texto.lower()
    assert "8bc1318c" not in texto and "SHA" not in texto and "FONTES" not in texto


def test_auditoria_sem_vazamento_de_segredos(tmp_path):
    """O registro de uma chamada com erro contendo chaves não grava as chaves e permite reconstruir a execução (RF11)."""
    audit = AuditManager()
    audit.arquivo_log_jsonl = tmp_path / "auditoria.jsonl"
    chaves = "AIza" + "D" * 35 + " AQ." + "X" * 40 + " sk-" + "a" * 32 + " hf_" + "b" * 30
    resposta = LLMResponse(conteudo="", modelo="gemini-teste", provedor="google", sucesso=False, latencia_ms=12.0,
                           codigo_erro="AUTENTICACAO", erro=f"chave recusada: {chaves}",
                           parametros={"temperatura": 0.2, "api_key": "segredo"})
    audit.registrar_execucao(caso_id="CASO_TESTE", etapa="extracao_estruturada", modalidade="texto",
                             arquivo_origem="dados/originais/entrada_texto.txt", resposta=resposta,
                             prompt_id="PROMPT_EXTRACAO_JSON", prompt_versao="1.1", prompt_texto="prompt de teste")

    linha = (tmp_path / "auditoria.jsonl").read_text(encoding="utf-8")
    registro = json.loads(linha)
    for trecho in ("AIzaD", "AQ.X", "sk-aaa", "hf_bbb", "segredo", "prompt de teste"):
        assert trecho not in linha
    assert registro["modelo"] == "gemini-teste" and registro["prompt"]["versao"] == "1.1"
    assert registro["prompt"]["sha256"] and registro["sha256_origem"] and registro["codigo_erro"] == "AUTENTICACAO"
