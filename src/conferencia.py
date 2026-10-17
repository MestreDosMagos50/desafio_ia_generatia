#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
==============================================================================
CONFERÊNCIA DE DADOS: GABARITOS, TRANSCRIÇÃO E CONSISTÊNCIA ENTRE CANAIS
Atende aos requisitos RF03, RF05, RF06, RF08 e RF13.
==============================================================================
- Comparação campo a campo entre resultado obtido e gabarito, distinguindo
  valores inventados (gabarito "não localizado") de valores omitidos;
- Taxa de erro de palavras (WER) e erros relevantes da transcrição;
- Conferência cruzada dos campos críticos entre texto, áudio e ficha;
- Verificação de ancoragem: valores extraídos precisam constar na fonte;
- Detecção heurística de instruções dirigidas à IA (prompt injection).
Funções determinísticas, sem chamadas a modelos.
==============================================================================
"""

import re
import json
import difflib
import unicodedata
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

NAO_LOCALIZADO = "não localizado"

# Campos comparados apenas pelos dígitos (pontuação de CPF, RG, protocolo etc. é ignorada)
CAMPOS_NUMERICOS = {"cpf", "rg", "protocolo", "codigo_matricula", "telefone_celular", "telefone_residencial"}

# Tradução de caminhos do gabarito para o registro de solicitação (texto e áudio)
MAPA_GABARITO_SOLICITACAO = {
    "canal": "canal_origem",
    "regras_assiduidade_declaradas.ciente_cancelamento_faltas": "declarou_ciencia_faltas",
    "classificacao.categoria": "categoria_tema",
    "classificacao.urgencia": "urgencia",
    "campos_ausentes_obrigatorios": "campos_ausentes",
}
IGNORAR_GABARITO_SOLICITACAO = [
    "classificacao.assunto",  # texto livre: avaliado na revisão humana
    "regras_assiduidade_declaradas.faltas_consecutivas_inicio_permitidas",
    "regras_assiduidade_declaradas.faltas_descontinuas_primeiros_10_dias",
    "pontos_criticos_para_conferencia_humana",
]
IGNORAR_GABARITO_FICHA = ["instituicao", "classificacao"]

# Campos críticos conferidos entre canais antes da minuta (critério de aceite do RF06)
CAMPOS_CRITICOS: Dict[str, Dict[str, str]] = {
    "protocolo": {"texto": "protocolo", "audio": "protocolo", "ficha": "codigo_matricula"},
    "data_solicitacao": {"texto": "data_solicitacao", "audio": "data_solicitacao", "ficha": "data_matricula"},
    "nome_completo": {"texto": "solicitante.nome_completo", "audio": "solicitante.nome_completo", "ficha": "solicitante.nome_completo"},
    "data_nascimento": {"texto": "solicitante.data_nascimento", "audio": "solicitante.data_nascimento", "ficha": "solicitante.data_nascimento"},
    "cpf": {"texto": "solicitante.cpf", "audio": "solicitante.cpf", "ficha": "solicitante.cpf"},
    "rg": {"texto": "solicitante.rg", "audio": "solicitante.rg", "ficha": "solicitante.rg"},
    "email": {"texto": "solicitante.email", "audio": "solicitante.email", "ficha": "solicitante.email"},
    "nome_mae": {"texto": "solicitante.nome_mae", "audio": "solicitante.nome_mae", "ficha": "solicitante.nome_mae"},
    "curso": {"texto": "curso.nome", "audio": "curso.nome", "ficha": "curso.nome"},
    "turno": {"texto": "curso.turno", "audio": "curso.turno", "ficha": "curso.turno"},
    "data_inicio": {"texto": "curso.data_inicio", "audio": "curso.data_inicio", "ficha": "curso.inicio_curso"},
}
PRIORIDADE_FONTES = ("texto", "ficha", "audio")

# Valores que precisam aparecer literalmente na fonte (datas ficam de fora: são normalizadas)
CAMPOS_ANCORAVEIS = (
    "protocolo",
    "solicitante.nome_completo",
    "solicitante.cpf",
    "solicitante.rg",
    "solicitante.email",
    "solicitante.nome_mae",
    "solicitante.nome_pai",
    "solicitante.telefone_celular",
    "solicitante.telefone_residencial",
)

# Padrões (sobre texto normalizado, sem acentos) de instruções dirigidas à IA
PADROES_INJECTION = (
    r"ignor\w*\s+(todas\s+)?(as\s+)?(suas\s+)?(instruc|regras|orientac|ordens)",
    r"instruc\w*\s+anteriores",
    r"voce\s+agora\s+e",
    r"sistema\s+de\s+ia",
    r"\baja\s+como\b",
    r"desconsider\w*\s+(as\s+|todas\s+)?(regras|instruc)",
    r"\bprompt\b",
    r"modo\s+(administrador|desenvolvedor)",
)


# Números falados comuns, para comparar transcrições que usam algarismos ou extenso
NUMEROS_POR_EXTENSO = {
    "zero": "0", "um": "1", "uma": "1", "dois": "2", "duas": "2", "tres": "3", "quatro": "4",
    "cinco": "5", "seis": "6", "sete": "7", "oito": "8", "nove": "9", "dez": "10", "onze": "11",
    "doze": "12", "treze": "13", "catorze": "14", "quatorze": "14", "quinze": "15", "dezesseis": "16",
    "dezessete": "17", "dezoito": "18", "dezenove": "19", "vinte": "20",
}


def normalizar(valor: Any) -> str:
    """Normaliza para comparação: minúsculas, sem acentos, sem separador de milhar e com espaços simples."""
    if isinstance(valor, bool):
        return "sim" if valor else "nao"
    texto = unicodedata.normalize("NFKD", str(valor)).encode("ascii", "ignore").decode("ascii")
    texto = re.sub(r"(?<=\d)\.(?=\d{3}\b)", "", texto)  # 1.200 -> 1200
    return re.sub(r"\s+", " ", texto).strip().casefold()


def _canonico(token: str) -> str:
    """Forma canônica de uma palavra da transcrição: número por extenso vira algarismo e
    tokens numéricos perdem a pontuação (123.456.789-00 == 123456789-00)."""
    texto = normalizar(token)
    if texto in NUMEROS_POR_EXTENSO:
        return NUMEROS_POR_EXTENSO[texto]
    if re.fullmatch(r"[\d.\-/]+", texto):
        return re.sub(r"\D", "", texto)
    return texto


def apenas_digitos(valor: Any) -> str:
    return re.sub(r"\D", "", str(valor))


def eh_ausente(valor: Any) -> bool:
    if isinstance(valor, bool):
        return False
    return valor is None or normalizar(valor) in ("", normalizar(NAO_LOCALIZADO))


def obter(dados: Dict[str, Any], caminho: str, padrao: Any = None) -> Any:
    """Lê um valor aninhado pelo caminho 'a.b.c'."""
    atual: Any = dados
    for parte in caminho.split("."):
        if not isinstance(atual, dict) or parte not in atual:
            return padrao
        atual = atual[parte]
    return atual


def definir(dados: Dict[str, Any], caminho: str, valor: Any) -> None:
    """Grava um valor aninhado pelo caminho 'a.b.c', criando níveis intermediários."""
    partes = caminho.split(".")
    atual = dados
    for parte in partes[:-1]:
        atual = atual.setdefault(parte, {})
    atual[partes[-1]] = valor


def achatar(dados: Dict[str, Any], prefixo: str = "") -> Dict[str, Any]:
    """Converte um dicionário aninhado em {caminho: valor}; listas são mantidas como valor."""
    plano = {}
    for chave, valor in dados.items():
        caminho = f"{prefixo}.{chave}" if prefixo else chave
        if isinstance(valor, dict):
            plano.update(achatar(valor, caminho))
        else:
            plano[caminho] = valor
    return plano


def carregar_gabarito(raiz_projeto: Path, config: dict, arquivo_entrada: str) -> Optional[dict]:
    """Localiza o gabarito da entrada pelo mapa 'gabaritos' do config.json."""
    caminho_rel = config.get("gabaritos", {}).get(Path(arquivo_entrada).as_posix())
    if not caminho_rel:
        return None
    caminho = raiz_projeto / caminho_rel
    if not caminho.exists():
        return None
    with open(caminho, "r", encoding="utf-8") as f:
        return json.load(f)


def comparar_valor(esperado: Any, obtido: Any, numerico: bool = False) -> str:
    """Classifica o resultado de um campo em relação ao gabarito."""
    if isinstance(esperado, list) or isinstance(obtido, list):
        conj_esperado = {normalizar(v) for v in (esperado or [])}
        conj_obtido = {normalizar(v) for v in (obtido or [])} if isinstance(obtido, list) else set()
        return "CORRETO" if conj_esperado == conj_obtido else "DIVERGENTE"
    if eh_ausente(esperado) and eh_ausente(obtido):
        return "CORRETO"
    if eh_ausente(esperado):
        return "INVENTADO"
    if eh_ausente(obtido):
        return "OMITIDO"
    if str(esperado).strip() == str(obtido).strip():
        return "CORRETO"
    if normalizar(esperado) == normalizar(obtido):
        return "EQUIVALENTE"
    if numerico and apenas_digitos(esperado) and apenas_digitos(esperado) == apenas_digitos(obtido):
        return "EQUIVALENTE"
    return "DIVERGENTE"


def comparar_com_gabarito(
    obtido: Dict[str, Any],
    esperado: Dict[str, Any],
    mapa: Optional[Dict[str, str]] = None,
    ignorar: Iterable[str] = ()
) -> Dict[str, Any]:
    """
    Compara campo a campo o resultado obtido com o gabarito (RF05, RF08, RF13).
    `mapa` traduz caminhos do gabarito para o resultado; caminhos em `ignorar` não são avaliados.
    CORRETO e EQUIVALENTE (diferença só de maiúsculas, acentos ou pontuação numérica) contam como acerto.
    """
    mapa = mapa or {}
    ignorar = list(ignorar)
    itens = []
    for caminho, valor_esperado in achatar(esperado).items():
        if any(caminho == ig or caminho.startswith(ig + ".") for ig in ignorar):
            continue
        valor_obtido = obter(obtido, mapa.get(caminho, caminho), NAO_LOCALIZADO)
        campo = caminho.split(".")[-1]
        itens.append({
            "campo": caminho,
            "esperado": valor_esperado,
            "obtido": valor_obtido,
            "status": comparar_valor(valor_esperado, valor_obtido, numerico=campo in CAMPOS_NUMERICOS)
        })

    acertos = sum(1 for item in itens if item["status"] in ("CORRETO", "EQUIVALENTE"))
    return {
        "total_campos": len(itens),
        "acertos": acertos,
        "taxa_acerto_pct": round(100.0 * acertos / len(itens), 2) if itens else 0.0,
        "inventados": [i["campo"] for i in itens if i["status"] == "INVENTADO"],
        "omitidos": [i["campo"] for i in itens if i["status"] == "OMITIDO"],
        "divergentes": [i["campo"] for i in itens if i["status"] == "DIVERGENTE"],
        "itens": itens
    }


def _tokenizar(texto: str) -> List[str]:
    tokens = (t.strip(".,;:!?-/") for t in re.findall(r"[\w@.\-/]+", texto))
    return [t for t in tokens if t]


def taxa_erro_palavras(referencia: str, hipotese: str) -> float:
    """Word Error Rate (%) entre referência e transcrição, sem pontuação, acentos ou diferença de grafia numérica."""
    ref = [_canonico(t) for t in _tokenizar(referencia)]
    hip = [_canonico(t) for t in _tokenizar(hipotese)]
    anterior = list(range(len(hip) + 1))
    for i, palavra_ref in enumerate(ref, 1):
        atual = [i] + [0] * len(hip)
        for j, palavra_hip in enumerate(hip, 1):
            atual[j] = min(anterior[j] + 1, atual[j - 1] + 1, anterior[j - 1] + (palavra_ref != palavra_hip))
        anterior = atual
    return round(100.0 * anterior[-1] / max(len(ref), 1), 2)


def diferencas_transcricao(referencia: str, hipotese: str, termos_criticos: Iterable[str] = ()) -> List[Dict[str, Any]]:
    """
    Lista as diferenças palavra a palavra entre referência e transcrição (RF06).
    Uma diferença é crítica quando envolve números, e-mail ou nomes dos termos críticos.
    """
    ref_original, hip_original = _tokenizar(referencia), _tokenizar(hipotese)
    ref = [_canonico(t) for t in ref_original]
    hip = [_canonico(t) for t in hip_original]
    # Partículas como "de" e "da" não tornam uma diferença crítica
    criticos = {_canonico(t) for termo in termos_criticos for t in _tokenizar(str(termo)) if len(t) > 3}
    tipos = {"replace": "SUBSTITUICAO", "delete": "OMISSAO", "insert": "INSERCAO"}

    diferencas = []
    for operacao, i1, i2, j1, j2 in difflib.SequenceMatcher(None, ref, hip, autojunk=False).get_opcodes():
        if operacao == "equal":
            continue
        trecho_ref = " ".join(ref_original[i1:i2])
        trecho_hip = " ".join(hip_original[j1:j2])
        envolvidos = set(ref[i1:i2]) | set(hip[j1:j2])
        diferencas.append({
            "tipo": tipos[operacao],
            "referencia": trecho_ref,
            "transcricao": trecho_hip,
            "critico": bool(re.search(r"\d|@", f"{trecho_ref} {trecho_hip}")) or bool(envolvidos & criticos)
        })
    return diferencas


def conferencia_cruzada(fontes: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Compara os campos críticos entre os canais disponíveis ('texto', 'audio', 'ficha').
    O valor sugerido é o da maioria; empates seguem a prioridade texto > ficha > áudio.
    """
    resultado = []
    for campo, caminhos in CAMPOS_CRITICOS.items():
        valores = {
            fonte: obter(fontes[fonte], caminhos[fonte], NAO_LOCALIZADO)
            for fonte in PRIORIDADE_FONTES if fonte in fontes
        }
        presentes = {fonte: valor for fonte, valor in valores.items() if not eh_ausente(valor)}
        chave = apenas_digitos if campo in CAMPOS_NUMERICOS else normalizar

        grupos: Dict[str, List[str]] = {}
        for fonte, valor in presentes.items():
            grupos.setdefault(chave(valor), []).append(fonte)

        if not presentes:
            status, sugerido = "AUSENTE", NAO_LOCALIZADO
        else:
            if len(grupos) > 1:
                status = "DIVERGENTE"
            else:
                status = "CONSISTENTE" if len(presentes) > 1 else "FONTE_UNICA"
            maioria = max(grupos.values(), key=lambda fs: (len(fs), -min(PRIORIDADE_FONTES.index(f) for f in fs)))
            sugerido = presentes[min(maioria, key=PRIORIDADE_FONTES.index)]

        resultado.append({"campo": campo, "valores": valores, "status": status, "valor_sugerido": sugerido})
    return resultado


# Campos de texto livre que repetem valores estruturados (enviados ao modelo na minuta)
CAMPOS_TEXTO_LIVRE = ("assunto", "pedido_detalhado")


def aplicar_valores_confirmados(registro: Dict[str, Any], confirmados: Dict[str, Any]) -> Dict[str, Any]:
    """
    Grava no registro de solicitação os valores críticos confirmados pelo operador.
    Quando um valor é corrigido, as menções ao valor antigo no assunto e no pedido são substituídas pelo novo,
    marcado como "[... corrigido pelo revisor]", para que o modelo não receba dados contraditórios. O texto
    original continua em 'texto_original' (não enviado ao modelo) e as correções ficam em 'correcoes_revisor'.
    """
    correcoes = list(registro.get("correcoes_revisor") or [])
    for campo, valor in confirmados.items():
        if campo not in CAMPOS_CRITICOS:
            continue
        caminho = CAMPOS_CRITICOS[campo]["texto"]
        antigo = obter(registro, caminho)
        definir(registro, caminho, valor)
        if eh_ausente(antigo) or normalizar(antigo) == normalizar(valor):
            continue
        correcoes.append(f"{campo}: '{antigo}' -> '{valor}'")
        if len(str(antigo).strip()) < 3:
            continue
        padrao = re.compile(re.escape(str(antigo).strip()), re.IGNORECASE)
        for livre in CAMPOS_TEXTO_LIVRE:
            texto = registro.get(livre)
            if isinstance(texto, str) and padrao.search(texto):
                registro[livre] = padrao.sub(f"[{valor} — corrigido pelo revisor]", texto)
    registro["correcoes_revisor"] = correcoes
    return registro


def verificar_ancoragem(registro: Dict[str, Any], texto_fonte: str) -> List[str]:
    """Aponta valores extraídos que não aparecem literalmente na fonte (possível invenção)."""
    fonte_normalizada = normalizar(texto_fonte)
    fonte_digitos = apenas_digitos(texto_fonte)
    alertas = []
    for caminho in CAMPOS_ANCORAVEIS:
        valor = obter(registro, caminho)
        if eh_ausente(valor):
            continue
        if caminho.split(".")[-1] in CAMPOS_NUMERICOS:
            encontrado = bool(apenas_digitos(valor)) and apenas_digitos(valor) in fonte_digitos
        else:
            encontrado = normalizar(valor) in fonte_normalizada
        if not encontrado:
            alertas.append(f"O valor extraído para '{caminho}' não aparece literalmente na fonte: conferir.")

    texto_ciencia = registro.get("texto_ciencia_faltas")
    if not eh_ausente(texto_ciencia) and normalizar(texto_ciencia) not in fonte_normalizada:
        alertas.append("A declaração de ciência de faltas extraída não aparece literalmente na fonte: conferir.")
    return alertas


def detectar_injection(texto: str) -> List[str]:
    """Retorna trechos do texto que se parecem com instruções dirigidas à IA (RF03)."""
    normalizado = normalizar(texto)
    trechos = []
    for padrao in PADROES_INJECTION:
        for achado in re.finditer(padrao, normalizado):
            inicio, fim = max(0, achado.start() - 40), min(len(normalizado), achado.end() + 60)
            trechos.append(normalizado[inicio:fim].strip())
    return list(dict.fromkeys(trechos))
