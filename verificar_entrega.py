#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
==============================================================================
VALIDADOR DE CONFORMIDADE E AUDITORIA PRÉ-ENTREGA (DESAFIO 02)
==============================================================================
Confere os entregáveis da Seção 13, a matriz T01-T15 (nenhum NAO_CONFERE), as
pendências que só a equipe conclui (revisão dos gabaritos, conferências e
decisões do operador) e a ausência de chaves de API nos arquivos e no zip.
Os artefatos da execução final do Desafio 01 aparecem só como informação.
Resultado: FALHA (entregável ausente, teste NAO_CONFERE ou credencial),
PENDÊNCIAS HUMANAS (tudo certo, falta a parte da equipe) ou HOMOLOGADA.
==============================================================================
"""

import sys
import os
import re
import json
import zipfile
from pathlib import Path

raiz_projeto = Path(__file__).resolve().parent

ITENS_OBRIGATORIOS = [
    # Configuração e ambiente (RF01, Seção 13)
    ("README.md", "README com instalação, indexação, Streamlit, testes e limitações"),
    ("requirements.txt", "Dependências com versões fixadas"),
    (".env.example", "Modelo de variáveis de ambiente sem segredos"),
    (".gitignore", "Proteção contra commit de .env, .streamlit, contexto/ e caches"),
    ("config.json", "Configuração centralizada: provedor, modelos, preços, limites, chunking e RAG"),
    ("AGENTS.md", "Convenções, comandos de teste e restrições para agentes de codificação"),
    ("pytest.ini", "Configuração dos testes (marcador de integração)"),
    ("resumir_auditoria.py", "Resumo de modelos, tokens e custos a partir do log"),
    ("limpar_resultados.py", "Limpeza do pipeline do Desafio 01 preservando o Desafio 02"),
    ("empacotar_entrega.py", "Gera o .zip sem .env, contexto/ e caches"),

    # Código-fonte
    ("src/main.py", "Ponto de entrada (python -m src.main) com os modos do Desafio 01 e 02"),
    ("src/llm_client.py", "Cliente com timeout, repetição única, orçamento e Gemini legado"),
    ("src/adaptadores.py", "Adaptadores OpenAI e simulado (RF21)"),
    ("src/schemas.py", "Contratos versionados do Desafio 02 (RF14, RF15, RF16, RF19, RF22)"),
    ("src/prompts.py", "Prompts versionados (VERSOES_PROMPTS)"),
    ("src/nlp.py", "Extração, regras de negócio e ficha de compreensão (RF14, RF15)"),
    ("src/guardrails.py", "Guardrails em camadas (RF16)"),
    ("src/ingestion.py", "Leitura por página e chunking (RF17, RF18)"),
    ("src/embeddings.py", "Embeddings e índice vetorial persistente (RF17, RF18, RF24)"),
    ("src/rag.py", "RAG fundamentado com recusa, ancoragem e conflito (RF19)"),
    ("src/sentiment.py", "Classificação de sentimentos (RF22)"),
    ("src/metrics.py", "Agregação determinística em pandas (RF22, RF23)"),
    ("src/atendimento.py", "Fluxo integrado e serviços da interface (RF20, RF21, RF24)"),
    ("src/app.py", "Interface Streamlit (RF20)"),
    ("src/avaliacao.py", "Matriz T01-T15, regressão T15 e segunda geração (RF21, RF23)"),
    ("src/audit.py", "Auditoria JSONL e decisões humanas (RF11, RF13, RF21, RF24)"),
    ("src/parsers.py", "Contratos e minuta do Desafio 01 (RF05, RF09)"),
    ("src/vision.py", "Leitura da ficha manuscrita (RF08), usada na regressão T15"),
    ("testes/conftest.py", "Testes de integração só com RODAR_TESTES_INTEGRACAO=1"),

    # Dados fictícios, acervo, gabaritos e prompts (Seções 6 e 13)
    ("dados/acervo/manifesto_acervo.json", "Acervo fictício identificado (doc_id, título, versão, vigência)"),
    ("dados/solicitacoes/solicitacoes_desafio02.json", "Seis solicitações fictícias"),
    ("dados/avaliacoes/avaliacoes_atendimento.json", "Doze avaliações fictícias"),
    ("dados/adversariais/ataques_rf16.json", "Três entradas adversariais e variantes"),
    ("dados/gabaritos/gabarito_solicitacoes_rf14_rf15.json", "Gabarito das solicitações"),
    ("dados/gabaritos/perguntas_rag_rf18_rf19.json", "Oito perguntas do RAG com trechos de referência"),
    ("dados/gabaritos/gabarito_sentimentos_rf22.json", "Gabarito dos sentimentos"),
    ("dados/gabaritos/gabarito_ataques_rf16.json", "Gabarito dos ataques"),
    ("dados/originais/entrada_texto.txt", "Solicitação textual do Desafio 01 (regressão T15)"),
    ("dados/originais/entrada_pdf-imagem.pdf", "Ficha manuscrita do Desafio 01 (regressão T15)"),
    ("prompts/politica_escopo_e_seguranca_v1.1.txt", "Política de escopo em uso"),
    ("prompts/politica_escopo_e_seguranca_v1.0.txt", "Versão anterior da política (rastreabilidade)"),
    ("scripts/gerar_acervo_ficticio.py", "Gerador determinístico do acervo fictício"),
    ("indice/manifesto_indice.json", "Manifesto do índice (modelo, chunking, hashes e exclusões)"),

    # Evidências (Seção 13)
    ("resultados/metricas/comparativo_json_esquema_rf14.md", "Comparação de JSON sintático e esquema (T01)"),
    ("resultados/nlp/t02_regras_negocio.json", "Regras de negócio (T02)"),
    ("resultados/metricas/avaliacao_nlp_rf15.md", "Resumo, classificação e entidades (T03)"),
    ("resultados/guardrails/avaliacao_guardrails_rf16.md", "Registros dos ataques e limites (T04, T05)"),
    ("resultados/indice/indexacoes.jsonl", "Indexação e reuso do índice (T06)"),
    ("resultados/metricas/comparacao_chunking_rf18.md", "Comparação de chunking (T07)"),
    ("resultados/metricas/calibracao_limiar_rag.md", "Calibração do limiar do RAG"),
    ("resultados/metricas/avaliacao_rag_rf19_*.md", "Oito consultas RAG com fontes e respostas (T08-T10)"),
    ("resultados/metricas/conferencia_sustentacao_rag.json", "Registro da conferência de sustentação (RF23)"),
    ("resultados/metricas/comparativo_geracao_rf21.md", "Segunda configuração de geração e falha (T12)"),
    ("resultados/sentimentos/rotulos_sentimentos_*.csv", "Doze avaliações rotuladas (RF22)"),
    ("resultados/metricas/avaliacao_sentimentos_rf22.md", "Sentimentos contra o gabarito e ficha técnica"),
    ("resultados/indice/exclusao_t14.md", "Demonstração da exclusão de documento (T14)"),
    ("resultados/metricas/regressao_t15.md", "Regressão textual e OCR (T15)"),
    ("resultados/logs/auditoria.jsonl", "Log estruturado sem segredos (RF11, RF21)"),

    # Documentação
    ("documentacao/matriz_testes_rf23.md", "Matriz T01-T15 e métricas do RF23"),
    ("documentacao/relatorio_tecnico_desafio02.md", "Relatório técnico do Desafio 02"),
    ("documentacao/uso_ia.md", "Registro do uso de IA no desenvolvimento (Seção 12)"),
    ("documentacao/roteiro_apresentacao_15min.md", "Roteiro da apresentação de 15 minutos (Seção 14)"),
    ("documentacao/resumo_execucoes.md", "Modelos, tokens e custos tirados do log"),
]

# Saídas da execução final do Desafio 01 (já entregue): conferidas só como informação
ITENS_DESAFIO01 = [
    ("resultados/minutas/minuta_institucional_2026-000142_*.txt", "minuta do caso 2026-000142 (também gerada pela regressão T15)"),
    ("resultados/minutas/minuta_institucional_2026-000187_*.txt", "minuta do caso de prompt injection"),
    ("resultados/audios/minuta_acessivel_2026-000142_*.mp3", "áudio acessível (RF07)"),
    ("resultados/imagens/cartaz_orientacao_matricula_*[0-9].png", "peça visual (RF10)"),
]

GABARITOS_COM_REVISAO = ("gabarito_solicitacoes_rf14_rf15.json", "perguntas_rag_rf18_rf19.json",
                         "gabarito_sentimentos_rf22.json", "gabarito_ataques_rf16.json")


def _ler_json(caminho_rel: str):
    caminho = raiz_projeto / caminho_rel
    try:
        return json.loads(caminho.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _existe(caminho_rel: str):
    encontrados = sorted(raiz_projeto.glob(caminho_rel)) if "*" in caminho_rel else [raiz_projeto / caminho_rel]
    arquivo = encontrados[-1] if encontrados else raiz_projeto / caminho_rel
    return arquivo if arquivo.exists() and arquivo.stat().st_size > 0 else None


def verificar_pendencias_humanas():
    """Etapas que só a equipe pode concluir. Retorna [(concluida, mensagem)]."""
    resultados = []
    for nome in GABARITOS_COM_REVISAO:
        status = ((_ler_json(f"dados/gabaritos/{nome}") or {}).get("revisao_humana") or {}).get("status")
        resultados.append((status not in (None, "PENDENTE"), f"revisão humana do {nome}: {status}"))
    conferencia = _ler_json("resultados/nlp/conferencia_humana_rf15.json") or {}
    resultados.append((bool(conferencia.get("revisado_por")),
                       "conferência humana do RF15 (resultados/nlp/conferencia_humana_rf15.json)"))
    sustentacao = _ler_json("resultados/metricas/conferencia_sustentacao_rag.json") or {"casos": []}
    afirmacoes = [a for c in sustentacao["casos"] for a in c.get("afirmacoes", [])]
    conferidas = sum(a.get("sustentada") is not None for a in afirmacoes)
    resultados.append((bool(afirmacoes) and conferidas == len(afirmacoes),
                       f"sustentação das afirmações do RAG: {conferidas}/{len(afirmacoes)} conferidas (RF23)"))
    decisoes = _ler_json("resultados/logs/decisoes_humanas_desafio02.json") or []
    ultimas = {}
    for d in sorted(decisoes, key=lambda d: d.get("registrado_em", "")):
        ultimas[d["caso_id"]] = d["estado"]
    estados = list(ultimas.values())
    resumo = ", ".join(f"{e} {estados.count(e)}" for e in sorted(set(estados))) or "nenhuma"
    resultados.append(("APROVADA" in estados and any(e in ("REJEITADA", "REVISAR") for e in estados),
                       f"decisões do operador na interface: {resumo} (RF24: ao menos uma aprovada e outra rejeitada "
                       "ou em revisão)"))
    return resultados


def verificar_matriz():
    """A matriz existe com os 15 testes e nenhum está NAO_CONFERE. Retorna [(ok, mensagem)]."""
    matriz = _ler_json("documentacao/matriz_testes_rf23.json")
    if not matriz:
        return [(False, "matriz T01-T15 ausente: python -m src.main --modo avaliacao-integrada")]
    situacoes = {l["id"]: l["situacao"] for l in matriz["testes"]}
    nao_conferem = [i for i, s in situacoes.items() if s == "NAO_CONFERE"]
    contagem = {s: list(situacoes.values()).count(s) for s in sorted(set(situacoes.values()))}
    mensagem = f"matriz de {matriz['gerado_em']}: {contagem}" + (f"; NAO_CONFERE: {', '.join(nao_conferem)}" if nao_conferem else "")
    return [(len(situacoes) == 15 and not nao_conferem, mensagem)]


def verificar_seguranca() -> bool:
    """Procura chaves nos arquivos e no zip; True se houver vazamento."""
    vazamento = False
    padrao_chave = re.compile(r'(AIza[0-9A-Za-z_-]{20,}|AQ\.[0-9A-Za-z_-]{20,}|sk-[A-Za-z0-9_-]{20,}|hf_[A-Za-z0-9]{20,})')

    def eh_ficticia(chave: str) -> bool:
        # Chaves de teste usam um único caractere repetido (ex.: "AQ." + "X" * 40)
        corpo = chave.split(".", 1)[-1] if chave.startswith("AQ.") else chave[4:] if chave.startswith("AIza") else chave[3:]
        return "sua_chave" in chave or len(set(corpo)) <= 2

    # Valor real das chaves configuradas no .env: não pode aparecer em nenhum outro arquivo
    chaves_reais = []
    arquivo_env = raiz_projeto / ".env"
    if arquivo_env.exists():
        for linha in arquivo_env.read_text(encoding="utf-8").splitlines():
            if "=" in linha and not linha.strip().startswith("#"):
                nome, valor = linha.split("=", 1)
                valor = valor.strip().strip('"').strip("'")
                if nome.strip().endswith(("_API_KEY", "_TOKEN")) and len(valor) >= 20 and "sua_chave" not in valor:
                    chaves_reais.append(valor.encode("utf-8"))

    for root, dirs, files in os.walk(raiz_projeto):
        dirs[:] = [d for d in dirs if d not in (".git", "venv", ".venv", "__pycache__")]
        for f in files:
            caminho = Path(root) / f
            if caminho == arquivo_env:
                continue  # .env é local do usuário e nunca vai no zip
            try:
                dados = caminho.read_bytes()
            except OSError:
                continue
            if any(chave in dados for chave in chaves_reais):
                print(f"  [ALERTA DE SEGURANÇA] Chave do .env encontrada em: {caminho}")
                vazamento = True
                continue
            if f.endswith((".py", ".json", ".md", ".txt", ".jsonl", ".example", ".csv")):
                conteudo = dados.decode("utf-8", errors="ignore")
                if [m for m in padrao_chave.findall(conteudo) if not eh_ficticia(m)]:
                    print(f"  [ALERTA DE SEGURANÇA] Possível chave em: {caminho}")
                    vazamento = True

    # O pacote de entrega também é verificado, se já existir
    caminho_zip = raiz_projeto.parent / "Desafio02-FICDEV-IAGenerativa.zip"
    if caminho_zip.exists():
        with zipfile.ZipFile(caminho_zip) as zf:
            for nome in zf.namelist():
                dados = zf.read(nome)
                if nome.endswith(".env") or "/.streamlit/" in nome or any(chave in dados for chave in chaves_reais):
                    print(f"  [ALERTA DE SEGURANÇA] Credencial ou configuração local dentro do zip: {nome}")
                    vazamento = True
                if "/contexto/" in nome:
                    print(f"  [ALERTA DE SEGURANÇA] Documento real de referência dentro do zip de entrega: {nome}")
                    vazamento = True
        if not vazamento:
            print(f"  [OK] Zip verificado: {caminho_zip.name}")
    if not vazamento:
        print("  [OK] Nenhuma credencial ou chave privada exposta nos arquivos públicos!")
    return vazamento


def validar_conformidade() -> bool:
    print("=" * 75)
    print("  VERIFICADOR DE CONFORMIDADE E AUDITORIA DA ENTREGA (FIC_DEV, DESAFIO 02)")
    print("=" * 75)

    todos_presentes = True
    for caminho_rel, descricao in ITENS_OBRIGATORIOS:
        arquivo = _existe(caminho_rel)
        if arquivo:
            print(f"  [OK] {caminho_rel:58} ({arquivo.stat().st_size} bytes)")
        else:
            print(f"  [FALHA] {caminho_rel:58} AUSENTE OU VAZIO! ({descricao})")
            todos_presentes = False

    print("\n[MATRIZ] Testes T01-T15...")
    for ok, mensagem in verificar_matriz():
        print(f"  [{'OK' if ok else 'FALHA'}] {mensagem}")
        todos_presentes = todos_presentes and ok

    print("\n[PENDÊNCIAS HUMANAS] Etapas que só a equipe conclui...")
    humanas = verificar_pendencias_humanas()
    for ok, mensagem in humanas:
        print(f"  [{'OK' if ok else 'PENDENTE'}] {mensagem}")
    pendencias = [m for ok, m in humanas if not ok]

    print("\n[INFORMATIVO] Artefatos da execução final do Desafio 01 (já entregue)...")
    for caminho_rel, descricao in ITENS_DESAFIO01:
        print(f"  [{'OK' if _existe(caminho_rel) else 'AUSENTE'}] {caminho_rel} ({descricao})")

    print("\n[SEGURANÇA] Verificando se há vazamento acidental de chaves de API...")
    vazamento = verificar_seguranca()

    print("\n" + "=" * 75)
    if not todos_presentes or vazamento:
        print("  RESULTADO: FALHAS DETECTADAS (entregável ausente, teste NAO_CONFERE ou credencial). Corrija antes de entregar.")
    elif pendencias:
        print(f"  RESULTADO: ENTREGÁVEIS E SEGURANÇA OK, COM {len(pendencias)} PENDÊNCIA(S) HUMANA(S).")
        print("  Conclua as etapas marcadas como PENDENTE, rode de novo a avaliação integrada e este verificador.")
    else:
        print("  RESULTADO: ENTREGA HOMOLOGADA. O projeto está apto para empacotamento.")
    print("=" * 75)
    print("Conferências manuais (não verificáveis por script):")
    print("  - a política de escopo (prompts/politica_escopo_e_seguranca_v1.1.txt) foi revisada pela equipe;")
    print("  - a configuração de chunking A e o limiar 0,45 foram confirmados pela equipe;")
    print("  - o zip foi testado em pasta nova (--check-env, --modo indexar e pytest).")
    return todos_presentes and not vazamento and not pendencias


if __name__ == "__main__":
    sucesso = validar_conformidade()
    sys.exit(0 if sucesso else 1)
