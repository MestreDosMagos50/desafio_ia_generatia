#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
==============================================================================
VALIDADOR DE CONFORMIDADE E AUDITORIA PRÉ-ENTREGA (RF01 A RF13)
==============================================================================
Varre o repositório checando a presença e integridade de todos os entregáveis
obrigatórios da Seção 11 do Edital e assegura a ausência de chaves de API.
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
    # RF01 - Configuração e Ambiente
    ("README.md", "README completo com instruções e versões"),
    ("requirements.txt", "Arquivo de dependências com versões"),
    (".env.example", "Modelo de variáveis de ambiente sem segredos"),
    (".gitignore", "Proteção contra commit de .env e caches"),
    ("config.json", "Configuração centralizada não sensível"),
    ("AGENTS.md", "Diretrizes e convenções para agentes de codificação"),
    ("pytest.ini", "Configuração dos testes (marcador de integração)"),
    ("resumir_auditoria.py", "Resumo de modelos, tokens e custos a partir do log"),
    ("limpar_resultados.py", "Limpeza dos resultados antes da execução final"),

    # Dados e Gabaritos
    ("dados/originais/entrada_texto.txt", "Solicitação textual original"),
    ("dados/originais/entrada_audio.mp3", "Mensagem de voz original"),
    ("dados/originais/entrada_pdf-imagem.pdf", "Ficha manuscrita digitalizada original"),
    ("dados/originais/brasao.png", "Brasão oficial do Estado de Mato Grosso"),
    ("dados/gabaritos/gabarito_texto.json", "Gabarito da solicitação textual"),
    ("dados/gabaritos/gabarito_audio.json", "Gabarito da transcrição e metadados"),
    ("dados/gabaritos/gabarito_visao.json", "Gabarito da Ficha de Matrícula manuscrita"),
    ("dados/originais/entrada_texto_injection.txt", "Caso de teste de prompt injection (RF03)"),
    ("dados/gabaritos/gabarito_texto_injection.json", "Gabarito do caso de prompt injection"),

    # Código-fonte (src/)
    ("src/main.py", "Ponto de entrada unificado executável (python -m src.main)"),
    ("src/llm_client.py", "Cliente resiliente com tratamento de erros (RF04)"),
    ("src/prompts.py", "Prompts blindados contra injeção e templates (RF03)"),
    ("src/audio.py", "Transcrição STT e Síntese TTS acessível (RF06, RF07)"),
    ("src/vision.py", "OCR e extração visual de documento manuscrito (RF08)"),
    ("src/image_generation.py", "Geração de cartaz com aviso de conteúdo sintético (RF10)"),
    ("src/parsers.py", "Schemas Pydantic e gerador de minuta oficial (RF05, RF09)"),
    ("src/audit.py", "Auditoria estruturada em JSONL e revisão humana (RF11, RF13)"),
    ("src/conferencia.py", "Gabaritos, WER e conferência cruzada entre canais (RF06, RF08)"),
    ("src/revisao_humana.py", "Interface de revisão humana no terminal (RF13)"),
    ("src/privacidade.py", "Minimização e mascaramento de dados pessoais (RF12)"),
    ("testes/conftest.py", "Testes de integração só com RODAR_TESTES_INTEGRACAO=1"),

    # Prompts e Experimento (RF02)
    ("prompts/prompt_a_zero_shot.txt", "Prompt A do experimento controlado"),
    ("prompts/prompt_b_estruturado.txt", "Prompt B v1 usado no experimento"),
    ("prompts/prompt_b_estruturado_v2.txt", "Prompt B v2 usado na produção"),
    ("prompts/metaprompt_gerador_prompt_c.txt", "Metaprompt que gerou o Prompt C"),
    ("prompts/prompt_c_metaprompt.txt", "Prompt C gerado pelo metaprompt"),
    ("prompts/prompt_c_metaprompt_origem.json", "Origem do Prompt C (modelo, data, seed)"),
    ("documentacao/matriz_comparativa_prompts.md", "Matriz comparativa dos 3 prompts"),
    ("documentacao/experimento_prompts_resultado.json", "Medições e telemetria do experimento"),
    ("documentacao/experimento_prompts_notas_equipe.json", "Notas da equipe (0 a 2) no experimento"),

    # Resultados e Evidências
    # Saídas versionadas (protocolo/nome + data e hora): basta existir ao menos uma versão
    ("resultados/minutas/minuta_institucional_2026-000142_*.txt", "Minuta institucional do caso 2026-000142"),
    ("resultados/minutas/minuta_institucional_2026-000187_*.txt", "Minuta do caso de prompt injection (2026-000187)"),
    ("resultados/audios/minuta_acessivel_2026-000142_*.mp3", "Áudio acessível gerado em MP3 (RF07)"),
    ("resultados/audios/minuta_acessivel_2026-000142_*[0-9].txt", "Texto exato enviado à síntese de voz (RF07)"),
    ("resultados/imagens/cartaz_orientacao_matricula_*[0-9].png", "Peça visual com identificação sintética (RF10)"),
    ("resultados/imagens/cartaz_orientacao_matricula_*_metadados.json", "Metadados e proveniência da imagem"),
    ("resultados/logs/auditoria.jsonl", "Log estruturado sem segredos (RF11)"),
    ("resultados/logs/decisoes_humanas.json", "Registro das decisões de revisão humana (RF13)"),

    # Documentação e Relatórios Técnicos
    ("documentacao/relatorio_tecnico.md", "Relatório técnico com arquitetura, custos e riscos"),
    ("documentacao/resumo_execucoes.md", "Modelos, tokens e custos reais tirados do log (RF11)"),
    ("documentacao/lgpd_mapeamento.md", "Mapeamento de privacidade e minimização LGPD (RF12)"),
    ("documentacao/relatorio_avaliacao_qualidade.md", "Protocolo de qualidade e taxa de aprovação (RF13)"),
    ("documentacao/soberania_e_privacidade_ocr.txt", "Justificativa de processamento local OCR"),
    ("documentacao/acessibilidade_recurso_tts.md", "Relatório técnico de acessibilidade auditiva"),
    ("documentacao/uso_ia.md", "Transparência do uso de IA no desenvolvimento (Seção 10)"),
    ("documentacao/roteiro_apresentacao_12min.md", "Roteiro da apresentação oral de 12 minutos (Seção 12)")
]


def _ler_json(caminho_rel: str):
    caminho = raiz_projeto / caminho_rel
    try:
        return json.loads(caminho.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def verificar_execucao_final():
    """Itens que só existem depois da execução interativa da equipe. Retorna [(ok, mensagem)]."""
    resultados = []
    decisoes = _ler_json("resultados/logs/decisoes_humanas.json") or []
    simuladas = [d for d in decisoes if d.get("simulada") or "SIMULADO" in str(d.get("operador_responsavel", ""))]
    resultados.append((bool(decisoes) and not simuladas,
                       f"decisoes_humanas.json: {len(decisoes)} decisão(ões) real(is), {len(simuladas)} simulada(s) misturada(s)"))
    objetos = {d.get("objeto_revisado") for d in decisoes}
    for objeto in ("minuta", "conferencia_cruzada", "ficha", "cartaz"):
        resultados.append((objeto in objetos, f"decisão humana registrada para '{objeto}'"))
    metadados = sorted((raiz_projeto / "resultados" / "imagens").glob("cartaz_orientacao_matricula_*_metadados.json"))
    meta = _ler_json(metadados[-1].relative_to(raiz_projeto).as_posix()) if metadados else {}
    resultados.append((meta.get("status_revisao") in ("APROVADO", "REJEITADO"),
                       f"cartaz revisado por pessoa (status_revisao = {meta.get('status_revisao')})"))
    # Cada caso dos gabaritos precisa de decisão final sobre o seu objeto (minuta ou ficha)
    sys.path.insert(0, str(raiz_projeto))
    from src.audit import AuditManager
    ultimas = AuditManager.ultimas_decisoes(decisoes)
    for caso, esperado in AuditManager()._decisoes_esperadas().items():
        do_caso = {objeto: d for (c, objeto), d in ultimas.items() if c == caso}
        obtido = AuditManager.resultado_do_caso(do_caso, esperado.get("objeto_final", "minuta"))
        resultados.append((obtido is not None, f"{caso}: decisão final = {obtido or 'sem decisão'} (esperado {esperado.get('decisao')})"))
    # Registros confirmados coerentes: o protocolo do conteúdo é o do nome do arquivo (casos não misturados)
    for registro in sorted((raiz_projeto / "dados" / "processados").glob("registro_confirmado_*.json")):
        protocolo = (_ler_json(registro.relative_to(raiz_projeto).as_posix()) or {}).get("protocolo")
        esperado = registro.stem.replace("registro_confirmado_", "")
        resultados.append((protocolo == esperado, f"{registro.name}: protocolo do conteúdo = {protocolo}"))
    notas = _ler_json("documentacao/experimento_prompts_notas_equipe.json") or {}
    preenchidas = sum(1 for a in notas.get("avaliacoes", []) for n in a.get("notas", {}).values()
                      for v in n.values() if isinstance(v, (int, float)))
    resultados.append((preenchidas > 0, f"notas da equipe no experimento RF02: {preenchidas} nota(s) preenchida(s)"))
    return resultados


def validar_conformidade() -> bool:
    print("=" * 75)
    print("  VERIFICADOR DE CONFORMIDADE E AUDITORIA DA ENTREGA (FIC_DEV)")
    print("=" * 75)

    todos_presentes = True
    for caminho_rel, descricao in ITENS_OBRIGATORIOS:
        encontrados = sorted(raiz_projeto.glob(caminho_rel)) if "*" in caminho_rel else [raiz_projeto / caminho_rel]
        arquivo = encontrados[-1] if encontrados else raiz_projeto / caminho_rel
        if arquivo.exists() and arquivo.stat().st_size > 0:
            print(f"  [OK] {caminho_rel:55} ({arquivo.stat().st_size} bytes)")
        else:
            print(f"  [FALHA] {caminho_rel:55} AUSENTE OU VAZIO!")
            todos_presentes = False

    # Estado da execução final: decisões humanas reais, cartaz revisado e notas da equipe
    print("\n[EXECUÇÃO FINAL] Verificando decisões humanas, revisão do cartaz e notas do experimento...")
    for ok, mensagem in verificar_execucao_final():
        print(f"  [{'OK' if ok else 'FALHA'}] {mensagem}")
        todos_presentes = todos_presentes and ok

    # Checagem de Segurança Ativa: NUNCA permitir chaves reais em arquivos públicos
    print("\n[SEGURANÇA] Verificando se há vazamento acidental de chaves de API...")
    vazamento = False
    padrao_chave = re.compile(r'(AIza[0-9A-Za-z_-]{20,}|AQ\.[0-9A-Za-z_-]{20,}|sk-[A-Za-z0-9_-]{20,}|hf_[A-Za-z0-9]{20,})')

    def eh_ficticia(chave: str) -> bool:
        # Chaves de teste usam um único caractere repetido (ex.: "AQ." + "X" * 40)
        corpo = chave.split(".", 1)[-1] if chave.startswith("AQ.") else chave[4:] if chave.startswith("AIza") else chave[3:]
        return "sua_chave" in chave or len(set(corpo)) <= 2

    # Valor real da chave configurada no .env: não pode aparecer em nenhum outro arquivo
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
        dirs[:] = [d for d in dirs if d not in (".git", "venv", ".venv")]
        for f in files:
            caminho = Path(root) / f
            if caminho == arquivo_env:
                continue  # .env é local do usuário e nunca irá no zip
            try:
                dados = caminho.read_bytes()
            except OSError:
                continue
            if any(chave in dados for chave in chaves_reais):
                print(f"  [ALERTA DE SEGURANÇA] Chave do .env encontrada em: {caminho}")
                vazamento = True
                continue
            if f.endswith((".py", ".json", ".md", ".txt", ".jsonl", ".example")):
                conteudo = dados.decode("utf-8", errors="ignore")
                suspeitas = [m for m in padrao_chave.findall(conteudo) if not eh_ficticia(m)]
                if suspeitas:
                    print(f"  [ALERTA DE SEGURANÇA] Possível chave em: {caminho}")
                    vazamento = True

    # O pacote de entrega também é verificado, se já existir
    caminho_zip = raiz_projeto.parent / "Desafio01-FICDEV-IAGenerativa.zip"
    if caminho_zip.exists():
        with zipfile.ZipFile(caminho_zip) as zf:
            for nome in zf.namelist():
                dados = zf.read(nome)
                if nome.endswith(".env") or any(chave in dados for chave in chaves_reais):
                    print(f"  [ALERTA DE SEGURANÇA] Credencial dentro do zip de entrega: {nome}")
                    vazamento = True

    if not vazamento:
        print("  [OK] Nenhuma credencial ou chave privada exposta nos arquivos públicos!")

    print("\n" + "=" * 75)
    if todos_presentes and not vazamento:
        print("  RESULTADO: 100% DOS REQUISITOS E ENTREGÁVEIS HOMOLOGADOS!")
        print("  O projeto está apto para empacotamento e entrega à banca avaliadora.")
    else:
        print("  RESULTADO: PENDÊNCIAS DETECTADAS. Verifique a lista acima.")
    print("=" * 75)
    print("Conferências manuais (não verificáveis por script):")
    print("  - a transcricao_referencia do gabarito_audio.json foi revisada ouvindo o áudio;")
    print("  - a chave de API exposta anteriormente foi revogada no Google AI Studio;")
    print("  - o zip foi testado em pasta nova com venv novo (--check-env e pytest).")
    return todos_presentes and not vazamento


if __name__ == "__main__":
    sucesso = validar_conformidade()
    sys.exit(0 if sucesso else 1)
