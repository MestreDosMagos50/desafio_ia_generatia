#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
==============================================================================
ASSISTENTE DE DOCUMENTOS E PAINEL — INTERFACE STREAMLIT (RF20, RF21, RF22, RF24)
==============================================================================
Execução: streamlit run src/app.py
- Acervo e índice: situação de cada documento (aviso de índice desatualizado),
  reindexação idempotente, inclusão de .txt/.pdf, busca top-k com a
  similaridade explicada e exclusão auditada (RF24, T14).
- Atendimento e revisão: solicitação de teste ou digitada -> guardrails ->
  contrato ("não localizado" nas ausências) -> ficha -> minuta com trechos
  consultados sempre visíveis, inclusive na recusa; fila de minutas com
  decisão do operador e justificativa (T11). O envio é sempre manual.
- Painel de sentimentos: ficha técnica no topo, filtros determinísticos,
  contagens com denominador (percentual só com base >= 10) e fila de revisão;
  nenhuma chamada de API (Aula 14 §6).
- Provedor e auditoria: troca da geração sem reconstruir o índice (T12),
  registros sanitizados, uso por modelo e relatórios de métricas.
Cada consulta é independente: não há memória conversacional (Aula 15 fora do
escopo). Objetos caros ficam em st.cache_resource; o estado da tela, em
st.session_state.
==============================================================================
"""

import json
import sys
from pathlib import Path

RAIZ_PROJETO = Path(__file__).resolve().parent.parent
if str(RAIZ_PROJETO) not in sys.path:
    sys.path.insert(0, str(RAIZ_PROJETO))

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from src import metrics  # noqa: E402
from src.atendimento import (  # noqa: E402
    cliente_de_geracao, configuracoes_de_geracao, indexar_documento_enviado, minutas_para_revisao, processar_atendimento,
    registrar_decisao, registros_de_auditoria, resumo_de_uso, situacao_do_acervo,
)
from src.audit import AuditManager  # noqa: E402
from src.embeddings import (  # noqa: E402
    EXPLICACAO_SIMILARIDADE, chunking_principal, diagnosticar_indice, documentos_do_indice_principal, preparar_indice,
)
from src.guardrails import Guardrails  # noqa: E402
from src.rag import SEM_EVIDENCIA  # noqa: E402
from src.sentiment import arquivo_de_rotulos_mais_recente, carregar_rotulos  # noqa: E402

ESTADOS_DECISAO = ["APROVADA", "REJEITADA", "REVISAR", "PENDENTE"]

st.set_page_config(page_title="Central de Atendimento — Desafio 02", layout="wide")
config = json.loads((RAIZ_PROJETO / "config.json").read_text(encoding="utf-8"))
COLECAO = config["indice"].get("colecao_principal", "acervo_principal")
CONFIGURACOES = configuracoes_de_geracao(config)


# ------------------------------------------------------------------------------
# Recursos compartilhados (criados uma vez por processo)
# ------------------------------------------------------------------------------
@st.cache_resource
def obter_audit() -> AuditManager:
    return AuditManager()


@st.cache_resource
def obter_indice():
    """Índice com embeddings da OpenAI; (None, motivo) sem chave. Não muda quando a geração é trocada (T12)."""
    return preparar_indice(config)


@st.cache_resource
def obter_cliente(chave: str):
    return cliente_de_geracao(chave, config)


@st.cache_resource
def obter_guardrails() -> Guardrails:
    """Camada de segurança sempre no cliente principal; trocar a geração não a enfraquece."""
    return Guardrails(llm_client=obter_cliente("principal"), audit=obter_audit())


def ler_json(relativo: str):
    caminho = RAIZ_PROJETO / relativo
    return json.loads(caminho.read_text(encoding="utf-8")) if caminho.exists() else None


def mostrar_fontes(rag: dict):
    """Painel de trechos em toda resposta, inclusive na recusa (Aula 13 §7.4)."""
    fontes = rag.get("fontes") or []
    if not fontes:
        st.warning("Nenhum trecho do acervo foi recuperado para esta resposta.")
        return
    rotulo = ("Trechos consultados (nenhum sustenta a resposta)" if rag["status"] == SEM_EVIDENCIA
              else "Fontes citadas e trechos consultados")
    with st.expander(f"{rotulo} — {len(fontes)} trecho(s)"):
        st.caption(EXPLICACAO_SIMILARIDADE)
        for f in fontes:
            similaridade = f"{f['similaridade_cosseno']:.4f}" if f.get("similaridade_cosseno") is not None else "—"
            st.markdown(f"**[{f['n']}] {f['rotulo']}** · {f['titulo']} · origem: {f['origem']} · similaridade "
                        f"{similaridade} · {'**citado**' if f['citado'] else 'não citado'}")
            st.text(f["trecho"])
            st.divider()


def mostrar_minuta(rag: dict):
    st.markdown(f"**Status:** `{rag['status']}` · **Encaminhamento:** `{rag['encaminhamento']}` · "
                f"**Revisão:** `{rag['status_revisao']}` · envio automático bloqueado")
    for alerta in rag.get("alertas") or []:
        st.warning(alerta)
    st.text(rag["minuta"])
    mostrar_fontes(rag)


st.session_state.setdefault("config_geracao", "principal")
audit = obter_audit()
indice, motivo_indice = obter_indice()

with st.sidebar:
    st.header("Central de Atendimento")
    st.caption("ETEC Cuiabá (fictícia) · Desafio 02 · todos os dados são fictícios")
    st.selectbox("Configuração de geração (RF21)", list(CONFIGURACOES), key="config_geracao",
                 format_func=lambda chave: CONFIGURACOES[chave]["rotulo"])
    cliente = obter_cliente(st.session_state["config_geracao"])
    if cliente.disponivel:
        st.success(f"Geração: {cliente.provedor} / {cliente.modelo}")
    else:
        st.error(f"Geração indisponível: {cliente.motivo_indisponibilidade}")
    if CONFIGURACOES[st.session_state["config_geracao"]]["provedor"] == "simulado":
        st.info("Simulado: não lê o texto, não inventa dados e manda tudo para revisão. Sem equivalência de qualidade.")
    st.caption("Cada consulta é independente; não há memória de conversa.")

aba_acervo, aba_atendimento, aba_sentimentos, aba_auditoria = st.tabs(
    ["Acervo e índice", "Atendimento e revisão", "Painel de sentimentos", "Provedor e auditoria"])

# ------------------------------------------------------------------------------
# Aba 1: acervo e índice
# ------------------------------------------------------------------------------
with aba_acervo:
    situacao, detalhe = diagnosticar_indice(config)
    documentos = situacao_do_acervo(config)
    pendentes = [d["doc_id"] for d in documentos if d["situacao"] in ("DESATUALIZADO", "NAO_INDEXADO")]
    if situacao != "COMPATIVEL":
        st.error(f"Índice {situacao}: {detalhe} Use o botão de reindexação abaixo.")
    elif pendentes:
        st.warning(f"Índice desatualizado: {', '.join(pendentes)} mudou ou ainda não foi indexado. Reindexe o acervo.")
    else:
        st.success(f"Índice {situacao}: {detalhe}")
    if indice is None:
        st.info(f"Busca, indexação e exclusão indisponíveis: {motivo_indice}")
    st.dataframe(pd.DataFrame(documentos), hide_index=True, width="stretch")

    coluna_indexar, coluna_enviar = st.columns(2)
    with coluna_indexar:
        st.subheader("Reindexar o acervo")
        st.caption("Idempotente: documento com o mesmo hash é reutilizado sem novo embedding (T06). Documento excluído só "
                   "volta com reinclusão explícita.")
        reincluir = st.checkbox("Reincluir documentos excluídos", key="reincluir")
        if st.button("Reindexar", key="reindexar", disabled=indice is None):
            with st.spinner("Indexando..."):
                relatorio = indice.indexar(COLECAO, documentos_do_indice_principal(config), chunking_principal(config),
                                           reincluir_excluidos=reincluir)
            st.success(f"Reutilizados: {relatorio['reutilizados'] or '-'} | indexados: {relatorio['indexados'] or '-'} | "
                       f"vetores: {relatorio['vetores_na_colecao']} | chamadas de embedding: {relatorio['chamadas_de_embedding']}")
            if relatorio["ignorados_por_exclusao"]:
                st.info(f"Fora do índice por exclusão registrada: {relatorio['ignorados_por_exclusao']}")
    with coluna_enviar:
        st.subheader("Incluir documento")
        st.caption("Envie apenas documentos fictícios: o texto é indexado e enviado ao serviço de embeddings. O arquivo "
                   "temporário é apagado logo após a indexação.")
        arquivo = st.file_uploader("Documento .txt (UTF-8) ou .pdf textual", type=["txt", "pdf"], key="upload")
        titulo = st.text_input("Título do documento", key="upload_titulo")
        versao = st.text_input("Versão", value="1.0", key="upload_versao")
        if st.button("Indexar documento enviado", key="indexar_upload", disabled=indice is None or arquivo is None):
            try:
                with st.spinner(f"Indexando {arquivo.name}..."):
                    relatorio = indexar_documento_enviado(indice, config, obter_guardrails(), arquivo.name,
                                                          arquivo.getvalue(), titulo, versao)
                st.success(f"{relatorio['doc_id']}: indexado ({relatorio['vetores_na_colecao']} vetores na coleção).")
            except ValueError as erro:
                st.error(str(erro))

    st.subheader("Busca no índice")
    st.caption(EXPLICACAO_SIMILARIDADE)
    consulta = st.text_input("Pergunta", key="consulta_busca")
    top_k = st.slider("Trechos (top-k)", 1, 10, int(config["chunking"].get("top_k", 4)), key="top_k")
    if st.button("Buscar", key="buscar", disabled=indice is None or not consulta):
        st.session_state["ultima_busca"] = {"consulta": consulta, "resultados": indice.buscar(COLECAO, consulta, top_k)}
    if st.session_state.get("ultima_busca"):
        busca = st.session_state["ultima_busca"]
        st.markdown(f"Resultados para: _{busca['consulta']}_")
        for r in busca["resultados"]:
            local = f"p. {r['pagina']}" if r["pagina"] else "sem paginação"
            st.markdown(f"**[{r['posicao']}] {r['doc_id']} v{r['versao']}** · {local} · {r['secao']} · similaridade "
                        f"{r['similaridade_cosseno']:.4f} · `{r['chunk_id']}`")
            st.text(r["texto"].split("\n", 1)[-1])

    st.subheader("Excluir documento do índice (RF24)")
    st.caption("Remove os vetores, registra a exclusão no manifesto e na auditoria; o documento não volta numa reindexação "
               "automática. Respostas já gravadas continuam no histórico como registro do que foi feito.")
    indexados = [d["doc_id"] for d in documentos if d["situacao"] in ("INDEXADO", "DESATUALIZADO")]
    alvo = st.selectbox("Documento", indexados, key="excluir_doc") if indexados else None
    motivo = st.text_input("Motivo da exclusão", key="excluir_motivo")
    confirmar = st.checkbox("Confirmo a exclusão dos vetores deste documento", key="excluir_confirmar")
    if st.button("Excluir", key="excluir", disabled=indice is None or not (alvo and motivo.strip() and confirmar)):
        st.session_state["ultima_exclusao"] = indice.excluir_documento(alvo, motivo.strip(), "interface Streamlit")
    if st.session_state.get("ultima_exclusao"):
        exclusao = st.session_state["ultima_exclusao"]
        st.success(f"{exclusao['doc_id']}: {sum(exclusao['vetores_removidos_por_colecao'].values())} vetor(es) removido(s); "
                   f"restantes: {exclusao['vetores_restantes']}.")

# ------------------------------------------------------------------------------
# Aba 2: atendimento e revisão humana
# ------------------------------------------------------------------------------
with aba_atendimento:
    st.subheader("Processar uma solicitação")
    solicitacoes = (ler_json(config["desafio02"]["solicitacoes"]) or {}).get("solicitacoes", [])
    origem = st.radio("Entrada", ["Solicitação de teste", "Mensagem digitada"], horizontal=True, key="origem_atendimento")
    if origem == "Solicitação de teste" and solicitacoes:
        escolhida = st.selectbox("Solicitação", solicitacoes, key="solicitacao",
                                 format_func=lambda s: f"{s['id']} — {s['tipo_caso']} — {s['canal']}")
        texto, canal, arquivo_origem, id_solicitacao = ((RAIZ_PROJETO / escolhida["arquivo"]).read_text(encoding="utf-8"),
                                                        escolhida["canal"], escolhida["arquivo"], escolhida["id"])
        with st.expander("Texto da solicitação"):
            st.text(texto)
    else:
        texto = st.text_area("Mensagem do cidadão (use apenas dados fictícios)", key="mensagem")
        canal, arquivo_origem, id_solicitacao = "texto (digitado na interface)", "(mensagem digitada)", None
    st.caption(f"Geração: {CONFIGURACOES[st.session_state['config_geracao']]['rotulo']}. Cada atendimento faz cerca de "
               "6 chamadas (moderação, política, contrato, ficha, embedding e minuta).")
    if st.button("Processar atendimento", key="processar", type="primary", disabled=not (texto or "").strip()):
        with st.spinner("Guardrails, contrato, ficha e minuta..."):
            resultado = processar_atendimento(texto, config, indice, obter_cliente(st.session_state["config_geracao"]),
                                              obter_guardrails(), audit, canal, arquivo_origem, id_solicitacao,
                                              CONFIGURACOES[st.session_state["config_geracao"]])
        st.session_state["ultimo_atendimento"] = resultado.to_dict()

    atendimento = st.session_state.get("ultimo_atendimento")
    if atendimento:
        st.markdown(f"### {atendimento['id_atendimento']} — `{atendimento['etapa_final']}`")
        st.caption(f"{atendimento['motivo']} · status: {atendimento['status_revisao']} · envio automático bloqueado")
        entrada = atendimento["entrada"]
        st.markdown(f"**Guardrails de entrada:** `{entrada['decisao']}` "
                    f"{('— ' + ', '.join(entrada['motivos'])) if entrada['motivos'] else ''}")
        if atendimento.get("contrato_exibicao"):
            coluna_contrato, coluna_ficha = st.columns(2)
            with coluna_contrato:
                st.markdown("**Contrato estruturado (RF14)**")
                contrato = atendimento["contrato_exibicao"]
                st.table(pd.DataFrame([{"campo": c, "valor": str(v)} for c, v in contrato.items() if c != "entidades"]))
                st.json(contrato["entidades"], expanded=False)
            with coluna_ficha:
                st.markdown("**Ficha de compreensão (RF15)**")
                ficha = atendimento.get("ficha")
                if ficha:
                    st.write(ficha["resumo"])
                    st.caption(f"Categoria: {ficha['categoria']} · {ficha['palavras_resumo']} palavras")
                    st.json({"entidades_literais": ficha["entidades_literais"],
                             "entidades_sem_apoio": ficha["entidades_sem_apoio"],
                             "informacoes_inferidas": ficha["informacoes_inferidas"]}, expanded=False)
                    for alerta in ficha.get("alertas") or []:
                        st.warning(alerta)
                else:
                    st.info("Ficha não gerada: não localizado.")
        if atendimento.get("rag"):
            st.markdown("**Minuta (RF19)**")
            mostrar_minuta(atendimento["rag"])
            with st.expander("Fatos enviados ao RAG (minimizados, sem nome nem documentos pessoais)"):
                st.text(atendimento.get("fatos_enviados_ao_rag") or "")
        else:
            st.warning(f"Sem minuta: {atendimento['motivo']}. O caso segue para o operador na fila abaixo.")

    st.divider()
    st.subheader("Fila de minutas e decisão do operador (T11)")
    st.caption("Aprovar libera o envio manual pelo operador; o sistema nunca envia sozinho. Justificativa obrigatória.")
    itens = minutas_para_revisao(audit)
    if not itens:
        st.info("Nenhuma minuta gravada ainda.")
    else:
        contagem = pd.Series([i["estado"] for i in itens]).value_counts()
        st.caption(" · ".join(f"{estado}: {int(contagem.get(estado, 0))}" for estado in ESTADOS_DECISAO))
        posicao = st.selectbox("Minuta", range(len(itens)), key="item_revisao",
                               format_func=lambda i: f"{itens[i]['caso_id']} — {itens[i]['estado']} — {itens[i]['status']} — "
                                                     f"{itens[i]['origem']}")
        item = itens[posicao]
        st.caption(f"Participação da IA: {item['provedor'] or 'nenhuma'} / {item['modelo'] or '—'} · prompt "
                   f"{(item['prompt'] or {}).get('id', '—')} v{(item['prompt'] or {}).get('versao', '—')} · execução "
                   f"{item['id_execucao'] or 'não localizado'}")
        rag_item = (item.get("dados") or {}).get("rag")
        if rag_item:
            mostrar_minuta(rag_item)
        else:
            st.text(item["minuta"])
        estado = st.radio("Decisão", ESTADOS_DECISAO, horizontal=True, key="estado_decisao")
        operador = st.text_input("Operador responsável", key="operador")
        justificativa = st.text_area("Justificativa", key="justificativa")
        if st.button("Registrar decisão", key="registrar_decisao"):
            try:
                registro = registrar_decisao(audit, item, estado, operador, justificativa)
                st.success(f"{registro['id_registro']}: {registro['estado']} registrada para {registro['caso_id']}.")
            except ValueError as erro:
                st.error(str(erro))
        historico = [d for d in audit.decisoes_minutas() if d["caso_id"] == item["caso_id"]]
        if historico:
            st.dataframe(pd.DataFrame(historico)[["registrado_em", "estado", "operador", "justificativa",
                                                  "liberada_para_envio_manual"]], hide_index=True, width="stretch")

# ------------------------------------------------------------------------------
# Aba 3: painel de sentimentos (sem chamada de API)
# ------------------------------------------------------------------------------
with aba_sentimentos:
    arquivo_rotulos = arquivo_de_rotulos_mais_recente()
    if arquivo_rotulos is None:
        st.info("Nenhuma classificação gravada. Execute: python -m src.main --modo sentimentos")
    else:
        df_bruto = carregar_rotulos(arquivo_rotulos)
        avaliacao = ler_json("resultados/metricas/avaliacao_sentimentos_rf22.json")
        df_unico, duplicatas = metrics.remover_duplicatas(df_bruto)
        ficha = metrics.ficha_tecnica(df_unico, duplicatas, avaliacao)
        st.subheader("Ficha técnica")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Avaliações", ficha["n_avaliacoes"], help=ficha["natureza"])
        acuracia = ficha["acuracia_polaridade_contra_gabarito"]
        c2.metric("Acurácia vs gabarito", f"{acuracia['numerador']}/{acuracia['denominador']}" if acuracia else "não localizado")
        c3.metric("Limítrofes", metrics.formatar(ficha["limitrofes"]))
        c4.metric("Para revisão", metrics.formatar(ficha["para_revisao"]))
        st.caption(f"{ficha['natureza']} · {ficha['intervalo_de_confianca']} · período {ficha['periodo']['inicio']} a "
                   f"{ficha['periodo']['fim']} · modelo {', '.join(ficha['modelos'])} · classificado em "
                   f"{ficha['classificado_em']['inicio']} · duplicatas removidas: {duplicatas} · atendimentos do período: "
                   f"não localizado · arquivo {arquivo_rotulos.name}")
        st.info(ficha["nota_etica"])

        st.subheader("Filtros")
        f1, f2, f3 = st.columns(3)
        canais = f1.multiselect("Canal", sorted(df_unico["canal"].dropna().unique()), key="filtro_canal")
        temas = f2.multiselect("Tema", sorted(df_unico["tema"].dropna().unique()), key="filtro_tema")
        polaridades = f3.multiselect("Polaridade", list(metrics.POLARIDADES), key="filtro_polaridade")
        datas = sorted(df_unico["data"].dropna().unique())
        f4, f5, f6 = st.columns(3)
        data_inicial = f4.selectbox("De", datas, index=0, key="filtro_data_inicial") if datas else None
        data_final = f5.selectbox("Até", datas, index=len(datas) - 1, key="filtro_data_final") if datas else None
        apenas_revisao = f6.checkbox("Só casos para revisão", key="filtro_revisao")
        resultado = metrics.indicadores(df_bruto, avaliacao, canais=canais, temas=temas, polaridades=polaridades,
                                        data_inicial=data_inicial, data_final=data_final, apenas_revisao=apenas_revisao)
        distribuicao = resultado["polaridade"]
        st.subheader(f"Polaridade no recorte: {distribuicao['denominador']} de {ficha['n_avaliacoes']} avaliações")
        if distribuicao["motivo_sem_percentual"]:
            st.warning(f"Percentual omitido: {distribuicao['motivo_sem_percentual']}. Só as contagens são exibidas.")
        tabela = pd.DataFrame([{"polaridade": c["categoria"], "avaliações": c["n"], "denominador": c["denominador"],
                                "percentual": "omitido" if c["percentual"] is None else f"{c['percentual']}%"}
                               for c in distribuicao["categorias"]])
        g1, g2 = st.columns(2)
        g1.dataframe(tabela, hide_index=True, width="stretch")
        g2.bar_chart(tabela.set_index("polaridade")["avaliações"])
        st.markdown("**Por canal** (percentual só com base de pelo menos "
                    f"{metrics.MINIMO_PARA_PERCENTUAL} avaliações)")
        st.dataframe(pd.DataFrame([{"canal": g["grupo"], "n": g["n"], **{c["categoria"]: metrics.formatar(c)
                                                                          for c in g["categorias"]}}
                                   for g in resultado["por_canal"]]), hide_index=True, width="stretch")
        st.subheader("Fila de revisão (indeterminadas, limítrofes ou sem rótulo válido)")
        textos = {a["id"]: a["texto"] for a in (ler_json(config["desafio02"]["avaliacoes"]) or {}).get("avaliacoes", [])}
        fila = pd.DataFrame(resultado["fila_de_revisao"])
        if fila.empty:
            st.success("Nenhum caso para revisão no recorte.")
        else:
            fila.insert(1, "texto", fila["id"].map(textos))
            st.dataframe(fila, hide_index=True, width="stretch")

# ------------------------------------------------------------------------------
# Aba 4: provedor e auditoria
# ------------------------------------------------------------------------------
with aba_auditoria:
    st.subheader("Troca da geração sem reconstruir o índice (RF21, T12)")
    escolhida = CONFIGURACOES[st.session_state["config_geracao"]]
    st.markdown(f"Configuração em uso: **{escolhida['rotulo']}** (troque na barra lateral).")
    if indice is not None:
        st.markdown(f"Índice em uso: objeto `{id(indice):x}` · coleção `{COLECAO}` · versão {indice.versao_indice} · "
                    f"embedding `{indice.embedder.modelo}` · chamadas de embedding nesta sessão: "
                    f"{len(indice.embedder.chamadas)}")
        st.caption("O mesmo objeto de índice atende todas as configurações de geração; trocar a geração não recalcula "
                   "embeddings nem regrava o manifesto.")
    else:
        st.info(f"Índice indisponível nesta sessão: {motivo_indice}")
    st.caption("Falha do serviço de geração (simulado com falha): a minuta vira a recusa padronizada com o código "
               "FALHA_NA_GERACAO, e a chamada fica registrada na auditoria com sucesso = false.")

    registros = registros_de_auditoria(audit, 300)
    st.subheader("Uso por provedor e modelo (últimos 300 registros)")
    uso = pd.DataFrame(resumo_de_uso(registros))
    if not uso.empty:
        uso["custo_usd"] = uso["custo_usd"].map(lambda v: "indisponível" if v is None else f"{v:.6f}")
    st.dataframe(uso, hide_index=True, width="stretch")
    st.subheader("Registros de auditoria (sanitizados)")
    filtro_caso = st.text_input("Filtrar por caso", key="filtro_caso")
    visiveis = [r for r in registros if not filtro_caso or filtro_caso.lower() in str(r.get("caso_id", "")).lower()]
    st.dataframe(pd.DataFrame(visiveis), hide_index=True, width="stretch")
    st.subheader("Decisões do operador")
    decisoes = audit.decisoes_minutas()
    st.dataframe(pd.DataFrame(decisoes) if decisoes else pd.DataFrame(), hide_index=True, width="stretch")
    st.subheader("Relatórios de métricas")
    relatorios = sorted((RAIZ_PROJETO / "resultados" / "metricas").glob("*.md"))
    if relatorios:
        escolhido = st.selectbox("Relatório", relatorios, key="relatorio", format_func=lambda p: p.name)
        st.markdown(escolhido.read_text(encoding="utf-8"))
    else:
        st.info("Nenhum relatório gerado ainda.")
