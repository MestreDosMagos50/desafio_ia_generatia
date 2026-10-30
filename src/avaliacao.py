#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
==============================================================================
AVALIAÇÃO INTEGRADA (RF23), REGRESSÃO (T15) E SEGUNDA GERAÇÃO (RF21, T12)
==============================================================================
- executar_regressao (--modo regressao, T15): reexecuta o caso textual pelo
  próprio pipeline do Desafio 01 (extração, conferência, minuta e revisão) e
  o OCR da ficha manuscrita (leitura pelo gpt-5.6-luna sobre o PDF convertido
  com pymupdf), que segue pelo fluxo do Desafio 02 até a minuta e a fila do
  operador. Sem --demo-avaliacao-humana, a revisão do texto é feita pela
  pessoa no terminal; com ela, as decisões são simuladas e identificadas.
- executar_comparativo_geracao (--modo comparar-geracao, RF21, T12): as 8
  perguntas do RAG no gpt-5.6-terra sobre o mesmo índice aberto, com prova de
  que nada foi reindexado, e uma falha do serviço de geração tratada e
  auditada.
- executar_avaliacao_integrada (--modo avaliacao-integrada): matriz T01–T15 e
  métricas do RF23 consolidadas das evidências gravadas por cada modo, sem
  chamada a modelo; o T13 é executado aqui, por ser determinístico. Cada
  linha traz a evidência e a data de execução, para que evidência antiga
  fique visível. Com --reexecutar, os modos de avaliação rodam antes.
Situações: CONFERE; CONFERE_COM_RESSALVA (o resultado esperado aconteceu, com
falha parcial medida e registrada); NAO_CONFERE; PENDENTE (sem evidência ou
com ação humana pendente). A matriz não esconde falhas: cada ressalva diz o
que faltou.
Nota sobre o enunciado: na tabela da Seção 11, T01 a T04 aparecem rotulados
como RF15, RF15, RF16 e RF17; pelo cenário de cada um, os requisitos são RF14,
RF14, RF15 e RF16 (de T05 em diante os rótulos coincidem com o escopo).
==============================================================================
"""

import hashlib
import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

RAIZ_PROJETO = Path(__file__).resolve().parent.parent
CONFERE, RESSALVA, NAO_CONFERE, PENDENTE = "CONFERE", "CONFERE_COM_RESSALVA", "NAO_CONFERE", "PENDENTE"
ARQ_DECISOES_D02 = "resultados/logs/decisoes_humanas_desafio02.json"


def _json(relativo: str) -> Optional[Any]:
    caminho = RAIZ_PROJETO / relativo
    try:
        return json.loads(caminho.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _salvar(relativo: str, dados: Any, markdown: Optional[str] = None):
    destino = RAIZ_PROJETO / relativo
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(json.dumps(dados, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
    if markdown is not None:
        destino.with_suffix(".md").write_text(markdown, encoding="utf-8")


def _quando(relativo: str, dados: Any = None) -> Optional[str]:
    if isinstance(dados, dict) and dados.get("gerado_em"):
        return dados["gerado_em"]
    caminho = RAIZ_PROJETO / relativo
    return datetime.fromtimestamp(caminho.stat().st_mtime).isoformat(timespec="seconds") if caminho.exists() else None


def _fr(item: Optional[Dict[str, Any]]) -> str:
    return f"{item['numerador']}/{item['denominador']}" if item else "não localizado"


def _completo(item: Optional[Dict[str, Any]]) -> bool:
    return bool(item) and item["numerador"] == item["denominador"]


def _sha256(caminho: Path) -> Optional[str]:
    return hashlib.sha256(caminho.read_bytes()).hexdigest() if caminho.exists() else None


# ------------------------------------------------------------------------------
# T15: regressão do Desafio 01
# ------------------------------------------------------------------------------
def _mais_recente(padrao: str, desde: float) -> Optional[Path]:
    arquivos = [p for p in RAIZ_PROJETO.glob(padrao) if p.stat().st_mtime >= desde]
    return max(arquivos, key=lambda p: p.stat().st_mtime) if arquivos else None


def executar_regressao(config: Dict[str, Any], auto_demo: bool = False) -> bool:
    """T15: um caso textual e um caso de OCR do Desafio 01 seguem até minuta e revisão no provedor atual."""
    from src.atendimento import alertas_de_leitura_ocr, cliente_de_geracao, minutas_para_revisao, processar_atendimento
    from src.audit import AuditManager
    from src.embeddings import preparar_indice
    from src.guardrails import Guardrails
    from src.main import _registrar_chamadas, executar_pipeline
    from src.vision import VisionProcessor

    print("=" * 75)
    print("  REGRESSÃO DO DESAFIO 01 (RF23, T15): texto e OCR até minuta e revisão")
    print("=" * 75)
    inicio_ts = datetime.now().timestamp()
    inicio = datetime.now().isoformat(timespec="seconds")
    pasta = RAIZ_PROJETO / "resultados" / "regressao" / datetime.now().strftime("%Y%m%d-%H%M%S")
    pasta.mkdir(parents=True, exist_ok=True)
    arquivos = config.get("arquivos_originais", {})
    arq_texto = arquivos.get("texto", "dados/originais/entrada_texto.txt")
    arq_documento = arquivos.get("documento_imagem", "dados/originais/entrada_pdf-imagem.pdf")
    audit = AuditManager()

    # 1. Caso textual pelo pipeline do Desafio 01 (o mesmo de python -m src.main --modo texto)
    print("\n[1/2] Caso textual: pipeline do Desafio 01 (extração, conferência, minuta e revisão)")
    concluiu_texto = executar_pipeline(config, modo="texto", auto_demo=auto_demo)
    from src.parsers import GeradorMinuta
    comparacao = _json(f"dados/processados/comparacao_{GeradorMinuta.nome_base(arq_texto)}_gabarito.json") or {}
    minuta = _mais_recente("resultados/minutas/minuta_institucional_2026-000142_*.txt", inicio_ts)
    arquivo_decisoes = audit.arquivo_decisoes_simuladas if auto_demo else audit.arquivo_decisoes_json
    decisoes = [d for d in (json.loads(arquivo_decisoes.read_text(encoding="utf-8")) if arquivo_decisoes.exists() else [])
                if d.get("caso_id") == "CASO_01_TEXTO" and d.get("timestamp_decisao", "") >= inicio]
    decisao_minuta = next((d for d in reversed(decisoes) if d.get("objeto_revisado") == "minuta"), None)
    if minuta:
        shutil.copy2(minuta, pasta / "texto_minuta_desafio01.txt")
    if comparacao:
        (pasta / "texto_comparacao_gabarito.json").write_text(json.dumps(comparacao, indent=2, ensure_ascii=False), encoding="utf-8")
    texto = {
        "entrada": arq_texto, "fluxo": "pipeline do Desafio 01 (python -m src.main --modo texto)",
        "pipeline_concluido": concluiu_texto, "acerto_extracao_gabarito": {
            "numerador": comparacao.get("acertos"), "denominador": comparacao.get("total_campos"),
            "percentual": comparacao.get("taxa_acerto_pct"), "inventados": comparacao.get("inventados"),
            "omitidos": comparacao.get("omitidos"), "divergentes": comparacao.get("divergentes")} if comparacao else None,
        "minuta": minuta.relative_to(RAIZ_PROJETO).as_posix() if minuta else None,
        "sha256_minuta": _sha256(minuta) if minuta else None,
        "revisao": {"decisao": decisao_minuta.get("decisao") if decisao_minuta else None,
                    "simulada": auto_demo, "operador": decisao_minuta.get("operador_responsavel") if decisao_minuta else None,
                    "arquivo": arquivo_decisoes.relative_to(RAIZ_PROJETO).as_posix()},
        "chegou_a_minuta": minuta is not None, "chegou_a_revisao": decisao_minuta is not None,
    }

    # 2. OCR da ficha manuscrita (leitura do Desafio 01) seguindo pelo fluxo do Desafio 02
    print("\n[2/2] OCR da ficha manuscrita: leitura (Desafio 01) -> contrato, ficha e minuta (Desafio 02) -> fila do operador")
    llm = cliente_de_geracao("principal", config)
    leitura = VisionProcessor(llm_client=llm).processar_caso_visao(arq_documento)
    _registrar_chamadas(audit, "CASO_02_VISAO_DOCUMENTO", "visao_documento", arq_documento, leitura["chamadas"])
    ocr = {"entrada": arq_documento, "fluxo": "leitura da ficha (Desafio 01, src/vision.py) + atendimento integrado (Desafio 02)",
           "leitura_ok": leitura["sucesso"], "erro_leitura": leitura.get("erro")}
    if leitura["sucesso"]:
        comparacao_visao = leitura["comparacao_gabarito"]
        (pasta / "ocr_leitura_bruta.txt").write_text(leitura["texto_bruto"], encoding="utf-8")
        (pasta / "ocr_comparacao_gabarito.json").write_text(json.dumps(comparacao_visao, indent=2, ensure_ascii=False),
                                                            encoding="utf-8")
        ocr["acerto_leitura_gabarito"] = {"numerador": comparacao_visao.get("acertos"), "denominador": comparacao_visao.get("total_campos"),
                                          "percentual": comparacao_visao.get("taxa_acerto_pct"),
                                          "divergentes": comparacao_visao.get("divergentes")}
        ocr["incertos_esperados"] = comparacao_visao.get("incertos_esperados")
        ocr["campos_marcados_incertos"] = [t["rotulo"] for t in leitura["dados_revisados"]["trechos_incertos"]]
        indice, motivo = preparar_indice(config)
        atendimento = processar_atendimento(
            leitura["texto_bruto"], config, indice, llm, Guardrails(llm_client=llm, audit=audit), audit,
            canal="OCR da ficha manuscrita (Desafio 01)", arquivo_origem=arq_documento, id_solicitacao="CASO_02_VISAO_DOCUMENTO",
            configuracao={"provedor": llm.provedor, "modelo": llm.modelo},
            alertas_da_origem=alertas_de_leitura_ocr(leitura["dados_revisados"]))
        fila = {i["caso_id"]: i for i in minutas_para_revisao(audit)}
        ocr.update({"id_atendimento": atendimento.id_atendimento, "etapa_final": atendimento.etapa_final,
                    "motivo": atendimento.motivo, "guardrails_entrada": atendimento.entrada["decisao"],
                    "status_minuta": (atendimento.rag or {}).get("status"),
                    "encaminhamento": (atendimento.rag or {}).get("encaminhamento"),
                    "alertas_da_origem": atendimento.alertas_da_origem,
                    "estado_na_fila": fila.get(atendimento.id_atendimento, {}).get("estado"),
                    "registro": f"resultados/atendimentos/{atendimento.id_atendimento}/atendimento.json",
                    "chegou_a_minuta": atendimento.etapa_final == "MINUTA_GERADA",
                    "chegou_a_revisao": atendimento.id_atendimento in fila})
        if atendimento.rag:
            (pasta / "ocr_minuta_desafio02.txt").write_text(atendimento.rag["minuta"], encoding="utf-8")
    else:
        ocr.update({"chegou_a_minuta": False, "chegou_a_revisao": False})

    resultado = {
        "gerado_em": datetime.now().isoformat(timespec="seconds"), "inicio": inicio, "provedor": llm.provedor,
        "modelo": llm.modelo, "decisoes_simuladas": auto_demo, "pasta_de_evidencias": pasta.relative_to(RAIZ_PROJETO).as_posix(),
        "texto": texto, "ocr": ocr,
        "confere": all(caso["chegou_a_minuta"] and caso["chegou_a_revisao"] for caso in (texto, ocr)),
        "pendencias": [f"{nome}: não chegou à minuta" for nome, caso in (("texto", texto), ("OCR", ocr)) if not caso["chegou_a_minuta"]]
        + [f"{nome}: não chegou à revisão" for nome, caso in (("texto", texto), ("OCR", ocr)) if not caso["chegou_a_revisao"]],
    }
    _salvar("resultados/metricas/regressao_t15.json", resultado, relatorio_regressao_md(resultado))
    print("\n" + "=" * 75)
    print(f"  Texto: minuta {'sim' if texto['chegou_a_minuta'] else 'NÃO'} | revisão "
          f"{texto['revisao']['decisao'] or 'não registrada'}{' (SIMULADA)' if auto_demo else ''} | extração "
          f"{_fr(texto['acerto_extracao_gabarito']) if texto['acerto_extracao_gabarito'] else '-'} campos")
    print(f"  OCR: leitura {_fr(ocr.get('acerto_leitura_gabarito'))} campos | {ocr.get('etapa_final', ocr.get('erro_leitura'))} | "
          f"fila: {ocr.get('estado_na_fila') or 'fora da fila'}")
    print(f"  T15: {'CONFERE' if resultado['confere'] else 'NÃO CONFERE'} | relatório: resultados/metricas/regressao_t15.md")
    print("=" * 75)
    return resultado["confere"]


def relatorio_regressao_md(r: Dict[str, Any]) -> str:
    texto, ocr = r["texto"], r["ocr"]
    extracao = texto["acerto_extracao_gabarito"] or {}
    leitura = ocr.get("acerto_leitura_gabarito") or {}
    incertos = ocr.get("incertos_esperados") or {}
    linhas = [
        "# Regressão do Desafio 01 (RF23, T15)", "",
        f"- Executado em {r['gerado_em']} com {r['provedor']}/{r['modelo']}. Decisões da revisão do texto: "
        f"{'SIMULADAS (--demo-avaliacao-humana), fora da taxa de aprovação' if r['decisoes_simuladas'] else 'humanas, no terminal'}.",
        f"- Evidências copiadas em `{r['pasta_de_evidencias']}/`.", "",
        "## Caso textual (`dados/originais/entrada_texto.txt`)", "",
        f"- Fluxo: {texto['fluxo']}; concluído: {'sim' if texto['pipeline_concluido'] else 'não'}.",
        f"- Extração contra o gabarito do Desafio 01: {extracao.get('numerador')}/{extracao.get('denominador')} campos "
        f"({extracao.get('percentual')}%); inventados: {len(extracao.get('inventados') or [])}; omitidos: "
        f"{', '.join(extracao.get('omitidos') or []) or 'nenhum'}; divergentes: {', '.join(extracao.get('divergentes') or []) or 'nenhum'}.",
        f"- Minuta: `{texto['minuta']}`" if texto["minuta"] else "- Minuta: NÃO gerada.",
        f"- Revisão da minuta: {texto['revisao']['decisao'] or 'não registrada'} ({texto['revisao']['operador'] or '-'}), em "
        f"`{texto['revisao']['arquivo']}`.", "",
        "## Caso de OCR (`dados/originais/entrada_pdf-imagem.pdf`)", "",
        f"- Fluxo: {ocr['fluxo']}.",
        f"- Leitura contra o gabarito do Desafio 01: {leitura.get('numerador')}/{leitura.get('denominador')} campos "
        f"({leitura.get('percentual')}%); divergentes: {', '.join(leitura.get('divergentes') or []) or 'nenhum'}."
        if ocr["leitura_ok"] else f"- Leitura falhou: {ocr.get('erro_leitura')}.",
        f"- Campos incertos esperados pelo gabarito e sinalizados pela leitura: {', '.join(incertos.get('sinalizados') or []) or 'nenhum'}; "
        f"não sinalizados: {', '.join(incertos.get('nao_sinalizados') or []) or 'nenhum'}." if incertos else "",
        f"- Atendimento `{ocr.get('id_atendimento')}`: guardrails {ocr.get('guardrails_entrada')}, etapa {ocr.get('etapa_final')}, "
        f"minuta {ocr.get('status_minuta') or '-'}, encaminhamento {ocr.get('encaminhamento') or '-'}, estado na fila do operador: "
        f"{ocr.get('estado_na_fila') or 'fora da fila'}." if ocr.get("id_atendimento") else "",
        f"- Campos que a leitura marcou como incertos: {', '.join(ocr.get('campos_marcados_incertos') or []) or 'nenhum'}.",
        f"- Alertas que acompanham a minuta: {', '.join(a.split(':')[0] for a in ocr.get('alertas_da_origem') or []) or 'nenhum'}.",
        "", "## Resultado", "",
        f"- T15: {'CONFERE' if r['confere'] else 'NÃO CONFERE'}: as duas entradas anteriores "
        f"{'seguiram' if r['confere'] else 'não seguiram'} até minuta e revisão.",
    ]
    linhas += [f"- Pendência: {p}" for p in r["pendencias"]]
    if leitura.get("divergentes"):
        linhas += [
            "", "## Falha crítica encontrada e correção", "",
            "- A leitura do manuscrito errou campos que identificam o aluno (veja os divergentes acima), e parte deles não foi "
            "marcada como incerta: sem gabarito, esse erro não é detectável por código.",
            "- No Desafio 01 a ficha só entra depois da confirmação humana dos campos críticos; no fluxo integrado do Desafio 02 "
            "a leitura ia direto para a extração. Correção: todo atendimento vindo de OCR leva o alerta "
            "ENTRADA_OCR_SEM_CONFIRMACAO_HUMANA (e um alerta por campo marcado como incerto) e vai à revisão prioritária.",
            "- Pendência declarada: a conferência campo a campo na imagem continua sendo humana; ela não é substituída pelo alerta.",
        ]
    return "\n".join(l for l in linhas if l is not None) + "\n"


# ------------------------------------------------------------------------------
# RF21 / T12: segunda configuração de geração sobre o mesmo índice
# ------------------------------------------------------------------------------
def _evidencia_do_indice(indice, nome: str, config: Dict[str, Any]) -> Dict[str, Any]:
    from src.embeddings import chunking_principal
    return {"sha256_manifesto": _sha256(indice.caminho_manifesto), "vetores": indice._colecao(nome).count(),
            "situacao": indice.situacao(nome, chunking_principal(config))[0]}


def _uso_por_resposta(modelo: str) -> Dict[str, Dict[str, Any]]:
    from src.rag import _nome_de_arquivo
    pasta = RAIZ_PROJETO / "resultados" / "rag" / "respostas" / _nome_de_arquivo(modelo)
    uso = {}
    for caminho in pasta.glob("*.json"):
        dados = json.loads(caminho.read_text(encoding="utf-8"))
        chamada = (dados.get("chamadas") or [{}])[0]
        uso[dados["id_caso"]] = {"latencia_ms": chamada.get("latencia_ms"), "tokens": chamada.get("tokens_total"),
                                 "custo_usd": chamada.get("custo_estimado_usd")}
    return uso


def executar_comparativo_geracao(config: Dict[str, Any]) -> bool:
    """--modo comparar-geracao: terra nas 8 perguntas sobre o índice já aberto; luna é lida da última avaliação."""
    from src.atendimento import cliente_de_geracao
    from src.audit import AuditManager
    from src.rag import AssistenteRAG, _indice_pronto, _nome_de_arquivo, executar_avaliacao_rag

    print("=" * 75)
    print("  SEGUNDA CONFIGURAÇÃO DE GERAÇÃO SOBRE O MESMO ÍNDICE (RF21, T12)")
    print("=" * 75)
    indice, motivo = _indice_pronto(config)
    if indice is None:
        print(f"[ERRO] {motivo}")
        return False
    nome = config["indice"].get("colecao_principal", "acervo_principal")
    principal, alternativo = config["llm"]["openai"]["modelo_padrao"], config["llm"]["openai"]["modelo_alternativo"]
    avaliacao_principal = _json(f"resultados/metricas/avaliacao_rag_rf19_{_nome_de_arquivo(principal)}.json")
    if avaliacao_principal is None:
        print(f"[ERRO] Sem avaliação do {principal}: execute antes python -m src.main --modo avaliar-rag")
        return False
    antes = _evidencia_do_indice(indice, nome, config)
    chamadas_antes = len(indice.embedder.chamadas)

    executar_avaliacao_rag(config, modelo=alternativo, indice=indice)

    # Falha do serviço de geração na mesma sessão, com o mesmo índice (T12)
    audit = AuditManager()
    pergunta = next(p for p in _json(config["desafio02"]["gabarito_rag"])["perguntas"] if p["id"] == "RAG-01")
    falha = AssistenteRAG(indice, cliente_de_geracao("simulado_falha", config), config, audit=audit).responder(
        pergunta["pergunta"], id_caso="T12-FALHA-SIMULADA", arquivo_origem=config["desafio02"]["gabarito_rag"])
    linha_falha = next((json.loads(l) for l in reversed(audit.arquivo_log_jsonl.read_text(encoding="utf-8").splitlines())
                        if json.loads(l).get("id_execucao") == falha.id_execucao), {})
    depois = _evidencia_do_indice(indice, nome, config)
    etapas_embedding = [c["etapa"] for c in indice.embedder.chamadas[chamadas_antes:]]
    avaliacao_alternativa = _json(f"resultados/metricas/avaliacao_rag_rf19_{_nome_de_arquivo(alternativo)}.json")

    uso = {principal: _uso_por_resposta(principal), alternativo: _uso_por_resposta(alternativo)}
    perguntas = []
    itens_alt = {i["id"]: i for i in avaliacao_alternativa["itens"]}
    for item in avaliacao_principal["itens"]:
        outro = itens_alt.get(item["id"], {})
        perguntas.append({"id": item["id"], "tipo": item["tipo"], "esperado": item["status_esperado"],
                          principal: {"status": item["status_obtido"], "confere": item["confere"], "citados": item["trechos_citados"],
                                      "alertas": len(item["alertas"]), **uso[principal].get(item["id"], {})},
                          alternativo: {"status": outro.get("status_obtido"), "confere": outro.get("confere"),
                                        "citados": outro.get("trechos_citados"), "alertas": len(outro.get("alertas") or []),
                                        **uso[alternativo].get(item["id"], {})}})

    def total(modelo: str, chave: str) -> Optional[float]:
        valores = [u[chave] for u in uso[modelo].values() if u.get(chave) is not None]
        return round(sum(valores), 6) if valores else None

    resultado = {
        "gerado_em": datetime.now().isoformat(timespec="seconds"), "modelos": [principal, alternativo],
        "indice": {"antes": antes, "depois": depois, "embeddings_nesta_execucao": etapas_embedding,
                   "preservado": antes["sha256_manifesto"] == depois["sha256_manifesto"] and antes["vetores"] == depois["vetores"]
                   and all(e.startswith("consulta") for e in etapas_embedding)},
        "agregados": {m: a["agregados"] for m, a in ((principal, avaliacao_principal), (alternativo, avaliacao_alternativa))},
        "execucao": {principal: avaliacao_principal["gerado_em"], alternativo: avaliacao_alternativa["gerado_em"]},
        "uso": {m: {"tokens": total(m, "tokens"), "custo_usd": total(m, "custo_usd"),
                    "latencia_media_ms": round(sum(u["latencia_ms"] for u in uso[m].values()) / len(uso[m]), 1) if uso[m] else None}
                for m in (principal, alternativo)},
        "perguntas": perguntas,
        "falha_simulada": {"id_caso": falha.id_caso, "status": falha.status, "codigo_motivo": falha.codigo_motivo,
                           "resposta_e_a_recusa_padronizada": falha.resposta.startswith("SEM_EVIDENCIA_SUFICIENTE:"),
                           "trechos_visiveis": len(falha.fontes), "id_execucao": falha.id_execucao,
                           "auditoria": {k: linha_falha.get(k) for k in ("sucesso", "codigo_erro", "provedor", "modelo",
                                                                          "mensagem_erro")}},
    }
    resultado["falha_simulada"]["tratada_e_auditada"] = (falha.codigo_motivo == "FALHA_NA_GERACAO"
                                                         and linha_falha.get("sucesso") is False)
    resultado["confere_t12"] = resultado["indice"]["preservado"] and resultado["falha_simulada"]["tratada_e_auditada"]
    _salvar("resultados/metricas/comparativo_geracao_rf21.json", resultado, relatorio_comparativo_md(resultado))
    print("\n" + "=" * 75)
    print(f"  Índice preservado: {'sim' if resultado['indice']['preservado'] else 'NÃO'} "
          f"({antes['vetores']} -> {depois['vetores']} vetores; embeddings só de consulta: {len(etapas_embedding)})")
    for m in (principal, alternativo):
        a = resultado["agregados"][m]
        print(f"  {m}: T08 {_fr(a['T08_respondiveis_conferem'])} | T09 {_fr(a['T09_abstencao_correta'])} | "
              f"T10 {_fr(a['T10_conflito_tratado'])} | custo US$ {resultado['uso'][m]['custo_usd']}")
    print(f"  Falha simulada: {falha.status} ({falha.codigo_motivo}) | auditada com sucesso=false: "
          f"{'sim' if resultado['falha_simulada']['tratada_e_auditada'] else 'NÃO'}")
    print("  Relatório: resultados/metricas/comparativo_geracao_rf21.md")
    print("=" * 75)
    return resultado["confere_t12"]


def relatorio_comparativo_md(r: Dict[str, Any]) -> str:
    principal, alternativo = r["modelos"]
    indice = r["indice"]
    linhas = [
        "# Segunda configuração de geração sobre o mesmo índice (RF21, T12)", "",
        f"- Gerado em {r['gerado_em']}. Execuções: {principal} em {r['execucao'][principal]}; {alternativo} em "
        f"{r['execucao'][alternativo]}. Mesmo índice, mesmo prompt (PROMPT_RAG), mesmas perguntas e mesmo limiar.",
        f"- Índice: manifesto `{indice['antes']['sha256_manifesto'][:16]}…` antes e `{indice['depois']['sha256_manifesto'][:16]}…` "
        f"depois; vetores {indice['antes']['vetores']} -> {indice['depois']['vetores']}; chamadas de embedding nesta execução: "
        f"{len(indice['embeddings_nesta_execucao'])}, todas de consulta. **Preservado: {'sim' if indice['preservado'] else 'NÃO'}.**",
        "", "## Resultado por configuração", "",
        "| Medida | " + principal + " | " + alternativo + " |", "|---|---:|---:|",
    ]
    for chave, rotulo in (("T08_respondiveis_conferem", "T08: respondíveis que conferem"),
                          ("T08_afirmacoes_essenciais_presentes", "T08: afirmações essenciais"),
                          ("T08_referencias_essenciais_citadas", "T08: referências essenciais citadas"),
                          ("T09_abstencao_correta", "T09: abstenção correta"), ("T10_conflito_tratado", "T10: conflito tratado"),
                          ("recusas_indevidas", "Recusas indevidas")):
        linhas.append(f"| {rotulo} | {_fr(r['agregados'][principal][chave])} | {_fr(r['agregados'][alternativo][chave])} |")
    for chave, rotulo in (("tokens", "Tokens de geração (9 perguntas)"), ("custo_usd", "Custo estimado (US$)"),
                          ("latencia_media_ms", "Latência média por resposta (ms)")):
        linhas.append(f"| {rotulo} | {r['uso'][principal][chave]} | {r['uso'][alternativo][chave]} |")
    linhas += ["", "## Por pergunta", "", f"| Pergunta | Esperado | {principal} | {alternativo} |", "|---|---|---|---|"]
    for p in r["perguntas"]:
        def celula(m):
            d = p[m]
            return f"{d['status']} ({'confere' if d['confere'] else 'NÃO confere'}; {d['alertas']} alerta(s))"
        linhas.append(f"| {p['id']} | {p['esperado']} | {celula(principal)} | {celula(alternativo)} |")
    falha = r["falha_simulada"]
    linhas += [
        "", "## Falha do serviço de geração (T12)", "",
        f"- Configuração simulada com falha `INDISPONIVEL`, mesmo índice: status {falha['status']} ({falha['codigo_motivo']}); "
        f"resposta é a recusa padronizada: {'sim' if falha['resposta_e_a_recusa_padronizada'] else 'não'}; trechos consultados "
        f"visíveis: {falha['trechos_visiveis']}.",
        f"- Auditoria (`{falha['id_execucao']}`): sucesso={falha['auditoria']['sucesso']}, codigo_erro="
        f"{falha['auditoria']['codigo_erro']}, provedor={falha['auditoria']['provedor']}.",
        "", "## Como ler", "",
        "- Oito perguntas não bastam para dizer que um modelo é melhor que o outro: as diferenças são indicativas e a "
        "variação entre execuções do mesmo modelo é da mesma ordem. O que o RF21 exige — trocar a geração sem "
        "reconstruir o índice e tratar a falha — é o que esta execução demonstra.",
        "- O simulado não entra na comparação de qualidade; ele só demonstra a falha controlada.",
    ]
    return "\n".join(linhas) + "\n"


# ------------------------------------------------------------------------------
# T13: agregação com filtro, duplicata e conjunto vazio sobre os rótulos reais
# ------------------------------------------------------------------------------
def executar_t13() -> Dict[str, Any]:
    from src import metrics
    from src.sentiment import arquivo_de_rotulos_mais_recente, carregar_rotulos

    arquivo = arquivo_de_rotulos_mais_recente()
    if arquivo is None:
        return {"confere": None, "motivo": "Sem rótulos gravados (python -m src.main --modo sentimentos)."}
    df = carregar_rotulos(arquivo)
    geral = metrics.indicadores(df)["polaridade"]
    canal = df["canal"].value_counts().index[0]
    filtro = metrics.indicadores(df, canais=[canal])["polaridade"]
    repetida = df.iloc[[0]].assign(classificado_em="9999-12-31T23:59:59")
    duplicado = metrics.indicadores(pd.concat([df, repetida], ignore_index=True))
    vazio = metrics.indicadores(df, canais=["canal-inexistente"])
    resultado = {
        "arquivo_rotulos": arquivo.relative_to(RAIZ_PROJETO).as_posix(),
        "geral": {"denominador": geral["denominador"], "soma": sum(c["n"] for c in geral["categorias"]),
                  "percentual_exibido": geral["percentual_exibido"]},
        "filtro": {"canal": canal, "denominador": filtro["denominador"], "esperado": int((df["canal"] == canal).sum()),
                   "soma": sum(c["n"] for c in filtro["categorias"]), "percentual_exibido": filtro["percentual_exibido"],
                   "motivo_sem_percentual": filtro["motivo_sem_percentual"]},
        "duplicata": {"duplicatas_removidas": duplicado["ficha_tecnica"]["duplicatas_removidas"],
                      "denominador": duplicado["polaridade"]["denominador"]},
        "vazio": {"denominador": vazio["polaridade"]["denominador"],
                  "percentuais": [c["percentual"] for c in vazio["polaridade"]["categorias"]],
                  "motivo_sem_percentual": vazio["polaridade"]["motivo_sem_percentual"]},
    }
    resultado["confere"] = (resultado["geral"]["denominador"] == resultado["geral"]["soma"] == len(df)
                            and resultado["filtro"]["denominador"] == resultado["filtro"]["esperado"] == resultado["filtro"]["soma"]
                            and resultado["filtro"]["percentual_exibido"] == (resultado["filtro"]["esperado"] >= metrics.MINIMO_PARA_PERCENTUAL)
                            and resultado["duplicata"] == {"duplicatas_removidas": 1, "denominador": len(df)}
                            and resultado["vazio"]["denominador"] == 0 and not any(resultado["vazio"]["percentuais"]))
    return resultado


# ------------------------------------------------------------------------------
# Matriz T01–T15 e métricas do RF23
# ------------------------------------------------------------------------------
def _linha(id_teste: str, requisito: str, impresso: str, cenario: str, entrada: str, esperado: str, obtido: str,
           situacao: str, evidencias: List[str], executado_em: Optional[str], observacao: str = "") -> Dict[str, Any]:
    return {"id": id_teste, "requisito": requisito, "requisito_impresso_no_enunciado": impresso, "cenario": cenario,
            "entrada": entrada, "esperado": esperado, "obtido": obtido, "situacao": situacao, "evidencias": evidencias,
            "executado_em": executado_em, "observacao": observacao}


def _sem_evidencia(id_teste, requisito, impresso, cenario, entrada, esperado, comando, evidencia) -> Dict[str, Any]:
    return _linha(id_teste, requisito, impresso, cenario, entrada, esperado, "não localizado", PENDENTE, [evidencia], None,
                  f"Sem evidência gravada: execute {comando}.")


def montar_matriz(config: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    from src.rag import _nome_de_arquivo

    principal = config["llm"]["openai"]["modelo_padrao"]
    linhas: List[Dict[str, Any]] = []

    # T01 e T02 (RF14)
    arq = "resultados/metricas/comparativo_json_esquema_rf14.json"
    c = _json(arq)
    if c:
        payloads = [p["confere"] for p in c["payloads_sinteticos"]]
        variantes = {v["variante"]: v for v in c["variantes"]}
        estruturado = variantes.get("structured_outputs_contrato", {})
        generico = variantes.get("json_object_instrucao_generica", {})
        ok = all(payloads) and estruturado.get("valido_no_contrato") and not generico.get("valido_no_contrato")
        linhas.append(_linha(
            "T01", "RF14", "RF15", "JSON válido com tipo incorreto e campo ausente", "SOL-01 e 4 payloads sintéticos",
            "Rejeição do esquema ou ausência explícita; nenhuma minuta inválida",
            f"Payloads com o erro esperado: {sum(payloads)}/{len(payloads)}; JSON Mode genérico: JSON válido e fora do contrato "
            f"({generico.get('erros_por_codigo')}); Structured Outputs: válido no contrato",
            CONFERE if ok else NAO_CONFERE, [arq, "dados/solicitacoes/casos_negativos_t01_t02.json"], _quando(arq)))
    else:
        linhas.append(_sem_evidencia("T01", "RF14", "RF15", "JSON válido com tipo incorreto e campo ausente", "SOL-01",
                                     "Rejeição do esquema", "python -m src.main --modo avaliar-nlp", arq))
    arq = "resultados/nlp/t02_regras_negocio.json"
    t02 = _json(arq)
    if t02:
        linhas.append(_linha(
            "T02", "RF14", "RF15", "Data impossível ou dado não presente no original", "T02-A (31/02/2026) e T02-B",
            "Regra de negócio bloqueia e solicita revisão",
            "; ".join(f"{c['id']}: {c['decisao_obtida']} ({', '.join(c['alertas_obtidos'])})" for c in t02),
            CONFERE if all(c["confere"] for c in t02) else NAO_CONFERE, [arq], _quando(arq)))
    else:
        linhas.append(_sem_evidencia("T02", "RF14", "RF15", "Data impossível", "T02-A, T02-B", "Bloqueio e revisão",
                                     "python -m src.main --modo avaliar-nlp", arq))

    # T03 (RF15)
    arq = "resultados/metricas/avaliacao_nlp_rf15.json"
    nlp = _json(arq)
    if nlp:
        a = nlp["agregados"]
        completos = all(_completo(a[k]) for k in ("acuracia_categoria", "campos_exatos_corretos", "fatos_essenciais_preservados",
                                                   "resumos_no_limite_de_100_palavras", "decisoes_corretas"))
        conferencia = _json("resultados/nlp/conferencia_humana_rf15.json") or {}
        linhas.append(_linha(
            "T03", "RF15", "RF16", "Seis solicitações com gabarito", "SOL-01 a SOL-06",
            "Resumo fiel, categoria e entidades avaliados",
            f"Categoria {_fr(a['acuracia_categoria'])}; campos exatos {_fr(a['campos_exatos_corretos'])}; fatos essenciais "
            f"{_fr(a['fatos_essenciais_preservados'])}; resumos até 100 palavras {_fr(a['resumos_no_limite_de_100_palavras'])}; "
            f"entidades omitidas {_fr(a['entidades_omitidas'])}; decisões {_fr(a['decisoes_corretas'])}",
            CONFERE if completos else RESSALVA, [arq, "resultados/metricas/avaliacao_nlp_rf15.md"], _quando(arq, nlp),
            "Conferência humana do resumo: " + ("registrada" if conferencia.get("revisado_por") else "PENDENTE")
            + " (resultados/nlp/conferencia_humana_rf15.json)."))
    else:
        linhas.append(_sem_evidencia("T03", "RF15", "RF16", "Seis solicitações", "SOL-01 a SOL-06", "Avaliados",
                                     "python -m src.main --modo avaliar-nlp", arq))

    # T04 e T05 (RF16)
    arq = "resultados/guardrails/avaliacao_guardrails_rf16.json"
    g = _json(arq)
    if g:
        a = g["agregados"]
        linhas.append(_linha(
            "T04", "RF16", "RF17", "Três entradas adversariais", "ATK-01 (solicitação), ATK-02 (acervo), ATK-03 (segredo)",
            "Instruções não executadas e segredo não revelado",
            f"Ataques contidos {_fr(a['ataques_contidos'])}; variantes {_fr(a['variantes_contidas'])}; legítimas permitidas "
            f"{_fr(a['legitimas_permitidas'])}; filtro de saída {_fr(a['camada3_exemplos_conferem'])}",
            CONFERE if all(_completo(a[k]) for k in ("ataques_contidos", "variantes_contidas", "legitimas_permitidas")) else NAO_CONFERE,
            [arq, "resultados/guardrails/avaliacao_guardrails_rf16.md"], _quando(arq, g)))
        linhas.append(_linha(
            "T05", "RF16", "RF16", "Fora de escopo, arquivo excessivo e limite de chamadas",
            "2 pedidos fora de escopo; arquivo acima de 10 MB; teto de chamadas e tokens", "Bloqueio ou revisão e limite respeitado",
            f"Fora de escopo contido {_fr(a['fora_de_escopo_contido'])}; limites {_fr(a['limites_t05_respeitados'])}; orçamento "
            f"{a['orcamento']['chamadas']}/{a['orcamento']['max_chamadas']} chamadas",
            CONFERE if _completo(a["fora_de_escopo_contido"]) and _completo(a["limites_t05_respeitados"]) else NAO_CONFERE,
            [arq], _quando(arq, g)))
    else:
        for t, imp, cen in (("T04", "RF17", "Três entradas adversariais"), ("T05", "RF16", "Fora de escopo e limites")):
            linhas.append(_sem_evidencia(t, "RF16", imp, cen, "-", "-", "python -m src.main --modo avaliar-guardrails", arq))

    # T06 (RF17)
    arq = "resultados/indice/indexacoes.jsonl"
    caminho = RAIZ_PROJETO / arq
    execucoes = [json.loads(l) for l in caminho.read_text(encoding="utf-8").splitlines()] if caminho.exists() else []
    reuso = next((e for e in reversed(execucoes) if e["situacao_inicial"] == "COMPATIVEL" and e["chamadas_de_embedding"] == 0
                  and e["vetores_na_colecao"] == e["vetores_no_manifesto"]), None)
    linhas.append(_linha(
        "T06", "RF17", "RF17", "Reinício e reindexação do mesmo acervo", "Acervo principal (DOC-01 a DOC-06, DOC-99)",
        "Índice reutilizado e sem duplicação",
        f"Execução de {reuso['executado_em']}: {len(reuso['reutilizados'])} documento(s) reutilizado(s), 0 chamadas de embedding, "
        f"{reuso['vetores_na_colecao']} vetores = manifesto" if reuso else "não localizado",
        CONFERE if reuso else PENDENTE, [arq, "indice/manifesto_indice.json"], reuso["executado_em"] if reuso else None,
        "" if reuso else "Execute python -m src.main --modo indexar duas vezes."))

    # T07 (RF18)
    arq = "resultados/metricas/comparacao_chunking_rf18.json"
    ch = _json(arq)
    if ch:
        escolhida = config["chunking"].get("configuracao_principal")
        resumo = "; ".join(f"{k} ({v['parametros']['tamanho']}/{v['parametros']['sobreposicao']}): acerto {_fr(v['acerto_recuperacao'])}, "
                           f"MRR {v['mrr']}" for k, v in ch["configuracoes"].items())
        linhas.append(_linha(
            "T07", "RF18", "RF18", "Duas configurações e cinco perguntas", "RAG-01 a RAG-05, mesmo embedding e top-k",
            "Top-k comparado e acerto calculado", f"{resumo}; escolhida: {escolhida}",
            CONFERE if escolhida else PENDENTE, [arq, "resultados/metricas/comparacao_chunking_rf18.md"], _quando(arq, ch)))
    else:
        linhas.append(_sem_evidencia("T07", "RF18", "RF18", "Duas configurações", "RAG-01 a RAG-05", "Acerto calculado",
                                     "python -m src.main --modo experimento-chunking", arq))

    # T08 a T10 (RF19) e controle do T14
    arq = f"resultados/metricas/avaliacao_rag_rf19_{_nome_de_arquivo(principal)}.json"
    rag = _json(arq)
    if rag:
        a = rag["agregados"]
        falhas = [i for i in rag["itens"] if i["tipo"] == "respondivel" and not i["confere"]]
        detalhe = "; ".join(f"{i['id']}: fontes exigidas {i['fontes_exigidas']}, citadas {i['documentos_citados']}"
                            if not i["fontes_exigidas_citadas"] else f"{i['id']}: {i['codigo_motivo']}" for i in falhas)
        situacao_t08 = CONFERE if _completo(a["T08_respondiveis_conferem"]) else (
            RESSALVA if _completo(a["T08_status_fundamentada"]) else NAO_CONFERE)
        sustentacao = _json("resultados/metricas/conferencia_sustentacao_rag.json") or {}
        linhas.append(_linha(
            "T08", "RF19", "RF19", "Cinco perguntas respondíveis", "RAG-01 a RAG-05",
            "Respostas e citações verificadas contra fontes",
            f"Conferem {_fr(a['T08_respondiveis_conferem'])}; FUNDAMENTADA {_fr(a['T08_status_fundamentada'])}; afirmações essenciais "
            f"{_fr(a['T08_afirmacoes_essenciais_presentes'])}; referências essenciais citadas {_fr(a['T08_referencias_essenciais_citadas'])}"
            + (f"; falha: {detalhe}" if detalhe else ""),
            situacao_t08, [arq, f"resultados/rag/respostas/{_nome_de_arquivo(principal)}/"], _quando(arq, rag),
            "Sustentação de cada afirmação contra a passagem citada: " + ("conferida pela equipe" if sustentacao.get("revisado_por")
                                                                          else "conferência humana PENDENTE")
            + " (resultados/metricas/conferencia_sustentacao_rag.json)."))
        linhas.append(_linha(
            "T09", "RF19", "RF19", "Duas perguntas sem evidência", "RAG-06, RAG-07", "Abstenção e encaminhamento ao operador",
            f"Abstenção correta {_fr(a['T09_abstencao_correta'])} (recusa padronizada exata, PENDENTE_REVISAO_HUMANA)",
            CONFERE if _completo(a["T09_abstencao_correta"]) else NAO_CONFERE, [arq], _quando(arq, rag)))
        conflito = next((i for i in rag["itens"] if i["tipo"] == "contraditoria"), {})
        linhas.append(_linha(
            "T10", "RF19", "RF19", "Fontes contraditórias", "RAG-08 (DOC-04: 5 dias úteis x DOC-05: 15 dias corridos)",
            "Prioridade documentada ou conflito e revisão",
            f"{conflito.get('status_obtido')}; documentos expostos: {conflito.get('documentos_nas_divergencias')}; "
            f"conflito tratado {_fr(a['T10_conflito_tratado'])}. Prioridade documentada (DOC-02 sobre DOC-01) aplicada na RAG-01.",
            CONFERE if _completo(a["T10_conflito_tratado"]) else NAO_CONFERE, [arq], _quando(arq, rag)))
    else:
        for t, cen in (("T08", "Cinco respondíveis"), ("T09", "Duas sem evidência"), ("T10", "Fontes contraditórias")):
            linhas.append(_sem_evidencia(t, "RF19", "RF19", cen, "-", "-", "python -m src.main --modo avaliar-rag", arq))

    # T11 (RF20, RF24): decisões reais do operador na interface
    decisoes = _json(ARQ_DECISOES_D02) or []
    ultimas: Dict[str, Dict[str, Any]] = {}
    for d in sorted(decisoes, key=lambda d: d.get("registrado_em", "")):
        ultimas[d["caso_id"]] = d
    estados = [d["estado"] for d in ultimas.values()]
    tem_aprovada = "APROVADA" in estados
    tem_outra = any(e in ("REJEITADA", "REVISAR") for e in estados)
    linhas.append(_linha(
        "T11", "RF20/RF24", "RF20/RF24", "Aprovação e rejeição na interface", "Fila de minutas (streamlit run src/app.py)",
        "Estados e justificativas persistidos; sem envio automático",
        f"{len(decisoes)} decisão(ões) do operador: " + (", ".join(f"{e} {estados.count(e)}" for e in sorted(set(estados))) or "nenhuma")
        + f"; envio automático bloqueado em todas: {'sim' if all(d.get('envio_automatico_bloqueado') for d in decisoes) else 'NÃO'}",
        CONFERE if tem_aprovada and tem_outra else PENDENTE, [ARQ_DECISOES_D02, "testes/test_app_streamlit.py"],
        max((d["registrado_em"] for d in decisoes), default=None),
        "" if tem_aprovada and tem_outra else "Ação humana pendente: aprovar ao menos uma minuta e rejeitar ou mandar para "
        "revisão outra, pela interface. Os testes automatizados do T11 (aprovar e rejeitar pelos widgets) passam."))

    # T12 (RF21)
    arq = "resultados/metricas/comparativo_geracao_rf21.json"
    cg = _json(arq)
    if cg:
        linhas.append(_linha(
            "T12", "RF21", "RF21", "Troca de geração e falha do serviço", f"8 perguntas do RAG em {' e '.join(cg['modelos'])}; simulado com falha",
            "Índice preservado; falha tratada e auditada",
            f"Índice preservado: {'sim' if cg['indice']['preservado'] else 'NÃO'} ({cg['indice']['antes']['vetores']} vetores, manifesto "
            f"inalterado); falha: {cg['falha_simulada']['status']} ({cg['falha_simulada']['codigo_motivo']}), auditada com "
            f"sucesso={cg['falha_simulada']['auditoria']['sucesso']}",
            CONFERE if cg["confere_t12"] else NAO_CONFERE, [arq, "resultados/metricas/comparativo_geracao_rf21.md"], _quando(arq, cg)))
    else:
        linhas.append(_sem_evidencia("T12", "RF21", "RF21", "Troca de geração e falha", "-", "Índice preservado",
                                     "python -m src.main --modo comparar-geracao", arq))

    # T13 (RF23), executado agora
    t13 = executar_t13()
    if t13["confere"] is None:
        linhas.append(_sem_evidencia("T13", "RF23", "RF23", "Filtro, duplicata e conjunto vazio", "-", "-",
                                     "python -m src.main --modo sentimentos", "resultados/sentimentos/"))
    else:
        _salvar("resultados/metricas/t13_agregacao.json", t13)
        linhas.append(_linha(
            "T13", "RF23", "RF23", "Filtro, duplicata e conjunto vazio", f"Rótulos reais ({t13['arquivo_rotulos']})",
            "Totais corretos, denominador visível e sem divisão por zero",
            f"Geral {t13['geral']['soma']}/{t13['geral']['denominador']}; canal {t13['filtro']['canal']}: "
            f"{t13['filtro']['soma']}/{t13['filtro']['denominador']} sem percentual ({t13['filtro']['motivo_sem_percentual']}); "
            f"duplicata removida {t13['duplicata']['duplicatas_removidas']} com total {t13['duplicata']['denominador']}; vazio: "
            f"denominador {t13['vazio']['denominador']}, sem percentual",
            CONFERE if t13["confere"] else NAO_CONFERE, ["resultados/metricas/t13_agregacao.json", "testes/test_metricas_t13.py"],
            datetime.now().isoformat(timespec="seconds")))

    # T14 (RF24)
    arq = "resultados/indice/exclusao_t14.json"
    ex = _json(arq)
    manifesto = _json("indice/manifesto_indice.json") or {"colecoes": {}}
    exclusoes = manifesto["colecoes"].get(config["indice"].get("colecao_principal", "acervo_principal"), {}).get("exclusoes", [])
    controle = (rag or {}).get("controle_t14") or {}
    if ex:
        vigente = any(e["doc_id"] == ex["doc_id"] and not e.get("reincluido_em") for e in exclusoes)
        linhas.append(_linha(
            "T14", "RF24", "RF24", "Exclusão de documento e derivados", f"{ex['doc_id']} (informativo temporário)",
            "Trechos removidos da busca e exclusão registrada",
            f"Antes: recuperado; removidos {sum(ex['exclusao']['vetores_removidos_por_colecao'].values())} vetores; depois: "
            f"{ex['depois']['trechos_do_documento_no_top_k']} trecho(s) no top-k; reindexação automática ignorou "
            f"{ex['reindexacao_automatica']['ignorados_por_exclusao']}; exclusão vigente no manifesto: {'sim' if vigente else 'não'}; "
            f"RAG depois da exclusão: {controle.get('status_obtido', 'não executado')}",
            CONFERE if ex["confere"] and vigente and controle.get("confere", True) else NAO_CONFERE,
            [arq, "resultados/indice/exclusao_t14.md", "indice/manifesto_indice.json"], _quando(arq)))
    else:
        linhas.append(_sem_evidencia("T14", "RF24", "RF24", "Exclusão de documento", "DOC-99", "Removido",
                                     "python -m src.main --modo demonstrar-exclusao", arq))

    # T15 (RF23)
    arq = "resultados/metricas/regressao_t15.json"
    rg = _json(arq)
    if rg:
        texto, ocr = rg["texto"], rg["ocr"]
        linhas.append(_linha(
            "T15", "RF23", "RF23", "Regressão textual e OCR", "entrada_texto.txt e entrada_pdf-imagem.pdf (Desafio 01)",
            "Entradas anteriores seguem até minuta e revisão",
            f"Texto: minuta {'sim' if texto['chegou_a_minuta'] else 'não'}, revisão {texto['revisao']['decisao'] or 'não'}"
            f"{' (simulada)' if rg['decisoes_simuladas'] else ''}, extração {_fr(texto['acerto_extracao_gabarito'])}; OCR: leitura "
            f"{_fr(ocr.get('acerto_leitura_gabarito'))}, {ocr.get('etapa_final')}, fila {ocr.get('estado_na_fila') or 'fora'}",
            (CONFERE if not rg["decisoes_simuladas"] else RESSALVA) if rg["confere"] else NAO_CONFERE,
            [arq, rg["pasta_de_evidencias"] + "/"], _quando(arq, rg),
            "A revisão do texto foi simulada (--demo-avaliacao-humana); para a decisão humana, rode python -m src.main --modo "
            "regressao no terminal." if rg["decisoes_simuladas"] else ""))
    else:
        linhas.append(_sem_evidencia("T15", "RF23", "RF23", "Regressão textual e OCR", "Desafio 01", "Até minuta e revisão",
                                     "python -m src.main --modo regressao", arq))

    return linhas, metricas_rf23(config, nlp, ch, rag, t13)


def metricas_rf23(config: Dict[str, Any], nlp, chunking, rag, t13) -> Dict[str, Any]:
    """Medidas formais do RF23, sempre com numerador e denominador."""
    institucionais = [i for i in (rag or {}).get("itens", []) if i["tipo"] != "sem_resposta"
                      and i["status_obtido"] != "SEM_EVIDENCIA_SUFICIENTE"]
    automatica = {"numerador": sum(i["afirmacoes_do_modelo"] > 0 and i["afirmacoes_com_citacao"] == i["afirmacoes_do_modelo"]
                                   and i["afirmacoes_com_numeros_no_trecho_citado"] == i["afirmacoes_do_modelo"] for i in institucionais),
                  "denominador": len(institucionais)}
    conferencia = _json("resultados/metricas/conferencia_sustentacao_rag.json") or {"casos": []}
    casos = [c for c in conferencia["casos"] if c["status"] != "SEM_EVIDENCIA_SUFICIENTE"]
    afirmacoes = [a for c in casos for a in c["afirmacoes"]]
    conferidas = [a for a in afirmacoes if a.get("sustentada") is not None]
    humana = ({"numerador": sum(all(a["sustentada"] for a in c["afirmacoes"]) for c in casos), "denominador": len(casos)}
              if afirmacoes and len(conferidas) == len(afirmacoes) else None)
    sentimentos = _json("resultados/metricas/avaliacao_sentimentos_rf22.json")
    escolhida = config["chunking"].get("configuracao_principal")
    return {
        "acuracia_de_categorias": (nlp or {}).get("agregados", {}).get("acuracia_categoria"),
        "acerto_de_recuperacao": (chunking or {}).get("configuracoes", {}).get(escolhida, {}).get("acerto_recuperacao"),
        "configuracao_de_chunking": escolhida,
        "respostas_institucionais_sustentadas": {
            "verificacao_automatica": automatica,
            "criterio_automatico": "toda afirmação da resposta cita trecho e todos os números dela estão no trecho citado",
            "conferencia_humana": humana,
            "conferencia_humana_situacao": "concluída" if humana else f"PENDENTE: {len(conferidas)} de {len(afirmacoes)} afirmações conferidas",
        },
        "abstencao_correta_sem_resposta": (rag or {}).get("agregados", {}).get("T09_abstencao_correta"),
        "caso_contraditorio": next(({"id": i["id"], "status": i["status_obtido"], "confere": i["confere"],
                                     "documentos": i.get("documentos_nas_divergencias")}
                                    for i in (rag or {}).get("itens", []) if i["tipo"] == "contraditoria"), None),
        "sentimentos": {"acuracia_polaridade": sentimentos["agregados"]["acuracia_polaridade"],
                        "revisao_esperada_sinalizada": sentimentos["agregados"]["revisao_esperada_sinalizada"],
                        "ambiguos_e_divergentes": [{"id": i["id"], "gabarito": i["polaridade_esperada"], "modelo": i["polaridade_obtida"],
                                                    "justificativa_gabarito": i["justificativa_gabarito"]}
                                                   for i in sentimentos["itens"]
                                                   if i["ambiguidade_esperada"] == "limitrofe" or not i["polaridade_confere"]]}
        if sentimentos else None,
        "t13_agregacao": t13.get("confere"),
    }


def relatorio_matriz_md(linhas: List[Dict[str, Any]], metricas: Dict[str, Any], gerado_em: str) -> str:
    contagem = pd.Series([l["situacao"] for l in linhas]).value_counts()
    saida = [
        "# Matriz de testes T01–T15 e métricas do RF23", "",
        f"- Consolidada em {gerado_em} por `python -m src.main --modo avaliacao-integrada`, a partir das evidências gravadas por "
        "cada modo (coluna Evidência). Os resultados de referência (gabaritos) foram elaborados antes das chamadas ao modelo.",
        "- Situação: " + " · ".join(f"{s}: {int(contagem.get(s, 0))}" for s in (CONFERE, RESSALVA, NAO_CONFERE, PENDENTE)),
        "- **Nota sobre a numeração do enunciado:** na tabela da Seção 11, T01 a T04 aparecem rotulados como RF15, RF15, RF16 e "
        "RF17. Pelo cenário de cada um (JSON e esquema, regra de negócio, seis solicitações, entradas adversariais), os "
        "requisitos são RF14, RF14, RF15 e RF16; a coluna Impresso guarda o rótulo original.", "",
        "| ID | Requisito | Impresso | Cenário | Esperado | Obtido | Situação | Evidência | Executado em |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for l in linhas:
        obtido = l["obtido"].replace("|", "/") + (f" — {l['observacao']}" if l["observacao"] else "")
        saida.append(f"| {l['id']} | {l['requisito']} | {l['requisito_impresso_no_enunciado']} | {l['cenario']} | {l['esperado']} | "
                     f"{obtido} | **{l['situacao']}** | {'<br>'.join(f'`{e}`' for e in l['evidencias'])} | {l['executado_em'] or '-'} |")
    m = metricas
    sustentacao = m["respostas_institucionais_sustentadas"]
    saida += [
        "", "## Métricas do RF23 (numerador / denominador)", "",
        f"- Acurácia de categorias (6 solicitações): **{_fr(m['acuracia_de_categorias'])}**",
        f"- Acerto de recuperação (configuração {m['configuracao_de_chunking']}, 5 perguntas respondíveis, top-k): "
        f"**{_fr(m['acerto_de_recuperacao'])}**",
        f"- Respostas institucionais com todas as afirmações sustentadas — verificação automática ({sustentacao['criterio_automatico']}): "
        f"**{_fr(sustentacao['verificacao_automatica'])}**; conferência humana: "
        f"**{_fr(sustentacao['conferencia_humana']) if sustentacao['conferencia_humana'] else sustentacao['conferencia_humana_situacao']}**",
        f"- Abstenção correta nas perguntas sem resposta: **{_fr(m['abstencao_correta_sem_resposta'])}**",
    ]
    if m["caso_contraditorio"]:
        c = m["caso_contraditorio"]
        saida.append(f"- Caso contraditório, registrado à parte: {c['id']} -> {c['status']} com {c['documentos']} expostos "
                     f"({'confere' if c['confere'] else 'NÃO confere'})")
    if m["sentimentos"]:
        s = m["sentimentos"]
        saida.append(f"- Sentimentos contra o gabarito: polaridade **{_fr(s['acuracia_polaridade'])}**; casos para revisão "
                     f"sinalizados {_fr(s['revisao_esperada_sinalizada'])}. Ambíguos e divergentes:")
        saida += [f"  - {a['id']}: gabarito {a['gabarito']}, modelo {a['modelo']} — {a['justificativa_gabarito']}"
                  for a in s["ambiguos_e_divergentes"]]
    saida += [
        "", "## Falhas, correções e riscos residuais", "",
        "- Falhas medidas aparecem como CONFERE_COM_RESSALVA ou NAO_CONFERE, com o que faltou na coluna Obtido; nada foi ajustado "
        "nos gabaritos depois da execução. As correções feitas durante o desenvolvimento e as execuções anteriores preservadas "
        "estão em `resultados/metricas/historico/` e no relatório técnico.",
        "- PENDENTE indica ação humana (decisões na interface, conferências) ou evidência ainda não gerada.",
        "- Riscos residuais: corpus pequeno e sintético; variação entre execuções do modelo; marcadores e trechos literais são "
        "conferência indicativa; a sustentação definitiva de cada afirmação depende da leitura humana.",
    ]
    return "\n".join(saida) + "\n"


def executar_avaliacao_integrada(config: Dict[str, Any], reexecutar: bool = False) -> bool:
    """--modo avaliacao-integrada: consolida a matriz T01–T15 e as métricas do RF23 (sem chamada a modelo)."""
    if reexecutar:
        from src.embeddings import executar_indexacao
        from src.guardrails import executar_avaliacao_guardrails
        from src.nlp import executar_avaliacao_nlp
        from src.rag import executar_avaliacao_rag
        from src.sentiment import executar_classificacao_sentimentos
        for etapa in (executar_avaliacao_nlp, executar_avaliacao_guardrails, executar_indexacao, executar_indexacao,
                      executar_avaliacao_rag, executar_classificacao_sentimentos, executar_comparativo_geracao):
            etapa(config)
    print("=" * 75)
    print("  AVALIAÇÃO INTEGRADA: MATRIZ T01–T15 E MÉTRICAS DO RF23")
    print("=" * 75)
    linhas, metricas = montar_matriz(config)
    gerado_em = datetime.now().isoformat(timespec="seconds")
    _salvar("documentacao/matriz_testes_rf23.json", {"gerado_em": gerado_em, "testes": linhas, "metricas_rf23": metricas},
            relatorio_matriz_md(linhas, metricas, gerado_em))
    for l in linhas:
        print(f"  {l['id']} ({l['requisito']}): {l['situacao']}" + (f" — {l['observacao']}" if l["situacao"] == PENDENTE else ""))
    print(f"\n  Matriz: documentacao/matriz_testes_rf23.md | métricas do RF23 no mesmo arquivo")
    print("=" * 75)
    return not any(l["situacao"] == NAO_CONFERE for l in linhas)
