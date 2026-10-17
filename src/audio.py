#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
==============================================================================
MÓDULO DE ÁUDIO: TRANSCRIÇÃO (STT) E COMPARAÇÃO COM GABARITO
Atende aos requisitos RF06 e RF07.
==============================================================================
Funcionalidades:
- Validação de formato e tamanho de áudio (RF06);
- Extração de metadados (duração, canais, taxa de amostragem) com mutagen;
- Transcrição bruta pelo modelo multimodal (áudio enviado ao Gemini) e
  versão revisada em segunda passada, sem completar trechos;
- Comparação com o texto de referência: WER e erros relevantes;
- Extração estruturada da transcrição revisada (mesmo esquema do texto);
- Síntese de voz (TTS) da minuta aprovada (RF07) via edge-tts, a partir dos
  campos aprovados, com o texto falado salvo ao lado do MP3 e verificação
  opcional por transcrição do áudio gerado.
==============================================================================
"""

import re
import json
import difflib
from pathlib import Path
from typing import Dict, Any, Tuple, Optional, List

import mutagen
from pydantic import BaseModel, Field, ValidationError

from src.llm_client import LLMClient, LLMResponse
from src.prompts import PROMPT_TRANSCRICAO_AUDIO, PROMPT_REVISAO_TRANSCRICAO
from src.parsers import ROTULOS_CAMPOS
from src.audit import nome_versionado
from src.conferencia import eh_ausente
from src.conferencia import (
    MAPA_GABARITO_SOLICITACAO,
    IGNORAR_GABARITO_SOLICITACAO,
    carregar_gabarito,
    comparar_com_gabarito,
    taxa_erro_palavras,
    diferencas_transcricao
)

# Formatos de áudio aceitos pelo Gemini para envio direto
MIME_AUDIO = {".mp3": "audio/mp3", ".wav": "audio/wav", ".ogg": "audio/ogg"}

MESES = ("janeiro", "fevereiro", "março", "abril", "maio", "junho",
         "julho", "agosto", "setembro", "outubro", "novembro", "dezembro")


class TranscricaoAudio(BaseModel):
    """Esquema da transcrição bruta retornada pelo modelo."""
    idioma_detectado: str = Field(description="Idioma no formato BCP-47, por exemplo pt-BR")
    transcricao_literal: str = Field(description="Transcrição literal, sem correções")
    trechos_inaudiveis: List[str] = Field(default_factory=list, description="Contexto dos trechos marcados como [INAUDÍVEL]")


class AudioProcessor:
    """Processador de áudio institucional para transcrição e síntese de voz."""

    def __init__(self, config_path: str = "config.json", llm_client: Optional[LLMClient] = None):
        self.raiz_projeto = Path(__file__).resolve().parent.parent
        self.config = self._carregar_config(config_path)
        self.audio_cfg = self.config.get("audio", {})
        self.max_size_mb = self.audio_cfg.get("tamanho_maximo_mb", 20)
        self.extensoes_permitidas = self.audio_cfg.get("extensoes_permitidas", list(MIME_AUDIO))
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

    def validar_arquivo(self, caminho_audio: Path) -> Tuple[bool, str]:
        """Valida extensão e tamanho do arquivo de áudio (RF06)."""
        if not caminho_audio.exists():
            return False, f"Arquivo não encontrado: {caminho_audio}"

        ext = caminho_audio.suffix.lower()
        if ext not in self.extensoes_permitidas or ext not in MIME_AUDIO:
            return False, f"Extensão '{ext}' inválida. Permitidas: {self.extensoes_permitidas}"

        tamanho_mb = caminho_audio.stat().st_size / (1024 * 1024)
        if tamanho_mb > self.max_size_mb:
            return False, f"Arquivo com {tamanho_mb:.2f} MB excede o limite de {self.max_size_mb} MB"

        return True, "Arquivo válido"

    def extrair_metadados(self, caminho_audio: Path) -> Dict[str, Any]:
        """Extrai duração, taxa de amostragem e canais usando mutagen."""
        audio = mutagen.File(str(caminho_audio))
        if audio is None or getattr(audio, "info", None) is None:
            return {"duracao_segundos": None, "duracao_formatada": "não disponível",
                    "erro": "Formato não reconhecido para leitura de metadados."}
        duracao = audio.info.length
        return {
            "duracao_segundos": round(duracao, 2),
            "duracao_formatada": f"{int(duracao // 60):02d}:{int(duracao % 60):02d}",
            "bitrate_bps": getattr(audio.info, "bitrate", None),
            "taxa_amostragem_hz": getattr(audio.info, "sample_rate", None),
            "canais": getattr(audio.info, "channels", None)
        }

    def transcrever_audio(self, caminho_audio: Path) -> Tuple[Optional[TranscricaoAudio], LLMResponse]:
        """Transcrição bruta: o arquivo de áudio é enviado ao modelo multimodal (RF06)."""
        resposta = self.llm_client.gerar_multimodal(
            caminho_audio,
            MIME_AUDIO[caminho_audio.suffix.lower()],
            PROMPT_TRANSCRICAO_AUDIO,
            schema=TranscricaoAudio
        )
        if not resposta.sucesso:
            return None, resposta
        try:
            return TranscricaoAudio.model_validate_json(resposta.conteudo), resposta
        except ValidationError as e:
            resposta.marcar_falha("RESPOSTA_FORA_DO_ESQUEMA", f"A transcrição retornada não segue o esquema esperado ({e.error_count()} erro(s)).")
            return None, resposta

    def revisar_transcricao(self, transcricao_bruta: str) -> Tuple[str, LLMResponse, str]:
        """Segunda passada: pontuação e números, sem acrescentar conteúdo. Retorna (texto, resposta, prompt)."""
        prompt = PROMPT_REVISAO_TRANSCRICAO.format(transcricao_bruta=transcricao_bruta)
        resposta = self.llm_client.gerar(prompt)
        return (resposta.conteudo.strip() if resposta.sucesso else ""), resposta, prompt

    def comparar_com_gabarito(self, arquivo_audio: str, bruta: str, revisada: str, registro: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Compara a transcrição com o texto de referência e aponta erros relevantes (RF06).
        Também compara os campos extraídos com os dados esperados do gabarito.
        """
        gabarito = carregar_gabarito(self.raiz_projeto, self.config, arquivo_audio)
        if not gabarito:
            return {"erro": "Gabarito de áudio não encontrado"}

        referencia = gabarito.get("transcricao_referencia", "")
        esperados = gabarito.get("dados_extraidos_esperados", {})
        termos_criticos = [
            esperados.get("solicitante", {}).get("nome_completo", ""),
            esperados.get("solicitante", {}).get("nome_mae", ""),
            esperados.get("solicitante", {}).get("email", "")
        ]
        diferencas = diferencas_transcricao(referencia, revisada, termos_criticos)
        return {
            "caso_id": gabarito.get("caso_id"),
            "wer_bruta_pct": taxa_erro_palavras(referencia, bruta),
            "wer_revisada_pct": taxa_erro_palavras(referencia, revisada),
            "similaridade_revisada_pct": round(difflib.SequenceMatcher(None, referencia.lower(), revisada.lower()).ratio() * 100, 2),
            "erros_relevantes_revisada": [d for d in diferencas if d["critico"]],
            "diferencas_revisada": diferencas,
            "campos_extraidos": comparar_com_gabarito(
                registro, esperados, mapa=MAPA_GABARITO_SOLICITACAO, ignorar=IGNORAR_GABARITO_SOLICITACAO
            ) if registro else None
        }

    def processar_caso_audio(self, arquivo_audio: str, gerador) -> Dict[str, Any]:
        """
        Pipeline de áudio (RF06): validação, metadados, transcrição bruta, revisão,
        extração estruturada e comparação com o gabarito.
        `gerador` é o GeradorMinuta usado na extração. As chamadas ao modelo são
        devolvidas em 'chamadas' para registro na auditoria.
        """
        caminho_audio = self.raiz_projeto / arquivo_audio
        resultado: Dict[str, Any] = {"sucesso": False, "arquivo_origem": arquivo_audio, "chamadas": []}

        valido, msg_validacao = self.validar_arquivo(caminho_audio)
        if not valido:
            resultado["erro"] = msg_validacao
            return resultado
        resultado["metadados"] = self.extrair_metadados(caminho_audio)
        self.dir_processados.mkdir(parents=True, exist_ok=True)

        # 1. Transcrição bruta (preservada sem alterações)
        transcricao, resposta = self.transcrever_audio(caminho_audio)
        caminho_bruta = self.dir_processados / "transcricao_bruta.txt"
        if transcricao:
            caminho_bruta.write_text(transcricao.transcricao_literal, encoding="utf-8")
        resultado["chamadas"].append({
            "etapa": "transcricao_bruta", "resposta": resposta,
            "prompt_id": "PROMPT_TRANSCRICAO_AUDIO", "prompt_texto": PROMPT_TRANSCRICAO_AUDIO,
            "arquivo_saida": caminho_bruta if transcricao else None,
            "resumo": (f"idioma={transcricao.idioma_detectado}; duracao={resultado['metadados'].get('duracao_formatada')} "
                       f"({resultado['metadados'].get('duracao_segundos')} s); {len(transcricao.transcricao_literal.split())} palavras")
                      if transcricao else None
        })
        if not transcricao:
            resultado["erro"] = resposta.erro
            return resultado
        resultado["idioma_detectado"] = transcricao.idioma_detectado
        resultado["trechos_inaudiveis"] = transcricao.trechos_inaudiveis
        resultado["transcricao_bruta"] = transcricao.transcricao_literal

        # 2. Versão revisada
        revisada, resposta, prompt = self.revisar_transcricao(transcricao.transcricao_literal)
        caminho_revisada = self.dir_processados / "transcricao_revisada.txt"
        if resposta.sucesso:
            caminho_revisada.write_text(revisada, encoding="utf-8")
        resultado["chamadas"].append({
            "etapa": "transcricao_revisada", "resposta": resposta,
            "prompt_id": "PROMPT_REVISAO_TRANSCRICAO", "prompt_texto": prompt,
            "arquivo_saida": caminho_revisada if resposta.sucesso else None,
            "resumo": f"{len(revisada.split())} palavras; {revisada.count('[INCERTO')} trecho(s) incerto(s)" if resposta.sucesso else None
        })
        if not resposta.sucesso:
            resultado["erro"] = resposta.erro
            return resultado
        resultado["transcricao_revisada"] = revisada

        # 3. Extração estruturada da transcrição revisada (mesmo esquema da entrada textual)
        registro, resposta, prompt = gerador.extrair_dados(
            revisada, "mensagem de voz", caminho_revisada, salvar_como="extracao_audio.json"
        )
        resultado["chamadas"].append({
            "etapa": "extracao_estruturada", "resposta": resposta,
            "prompt_id": "PROMPT_EXTRACAO_JSON", "prompt_texto": prompt,
            "arquivo_saida": self.dir_processados / "extracao_audio.json" if registro else None,
            "resumo": f"categoria={registro.categoria_tema}; campos_ausentes={len(registro.campos_ausentes)}" if registro else None
        })
        if not registro:
            resultado["erro"] = resposta.erro
            return resultado
        resultado["registro"] = registro

        # 4. Comparação com o texto de referência e com os dados esperados
        comparacao = self.comparar_com_gabarito(arquivo_audio, transcricao.transcricao_literal, revisada, registro.model_dump())
        comparacao["metadados_audio"] = resultado["metadados"]
        comparacao["idioma_detectado"] = transcricao.idioma_detectado
        (self.dir_processados / "comparacao_audio_gabarito.json").write_text(
            json.dumps(comparacao, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        resultado["comparacao_gabarito"] = comparacao
        resultado["sucesso"] = True
        return resultado

    @staticmethod
    def _adaptar_pronuncia(texto: str) -> str:
        """Ajustes de leitura que não mudam o conteúdo: datas por extenso e siglas."""
        def data_falada(m: "re.Match") -> str:
            dia, mes, ano = int(m.group(1)), int(m.group(2)), m.group(3)
            if not 1 <= mes <= 12:
                return m.group(0)
            return f"{'primeiro' if dia == 1 else dia} de {MESES[mes - 1]} de {ano}"
        texto = re.sub(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b", data_falada, texto)
        texto = texto.replace("SECITECI/MT", "Seciteci, Mato Grosso")
        return texto

    def montar_texto_locucao(self, registro, conteudo: Dict[str, Any]) -> str:
        """
        Texto falado da minuta aprovada (RF07), montado a partir dos mesmos campos
        usados no documento: assunto, saudação, parágrafos, lista de informações não
        localizadas e fechamento. Não inclui hash, lista de fontes nem a seção de
        auditoria. O aviso final descreve o status real (aprovada pelo servidor).
        """
        # Protocolo lido dígito a dígito ("2026-000142" -> "2 0 2 6, 0 0 0 1 4 2"); ausente é dito por extenso
        if eh_ausente(registro.protocolo):
            frase_protocolo = "Resposta à solicitação. Número de protocolo não localizado."
        else:
            protocolo_falado = ", ".join(" ".join(grupo) for grupo in re.split(r"[-/.\s]+", registro.protocolo) if grupo)
            frase_protocolo = f"Resposta à solicitação de protocolo {protocolo_falado}."
        partes = [
            "Escola Técnica Estadual de Cuiabá. Secretaria Escolar.",
            frase_protocolo,
            f"Assunto: {conteudo['assunto']}.",
            conteudo["saudacao"],
            *conteudo["paragrafos"],
        ]
        if registro.campos_ausentes:
            rotulos = [ROTULOS_CAMPOS.get(c, c) for c in registro.campos_ausentes]
            partes.append(
                "Atenção: as seguintes informações não foram localizadas nos dados recebidos: "
                + "; ".join(rotulos) + "."
            )
        partes += [
            conteudo["fechamento"],
            "Secretaria Escolar da Escola Técnica Estadual de Cuiabá.",
            "Esta resposta foi redigida com apoio de inteligência artificial e aprovada por servidor da secretaria escolar."
        ]
        texto = " ".join(p.strip() for p in partes if p and p.strip())
        return self._adaptar_pronuncia(texto)

    def sintetizar_minuta_acessivel(self, registro, conteudo: Dict[str, Any], protocolo: str) -> Dict[str, Any]:
        """
        Gera a versão falada (MP3) da minuta aprovada com edge-tts (RF07) e salva, ao lado,
        o texto exato enviado ao sintetizador (.txt).
        """
        import asyncio
        import edge_tts

        voz = self.audio_cfg.get("tts_voz_padrao", "pt-BR-FranciscaNeural")
        taxa = self.audio_cfg.get("tts_taxa", "+0%")
        volume = self.audio_cfg.get("tts_volume", "+0%")
        tom = self.audio_cfg.get("tts_tom", "+0Hz")
        dir_audios = self.raiz_projeto / "resultados" / "audios"
        dir_audios.mkdir(parents=True, exist_ok=True)
        # Nome versionado: uma nova síntese não sobrescreve a anterior
        nome = nome_versionado(dir_audios, f"minuta_acessivel_{protocolo}", [".mp3", ".txt", "_verificacao.json"])
        caminho_saida = dir_audios / f"{nome}.mp3"
        caminho_texto = dir_audios / f"{nome}.txt"

        texto_locucao = self.montar_texto_locucao(registro, conteudo)
        caminho_texto.write_text(texto_locucao + "\n", encoding="utf-8")

        async def _executar_tts():
            comunicador = edge_tts.Communicate(texto_locucao, voz, rate=taxa, volume=volume, pitch=tom)
            await comunicador.save(str(caminho_saida))

        try:
            asyncio.run(_executar_tts())
            sucesso = True
            msg = "Áudio de acessibilidade sintetizado com sucesso."
        except Exception as e:
            sucesso = False
            msg = f"Falha na síntese de voz: {type(e).__name__}: {e}"

        return {
            "sucesso": sucesso,
            "caminho_audio": str(caminho_saida),
            "caminho_texto": str(caminho_texto),
            "texto_locucao": texto_locucao,
            "voz_utilizada": voz,
            "parametros": {"voz": voz, "taxa": taxa, "volume": volume, "tom": tom},
            "tamanho_bytes": caminho_saida.stat().st_size if sucesso and caminho_saida.exists() else 0,
            "mensagem": msg
        }

    def verificar_locucao(self, caminho_audio: Path, texto_locucao: str) -> Tuple[Dict[str, Any], LLMResponse]:
        """
        Verificação opcional do critério de aceite do RF07: transcreve o MP3 gerado e
        compara com o texto enviado ao sintetizador (WER e palavras acrescentadas).
        """
        transcricao, resposta = self.transcrever_audio(Path(caminho_audio))
        if not transcricao:
            return {"sucesso": False, "erro": resposta.erro}, resposta
        diferencas = diferencas_transcricao(texto_locucao, transcricao.transcricao_literal)
        acrescimos = [d for d in diferencas if d["tipo"] == "INSERCAO"]
        resultado = {
            "sucesso": True,
            "wer_pct": taxa_erro_palavras(texto_locucao, transcricao.transcricao_literal),
            "trechos_acrescentados": acrescimos,
            "diferencas": diferencas,
            "transcricao_do_audio": transcricao.transcricao_literal
        }
        caminho = Path(caminho_audio).with_name(Path(caminho_audio).stem + "_verificacao.json")
        caminho.write_text(json.dumps(resultado, indent=2, ensure_ascii=False), encoding="utf-8")
        resultado["caminho_verificacao"] = str(caminho)
        return resultado, resposta
