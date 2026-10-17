#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
==============================================================================
MÓDULO DE GERAÇÃO E EDIÇÃO DE IMAGEM INSTITUCIONAL (RF10)
==============================================================================
Fluxo:
1. Ilustração gerada por um modelo de imagem a partir de um prompt estruturado
   (sujeito, composição, estilo, iluminação, proporção e restrições), SEM texto:
   modelos de imagem erram letras. Modelo principal: Gemini (config.json,
   seção "imagem"); se a cota não incluir imagem, modelo aberto FLUX.1-schnell
   no Space oficial do Hugging Face (HF_TOKEN), com a substituição registrada.
2. Edição com Pillow: brasão oficial, textos conferidos (dados confirmados pelo
   servidor e texto impresso na ficha de matrícula) e tarja de proveniência.
   Cada texto é medido com draw.textbbox e quebrado/reduzido para caber na área;
   caracteres sem glifo na fonte (que apareceriam como "□") são detectados.
3. Metadados reais: modelo, prompt enviado, seed, data, hashes e edições.
   A revisão humana começa como PENDENTE.
==============================================================================
"""

import io
import os
import json
import time
import hashlib
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import httpx
import PIL
from PIL import Image, ImageDraw, ImageFont, ImageOps

from src.llm_client import LLMClient, LLMResponse
from src.conferencia import NAO_LOCALIZADO, eh_ausente
from src.prompts import PROMPT_ILUSTRACAO_CARTAZ_ESTRUTURADO, montar_prompt_ilustracao
from src.audit import nome_versionado

LARGURA, ALTURA, MARGEM = 1080, 1350, 40

AZUL = (10, 35, 75)
VERDE = (26, 107, 53)
DOURADO = (212, 160, 23)
VERMELHO = (160, 30, 30)
TEXTO = (30, 41, 59)
FUNDO = (248, 249, 250)

# Fontes com cobertura de acentos do português (regular, negrito)
FONTES_CANDIDATAS = [
    (r"C:\Windows\Fonts\segoeui.ttf", r"C:\Windows\Fonts\segoeuib.ttf"),
    (r"C:\Windows\Fonts\arial.ttf", r"C:\Windows\Fonts\arialbd.ttf"),
    ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
    ("/System/Library/Fonts/Supplemental/Arial.ttf", "/System/Library/Fonts/Supplemental/Arial Bold.ttf"),
]

# Texto impresso na ficha de matrícula (dados/originais/entrada_pdf-imagem.pdf), reproduzido sem alterar o sentido
REGRA_FALTAS_FICHA = [
    "A matrícula será automaticamente cancelada se o estudante faltar, sem justificativa comprovada:",
    "• nos 02 (dois) primeiros dias de aula consecutivos;",
    "• 03 (três) dias de aula, consecutivos ou não, no período dos 10 (dez) primeiros dias de aula.",
]
FONTE_REGRA_FALTAS = "Texto impresso na ficha de matrícula (dados/originais/entrada_pdf-imagem.pdf)"

ERROS_QUE_ACIONAM_ALTERNATIVA = {"LIMITE_REQUISICOES", "MODELO_NAO_ENCONTRADO", "REQUISICAO_INVALIDA", "RESPOSTA_VAZIA"}


def _sha256(dados: bytes) -> str:
    return hashlib.sha256(dados).hexdigest()


class ImageGenerator:
    """Gera a ilustração por IA e compõe o cartaz institucional com identificação de proveniência."""

    def __init__(self, config_path: str = "config.json", llm_client: Optional[LLMClient] = None,
                 dir_saida: Optional[Path] = None):
        self.raiz_projeto = Path(__file__).resolve().parent.parent
        caminho_config = self.raiz_projeto / config_path
        self.config = json.loads(caminho_config.read_text(encoding="utf-8")) if caminho_config.exists() else {}
        self.img_cfg = self.config.get("imagem", {})
        self.llm_client = llm_client
        self.dir_saida = dir_saida or self.raiz_projeto / "resultados" / "imagens"
        self.caminho_fonte, self.caminho_fonte_negrito = self._localizar_fontes()

    # --------------------------------------------------------------------------
    # 1. Geração da ilustração
    # --------------------------------------------------------------------------
    def gerar_ilustracao(self, prompt: str) -> Tuple[LLMResponse, Optional[Dict[str, Any]]]:
        """
        Tenta o modelo principal (Gemini) e, se a cota ou o modelo não estiverem disponíveis,
        o modelo aberto configurado. Retorna (resposta, substituição registrada ou None).
        """
        seed = self.img_cfg.get("seed")
        resposta = None
        if self.llm_client is not None and self.llm_client.disponivel:
            resposta = self.llm_client.gerar_imagem(
                prompt, self.img_cfg.get("modelo", "gemini-3.1-flash-image"),
                proporcao=self.img_cfg.get("proporcao", "16:9"), seed=seed
            )
            if resposta.sucesso or resposta.codigo_erro not in ERROS_QUE_ACIONAM_ALTERNATIVA:
                return resposta, None

        alternativa = self.img_cfg.get("alternativa_aberta")
        if not alternativa:
            return resposta or self._falha("google", "-", "SEM_PROVEDOR", "Nenhum provedor de imagem configurado."), None
        substituicao = {
            "modelo_original": self.img_cfg.get("modelo"),
            "motivo": f"{resposta.codigo_erro}: {resposta.erro}" if resposta else "Cliente Gemini indisponível.",
            "modelo_substituto": alternativa["modelo"],
            "licenca_substituto": alternativa.get("licenca"),
            "base": "O edital permite gerar a imagem por API ou modelo aberto (RF10)."
        }
        return self._gerar_huggingface(prompt, alternativa, seed), substituicao

    def _gerar_huggingface(self, prompt: str, cfg: Dict[str, Any], seed: Optional[int]) -> LLMResponse:
        """
        Geração com o modelo aberto no Space oficial do Hugging Face (gradio_client).
        O Space usa a cota gratuita de GPU (ZeroGPU) da conta do HF_TOKEN.
        """
        modelo = cfg["modelo"]
        token = os.getenv(cfg.get("variavel_token", "HF_TOKEN"), "").strip()
        parametros = {"space": cfg.get("space"), "largura": cfg.get("largura", 1024), "altura": cfg.get("altura", 576),
                      "passos_inferencia": cfg.get("passos_inferencia", 4), "seed": seed}
        if not token:
            return self._falha("huggingface", modelo, "CHAVE_AUSENTE",
                               "HF_TOKEN não configurado no .env: o modelo aberto de imagem não pode ser chamado.", parametros)
        try:
            from gradio_client import Client
        except ImportError:
            return self._falha("huggingface", modelo, "BIBLIOTECA_AUSENTE",
                               "A biblioteca gradio_client não está instalada (pip install -r requirements.txt).", parametros)
        inicio = time.perf_counter()
        try:
            cliente = Client(cfg["space"], token=token, verbose=False)
            resultado = cliente.predict(prompt, seed, False, parametros["largura"], parametros["altura"],
                                        parametros["passos_inferencia"], api_name=cfg.get("api_name", "/infer"))
            caminho = resultado[0] if isinstance(resultado, (list, tuple)) else resultado
            caminho = caminho.get("path") if isinstance(caminho, dict) else caminho
            dados = Path(caminho).read_bytes()
        except httpx.TimeoutException:
            return self._falha("huggingface", modelo, "TIMEOUT", "O Space de imagem não respondeu no tempo limite.", parametros, inicio)
        except httpx.TransportError:
            return self._falha("huggingface", modelo, "SEM_CONEXAO", "Não foi possível conectar ao Hugging Face.", parametros, inicio)
        except Exception as e:
            detalhe = str(e).lower()
            if "quota" in detalhe or "exceeded" in detalhe:
                codigo, mensagem = "LIMITE_REQUISICOES", "Cota gratuita de GPU do Hugging Face esgotada; tente mais tarde."
            elif "401" in detalhe or "unauthorized" in detalhe or "invalid" in detalhe and "token" in detalhe:
                codigo, mensagem = "AUTENTICACAO", "HF_TOKEN recusado pelo Hugging Face."
            else:
                codigo, mensagem = "INDISPONIVEL", f"Falha no Space de imagem ({type(e).__name__})."
            return self._falha("huggingface", modelo, codigo, mensagem, parametros, inicio)
        sufixo = Path(caminho).suffix.lower().lstrip(".") or "png"
        return LLMResponse(conteudo="", modelo=modelo, provedor="huggingface", sucesso=True,
                           latencia_ms=(time.perf_counter() - inicio) * 1000.0, tentativas=1,
                           parametros=parametros, dados_binarios=dados, mime_type=f"image/{sufixo}")

    @staticmethod
    def _falha(provedor: str, modelo: str, codigo: str, mensagem: str,
               parametros: Optional[Dict[str, Any]] = None, inicio: Optional[float] = None) -> LLMResponse:
        latencia = (time.perf_counter() - inicio) * 1000.0 if inicio else 0.0
        return LLMResponse(conteudo="", modelo=modelo, provedor=provedor, sucesso=False, latencia_ms=latencia,
                           codigo_erro=codigo, erro=mensagem, parametros=parametros or {})

    # --------------------------------------------------------------------------
    # 2. Edição: tipografia medida e verificação de glifos
    # --------------------------------------------------------------------------
    @staticmethod
    def _localizar_fontes() -> Tuple[Optional[str], Optional[str]]:
        for regular, negrito in FONTES_CANDIDATAS:
            if os.path.exists(regular):
                return regular, negrito if os.path.exists(negrito) else regular
        return None, None

    def _fonte(self, tamanho: int, negrito: bool = False) -> ImageFont.FreeTypeFont:
        caminho = self.caminho_fonte_negrito if negrito else self.caminho_fonte
        if caminho is None:
            return ImageFont.load_default(size=tamanho)
        return ImageFont.truetype(caminho, tamanho)

    @staticmethod
    def glifos_ausentes(fonte: ImageFont.FreeTypeFont, texto: str) -> List[str]:
        """Caracteres sem glifo na fonte (desenhados como o glifo 'não definido', o '□')."""
        def desenho(caractere: str) -> bytes:
            img = Image.new("L", (64, 64), 0)
            ImageDraw.Draw(img).text((8, 8), caractere, font=fonte, fill=255)
            return img.tobytes()
        referencia = desenho("\U000F0000")  # ponto de código de uso privado: sem glifo em fontes comuns
        return sorted({c for c in texto if not c.isspace() and desenho(c) == referencia})

    @staticmethod
    def _quebrar(draw: ImageDraw.ImageDraw, texto: str, fonte, largura_max: int) -> List[str]:
        """Quebra o texto em linhas que cabem em largura_max, medidas com draw.textbbox."""
        linhas = []
        for paragrafo in texto.split("\n"):
            atual = ""
            for palavra in paragrafo.split():
                tentativa = f"{atual} {palavra}".strip()
                if draw.textbbox((0, 0), tentativa, font=fonte)[2] <= largura_max or not atual:
                    atual = tentativa
                else:
                    linhas.append(atual)
                    atual = palavra
            linhas.append(atual)
        return linhas

    def escrever(self, draw: ImageDraw.ImageDraw, texto: str, caixa: Tuple[int, int, int, int],
                 tamanho: int, cor, negrito: bool = False, centralizar: bool = False,
                 tamanho_min: int = 14, entrelinha: float = 1.25) -> Dict[str, Any]:
        """
        Escreve `texto` dentro de `caixa` (x0, y0, x1, y1), reduzindo a fonte até caber.
        Retorna a medição: tamanho usado, caixa ocupada, se coube e glifos ausentes.
        """
        x0, y0, x1, y1 = caixa
        while True:
            fonte = self._fonte(tamanho, negrito)
            linhas = self._quebrar(draw, texto, fonte, x1 - x0)
            altura_linha = int(tamanho * entrelinha)
            larguras = [draw.textbbox((0, 0), l, font=fonte)[2] for l in linhas]
            cabe = len(linhas) * altura_linha <= (y1 - y0) and max(larguras, default=0) <= (x1 - x0)
            if cabe or tamanho <= tamanho_min:
                break
            tamanho -= 1

        ocupada = [x1, y0, x0, y0]
        for i, (linha, largura) in enumerate(zip(linhas, larguras)):
            x = x0 + ((x1 - x0) - largura) // 2 if centralizar else x0
            y = y0 + i * altura_linha
            draw.text((x, y), linha, font=fonte, fill=cor)
            bbox = draw.textbbox((x, y), linha, font=fonte)
            ocupada = [min(ocupada[0], bbox[0]), y0, max(ocupada[2], bbox[2]), max(ocupada[3], bbox[3])]
        dentro = ocupada[0] >= x0 and ocupada[2] <= x1 and ocupada[3] <= y1
        return {"texto": texto, "tamanho_fonte": tamanho, "caixa": list(caixa), "ocupado": ocupada,
                "dentro_da_area": dentro, "glifos_ausentes": self.glifos_ausentes(fonte, texto)}

    @staticmethod
    def _cobrir(imagem: Image.Image, largura: int, altura: int, raio: int = 18) -> Image.Image:
        """Recorte centralizado para preencher a área, com cantos arredondados."""
        recorte = ImageOps.fit(imagem.convert("RGB"), (largura, altura), Image.Resampling.LANCZOS)
        mascara = Image.new("L", (largura, altura), 0)
        ImageDraw.Draw(mascara).rounded_rectangle([(0, 0), (largura - 1, altura - 1)], radius=raio, fill=255)
        recorte.putalpha(mascara)
        return recorte

    @staticmethod
    def _campos_do_curso(registro: Optional[Dict[str, Any]]) -> List[Tuple[str, str]]:
        """(rótulo, valor) do curso a partir dos dados confirmados pelo servidor; campos ausentes ficam de fora."""
        curso = (registro or {}).get("curso", {})
        campos = [("Curso", curso.get("nome")), ("Eixo tecnológico", curso.get("eixo_tecnologico")),
                  ("Carga horária", curso.get("carga_horaria")), ("Turno", curso.get("turno")),
                  ("Início das aulas", curso.get("data_inicio"))]
        return [(rotulo, str(valor)) for rotulo, valor in campos if valor and not eh_ausente(valor)]

    def compor_cartaz(self, ilustracao: Image.Image, registro: Optional[Dict[str, Any]],
                      nota_proveniencia: str) -> Tuple[Image.Image, List[Dict[str, Any]], List[str], List[Dict[str, str]]]:
        """
        Compõe o cartaz. Retorna (imagem, medições dos textos, operações de edição, textos inseridos com a fonte).
        Todo texto vem dos dados confirmados pelo servidor, do texto impresso na ficha ou é orientação genérica da equipe.
        """
        cartaz = Image.new("RGB", (LARGURA, ALTURA), FUNDO)
        draw = ImageDraw.Draw(cartaz)
        medicoes, operacoes, textos = [], [], []
        branco, borda = (255, 255, 255), (210, 220, 235)

        def texto(conteudo: str, caixa, tamanho: int, cor, fonte: str, **opcoes):
            medicoes.append(self.escrever(draw, conteudo, caixa, tamanho, cor, **opcoes))
            textos.append({"texto": conteudo, "fonte_do_conteudo": fonte})

        # Cabeçalho com brasão
        draw.rectangle([(0, 0), (LARGURA, 200)], fill=AZUL)
        draw.rectangle([(0, 200), (LARGURA, 208)], fill=DOURADO)
        caminho_brasao = self.raiz_projeto / self.config.get("arquivos_originais", {}).get("brasao", "dados/originais/brasao.png")
        x_texto = MARGEM
        if caminho_brasao.exists():
            brasao = Image.open(caminho_brasao).convert("RGBA")
            brasao.thumbnail((140, 140), Image.Resampling.LANCZOS)
            cartaz.paste(brasao, (MARGEM, (200 - brasao.height) // 2), brasao)
            x_texto = MARGEM + brasao.width + 30
            operacoes.append(f"Brasão inserido a partir de {caminho_brasao.relative_to(self.raiz_projeto).as_posix()} (sem alteração)")
        institucional = "Modelo institucional definido pela equipe"
        texto("GOVERNO DO ESTADO DE MATO GROSSO", (x_texto, 38, LARGURA - MARGEM, 76), 30, "white", institucional, negrito=True)
        texto("Secretaria de Estado de Ciência, Tecnologia e Inovação - SECITECI/MT", (x_texto, 82, LARGURA - MARGEM, 140), 22,
              "white", institucional)
        texto("Escola Técnica Estadual de Cuiabá", (x_texto, 140, LARGURA - MARGEM, 176), 26, DOURADO, institucional, negrito=True)

        # Título
        texto("Matrícula no curso técnico: atenção à frequência", (MARGEM, 222, LARGURA - MARGEM, 300), 42, AZUL,
              institucional, negrito=True, centralizar=True)
        y = 312

        # Ficha do curso em duas colunas (dados confirmados pelo servidor)
        campos = self._campos_do_curso(registro)
        fonte_registro = "Dados confirmados pelo servidor na conferência humana (registro_confirmado)"
        if campos:
            linhas = (len(campos) + 1) // 2
            draw.rounded_rectangle([(MARGEM, y), (LARGURA - MARGEM, y + 28 + 40 * linhas)], radius=14, fill=branco, outline=borda, width=2)
            largura_coluna = (LARGURA - 2 * MARGEM - 48) // 2
            for i, (rotulo, valor) in enumerate(campos):
                x0 = MARGEM + 24 + (i % 2) * largura_coluna
                y0 = y + 14 + (i // 2) * 40
                texto(f"{rotulo}: {valor}", (x0, y0, x0 + largura_coluna - 12, y0 + 36), 25, TEXTO, fonte_registro, negrito=(i == 0))
            y += 28 + 40 * linhas + 14

        # Faixa de atenção às datas
        inicio = dict(campos).get("Início das aulas")
        draw.rounded_rectangle([(MARGEM, y), (LARGURA - MARGEM, y + 64)], radius=12, fill=DOURADO)
        texto("Atenção aos 10 primeiros dias de aula" + (f" (início em {inicio})" if inicio else ""),
              (MARGEM + 20, y + 12, LARGURA - MARGEM - 20, y + 54), 28, AZUL,
              FONTE_REGRA_FALTAS + (" e data de início confirmada pelo servidor" if inicio else ""), negrito=True, centralizar=True)
        y += 80

        # Regra de faltas: as duas condições do texto impresso na ficha, com os números em destaque
        draw.rounded_rectangle([(MARGEM, y), (LARGURA - MARGEM, y + 300)], radius=14, fill=(255, 241, 242), outline=VERMELHO, width=3)
        texto("Cancelamento automático da matrícula", (MARGEM + 24, y + 14, LARGURA - MARGEM - 24, y + 52), 28, VERMELHO,
              FONTE_REGRA_FALTAS, negrito=True)
        texto(REGRA_FALTAS_FICHA[0], (MARGEM + 24, y + 54, LARGURA - MARGEM - 24, y + 120), 23, (120, 20, 20), FONTE_REGRA_FALTAS)
        largura_bloco = (LARGURA - 2 * MARGEM - 48 - 60) // 2
        condicoes = [("2", "primeiros dias de aula consecutivos"),
                     ("3", "dias de aula, consecutivos ou não, no período dos 10 primeiros dias de aula")]
        for i, (numero, descricao) in enumerate(condicoes):
            x0 = MARGEM + 24 + i * (largura_bloco + 60)
            draw.rounded_rectangle([(x0, y + 126), (x0 + largura_bloco, y + 288)], radius=12, fill=branco, outline=(240, 200, 200), width=2)
            texto(numero, (x0, y + 128, x0 + largura_bloco, y + 202), 64, VERMELHO, FONTE_REGRA_FALTAS, negrito=True, centralizar=True)
            texto(descricao, (x0 + 14, y + 204, x0 + largura_bloco - 14, y + 284), 22, (120, 20, 20), FONTE_REGRA_FALTAS, centralizar=True)
        x_ou = MARGEM + 24 + largura_bloco
        texto("ou", (x_ou, y + 180, x_ou + 60, y + 220), 24, VERMELHO, FONTE_REGRA_FALTAS + " (as duas condições são alternativas)",
              negrito=True, centralizar=True)
        y += 316

        # Falta com justificativa
        orientacao = "Orientação da equipe, derivada da regra (\"sem justificativa comprovada\"); sem prazos ou documentos inventados"
        draw.rounded_rectangle([(MARGEM, y), (LARGURA - MARGEM, y + 110)], radius=14, fill=branco, outline=borda, width=2)
        texto("Falta com justificativa", (MARGEM + 24, y + 10, LARGURA - MARGEM - 24, y + 50), 26, AZUL, orientacao, negrito=True)
        texto("A regra vale para faltas sem justificativa comprovada. Para justificar uma falta, procure a Secretaria Escolar.",
              (MARGEM + 24, y + 50, LARGURA - MARGEM - 24, y + 104), 23, TEXTO, orientacao)
        y += 124

        # Orientação sobre documentos (a lista não consta nos dados)
        texto("Dúvidas sobre documentos e prazos: procure a Secretaria Escolar.", (MARGEM, y, LARGURA - MARGEM, y + 40), 26, AZUL,
              "Orientação da equipe; a lista de documentos não consta nos dados recebidos", negrito=True, centralizar=True)
        y += 52

        # Ilustração gerada por IA numa faixa estreita
        area = (MARGEM, y, LARGURA - MARGEM, ALTURA - 107)
        recorte = self._cobrir(ilustracao, area[2] - area[0], area[3] - area[1])
        cartaz.paste(recorte, (area[0], area[1]), recorte)
        operacoes.append(f"Ilustração redimensionada e recortada ({ilustracao.width}x{ilustracao.height} -> "
                         f"{area[2] - area[0]}x{area[3] - area[1]}) numa faixa no rodapé, cantos arredondados")

        # Tarja de proveniência
        draw.rectangle([(0, ALTURA - 95), (LARGURA, ALTURA)], fill=(15, 23, 42))
        medicoes.append(self.escrever(draw, nota_proveniencia, (MARGEM, ALTURA - 85, LARGURA - MARGEM, ALTURA - 10), 19, DOURADO, centralizar=True))
        operacoes.append("Textos, blocos e tarja de proveniência desenhados com Pillow (textos medidos com draw.textbbox)")
        return cartaz, medicoes, operacoes, textos

    # --------------------------------------------------------------------------
    # 3. Orquestração e metadados
    # --------------------------------------------------------------------------
    def gerar_cartaz_orientacao(self, registro: Optional[Dict[str, Any]] = None, protocolo: str = NAO_LOCALIZADO) -> Dict[str, Any]:
        """
        Gera a ilustração por IA, compõe o cartaz e grava os metadados de proveniência (RF10).
        `registro`: dados confirmados pelo servidor (fonte dos textos do curso).
        """
        self.dir_saida.mkdir(parents=True, exist_ok=True)
        # Nome versionado: cada geração preserva as anteriores
        nome = nome_versionado(self.dir_saida, "cartaz_orientacao_matricula", [".png", "_metadados.json"])
        caminho_saida = self.dir_saida / f"{nome}.png"
        caminho_metadados = self.dir_saida / f"{nome}_metadados.json"

        prompt = montar_prompt_ilustracao(PROMPT_ILUSTRACAO_CARTAZ_ESTRUTURADO)
        resposta, substituicao = self.gerar_ilustracao(prompt)
        resultado: Dict[str, Any] = {"sucesso": False, "resposta": resposta, "prompt": prompt, "substituicao": substituicao}
        if not resposta.sucesso:
            resultado["erro"] = resposta.erro
            return resultado

        try:
            ilustracao = Image.open(io.BytesIO(resposta.dados_binarios))
            ilustracao.load()
        except Exception as e:
            resposta.marcar_falha("IMAGEM_INVALIDA", f"O provedor retornou dados que não são uma imagem válida ({type(e).__name__}).")
            resultado["erro"] = resposta.erro
            return resultado
        # A ilustração é salva com os bytes exatamente como recebidos: o hash dos metadados confere com o arquivo
        extensao = {"JPEG": ".jpg", "PNG": ".png", "WEBP": ".webp"}.get(ilustracao.format or "", ".img")
        caminho_ilustracao = self.dir_saida / f"{nome}_ilustracao_ia{extensao}"
        caminho_ilustracao.write_bytes(resposta.dados_binarios)

        data_geracao = datetime.now()
        nota = (f"Ilustração gerada por IA ({resposta.modelo}, {data_geracao.strftime('%d/%m/%Y')}) e editada pela equipe. "
                f"Textos inseridos e conferidos por pessoas. Material fictício, para fins didáticos.")
        cartaz, medicoes, operacoes, textos = self.compor_cartaz(ilustracao, registro, nota)
        cartaz.save(caminho_saida, format="PNG")

        fora_da_area = [m["texto"][:60] for m in medicoes if not m["dentro_da_area"]]
        glifos = sorted({g for m in medicoes for g in m["glifos_ausentes"]})
        metadados = {
            "arquivo_gerado": caminho_saida.name,
            "sha256_cartaz": _sha256(caminho_saida.read_bytes()),
            "data_geracao": data_geracao.isoformat(timespec="seconds"),
            "caso_relacionado": {"protocolo": protocolo},
            "ilustracao": {
                "arquivo_original": caminho_ilustracao.name,
                "sha256_original": _sha256(caminho_ilustracao.read_bytes()),
                "dimensoes_recebidas": f"{ilustracao.width}x{ilustracao.height}",
                "provedor": resposta.provedor,
                "modelo": resposta.modelo,
                "versao_modelo": resposta.parametros.get("versao_modelo"),
                "seed": self.img_cfg.get("seed"),
                "observacao_seed": "Enviado ao provedor; nem todos os modelos garantem reprodutibilidade com a mesma seed.",
                "parametros": {k: v for k, v in resposta.parametros.items() if k != "versao_modelo"},
                "prompt_estruturado": PROMPT_ILUSTRACAO_CARTAZ_ESTRUTURADO,
                "prompt_enviado": prompt,
                "substituicao_de_modelo": substituicao,
            },
            "edicao": {
                "ferramenta": f"Pillow {PIL.__version__}",
                "fonte_tipografica": Path(self.caminho_fonte).name if self.caminho_fonte else "fonte padrão do Pillow",
                "operacoes": operacoes,
            },
            "textos_inseridos": textos,
            "nota_de_proveniencia": nota,
            "verificacoes_automaticas": {
                "textos_dentro_das_areas": not fora_da_area,
                "textos_fora_da_area": fora_da_area,
                "glifos_ausentes_na_fonte": glifos,
                "nota_de_proveniencia_visivel": any(m["texto"] == nota and m["dentro_da_area"] for m in medicoes),
                "medicoes": medicoes,
            },
            "checklist_revisao_humana": {
                "ilustracao_sem_texto_letras_ou_logotipos": None,
                "objetos_e_formas_coerentes": None,
                "sem_pessoa_real_ou_rosto_identificavel": None,
                "brasao_e_cores_institucionais_corretos": None,
                "textos_conferidos_com_as_fontes": None,
            },
            "status_revisao": "PENDENTE",
        }
        caminho_metadados.write_text(json.dumps(metadados, indent=2, ensure_ascii=False), encoding="utf-8")

        resultado.update({
            "sucesso": True,
            "caminho_imagem": str(caminho_saida),
            "caminho_ilustracao": str(caminho_ilustracao),
            "caminho_metadados": str(caminho_metadados),
            "dimensoes": f"{LARGURA}x{ALTURA}",
            "metadados": metadados,
        })
        return resultado
