#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
==============================================================================
AGREGAÇÃO DETERMINÍSTICA DOS RÓTULOS DE SENTIMENTO (RF22, RF23, T13)
==============================================================================
Aula 14 §3.4 e §5: o modelo classifica cada avaliação; toda conta é feita
aqui, em pandas, sobre os rótulos gravados, e por isso é gratuita,
reprodutível e conferível linha a linha.
- Todo percentual vem com a contagem e o denominador; recorte com menos de
  MINIMO_PARA_PERCENTUAL casos mostra só a contagem (o "problema de junho").
- O lote é um censo (E_AMOSTRA = False): não cabe intervalo de confiança
  amostral. O erro do classificador, medido contra o gabarito, vai na ficha
  técnica, porque não desaparece no censo.
- Avaliação repetida (mesmo id) conta uma vez, pela classificação mais
  recente, e o número de duplicatas removidas é informado.
- Filtro sem resultado devolve zeros e percentuais ausentes, sem divisão por
  zero.
==============================================================================
"""

from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple, get_args

import pandas as pd

from src.schemas import Polaridade

MINIMO_PARA_PERCENTUAL = 10
E_AMOSTRA = False
POLARIDADES: Tuple[str, ...] = get_args(Polaridade)
COLUNAS_BOOLEANAS = ("necessita_revisao", "classificacao_valida")
COLUNAS_DE_TEXTO_LIVRE = ("alertas", "ajustes_por_regra")
NOTA_ETICA = (
    "Os rótulos descrevem o texto de cada avaliação, não o autor: não se infere personalidade, estado emocional, "
    "diagnóstico ou característica sensível. A ambiguidade é autodeclarada pelo modelo, uma estimativa não "
    "calibrada que orienta a revisão e não é probabilidade de acerto. O percentual descreve quem avaliou, não todos "
    "os atendidos (viés de resposta)."
)


# ------------------------------------------------------------------------------
# Preparação
# ------------------------------------------------------------------------------
def de_registros(registros: Iterable[Dict[str, Any]]) -> pd.DataFrame:
    df = pd.DataFrame(list(registros))
    return normalizar_tipos(df)


def normalizar_tipos(df: pd.DataFrame) -> pd.DataFrame:
    """Booleanos lidos de CSV como texto voltam a ser booleanos; datas ficam como texto ISO (AAAA-MM-DD)."""
    df = df.copy()
    for coluna in COLUNAS_BOOLEANAS:
        if coluna in df.columns:
            df[coluna] = df[coluna].map(lambda v: v if isinstance(v, bool) else str(v).strip().lower() == "true").astype(bool)
    for coluna in COLUNAS_DE_TEXTO_LIVRE:
        if coluna in df.columns:
            df[coluna] = df[coluna].astype(object).where(df[coluna].notna(), "").astype(str)
    if "data" in df.columns:
        df["data"] = df["data"].astype(str)
    return df


def registros(df: pd.DataFrame) -> List[Dict[str, Any]]:
    """Linhas como dicionários, com célula vazia como None (JSON válido, sem NaN)."""
    return df.astype(object).where(df.notna(), None).to_dict(orient="records")


def remover_duplicatas(df: pd.DataFrame) -> Tuple[pd.DataFrame, int]:
    """Uma linha por avaliação: fica a classificação mais recente. Devolve também quantas linhas saíram."""
    if df.empty or "id" not in df.columns:
        return df, 0
    ordenado = df.sort_values("classificado_em", kind="stable") if "classificado_em" in df.columns else df
    unico = ordenado.drop_duplicates(subset="id", keep="last").sort_values("id", kind="stable")
    return unico.reset_index(drop=True), len(df) - len(unico)


def filtrar(df: pd.DataFrame, canais: Optional[Sequence[str]] = None, temas: Optional[Sequence[str]] = None,
            polaridades: Optional[Sequence[str]] = None, data_inicial: Optional[str] = None,
            data_final: Optional[str] = None, apenas_revisao: bool = False) -> pd.DataFrame:
    """Filtros determinísticos; lista vazia ou None não filtra. Datas no formato AAAA-MM-DD, inclusivas."""
    mascara = pd.Series(True, index=df.index)
    for coluna, valores in (("canal", canais), ("tema", temas), ("polaridade", polaridades)):
        if valores:
            mascara &= df[coluna].isin(list(valores))
    if data_inicial:
        mascara &= df["data"] >= data_inicial
    if data_final:
        mascara &= df["data"] <= data_final
    if apenas_revisao:
        mascara &= precisa_de_revisao(df)
    return df[mascara].reset_index(drop=True)


# ------------------------------------------------------------------------------
# Contagens
# ------------------------------------------------------------------------------
def percentual(n: int, denominador: int, minimo: int = MINIMO_PARA_PERCENTUAL) -> Optional[float]:
    """Percentual com uma casa, ou None quando a base é vazia ou menor que o mínimo (só a contagem é exibida)."""
    if denominador <= 0 or denominador < minimo:
        return None
    return round(100.0 * n / denominador, 1)


def motivo_sem_percentual(denominador: int, minimo: int = MINIMO_PARA_PERCENTUAL) -> Optional[str]:
    if denominador == 0:
        return "nenhuma avaliação no recorte"
    if denominador < minimo:
        return f"base de {denominador} avaliação(ões), abaixo do mínimo de {minimo} para percentual"
    return None


def distribuicao(df: pd.DataFrame, coluna: str = "polaridade", categorias: Optional[Sequence[str]] = POLARIDADES,
                 minimo: int = MINIMO_PARA_PERCENTUAL) -> Dict[str, Any]:
    """
    Contagem por categoria com o denominador explícito (Aula 14 §3.4). Categorias da lista aparecem mesmo com zero;
    valores fora da lista, como rótulo ausente por falha, aparecem com o próprio nome.
    """
    denominador = len(df)
    contagem = df[coluna].fillna("sem rótulo").value_counts() if denominador else pd.Series(dtype="int64")
    ordem = list(categorias or []) + [c for c in contagem.index if c not in (categorias or [])]
    return {
        "coluna": coluna, "denominador": denominador, "minimo_para_percentual": minimo,
        "percentual_exibido": percentual(0, denominador, minimo) is not None,
        "motivo_sem_percentual": motivo_sem_percentual(denominador, minimo),
        "categorias": [{"categoria": str(c), "n": int(contagem.get(c, 0)), "denominador": denominador,
                        "percentual": percentual(int(contagem.get(c, 0)), denominador, minimo)} for c in ordem],
    }


def recorte(df: pd.DataFrame, por: str, coluna: str = "polaridade", categorias: Optional[Sequence[str]] = POLARIDADES,
            minimo: int = MINIMO_PARA_PERCENTUAL) -> List[Dict[str, Any]]:
    """Distribuição dentro de cada grupo (canal, tema...): o percentual some quando o grupo tem menos de `minimo`."""
    if df.empty:
        return []
    return [{"grupo": str(grupo), "n": len(parte), **distribuicao(parte, coluna, categorias, minimo)}
            for grupo, parte in df.groupby(por, sort=True)]


def precisa_de_revisao(df: pd.DataFrame) -> pd.Series:
    if df.empty:
        return pd.Series(dtype=bool)
    return (df["necessita_revisao"] | (df["polaridade"] == "indeterminada") | (df["ambiguidade"] == "limitrofe")
            | ~df["classificacao_valida"])


def fila_de_revisao(df: pd.DataFrame) -> pd.DataFrame:
    """Avaliações indeterminadas, limítrofes, marcadas para revisão ou sem rótulo válido (Aula 14 §6)."""
    colunas = [c for c in ("id", "canal", "polaridade", "ambiguidade", "tema", "trecho_determinante",
                           "justificativa_curta", "alertas") if c in df.columns]
    return df[precisa_de_revisao(df)][colunas].reset_index(drop=True) if not df.empty else df


def proporcao(n: int, denominador: int, minimo: int = MINIMO_PARA_PERCENTUAL) -> Dict[str, Any]:
    return {"n": int(n), "denominador": int(denominador), "percentual": percentual(n, denominador, minimo)}


# ------------------------------------------------------------------------------
# Ficha técnica e indicadores
# ------------------------------------------------------------------------------
def ficha_tecnica(df: pd.DataFrame, duplicatas_removidas: int = 0, avaliacao: Optional[Dict[str, Any]] = None,
                  atendimentos_no_periodo: Optional[int] = None) -> Dict[str, Any]:
    """Os cinco itens da Aula 14 §5.2, que precedem qualquer número: tamanho, distribuição, ambiguidade, erro e proveniência."""
    n = len(df)
    acuracia = (avaliacao or {}).get("agregados", {}).get("acuracia_polaridade")
    return {
        "n_avaliacoes": n,
        "n_atendimentos_avaliados": int(df["atendimento_id"].nunique()) if n and "atendimento_id" in df else 0,
        "atendimentos_no_periodo": atendimentos_no_periodo,
        "taxa_de_resposta": proporcao(n, atendimentos_no_periodo) if atendimentos_no_periodo else None,
        "natureza": "amostra" if E_AMOSTRA else "censo do lote fictício avaliado",
        "e_amostra": E_AMOSTRA,
        "intervalo_de_confianca": "aplicável (amostra)" if E_AMOSTRA else "não se aplica (sem margem amostral no censo)",
        "periodo": {"inicio": df["data"].min(), "fim": df["data"].max()} if n else {"inicio": None, "fim": None},
        "modelos": sorted(df["modelo"].dropna().astype(str).unique().tolist()) if n and "modelo" in df else [],
        "classificado_em": {"inicio": df["classificado_em"].min(), "fim": df["classificado_em"].max()}
        if n and "classificado_em" in df else {"inicio": None, "fim": None},
        "duplicatas_removidas": duplicatas_removidas,
        "sem_rotulo_valido": proporcao(int((~df["classificacao_valida"]).sum()) if n else 0, n),
        "limitrofes": proporcao(int((df["ambiguidade"] == "limitrofe").sum()) if n else 0, n),
        "para_revisao": proporcao(int(precisa_de_revisao(df).sum()) if n else 0, n),
        "acuracia_polaridade_contra_gabarito": acuracia,
        "minimo_para_percentual": MINIMO_PARA_PERCENTUAL,
        "nota_etica": NOTA_ETICA,
    }


def indicadores(df_bruto: pd.DataFrame, avaliacao: Optional[Dict[str, Any]] = None, **filtros) -> Dict[str, Any]:
    """Ficha técnica, distribuição geral e recortes por canal e tema, depois de deduplicar e filtrar."""
    df, duplicatas = remover_duplicatas(df_bruto)
    df = filtrar(df, **filtros) if filtros else df
    return {
        "filtros": {k: v for k, v in filtros.items() if v},
        "ficha_tecnica": ficha_tecnica(df, duplicatas, avaliacao),
        "polaridade": distribuicao(df, "polaridade"),
        "tema": distribuicao(df, "tema", categorias=None),
        "por_canal": recorte(df, "canal"),
        "por_tema": recorte(df, "tema"),
        "fila_de_revisao": registros(fila_de_revisao(df)),
    }


def formatar(item: Dict[str, Any]) -> str:
    """'4/12 (33,3%)' ou '4/7' quando o percentual é suprimido; vírgula decimal (norma brasileira)."""
    texto = f"{item['n']}/{item['denominador']}"
    return texto if item.get("percentual") is None else f"{texto} ({str(item['percentual']).replace('.', ',')}%)"
