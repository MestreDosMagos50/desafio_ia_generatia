#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
==============================================================================
CENTRAL INTELIGENTE DE ATENDIMENTO E COMUNICAÇÃO INSTITUCIONAL
FIC_DEV - Programa Programador de Sistemas com IA - Desafio Prático 1
==============================================================================
Ponto de entrada unificado da aplicação (executável via: python -m src.main)
Atende aos requisitos RF01, RF05, RF06, RF07, RF08, RF09, RF10, RF11 e RF13.
==============================================================================
"""

import os
import sys
import json
import time
import logging
import argparse
from importlib import metadata
from pathlib import Path
from typing import Any, Dict, List

# Carregamento de variáveis de ambiente do .env
try:
    from dotenv import load_dotenv
    load_dotenv(dotenv_path=Path(__file__).resolve().parent.parent / ".env")
except ImportError:
    pass

# Os módulos de processamento são importados dentro das funções para que
# --check-env consiga diagnosticar bibliotecas ausentes sem interromper a execução.

RAIZ_PROJETO = Path(__file__).resolve().parent.parent

BIBLIOTECAS_PRINCIPAIS = [
    "google-genai",
    "httpx",
    "python-dotenv",
    "pydantic",
    "mutagen",
    "edge-tts",
    "pillow",
    "gradio_client",
    "pypdf",
    "python-docx",
    "pytest",
]


def carregar_configuracao(caminho_config: str = "config.json") -> dict:
    """Carrega o arquivo de configuração central do projeto."""
    caminho = Path(caminho_config)
    if not caminho.is_absolute():
        caminho = RAIZ_PROJETO / caminho_config

    if not caminho.exists():
        raise FileNotFoundError(f"Arquivo de configuração não localizado: {caminho}")

    with open(caminho, "r", encoding="utf-8") as f:
        return json.load(f)


def _versoes_fixadas() -> Dict[str, str]:
    """Lê as versões fixadas (==) no requirements.txt."""
    fixadas = {}
    requirements = RAIZ_PROJETO / "requirements.txt"
    if requirements.exists():
        for linha in requirements.read_text(encoding="utf-8").splitlines():
            linha = linha.split("#")[0].strip()
            if "==" in linha:
                nome, versao = linha.split("==", 1)
                fixadas[nome.strip().lower()] = versao.strip()
    return fixadas


def verificar_ambiente(config: dict) -> bool:
    """Executa a checagem de integridade do ambiente (RF01)."""
    print("=" * 70)
    print("  VERIFICAÇÃO DE AMBIENTE - CENTRAL DE ATENDIMENTO INTELIGENTE")
    print("=" * 70)
    print(f"• Diretório Raiz: {RAIZ_PROJETO}")
    print(f"• Versão do Python: {sys.version.split()[0]} ({sys.platform})")

    # 1. Checagem de Diretórios
    print("\n[1/4] Verificando Diretórios da Estrutura...")
    todos_diretorios_ok = True
    for chave, rel_path in config.get("diretorios", {}).items():
        dir_path = RAIZ_PROJETO / rel_path
        status = "OK" if dir_path.exists() else "AUSENTE"
        if not dir_path.exists():
            todos_diretorios_ok = False
        print(f"  - {rel_path:25} : {status}")

    # 2. Checagem de Arquivos Originais
    print("\n[2/4] Verificando Arquivos Originais de Entrada...")
    todos_arquivos_ok = True
    for chave, rel_path in config.get("arquivos_originais", {}).items():
        arq_path = RAIZ_PROJETO / rel_path
        if arq_path.exists():
            tamanho_kb = arq_path.stat().st_size / 1024
            print(f"  - {rel_path:35} : OK ({tamanho_kb:.1f} KB)")
        else:
            todos_arquivos_ok = False
            print(f"  - {rel_path:35} : AUSENTE")

    # 3. Checagem de Bibliotecas (versões instaladas x fixadas no requirements.txt)
    print("\n[3/4] Verificando Bibliotecas Instaladas...")
    fixadas = _versoes_fixadas()
    todas_bibliotecas_ok = True
    for pacote in BIBLIOTECAS_PRINCIPAIS:
        try:
            versao = metadata.version(pacote)
        except metadata.PackageNotFoundError:
            todas_bibliotecas_ok = False
            print(f"  - {pacote:15} : NÃO INSTALADA (execute: pip install -r requirements.txt)")
            continue
        esperada = fixadas.get(pacote.lower())
        if esperada and esperada != versao:
            print(f"  - {pacote:15} : v{versao} (ATENÇÃO: requirements.txt fixa v{esperada})")
        else:
            print(f"  - {pacote:15} : OK (v{versao})")

    # 4. Checagem do Provedor de IA (sem chamada de rede)
    print("\n[4/4] Verificando Provedor de IA e Credenciais...")
    provedor_ok = False
    try:
        from src.llm_client import LLMClient
        cliente = LLMClient()
        print(f"  - Provedor: {cliente.provedor} | Modelo: {cliente.modelo} | Timeout: {cliente.timeout} s")
        if cliente.disponivel:
            provedor_ok = True
            print("  - GEMINI_API_KEY: configurada (valor não exibido; a validade é confirmada na primeira chamada)")
        else:
            print(f"  - INDISPONÍVEL: {cliente.motivo_indisponibilidade}")
    except ImportError as e:
        print(f"  - Não foi possível carregar o cliente de IA: {e}")

    print("\n" + "=" * 70)
    sucesso = todos_diretorios_ok and todos_arquivos_ok and todas_bibliotecas_ok
    print(f"  STATUS GERAL: {'AMBIENTE E ARQUIVOS BASE ÍNTEGROS!' if sucesso else 'ATENÇÃO: PENDÊNCIAS'}")
    if sucesso and not provedor_ok:
        print("  Configure o provedor de IA (.env) para executar o pipeline.")
    print("=" * 70)
    return sucesso


def exibir_info(config: dict):
    """Exibe informações sobre o sistema e seus módulos configurados."""
    app = config.get("app", {})
    llm = config.get("llm", {})
    print("=" * 70)
    print(f"  {app.get('name', 'Central de Atendimento').upper()}")
    print(f"  Versão: {app.get('version')} | {app.get('institution')}")
    print("=" * 70)
    print(f"Descrição: {app.get('description')}")
    print(f"Provedor LLM: {llm.get('provider_padrao')} | Modelo: {os.getenv('GEMINI_MODEL', llm.get('modelo_padrao'))}")
    print(f"Voz TTS Padrão: {config.get('audio', {}).get('tts_voz_padrao')}")
    print(f"Categorias: {', '.join(config.get('classificacao', {}).get('categorias_validas', []))}")
    print("=" * 70)


def _ms(inicio: float) -> float:
    """Tempo decorrido em milissegundos desde `inicio` (time.perf_counter)."""
    return (time.perf_counter() - inicio) * 1000.0


def _caso_id(config: dict, arquivo: str, padrao: str) -> str:
    """Identificador do caso definido no gabarito da entrada (RF11: relaciona saída e caso)."""
    from src.conferencia import carregar_gabarito
    gabarito = carregar_gabarito(RAIZ_PROJETO, config, arquivo)
    return gabarito.get("caso_id", padrao) if gabarito else padrao


def _registrar_chamadas(audit, caso_id: str, modalidade: str, arquivo_origem: str, chamadas: List[Dict[str, Any]]) -> Dict[str, str]:
    """Registra na auditoria cada chamada ao modelo devolvida por um módulo. Retorna {etapa: id_execucao}."""
    from src.prompts import VERSOES_PROMPTS
    ids = {}
    for chamada in chamadas:
        ids[chamada["etapa"]] = audit.registrar_execucao(
            caso_id=caso_id,
            etapa=chamada["etapa"],
            modalidade=modalidade,
            arquivo_origem=arquivo_origem,
            resposta=chamada["resposta"],
            prompt_id=chamada["prompt_id"],
            prompt_versao=VERSOES_PROMPTS.get(chamada["prompt_id"]),
            prompt_texto=chamada["prompt_texto"],
            arquivo_saida=chamada.get("arquivo_saida"),
            resumo_saida=chamada.get("resumo") or ""
        )
    return ids


CASO_CARTAZ = "RF10_CARTAZ"



def gerar_e_revisar_cartaz(llm, audit, registro: Dict[str, Any], protocolo: str, arq_brasao: str, auto_demo: bool) -> bool:
    """Retorna False se o cartaz não for gerado."""
    """Gera a ilustração por IA, compõe o cartaz (RF10), registra a execução e pede a revisão humana."""
    from src.image_generation import ImageGenerator
    from src.prompts import VERSOES_PROMPTS
    from src import revisao_humana as revisao

    res_img = ImageGenerator(llm_client=llm).gerar_cartaz_orientacao(registro, protocolo)
    substituicao = res_img.get("substituicao")
    id_cartaz = audit.registrar_execucao(
        caso_id=CASO_CARTAZ,
        etapa="comunicacao_visual",
        modalidade="imagem",
        arquivo_origem=arq_brasao,
        resposta=res_img["resposta"],
        prompt_id="PROMPT_ILUSTRACAO_CARTAZ",
        prompt_versao=VERSOES_PROMPTS["PROMPT_ILUSTRACAO_CARTAZ"],
        prompt_texto=res_img["prompt"],
        arquivo_saida=res_img.get("caminho_imagem"),
        resumo_saida=(f"dimensoes={res_img['dimensoes']}; protocolo={protocolo}; metadados={Path(res_img['caminho_metadados']).name}"
                      if res_img["sucesso"] else ""),
        observacao=("Ilustração gerada por modelo de imagem e editada com Pillow (brasão, textos conferidos e tarja)."
                    + (f" Substituição de modelo: {substituicao['modelo_original']} -> {substituicao['modelo_substituto']} "
                       f"({substituicao['motivo']})." if substituicao else ""))
    )
    if substituicao:
        print(f"  [!] {substituicao['modelo_original']} indisponível ({substituicao['motivo']})")
        print(f"      Modelo aberto usado como alternativa: {substituicao['modelo_substituto']}")
    if not res_img["sucesso"]:
        print(f"  [ERRO] Cartaz não gerado: {res_img['erro']}")
        return False
    print(f"  -> Cartaz gerado: {res_img['caminho_imagem']} (ilustração: {res_img['resposta'].modelo})")
    print(f"  -> Metadados: {res_img['caminho_metadados']}")
    revisao.revisar_cartaz(audit, res_img, id_cartaz, CASO_CARTAZ, auto_demo)
    return True


def executar_cartaz(config: dict, auto_demo: bool) -> bool:
    """
    Modo cartaz: gera e revisa só a peça visual (RF10). Os textos do curso vêm do último
    registro confirmado pelo servidor (dados/processados/registro_confirmado_*.json), se existir.
    """
    from src.llm_client import LLMClient
    from src.audit import AuditManager

    registros = sorted((RAIZ_PROJETO / "dados" / "processados").glob("registro_confirmado_*.json"),
                       key=lambda p: p.stat().st_mtime)
    registro = json.loads(registros[-1].read_text(encoding="utf-8")) if registros else None
    print("\n" + "#" * 75)
    print("  PEÇA VISUAL INSTITUCIONAL (RF10)")
    print(f"  Dados do curso: {registros[-1].relative_to(RAIZ_PROJETO).as_posix() if registros else 'nenhum registro confirmado (cartaz sem a linha do curso)'}")
    print("#" * 75)
    llm = LLMClient()
    protocolo = registro.get("protocolo", "não localizado") if registro else "não localizado"
    arq_brasao = config.get("arquivos_originais", {}).get("brasao", "dados/originais/brasao.png")
    return gerar_e_revisar_cartaz(llm, AuditManager(), registro, protocolo, arq_brasao, auto_demo)


def executar_pipeline(config: dict, modo: str = "completo", auto_demo: bool = False, entrada_texto: str = None) -> bool:
    """
    Orquestra o pipeline multimodal conforme o modo escolhido:
    - texto:    extração (RF05), conferência, minuta (RF09), revisão (RF13) e TTS (RF07);
    - audio:    transcrição e revisão (RF06), extração, conferência, minuta, revisão e TTS;
    - visao:    leitura da ficha (RF08) e conferência humana dos dados críticos;
    - completo: as três modalidades, conferência cruzada entre canais e peça visual (RF10).
    Cada chamada ao modelo e cada decisão humana é registrada na auditoria (RF11).
    """
    from src.llm_client import LLMClient
    from src.audit import AuditManager
    from src.parsers import GeradorMinuta, SolicitacaoEstruturada
    from src.audio import AudioProcessor
    from src.vision import VisionProcessor
    from src.prompts import VERSOES_PROMPTS
    from src.conferencia import conferencia_cruzada, aplicar_valores_confirmados
    from src import revisao_humana as revisao

    arquivos = config.get("arquivos_originais", {})
    arq_texto = entrada_texto or arquivos.get("texto", "dados/originais/entrada_texto.txt")
    arq_audio = arquivos.get("audio", "dados/originais/entrada_audio.mp3")
    arq_documento = arquivos.get("documento_imagem", "dados/originais/entrada_pdf-imagem.pdf")
    arq_brasao = arquivos.get("brasao", "dados/originais/brasao.png")

    executar_texto = modo in ("texto", "completo")
    executar_audio = modo in ("audio", "completo")
    executar_visao = modo in ("visao", "completo")
    executar_imagem = modo == "completo"
    gera_minuta = executar_texto or executar_audio

    llm = LLMClient()
    if not llm.disponivel:
        print(f"\n[ERRO] {llm.motivo_indisponibilidade}")
        print("Nenhuma etapa foi executada e nenhum arquivo foi alterado.")
        return False

    audit = AuditManager()
    gerador = GeradorMinuta(llm_client=llm)
    audio_proc = AudioProcessor(llm_client=llm) if gera_minuta else None
    dir_processados = RAIZ_PROJETO / "dados" / "processados"

    etapas_previstas = sum([executar_texto, executar_audio, executar_visao, True, gera_minuta, executar_imagem, gera_minuta])
    etapa_atual = [0]

    def anunciar(titulo: str):
        etapa_atual[0] += 1
        print(f"\n[ETAPA {etapa_atual[0]}/{etapas_previstas}] {titulo}")

    print("\n" + "#" * 75)
    print(f"  INICIANDO PIPELINE DE ATENDIMENTO INSTITUCIONAL (modo: {modo})")
    print(f"  Modelo: {llm.modelo} | Demonstração automatizada: {'sim' if auto_demo else 'não'}")
    print("#" * 75)

    fontes_registros: Dict[str, Dict[str, Any]] = {}
    fontes_minuta: List[Dict[str, str]] = []
    pendencias: List[str] = []  # etapas obrigatórias que falharam: a execução termina como incompleta
    pontos_atencao: List[str] = []
    registro_texto = registro_audio = None
    caso_texto = _caso_id(config, arq_texto, f"CASO_TEXTO_{gerador.nome_base(arq_texto).upper()}")
    caso_audio = _caso_id(config, arq_audio, "CASO_03_AUDIO")
    caso_visao = _caso_id(config, arq_documento, "CASO_02_VISAO")

    # --------------------------------------------------------------------------
    # SOLICITAÇÃO TEXTUAL: EXTRAÇÃO ESTRUTURADA (RF05)
    # --------------------------------------------------------------------------
    if executar_texto:
        anunciar(f"Processando Solicitação Textual ({Path(arq_texto).name})...")
        registro_texto, resposta, prompt, saida = gerador.extrair_dados_texto(arq_texto)
        audit.registrar_execucao(
            caso_id=caso_texto,
            etapa="extracao_estruturada",
            modalidade="texto",
            arquivo_origem=arq_texto,
            resposta=resposta,
            prompt_id="PROMPT_EXTRACAO_JSON",
            prompt_versao=VERSOES_PROMPTS["PROMPT_EXTRACAO_JSON"],
            prompt_texto=prompt,
            arquivo_saida=saida if registro_texto else None,
            resumo_saida=(
                f"categoria={registro_texto.categoria_tema}; campos_ausentes={len(registro_texto.campos_ausentes)}; "
                f"alertas={len(registro_texto.alertas)}" if registro_texto else ""
            )
        )
        if registro_texto is None:
            print(f"  [ERRO] Extração não realizada: {resposta.erro}")
            pendencias.append(f"Extração do texto falhou ({resposta.codigo_erro})")
        else:
            comparacao = gerador.comparar_com_gabarito(registro_texto, arq_texto)
            print(f"  -> Extração: {saida.relative_to(RAIZ_PROJETO).as_posix()} | categoria: {registro_texto.categoria_tema}")
            print(f"  -> Campos ausentes: {', '.join(registro_texto.campos_ausentes) or 'nenhum'}")
            if comparacao:
                print(f"  -> Gabarito: {comparacao['taxa_acerto_pct']}% de acerto ({comparacao['acertos']}/{comparacao['total_campos']}) | "
                      f"inventados: {len(comparacao['inventados'])} | omitidos: {len(comparacao['omitidos'])} | divergentes: {len(comparacao['divergentes'])}")
            for alerta in registro_texto.alertas:
                print(f"  [!] {alerta}")
            fontes_registros["texto"] = registro_texto.model_dump()
            fontes_minuta.append({"canal": "texto", "arquivo": arq_texto,
                                  "sha256": registro_texto.hash_origem_sha256, "texto": registro_texto.texto_original})
            pontos_atencao += [f"Texto: {a}" for a in registro_texto.alertas]

    # --------------------------------------------------------------------------
    # MENSAGEM DE VOZ: TRANSCRIÇÃO E EXTRAÇÃO (RF06)
    # --------------------------------------------------------------------------
    res_audio, ids_audio = None, {}
    if executar_audio:
        anunciar(f"Processando Mensagem de Voz ({Path(arq_audio).name})...")
        t0 = time.perf_counter()
        res_audio = audio_proc.processar_caso_audio(arq_audio, gerador)
        ids_audio = _registrar_chamadas(audit, caso_audio, "audio", arq_audio, res_audio["chamadas"])
        if not res_audio["chamadas"]:
            audit.registrar_execucao(caso_id=caso_audio, etapa="validacao_entrada", modalidade="audio",
                                     arquivo_origem=arq_audio, duracao_ms=_ms(t0), sucesso=False, erro=res_audio.get("erro"))
        if not res_audio["sucesso"]:
            print(f"  [ERRO] {res_audio.get('erro')}")
            pendencias.append(f"Processamento do áudio falhou ({res_audio.get('erro')})")
        else:
            metadados = res_audio["metadados"]
            comparacao = res_audio["comparacao_gabarito"]
            registro_audio = res_audio["registro"]
            print(f"  -> Duração: {metadados['duracao_formatada']} | Idioma detectado: {res_audio['idioma_detectado']}")
            print(f"  -> WER em relação à referência: bruta {comparacao.get('wer_bruta_pct')}% | revisada {comparacao.get('wer_revisada_pct')}%")
            campos = comparacao.get("campos_extraidos") or {}
            if campos:
                print(f"  -> Campos extraídos x gabarito: {campos['taxa_acerto_pct']}% de acerto | divergentes: {', '.join(campos['divergentes']) or 'nenhum'}")
            for alerta in registro_audio.alertas:
                print(f"  [!] {alerta}")

    # --------------------------------------------------------------------------
    # DOCUMENTO DIGITALIZADO: LEITURA DA FICHA (RF08)
    # --------------------------------------------------------------------------
    res_visao, ids_visao = None, {}
    if executar_visao:
        anunciar(f"Processando Ficha de Matrícula Manuscrita ({Path(arq_documento).name})...")
        t0 = time.perf_counter()
        res_visao = VisionProcessor(llm_client=llm).processar_caso_visao(arq_documento)
        ids_visao = _registrar_chamadas(audit, caso_visao, "visao_documento", arq_documento, res_visao["chamadas"])
        if not res_visao["chamadas"]:
            audit.registrar_execucao(caso_id=caso_visao, etapa="validacao_entrada", modalidade="visao_documento",
                                     arquivo_origem=arq_documento, duracao_ms=_ms(t0), sucesso=False, erro=res_visao.get("erro"))
        if not res_visao["sucesso"]:
            print(f"  [ERRO] {res_visao.get('erro')}")
            pendencias.append(f"Leitura da ficha falhou ({res_visao.get('erro')})")
        else:
            revisada = res_visao["dados_revisados"]
            comparacao = res_visao["comparacao_gabarito"]
            print(f"  -> Gabarito: {comparacao.get('taxa_acerto_pct')}% de acerto | divergentes: {', '.join(comparacao.get('divergentes', [])) or 'nenhum'}")
            print(f"  -> Campos em branco: {', '.join(revisada['campos_em_branco_detectados']) or 'nenhum'}")
            print(f"  -> Trechos incertos ou ilegíveis: {len(revisada['trechos_incertos'])}")
            incertos = comparacao.get("incertos_esperados")
            if incertos:
                print(f"  -> Incertos esperados pelo gabarito: sinalizados {', '.join(incertos['sinalizados']) or 'nenhum'} | "
                      f"não sinalizados {', '.join(incertos['nao_sinalizados']) or 'nenhum'}")

    # --------------------------------------------------------------------------
    # REVISÃO DA TRANSCRIÇÃO E CONFERÊNCIA DOS DADOS CRÍTICOS (RF06 / RF08)
    # --------------------------------------------------------------------------
    if not fontes_registros and not (res_audio and res_audio["sucesso"]) and not (res_visao and res_visao["sucesso"]):
        print("\n[ERRO] Nenhuma entrada foi processada com sucesso; pipeline interrompido.")
        return False

    anunciar("Revisão humana e conferência dos dados críticos...")
    if res_visao and res_visao["sucesso"]:
        confirmada = revisao.revisar_ficha(audit, res_visao, ids_visao.get("ocr_visao"), caso_visao, auto_demo, dir_processados)
        if confirmada is None:
            print("  -> A leitura da ficha foi rejeitada e não entra na conferência.")
        else:
            fontes_registros["ficha"] = confirmada
            fontes_minuta.append({"canal": "ficha manuscrita", "arquivo": arq_documento,
                                  "sha256": audit.sha256_arquivo(RAIZ_PROJETO / arq_documento), "texto": res_visao["texto_bruto"]})
            pontos_atencao += [
                f"Ficha: campo {t['rotulo']} {t['situacao']} (lido: '{t['valor_lido']}') {t['observacao']}".strip()
                for t in confirmada["trechos_incertos"]
            ]
            pontos_atencao += [f"Ficha: campo '{c}' ficou PENDENTE de confirmação humana"
                               for c in confirmada.get("confirmacao_humana", {}).get("pendentes", [])]

    if res_audio and res_audio["sucesso"]:
        decisao_audio = revisao.revisar_transcricao_audio(
            audit, res_audio, ids_audio.get("transcricao_revisada"), caso_audio, auto_demo
        )
        if decisao_audio == "APROVADO":
            fontes_registros["audio"] = registro_audio.model_dump()
            fontes_minuta.append({"canal": "mensagem de voz", "arquivo": arq_audio,
                                  "sha256": audit.sha256_arquivo(RAIZ_PROJETO / arq_audio),
                                  "texto": res_audio["transcricao_revisada"]})
            pontos_atencao += [f"Áudio: {a}" for a in registro_audio.alertas]
        else:
            print("  -> Os dados da mensagem de voz foram excluídos da conferência.")
            registro_audio = None

    if not fontes_registros:
        print("\n  Nenhuma fonte aprovada para conferência: minuta não gerada.")
        if gera_minuta:
            pendencias.append("Nenhuma fonte aprovada: minuta não gerada")
        return _encerrar(pendencias, auto_demo)

    t0 = time.perf_counter()
    conferencia = conferencia_cruzada(fontes_registros)
    protocolo_sugerido = next((c["valor_sugerido"] for c in conferencia if c["campo"] == "protocolo"), "sem_protocolo")
    protocolo_arquivo = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in str(protocolo_sugerido))
    caminho_conferencia = dir_processados / f"conferencia_cruzada_{protocolo_arquivo}.json"
    caminho_conferencia.write_text(json.dumps(
        {"fontes": list(fontes_registros), "campos": conferencia, "pontos_atencao": pontos_atencao},
        indent=2, ensure_ascii=False
    ), encoding="utf-8")
    caso_principal = caso_texto if registro_texto else (caso_audio if registro_audio else caso_visao)
    divergentes = [c["campo"] for c in conferencia if c["status"] == "DIVERGENTE"]
    id_conferencia = audit.registrar_execucao(
        caso_id=caso_principal,
        etapa="conferencia_cruzada",
        modalidade="multimodal",
        arquivo_origem=fontes_minuta[0]["arquivo"],
        arquivo_saida=caminho_conferencia,
        resumo_saida=f"fontes={'+'.join(fontes_registros)}; divergentes={', '.join(divergentes) or 'nenhum'}",
        duracao_ms=_ms(t0),
        observacao="Comparação determinística entre canais; sem chamada a modelo de IA."
    )
    confirmados = revisao.conferir_dados_criticos(audit, conferencia, pontos_atencao, id_conferencia, caso_principal, auto_demo)

    # --------------------------------------------------------------------------
    # MINUTA INSTITUCIONAL (RF09) A PARTIR DOS DADOS CONFIRMADOS
    # --------------------------------------------------------------------------
    registro_base = registro_texto or registro_audio
    res_minuta, registro_confirmado, id_minuta = None, None, None
    caminho_registro = dir_processados / f"registro_confirmado_{protocolo_arquivo}.json"

    def gerar_minuta(dados: Dict[str, Any], id_anterior: str = None, motivo: str = None):
        """Gera a minuta a partir do registro confirmado e registra a execução (ligada à anterior, se houver)."""
        dados["campos_ausentes"] = gerador.calcular_campos_ausentes(dados)
        registro = SolicitacaoEstruturada(**dados)
        caminho_registro.write_text(registro.model_dump_json(indent=2), encoding="utf-8")
        res = gerador.gerar_minuta_institucional(registro, fontes_minuta)
        id_exec = audit.registrar_execucao(
            caso_id=caso_principal,
            etapa="geracao_minuta",
            modalidade="texto",
            arquivo_origem=caminho_registro,
            resposta=res["resposta"],
            prompt_id=res["prompt_id"],
            prompt_versao=res["prompt_versao"],
            prompt_texto=res["prompt_completo"],
            arquivo_saida=res.get("caminho_arquivo"),
            resumo_saida=f"alertas_validacao={len(res.get('alertas', []))}" if res["sucesso"] else "",
            id_execucao_anterior=id_anterior,
            observacao=f"Nova geração solicitada pelo revisor: {motivo}" if motivo else None
        )
        return registro, res, id_exec

    if gera_minuta:
        anunciar("Gerando Minuta Institucional (RF09)...")
        if registro_base is None:
            print("  Minuta não gerada: nenhuma solicitação (texto ou áudio aprovado) disponível.")
            pendencias.append("Minuta não gerada: nenhuma solicitação aprovada")
        else:
            dados = aplicar_valores_confirmados(registro_base.model_dump(), confirmados)
            registro_confirmado, res_minuta, id_minuta = gerar_minuta(dados)
            if not res_minuta["sucesso"]:
                print(f"  [ERRO] Minuta não gerada: {res_minuta.get('erro')}")
                pendencias.append(f"Geração da minuta falhou ({res_minuta['resposta'].codigo_erro if res_minuta.get('resposta') else res_minuta.get('erro')})")
            else:
                print(f"  -> Minuta: {res_minuta['caminho_arquivo']}")
                if res_minuta.get("caminho_docx"):
                    print(f"  -> Versão com brasão: {res_minuta['caminho_docx']}")
                print(f"  -> Alertas da validação automática: {len(res_minuta['alertas'])}")

    # --------------------------------------------------------------------------
    # COMUNICAÇÃO VISUAL (RF10)
    # --------------------------------------------------------------------------
    if executar_imagem:
        anunciar("Gerando Peça Visual Institucional...")
        protocolo = registro_confirmado.protocolo if registro_confirmado else str(protocolo_sugerido)
        if not gerar_e_revisar_cartaz(llm, audit, registro_confirmado.model_dump() if registro_confirmado else None,
                                      protocolo, arq_brasao, auto_demo):
            pendencias.append("Cartaz não gerado (RF10)")

    # --------------------------------------------------------------------------
    # REVISÃO HUMANA DA MINUTA (RF13) E ACESSIBILIDADE TTS (RF07)
    # --------------------------------------------------------------------------
    if res_minuta and res_minuta["sucesso"]:
        anunciar("Revisão Humana da Minuta (Human-in-the-Loop)...")
        revisao.revisar_minuta(audit, id_minuta, caso_principal, registro_confirmado, res_minuta, audio_proc, auto_demo,
                               regerar=gerar_minuta, pendencias=pendencias)

    return _encerrar(pendencias, auto_demo)


def _encerrar(pendencias: List[str], auto_demo: bool) -> bool:
    """Resumo final: concluído só se nenhuma etapa obrigatória falhou."""
    print("\n" + "=" * 75)
    if pendencias:
        print("  EXECUÇÃO INCOMPLETA — etapas obrigatórias com falha:")
        for pendencia in pendencias:
            print(f"   - {pendencia}")
        print("  Corrija a causa (ex.: aguarde a cota) e execute este modo novamente.")
    else:
        print("  PIPELINE CONCLUÍDO" + (" (DEMONSTRAÇÃO: decisões SIMULADAS, sem revisão humana)" if auto_demo else ""))
    print("  • Dados extraídos e comparações: dados/processados/")
    print("  • Minutas: resultados/minutas/ | Áudios: resultados/audios/ | Imagens: resultados/imagens/")
    print(f"  • Auditoria: resultados/logs/auditoria.jsonl e {'decisoes_simuladas.json (SIMULADO)' if auto_demo else 'decisoes_humanas.json'}")
    print("  • Relatório de qualidade: documentacao/relatorio_avaliacao_qualidade.md")
    print("=" * 75)
    return not pendencias


def parse_arguments():
    """Configura argumentos da linha de comando."""
    parser = argparse.ArgumentParser(
        description="Central Inteligente de Atendimento e Comunicação Institucional (FIC_DEV - Desafio 1)"
    )
    parser.add_argument(
        "--check-env",
        action="store_true",
        help="Executa diagnóstico completo da estrutura, arquivos originais e dependências (RF01)"
    )
    parser.add_argument(
        "--info",
        action="store_true",
        help="Exibe dados institucionais e configurações ativas do sistema"
    )
    parser.add_argument(
        "--modo",
        choices=["texto", "audio", "visao", "cartaz", "completo", "experimento-prompts"],
        default="completo",
        help="Etapas: texto, audio, visao, cartaz (peça visual, RF10), completo (todas + cartaz) ou experimento-prompts (RF02)"
    )
    parser.add_argument(
        "--entrada-texto",
        metavar="ARQUIVO",
        help="Solicitação textual alternativa, relativa à raiz do projeto (ex.: dados/originais/entrada_texto_injection.txt)"
    )
    parser.add_argument(
        "--demo-avaliacao-humana",
        action="store_true",
        help="Demonstração automatizada: decisões simuladas, gravadas em decisoes_simuladas.json e fora da taxa de aprovação (RF13)"
    )
    return parser.parse_args()


def configurar_logging():
    """Configura o nível de log a partir de LOG_LEVEL (padrão: WARNING)."""
    nivel = getattr(logging, os.getenv("LOG_LEVEL", "WARNING").strip().upper(), logging.WARNING)
    if not isinstance(nivel, int):
        nivel = logging.WARNING
    logging.basicConfig(level=nivel, format="%(levelname)s [%(name)s] %(message)s")
    # Bibliotecas de rede registram cada requisição em INFO; mantidas em WARNING
    for nome in ("httpx", "httpcore", "google_genai"):
        logging.getLogger(nome).setLevel(logging.WARNING)


def main():
    """Função principal de orquestração do sistema."""
    args = parse_arguments()
    configurar_logging()
    try:
        config = carregar_configuracao()
    except Exception as e:
        print(f"[ERRO CRÍTICO] Falha ao carregar configurações: {e}", file=sys.stderr)
        sys.exit(1)

    if args.check_env:
        sucesso = verificar_ambiente(config)
        sys.exit(0 if sucesso else 1)

    if args.info:
        exibir_info(config)
        sys.exit(0)

    if args.modo == "experimento-prompts":
        from testes.executar_experimento_prompts import executar_experimento
        sys.exit(0 if executar_experimento() else 1)

    if args.entrada_texto and not (RAIZ_PROJETO / args.entrada_texto).is_file():
        print(f"[ERRO] Arquivo de entrada não encontrado: {args.entrada_texto}", file=sys.stderr)
        sys.exit(1)

    if args.modo == "cartaz":
        sys.exit(0 if executar_cartaz(config, args.demo_avaliacao_humana) else 1)

    sucesso = executar_pipeline(config, modo=args.modo, auto_demo=args.demo_avaliacao_humana, entrada_texto=args.entrada_texto)
    sys.exit(0 if sucesso else 1)


if __name__ == "__main__":
    main()
