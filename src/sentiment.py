#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
==============================================================================
CLASSIFICAÇÃO DE SENTIMENTOS DAS AVALIAÇÕES DE ATENDIMENTO (RF22) — Aula 14
==============================================================================
Quatro etapas e dois executores (Aula 14 §3.1):
1. Classificar (modelo): UMA avaliação por chamada, texto delimitado como dado
   não confiável, Structured Outputs com Literal em todo campo categórico.
   Só o texto e o canal vão ao provedor (RF24); ID, atendimento e data são
   dados estruturados e não são pedidos ao modelo.
2. Conferir (código): mista, irônica ou sem contexto fica "indeterminada" e
   limítrofe; todo limítrofe vai à revisão; trecho determinante conferido por
   busca literal no texto e limitado a 15 palavras; justificativa que fala do
   autor, e não do texto, vai à revisão.
3. Persistir (código): CSV e JSON versionados, com as colunas modelo e
   classificado_em; versões anteriores não são sobrescritas.
4. Agregar (código): src/metrics.py, sem chamada de API.
O esquema não pede confiança numérica. A ambiguidade autodeclarada é
estimativa não calibrada: orienta a fila de revisão e não mede acerto.
==============================================================================
"""

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from src.audit import nome_versionado
from src.conferencia import normalizar
from src.llm_client import LLMClient
from src import metrics
from src.prompts import PROMPT_SENTIMENTO_SISTEMA, PROMPT_SENTIMENTO_USUARIO, VERSOES_PROMPTS, delimitar_dados_externos
from src.schemas import VERSAO_ESQUEMA_SENTIMENTO, ClassificacaoSentimento

RAIZ_PROJETO = Path(__file__).resolve().parent.parent
DIR_ROTULOS = RAIZ_PROJETO / "resultados" / "sentimentos"
LIMITE_PALAVRAS_TRECHO = 15
# Termos que indicam julgamento do autor, e não do texto (R9); a lista é indicativa e só manda o caso à revisão
TERMOS_SOBRE_O_AUTOR = ("personalidade", "perfil", "diagnost", "transtorno", "ansios", "deprimid", "agressiv",
                        "impacien", "frustrad", "irritad", "nervos", "emocional", "temperamento")
CAMPOS_ROTULO = ("polaridade", "intensidade", "ambiguidade", "tema", "trecho_determinante", "justificativa_curta",
                 "necessita_revisao")


def aplicar_regras(saida: ClassificacaoSentimento, texto: str) -> Tuple[Dict[str, Any], List[str], List[str]]:
    """Regras R2–R9 conferidas em código. Devolve os rótulos finais, os ajustes feitos e os alertas."""
    rotulo = saida.model_dump()
    ajustes, alertas = [], []
    if rotulo["polaridade"] == "indeterminada" and rotulo["ambiguidade"] != "limitrofe":
        rotulo["ambiguidade"] = "limitrofe"
        ajustes.append("R7: polaridade indeterminada passou a ambiguidade limitrofe")
    if (rotulo["polaridade"] == "indeterminada" or rotulo["ambiguidade"] == "limitrofe") and not rotulo["necessita_revisao"]:
        rotulo["necessita_revisao"] = True
        ajustes.append("R7: caso indeterminado ou limítrofe marcado para revisão")
    trecho = rotulo["trecho_determinante"].strip().strip('"“”')
    if not trecho or normalizar(trecho) not in normalizar(texto):
        alertas.append("TRECHO_NAO_LITERAL: o trecho determinante não aparece no texto da avaliação")
    if len(trecho.split()) > LIMITE_PALAVRAS_TRECHO:
        alertas.append(f"TRECHO_ACIMA_DE_{LIMITE_PALAVRAS_TRECHO}_PALAVRAS: {len(trecho.split())} palavras")
    justificativa = normalizar(rotulo["justificativa_curta"])
    termos = [t for t in TERMOS_SOBRE_O_AUTOR if re.search(rf"\b{t}", justificativa)]
    if termos:
        alertas.append(f"INFERENCIA_SOBRE_O_AUTOR: a justificativa usa {', '.join(termos)}; descreva o texto, não o autor")
    if alertas and not rotulo["necessita_revisao"]:
        rotulo["necessita_revisao"] = True
        ajustes.append("alerta de conferência marcou o caso para revisão")
    return rotulo, ajustes, alertas


class ClassificadorSentimentos:
    """Classifica uma avaliação por chamada e devolve o registro pronto para persistir (uma linha do CSV)."""

    def __init__(self, llm: LLMClient, audit: Any = None, arquivo_origem: str = "dados/avaliacoes/avaliacoes_atendimento.json",
                 reasoning_effort: str = "low", max_completion_tokens: int = 2000):
        self.llm, self.audit, self.arquivo_origem = llm, audit, arquivo_origem
        self.reasoning_effort, self.max_completion_tokens = reasoning_effort, max_completion_tokens

    def classificar(self, avaliacao: Dict[str, Any]) -> Dict[str, Any]:
        texto = avaliacao["texto"]
        usuario = PROMPT_SENTIMENTO_USUARIO.format(canal=avaliacao.get("canal") or "não informado",
                                                   conteudo_delimitado=delimitar_dados_externos(texto))
        resposta = self.llm.gerar(usuario, system_instruction=PROMPT_SENTIMENTO_SISTEMA, schema=ClassificacaoSentimento,
                                  reasoning_effort=self.reasoning_effort, max_completion_tokens=self.max_completion_tokens)
        resposta.parametros["versao_esquema"] = VERSAO_ESQUEMA_SENTIMENTO
        registro = {
            "id": avaliacao["id"], "atendimento_id": avaliacao.get("atendimento_id"), "data": avaliacao.get("data"),
            "canal": avaliacao.get("canal"), **{campo: None for campo in CAMPOS_ROTULO},
            "classificacao_valida": False, "alertas": "", "ajustes_por_regra": "",
            "modelo": resposta.modelo, "provedor": resposta.provedor, "prompt_versao": VERSOES_PROMPTS["PROMPT_SENTIMENTO"],
            "versao_esquema": VERSAO_ESQUEMA_SENTIMENTO, "classificado_em": datetime.now().isoformat(timespec="seconds"),
            "tokens_total": resposta.tokens_total, "custo_estimado_usd": resposta.custo_estimado_usd,
        }
        try:
            saida = ClassificacaoSentimento.model_validate_json(resposta.conteudo) if resposta.sucesso else None
        except ValueError:
            saida = None
        if saida is None:
            motivo = f"FALHA_NA_CLASSIFICACAO: {resposta.codigo_erro or 'SAIDA_FORA_DO_ESQUEMA'}"
            registro.update({"necessita_revisao": True, "alertas": motivo})
        else:
            rotulo, ajustes, alertas = aplicar_regras(saida, texto)
            registro.update({**rotulo, "classificacao_valida": True, "alertas": "; ".join(alertas),
                             "ajustes_por_regra": "; ".join(ajustes)})
        if self.audit is not None:
            self.audit.registrar_execucao(
                caso_id=avaliacao["id"], etapa="classificacao_sentimento", modalidade="avaliacao_atendimento",
                arquivo_origem=self.arquivo_origem, resposta=resposta, prompt_id="PROMPT_SENTIMENTO",
                prompt_versao=VERSOES_PROMPTS["PROMPT_SENTIMENTO"], prompt_texto=PROMPT_SENTIMENTO_SISTEMA + usuario,
                resumo_saida=f"polaridade={registro['polaridade']}; ambiguidade={registro['ambiguidade']}; "
                             f"revisao={registro['necessita_revisao']}")
        return registro


# ------------------------------------------------------------------------------
# Persistência (Aula 14 §3.3)
# ------------------------------------------------------------------------------
def persistir_rotulos(registros: List[Dict[str, Any]], destino: Path = DIR_ROTULOS,
                      metadados: Optional[Dict[str, Any]] = None) -> Tuple[Path, Path]:
    """Grava CSV e JSON com nome versionado; nada é sobrescrito."""
    destino.mkdir(parents=True, exist_ok=True)
    nome = nome_versionado(destino, "rotulos_sentimentos", [".csv", ".json"])
    caminho_csv, caminho_json = destino / f"{nome}.csv", destino / f"{nome}.json"
    pd.DataFrame(registros).to_csv(caminho_csv, index=False, encoding="utf-8")
    caminho_json.write_text(json.dumps({**(metadados or {}), "registros": registros}, indent=2, ensure_ascii=False) + "\n",
                            encoding="utf-8")
    return caminho_csv, caminho_json


def arquivo_de_rotulos_mais_recente(destino: Path = DIR_ROTULOS) -> Optional[Path]:
    arquivos = sorted(destino.glob("rotulos_sentimentos_*.csv"), key=lambda p: p.stat().st_mtime)
    return arquivos[-1] if arquivos else None


def carregar_rotulos(caminho: Path) -> pd.DataFrame:
    return metrics.normalizar_tipos(pd.read_csv(caminho, encoding="utf-8", dtype={"data": str}, keep_default_na=True))


# ------------------------------------------------------------------------------
# Avaliação contra o gabarito (RF22, RF23)
# ------------------------------------------------------------------------------
def avaliar_contra_gabarito(df: pd.DataFrame, gabarito: Dict[str, Any]) -> Dict[str, Any]:
    """Acurácia por campo, matriz de confusão da polaridade e fila de revisão esperada x sinalizada."""
    esperados = {r["id"]: r for r in gabarito["rotulos_esperados"]}
    obtidos = {r["id"]: r for r in metrics.registros(df)}
    itens = []
    for id_avaliacao, esperado in esperados.items():
        obtido = obtidos.get(id_avaliacao, {})
        item = {"id": id_avaliacao, "classificacao_valida": bool(obtido.get("classificacao_valida")),
                "justificativa_gabarito": esperado["justificativa"], "justificativa_modelo": obtido.get("justificativa_curta"),
                "trecho_modelo": obtido.get("trecho_determinante"), "alertas": obtido.get("alertas") or ""}
        for campo in ("polaridade", "intensidade", "ambiguidade", "tema", "necessita_revisao"):
            item[f"{campo}_esperada"] = esperado[campo]
            item[f"{campo}_obtida"] = obtido.get(campo)
            item[f"{campo}_confere"] = obtido.get(campo) == esperado[campo]
        item["trecho_literal"] = item["classificacao_valida"] and "TRECHO_NAO_LITERAL" not in item["alertas"]
        itens.append(item)

    def taxa(chave: str) -> Dict[str, int]:
        return {"numerador": sum(bool(i[chave]) for i in itens), "denominador": len(itens)}

    revisao_esperada = {i for i, r in esperados.items() if r["necessita_revisao"]}
    revisao_sinalizada = {i for i, r in obtidos.items() if r.get("necessita_revisao")}
    confusao = pd.crosstab(pd.Series([i["polaridade_esperada"] for i in itens], name="esperada"),
                           pd.Series([i["polaridade_obtida"] or "sem rótulo" for i in itens], name="obtida"))
    return {
        "versao_gabarito": gabarito["versao_gabarito"], "revisao_gabarito": gabarito["revisao_humana"]["status"],
        "agregados": {
            "saidas_validas": taxa("classificacao_valida"),
            "acuracia_polaridade": taxa("polaridade_confere"),
            "acuracia_ambiguidade": taxa("ambiguidade_confere"),
            "acuracia_tema": taxa("tema_confere"),
            "acuracia_intensidade": taxa("intensidade_confere"),
            "trechos_literais": taxa("trecho_literal"),
            "casos_para_revisao_esperados": sorted(revisao_esperada),
            "casos_para_revisao_sinalizados": sorted(revisao_sinalizada),
            "revisao_esperada_sinalizada": {"numerador": len(revisao_esperada & revisao_sinalizada),
                                            "denominador": len(revisao_esperada)},
            "revisao_sinalizada_alem_do_esperado": sorted(revisao_sinalizada - revisao_esperada),
        },
        "matriz_confusao_polaridade": {str(linha): {str(c): int(v) for c, v in valores.items()}
                                       for linha, valores in confusao.to_dict(orient="index").items()},
        "itens": itens,
    }


def relatorio_sentimentos_md(avaliacao: Dict[str, Any], indicadores: Dict[str, Any], contexto: Dict[str, Any]) -> str:
    ficha, a = indicadores["ficha_tecnica"], avaliacao["agregados"]

    def fr(chave: str) -> str:
        return f"{a[chave]['numerador']}/{a[chave]['denominador']}"

    linhas = [
        "# Classificação de sentimentos das avaliações de atendimento (RF22)", "",
        "## Ficha técnica", "",
        f"- Avaliações: **{ficha['n_avaliacoes']}** ({ficha['natureza']}; intervalo de confiança: {ficha['intervalo_de_confianca']}) | "
        f"atendimentos avaliados: {ficha['n_atendimentos_avaliados']} | atendimentos do período: não localizado "
        "(taxa de resposta não calculável)",
        f"- Período das avaliações: {ficha['periodo']['inicio']} a {ficha['periodo']['fim']} | modelo: "
        f"{', '.join(ficha['modelos'])} | prompt PROMPT_SENTIMENTO v{contexto['prompt_versao']} | esquema "
        f"{contexto['versao_esquema']} | classificado em {ficha['classificado_em']['inicio']}",
        f"- Acurácia da polaridade contra o gabarito v{avaliacao['versao_gabarito']} (revisão humana: "
        f"{avaliacao['revisao_gabarito']}): **{fr('acuracia_polaridade')}**",
        f"- Limítrofes: {metrics.formatar(ficha['limitrofes'])} | para revisão: {metrics.formatar(ficha['para_revisao'])} | "
        f"sem rótulo válido: {metrics.formatar(ficha['sem_rotulo_valido'])}",
        f"- Percentual só com base de pelo menos {ficha['minimo_para_percentual']} avaliações.",
        f"- {ficha['nota_etica']}", "",
        "## Distribuição da polaridade (calculada em pandas)", "",
        "| Polaridade | Avaliações |", "|---|---:|",
    ]
    linhas += [f"| {c['categoria']} | {metrics.formatar(c)} |" for c in indicadores["polaridade"]["categorias"]]
    linhas += ["", "Por canal (percentual omitido abaixo do mínimo):", "",
               "| Canal | n | " + " | ".join(metrics.POLARIDADES) + " |", "|---|---:|" + "---:|" * len(metrics.POLARIDADES)]
    for grupo in indicadores["por_canal"]:
        valores = {c["categoria"]: metrics.formatar(c) for c in grupo["categorias"]}
        linhas.append(f"| {grupo['grupo']} | {grupo['n']} | " + " | ".join(valores.get(p, "0") for p in metrics.POLARIDADES) + " |")
    linhas += [
        "", "## Conferência contra o gabarito", "",
        f"- Saídas válidas: {fr('saidas_validas')} | trechos determinantes literais: {fr('trechos_literais')}",
        f"- Acurácia: polaridade {fr('acuracia_polaridade')} | ambiguidade {fr('acuracia_ambiguidade')} | tema "
        f"{fr('acuracia_tema')} | intensidade {fr('acuracia_intensidade')}",
        f"- Casos que o gabarito manda revisar e que foram sinalizados: {fr('revisao_esperada_sinalizada')} "
        f"({', '.join(a['casos_para_revisao_esperados'])}); sinalizados além do esperado: "
        f"{', '.join(a['revisao_sinalizada_alem_do_esperado']) or 'nenhum'}", "",
        "Matriz de confusão da polaridade (linhas: gabarito; colunas: modelo):", "",
    ]
    colunas = sorted({c for v in avaliacao["matriz_confusao_polaridade"].values() for c in v})
    linhas += ["| gabarito \\ modelo | " + " | ".join(colunas) + " |", "|---|" + "---:|" * len(colunas)]
    for esperada, valores in avaliacao["matriz_confusao_polaridade"].items():
        linhas.append(f"| {esperada} | " + " | ".join(str(valores.get(c, 0)) for c in colunas) + " |")
    linhas += ["", "## Por avaliação", "",
               "| ID | Esperada | Obtida | Ambiguidade (esp./obt.) | Tema (esp./obt.) | Revisão | Trecho determinante | Confere |",
               "|---|---|---|---|---|---|---|---|"]
    for i in avaliacao["itens"]:
        linhas.append(f"| {i['id']} | {i['polaridade_esperada']} | {i['polaridade_obtida']} | {i['ambiguidade_esperada']}/"
                      f"{i['ambiguidade_obtida']} | {i['tema_esperada']}/{i['tema_obtida']} | "
                      f"{'sim' if i['necessita_revisao_obtida'] else 'não'} | {i['trecho_modelo'] or '-'} | "
                      f"{'sim' if i['polaridade_confere'] else 'NÃO'} |")
    ambiguos = [i for i in avaliacao["itens"] if i["ambiguidade_esperada"] == "limitrofe" or not i["polaridade_confere"]]
    linhas += ["", "## Casos ambíguos e divergências", ""]
    for i in ambiguos:
        linhas.append(f"- **{i['id']}** — gabarito: {i['polaridade_esperada']} ({i['justificativa_gabarito']}) | modelo: "
                      f"{i['polaridade_obtida']} ({i['justificativa_modelo']})" + (f" | alertas: {i['alertas']}" if i["alertas"] else ""))
    linhas += [
        "", "## Limites", "",
        "- Corpus sintético de 12 avaliações, escrito pela mesma equipe que fez o gabarito: textos mais limpos que os reais; "
        "acurácia alta aqui não prevê desempenho em avaliações reais (Aula 14 §4.3).",
        "- Uma única execução: a concordância entre execuções (Aula 14 §4.1) não foi medida; os casos limítrofes são os "
        "que mais oscilam.",
        "- A ambiguidade autodeclarada prioriza a revisão, mas não a delimita: o modelo pode acertar o rótulo sem perceber "
        "que o caso era disputável.",
        f"- Rótulos: {contexto['arquivo_rotulos']} | chamadas: {contexto['chamadas']} | custo estimado: "
        f"US$ {contexto['custo_total_usd']:.6f}",
    ]
    return "\n".join(linhas) + "\n"


def executar_classificacao_sentimentos(config: Dict[str, Any]) -> bool:
    """--modo sentimentos: classifica as 12 avaliações, persiste, confere com o gabarito e agrega em código."""
    from src.audit import AuditManager
    from src.llm_client import OrcamentoExecucao

    print("=" * 75)
    print("  CLASSIFICAÇÃO DE SENTIMENTOS DAS AVALIAÇÕES (RF22)")
    print("=" * 75)
    arquivos = config["desafio02"]
    avaliacoes = json.loads((RAIZ_PROJETO / arquivos["avaliacoes"]).read_text(encoding="utf-8"))["avaliacoes"]
    gabarito = json.loads((RAIZ_PROJETO / arquivos["gabarito_sentimentos"]).read_text(encoding="utf-8"))
    llm = LLMClient()
    llm.orcamento = OrcamentoExecucao.do_config(config)
    print(f"• Provedor: {llm.provedor} | modelo: {llm.modelo} | {len(avaliacoes)} avaliações, uma por chamada | gabarito "
          f"v{gabarito['versao_gabarito']} (revisão humana: {gabarito['revisao_humana']['status']})")
    if not llm.disponivel:
        print(f"[ERRO] {llm.motivo_indisponibilidade}")
        return False
    cfg = config.get("sentimentos", {})
    classificador = ClassificadorSentimentos(llm, AuditManager(), arquivos["avaliacoes"], cfg.get("reasoning_effort", "low"),
                                             int(cfg.get("max_completion_tokens", 2000)))
    registros = []
    for avaliacao in avaliacoes:
        registro = classificador.classificar(avaliacao)
        registros.append(registro)
        print(f"  - {registro['id']}: {registro['polaridade']} | {registro['ambiguidade']} | revisão "
              f"{'sim' if registro['necessita_revisao'] else 'não'}" + (f" | {registro['alertas']}" if registro["alertas"] else ""))

    contexto = {"gerado_em": datetime.now().isoformat(timespec="seconds"), "provedor": llm.provedor, "modelo": llm.modelo,
                "prompt_versao": VERSOES_PROMPTS["PROMPT_SENTIMENTO"], "versao_esquema": VERSAO_ESQUEMA_SENTIMENTO,
                "chamadas": len(registros), "custo_total_usd": sum(r["custo_estimado_usd"] or 0.0 for r in registros)}
    caminho_csv, _ = persistir_rotulos(registros, metadados=contexto)
    contexto["arquivo_rotulos"] = caminho_csv.relative_to(RAIZ_PROJETO).as_posix()
    df = carregar_rotulos(caminho_csv)
    avaliacao = avaliar_contra_gabarito(df, gabarito)
    resultado = metrics.indicadores(df, avaliacao)
    dir_metricas = RAIZ_PROJETO / "resultados" / "metricas"
    dir_metricas.mkdir(parents=True, exist_ok=True)
    (dir_metricas / "avaliacao_sentimentos_rf22.json").write_text(
        json.dumps({**contexto, **avaliacao}, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
    (dir_metricas / "avaliacao_sentimentos_rf22.md").write_text(relatorio_sentimentos_md(avaliacao, resultado, contexto),
                                                                encoding="utf-8")
    (dir_metricas / "indicadores_sentimentos.json").write_text(
        json.dumps({**contexto, **resultado}, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")

    a = avaliacao["agregados"]
    print("\n" + "=" * 75)
    for chave in ("saidas_validas", "acuracia_polaridade", "acuracia_ambiguidade", "acuracia_tema", "trechos_literais",
                  "revisao_esperada_sinalizada"):
        print(f"  {chave}: {a[chave]['numerador']}/{a[chave]['denominador']}")
    print(f"  Sinalizados além do esperado: {a['revisao_sinalizada_alem_do_esperado'] or 'nenhum'}")
    print(f"  Distribuição: " + ", ".join(metrics.formatar(c) + f" {c['categoria']}" for c in resultado["polaridade"]["categorias"]))
    print(f"  Custo estimado: US$ {contexto['custo_total_usd']:.6f}")
    print(f"  Rótulos: {contexto['arquivo_rotulos']}")
    print("  Relatório: resultados/metricas/avaliacao_sentimentos_rf22.md | indicadores: indicadores_sentimentos.json")
    print("=" * 75)
    return a["saidas_validas"]["numerador"] == a["saidas_validas"]["denominador"]
