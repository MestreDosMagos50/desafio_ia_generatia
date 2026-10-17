#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
==============================================================================
EXPERIMENTO DE ENGENHARIA DE PROMPTS (RF02)
==============================================================================
Compara os prompts A (zero-shot), B v1 (estruturado) e C (gerado por metaprompt)
com o mesmo modelo, temperatura, seed e entrada.

- O script preenche apenas o que é MEDIDO: latência, tokens, custo, exposição
  de dados pessoais, uso de "não localizado", menção a "alternados" e
  documentos citados que não constam na entrada.
- Os critérios subjetivos (notas 0 a 2) são dados pela equipe em
  documentacao/experimento_prompts_notas_equipe.json.

Uso:
  python testes/executar_experimento_prompts.py --gerar-prompt-c   # 1 chamada: metaprompt -> Prompt C
  python testes/executar_experimento_prompts.py                    # 3 chamadas: A, B v1 e C
  python testes/executar_experimento_prompts.py --somente-matriz   # 0 chamadas: refaz a matriz com as notas
==============================================================================
"""

import re
import sys
import json
import shutil
import argparse
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

raiz_projeto = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(raiz_projeto))

from src.llm_client import LLMClient
from src.audit import AuditManager
from src.conferencia import normalizar
from src.prompts import (
    PROMPT_A_ZERO_SHOT, PROMPT_B_ESTRUTURADO, VERSOES_PROMPTS,
    ARQUIVO_METAPROMPT_C, ARQUIVO_PROMPT_C, MARCADOR_SOLICITACAO, carregar_prompt_c
)

ARQUIVO_ENTRADA_REL = "dados/originais/entrada_texto.txt"
CASO_ID = "RF02_EXPERIMENTO_PROMPTS"
DIR_DOC = raiz_projeto / "documentacao"
DIR_MINUTAS = raiz_projeto / "resultados" / "minutas"
ARQUIVO_RESULTADO = DIR_DOC / "experimento_prompts_resultado.json"
ARQUIVO_NOTAS = DIR_DOC / "experimento_prompts_notas_equipe.json"
ARQUIVO_MATRIZ = DIR_DOC / "matriz_comparativa_prompts.md"
ARQUIVO_ORIGEM_C = ARQUIVO_PROMPT_C.with_name("prompt_c_metaprompt_origem.json")
DIR_EVIDENCIA_ANTERIOR = DIR_DOC / "evidencias" / "experimento_2026-10-16"

PROMPTS = [
    ("prompt_a", "Prompt A (zero-shot)", "PROMPT_A_ZERO_SHOT"),
    ("prompt_b", "Prompt B v1 (estruturado)", "PROMPT_B_ESTRUTURADO"),
    ("prompt_c", "Prompt C (gerado por metaprompt)", "PROMPT_C_METAPROMPT"),
]

CRITERIOS_EQUIPE = {
    "fidelidade": "Todos os fatos da minuta estão na entrada (2 = sim; 1 = pequenos desvios; 0 = fatos distorcidos)",
    "dados_inventados": "Ausência de prazos, normas ou documentos inventados (2 = nenhum; 1 = um; 0 = vários)",
    "formato": "Segue um modelo institucional utilizável como minuta (2 = sim; 1 = com ajustes; 0 = não)",
    "tom": "Formal, claro e acolhedor (2 = adequado; 1 = burocrático ou informal demais; 0 = inadequado)",
    "lacunas": "Informações ausentes marcadas como 'não localizado' e pergunta do cidadão tratada (2/1/0)",
    "tempo_ate_resultado_utilizavel": "Esforço de edição até poder enviar (2 = pouco; 1 = moderado; 0 = reescrever)",
}

# Documentos que um modelo costuma "listar" sem que constem na entrada (texto normalizado, sem acentos)
DOCUMENTOS_CONHECIDOS = {
    "certidão de nascimento ou casamento": r"certidao de (nascimento|casamento)",
    "histórico escolar": r"historico escolar",
    "certificado de conclusão": r"certificado de conclusao|declaracao (oficial )?de conclusao",
    "comprovante de residência": r"comprovante de (residencia|endereco)",
    "foto 3x4": r"foto(grafia)?s? 3 ?x ?4",
    "quitação eleitoral / título de eleitor": r"quitacao eleitoral|titulo de eleitor",
    "serviço militar / reservista": r"servico militar|reservista|alistamento",
    "carteira de vacinação": r"carteira de vacinacao|cartao de vacina",
}


# ------------------------------------------------------------------------------
# Medições objetivas
# ------------------------------------------------------------------------------
def medir_saida(conteudo: str, entrada: str) -> Dict[str, Any]:
    """Propriedades verificáveis da saída de um prompt (sem julgamento subjetivo)."""
    texto_n, entrada_n = normalizar(conteudo), normalizar(entrada)
    rg = re.search(r"\bRG:?\s*([\d.\-]{5,})", entrada)
    mae = re.search(r"nome da m[ãa]e,?\s*([^;\n.]+)", entrada, re.IGNORECASE)
    alternados = re.search(r"[^.\n]{0,60}alternad[oa]s[^.\n]{0,40}", conteudo, re.IGNORECASE)
    documentos = [nome for nome, padrao in DOCUMENTOS_CONHECIDOS.items()
                  if re.search(padrao, texto_n) and not re.search(padrao, entrada_n)]
    return {
        "palavras": len(conteudo.split()),
        "cpf_completo_exposto": bool(re.search(r"\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b", conteudo)),
        "rg_exposto": bool(rg and rg.group(1).strip(".-") in conteudo),
        "email_exposto": bool(re.search(r"[\w.+-]+@[\w-]+\.[\w.]+", conteudo)),
        "nome_mae_exposto": bool(mae and normalizar(mae.group(1).strip()) in texto_n),
        "ocorrencias_nao_localizado": texto_n.count("nao localizad"),
        "menciona_alternados": bool(alternados),
        "trecho_alternados": alternados.group(0).strip() if alternados else None,
        "documentos_citados_fora_da_entrada": documentos,
        "qtd_documentos_citados_fora_da_entrada": len(documentos),
    }


def _ler_saida_salva(caminho: Path) -> str:
    """Conteúdo de um arquivo experimento_prompt_x.txt sem o cabeçalho de telemetria."""
    texto = caminho.read_text(encoding="utf-8")
    return texto.split("=" * 50 + "\n\n", 1)[-1]


def preservar_execucao_anterior():
    """Copia as saídas de 16/10/2026 (prompt C sem metaprompt) para documentacao/evidencias antes de sobrescrever."""
    if DIR_EVIDENCIA_ANTERIOR.exists():
        return
    arquivos = [DIR_MINUTAS / f"experimento_{tag}.txt" for tag, *_ in PROMPTS]
    if not all(a.exists() for a in arquivos):
        return
    DIR_EVIDENCIA_ANTERIOR.mkdir(parents=True)
    for arquivo in arquivos:
        shutil.copy2(arquivo, DIR_EVIDENCIA_ANTERIOR / arquivo.name)
    shutil.copy2(raiz_projeto / "prompts" / "prompt_c_v1_sem_metaprompt.txt", DIR_EVIDENCIA_ANTERIOR / "prompt_c_v1_sem_metaprompt.txt")
    print(f"[+] Saídas de 16/10/2026 preservadas em {DIR_EVIDENCIA_ANTERIOR.relative_to(raiz_projeto).as_posix()}/")


# ------------------------------------------------------------------------------
# Prompt C por metaprompt
# ------------------------------------------------------------------------------
def gerar_prompt_c() -> bool:
    """Envia o metaprompt ao modelo e grava a saída como Prompt C (1 chamada)."""
    client = LLMClient()
    if not client.disponivel:
        print(f"[ERRO] {client.motivo_indisponibilidade}")
        return False
    metaprompt = ARQUIVO_METAPROMPT_C.read_text(encoding="utf-8")
    seed = client.llm_cfg.get("seed_experimento")
    print(f"[-] Gerando o Prompt C a partir de {ARQUIVO_METAPROMPT_C.name} ({client.modelo}, seed {seed})...")
    resposta = client.gerar(metaprompt, seed=seed, permitir_alternativos=False)
    audit = AuditManager()
    prompt_c = resposta.conteudo.strip().strip("`").strip() if resposta.sucesso else ""
    valido = prompt_c.count(MARCADOR_SOLICITACAO) == 1
    audit.registrar_execucao(
        caso_id=CASO_ID, etapa="geracao_prompt_c_por_metaprompt", modalidade="texto",
        arquivo_origem=ARQUIVO_METAPROMPT_C, resposta=resposta, prompt_id="METAPROMPT_GERADOR_PROMPT_C",
        prompt_versao="1.0", prompt_texto=metaprompt, arquivo_saida=ARQUIVO_PROMPT_C if valido else None,
        resumo_saida=f"{len(prompt_c.split())} palavras; marcador presente={valido}" if resposta.sucesso else ""
    )
    if not resposta.sucesso:
        print(f"[ERRO] {resposta.codigo_erro}: {resposta.erro}")
        return False
    if not valido:
        print(f"[ERRO] A saída não contém exatamente um marcador {MARCADOR_SOLICITACAO}; Prompt C não foi alterado.")
        return False

    ARQUIVO_PROMPT_C.write_text(prompt_c + "\n", encoding="utf-8")
    ARQUIVO_ORIGEM_C.write_text(json.dumps({
        "gerado_em": datetime.now().isoformat(timespec="seconds"),
        "metaprompt": ARQUIVO_METAPROMPT_C.relative_to(raiz_projeto).as_posix(),
        "provedor": resposta.provedor, "modelo": resposta.modelo, "parametros": resposta.parametros,
        "tokens_prompt": resposta.tokens_prompt, "tokens_resposta": resposta.tokens_resposta,
        "tokens_raciocinio": resposta.tokens_raciocinio, "latencia_ms": round(resposta.latencia_ms, 1),
        "versao_anterior": "prompts/prompt_c_v1_sem_metaprompt.txt (escrita sem metaprompt; usada na execução de 16/10/2026)",
        "edicao_humana": "nenhuma"
    }, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[+] Prompt C gravado em {ARQUIVO_PROMPT_C.relative_to(raiz_projeto).as_posix()} ({len(prompt_c.split())} palavras)")
    return True


# ------------------------------------------------------------------------------
# Experimento
# ------------------------------------------------------------------------------
def executar_experimento() -> bool:
    """Executa A, B v1 e C nas mesmas condições (3 chamadas). Retorna True se todos concluíram."""
    print("=" * 75)
    print("  EXPERIMENTO CONTROLADO DE ENGENHARIA DE PROMPTS (RF02)")
    print("=" * 75)
    if not ARQUIVO_ORIGEM_C.exists():
        print("[ERRO] O Prompt C ainda não foi gerado pelo metaprompt. Execute antes: --gerar-prompt-c")
        return False

    entrada = (raiz_projeto / ARQUIVO_ENTRADA_REL).read_text(encoding="utf-8")
    client = LLMClient()
    if not client.disponivel:
        print(f"[ERRO] Experimento não executado: {client.motivo_indisponibilidade}")
        return False
    seed = client.llm_cfg.get("seed_experimento")
    print(f"• Modelo: {client.modelo} | Temperatura: {client.temperatura} | Seed: {seed}")
    print(f"• Entrada: {ARQUIVO_ENTRADA_REL}\n")

    modelos = {"prompt_a": PROMPT_A_ZERO_SHOT, "prompt_b": PROMPT_B_ESTRUTURADO, "prompt_c": carregar_prompt_c()}
    execucoes = []
    for tag, nome, prompt_id in PROMPTS:
        print(f"[-] {nome}...")
        prompt = modelos[tag].replace(MARCADOR_SOLICITACAO, entrada)
        resposta = client.gerar(prompt, temperatura=client.temperatura, seed=seed, permitir_alternativos=False)
        execucoes.append((tag, nome, prompt_id, prompt, resposta))
        if not resposta.sucesso:
            print(f"    -> FALHA ({resposta.codigo_erro}): {resposta.erro}")
            break
        print(f"    -> {resposta.latencia_ms / 1000:.1f} s | tokens {resposta.tokens_total}")

    audit = AuditManager()
    if any(not r.sucesso for *_, r in execucoes):
        for tag, nome, prompt_id, prompt, resposta in execucoes:
            audit.registrar_execucao(caso_id=CASO_ID, etapa=f"experimento_{tag}", modalidade="texto",
                                     arquivo_origem=ARQUIVO_ENTRADA_REL, resposta=resposta, prompt_id=prompt_id,
                                     prompt_versao=VERSOES_PROMPTS[prompt_id], prompt_texto=prompt,
                                     observacao="Execução interrompida: resultados não gravados.")
        print("\n[ERRO] Experimento interrompido. Nenhum arquivo de resultado foi alterado.")
        return False

    preservar_execucao_anterior()
    resultados = []
    for tag, nome, prompt_id, prompt, resposta in execucoes:
        saida = DIR_MINUTAS / f"experimento_{tag}.txt"
        DIR_MINUTAS.mkdir(parents=True, exist_ok=True)
        saida.write_text(
            f"=== {nome.upper()} ===\n"
            f"Timestamp: {resposta.timestamp}\n"
            f"Modelo: {resposta.modelo} | Temperatura: {resposta.parametros.get('temperatura')} | Seed: {seed}\n"
            f"Latência: {resposta.latencia_ms:.1f} ms | Tokens prompt: {resposta.tokens_prompt} | "
            f"Tokens resposta: {resposta.tokens_resposta} | Tokens raciocínio: {resposta.tokens_raciocinio}\n"
            f"Custo estimado: {resposta.custo_estimado_usd if resposta.custo_estimado_usd is not None else 'não informado'} USD\n"
            + "=" * 50 + "\n\n" + resposta.conteudo,
            encoding="utf-8"
        )
        id_execucao = audit.registrar_execucao(
            caso_id=CASO_ID, etapa=f"experimento_{tag}", modalidade="texto", arquivo_origem=ARQUIVO_ENTRADA_REL,
            resposta=resposta, prompt_id=prompt_id, prompt_versao=VERSOES_PROMPTS[prompt_id], prompt_texto=prompt,
            arquivo_saida=saida, resumo_saida=f"{len(resposta.conteudo.split())} palavras"
        )
        resultados.append({
            "tag": tag, "nome": nome, "prompt_id": prompt_id, "prompt_versao": VERSOES_PROMPTS[prompt_id],
            "id_execucao": id_execucao, "arquivo_saida": saida.relative_to(raiz_projeto).as_posix(),
            "telemetria": {
                "latencia_ms": round(resposta.latencia_ms, 1), "tokens_prompt": resposta.tokens_prompt,
                "tokens_resposta": resposta.tokens_resposta, "tokens_raciocinio": resposta.tokens_raciocinio,
                "tokens_total": resposta.tokens_total, "custo_estimado_usd": resposta.custo_estimado_usd,
            },
            "medicoes": medir_saida(resposta.conteudo, entrada),
        })

    ARQUIVO_RESULTADO.write_text(json.dumps({
        "executado_em": datetime.now().isoformat(timespec="seconds"),
        "condicoes": {"provedor": client.provedor, "modelo": client.modelo, "temperatura": client.temperatura,
                      "seed": seed, "entrada": ARQUIVO_ENTRADA_REL},
        "resultados": resultados,
    }, indent=2, ensure_ascii=False), encoding="utf-8")
    garantir_arquivo_notas()
    gerar_matriz_comparativa()
    print(f"\n[+] Resultado: {ARQUIVO_RESULTADO.relative_to(raiz_projeto).as_posix()}")
    print(f"[+] Matriz: {ARQUIVO_MATRIZ.relative_to(raiz_projeto).as_posix()}")
    print(f"[!] Notas da equipe pendentes: {ARQUIVO_NOTAS.relative_to(raiz_projeto).as_posix()} (depois: --somente-matriz)")
    return True


# ------------------------------------------------------------------------------
# Notas da equipe e matriz
# ------------------------------------------------------------------------------
def garantir_arquivo_notas():
    """Cria o modelo de notas (0 a 2) para a equipe preencher, sem sobrescrever notas existentes."""
    if ARQUIVO_NOTAS.exists():
        return
    ARQUIVO_NOTAS.write_text(json.dumps({
        "instrucoes": "Cada integrante lê as três saídas em resultados/minutas/experimento_prompt_*.txt e dá nota 0, 1 ou 2 "
                      "em cada critério. Use null para critério não avaliado. Depois execute: "
                      "python testes/executar_experimento_prompts.py --somente-matriz",
        "criterios": CRITERIOS_EQUIPE,
        "avaliacoes": [
            {"avaliador": "Estudante 1",
             "notas": {tag: {c: None for c in CRITERIOS_EQUIPE} for tag, *_ in PROMPTS},
             "comentarios": {tag: "" for tag, *_ in PROMPTS}}
        ]
    }, indent=2, ensure_ascii=False), encoding="utf-8")


def _media_notas() -> Dict[str, Dict[str, Optional[float]]]:
    """Média das notas da equipe por prompt e critério (None se ninguém avaliou)."""
    if not ARQUIVO_NOTAS.exists():
        return {}
    dados = json.loads(ARQUIVO_NOTAS.read_text(encoding="utf-8"))
    medias: Dict[str, Dict[str, Optional[float]]] = {}
    for tag, *_ in PROMPTS:
        medias[tag] = {}
        for criterio in CRITERIOS_EQUIPE:
            valores = [a["notas"].get(tag, {}).get(criterio) for a in dados.get("avaliacoes", [])]
            valores = [v for v in valores if isinstance(v, (int, float))]
            medias[tag][criterio] = round(sum(valores) / len(valores), 2) if valores else None
    return medias


def _medicoes_anteriores() -> Dict[str, Dict[str, Any]]:
    """Medições das saídas de 16/10/2026 preservadas como evidência."""
    if not DIR_EVIDENCIA_ANTERIOR.exists():
        return {}
    entrada = (raiz_projeto / ARQUIVO_ENTRADA_REL).read_text(encoding="utf-8")
    return {tag: medir_saida(_ler_saida_salva(DIR_EVIDENCIA_ANTERIOR / f"experimento_{tag}.txt"), entrada)
            for tag, *_ in PROMPTS if (DIR_EVIDENCIA_ANTERIOR / f"experimento_{tag}.txt").exists()}


def _variacoes(anteriores: Dict[str, Dict[str, Any]], atuais: Dict[str, Dict[str, Any]], nomes: Dict[str, str]) -> List[str]:
    """Medições que mudaram entre a execução anterior e a atual."""
    rotulos = {"cpf_completo_exposto": "CPF completo exposto", "rg_exposto": "RG exposto", "email_exposto": "e-mail exposto",
               "nome_mae_exposto": "nome da mãe exposto", "menciona_alternados": 'menciona "alternados"',
               "qtd_documentos_citados_fora_da_entrada": "documentos fora da entrada"}
    linhas = []
    for tag in atuais:
        if tag not in anteriores:
            continue
        mudancas = [f"{rotulo}: {anteriores[tag][campo]} -> {atuais[tag][campo]}"
                    for campo, rotulo in rotulos.items() if anteriores[tag][campo] != atuais[tag][campo]]
        if mudancas:
            linhas.append(f"- **{nomes[tag]}:** " + "; ".join(mudancas))
    return linhas


def _sim_nao(valor: bool) -> str:
    return "**sim**" if valor else "não"


def _linhas_medicoes(medicoes: Dict[str, Dict[str, Any]]) -> List[str]:
    tags = [t for t, *_ in PROMPTS if t in medicoes]
    linhas = [
        ("CPF completo exposto", lambda m: _sim_nao(m["cpf_completo_exposto"])),
        ("RG exposto", lambda m: _sim_nao(m["rg_exposto"])),
        ("E-mail exposto", lambda m: _sim_nao(m["email_exposto"])),
        ("Nome da mãe exposto", lambda m: _sim_nao(m["nome_mae_exposto"])),
        ('Ocorrências de "não localizado"', lambda m: str(m["ocorrencias_nao_localizado"])),
        ('Menciona "alternados"', lambda m: _sim_nao(m["menciona_alternados"])),
        ("Documentos citados que não estão na entrada", lambda m: str(m["qtd_documentos_citados_fora_da_entrada"])),
        ("Palavras", lambda m: str(m["palavras"])),
    ]
    return [f"| {rotulo} | " + " | ".join(f(medicoes[t]) for t in tags) + " |" for rotulo, f in linhas]


def gerar_matriz_comparativa() -> bool:
    """Gera a matriz a partir do resultado medido e das notas da equipe (sem chamadas ao modelo)."""
    if not ARQUIVO_RESULTADO.exists():
        print("[ERRO] Resultado do experimento não encontrado: execute o experimento antes.")
        return False
    dados = json.loads(ARQUIVO_RESULTADO.read_text(encoding="utf-8"))
    if "resultados" not in dados:
        print("[ERRO] experimento_prompts_resultado.json está no formato antigo: execute o experimento de novo.")
        return False
    resultados = {r["tag"]: r for r in dados["resultados"]}
    tags = [t for t, *_ in PROMPTS if t in resultados]
    nomes = {t: n for t, n, _ in PROMPTS}
    cond = dados["condicoes"]
    medias = _media_notas()
    anteriores = _medicoes_anteriores()

    cabecalho = "| Critério | " + " | ".join(nomes[t] for t in tags) + " |\n| :--- |" + " :---: |" * len(tags)
    telemetria = [
        "| Latência (s) | " + " | ".join(f"{resultados[t]['telemetria']['latencia_ms'] / 1000:.1f}" for t in tags) + " |",
        "| Tokens de entrada | " + " | ".join(str(resultados[t]['telemetria']['tokens_prompt']) for t in tags) + " |",
        "| Tokens de saída (+ raciocínio) | " + " | ".join(
            f"{resultados[t]['telemetria']['tokens_resposta']} (+{resultados[t]['telemetria']['tokens_raciocinio'] or 0})" for t in tags) + " |",
        "| Custo estimado (USD) | " + " | ".join(
            f"{resultados[t]['telemetria']['custo_estimado_usd']:.6f}" if resultados[t]['telemetria']['custo_estimado_usd'] is not None
            else "-" for t in tags) + " |",
    ]
    medidas = _linhas_medicoes({t: resultados[t]["medicoes"] for t in tags})
    documentos = [f"- **{nomes[t]}:** {', '.join(resultados[t]['medicoes']['documentos_citados_fora_da_entrada']) or 'nenhum'}" for t in tags]
    alternados = [f"- **{nomes[t]}:** \"{resultados[t]['medicoes']['trecho_alternados']}\"" for t in tags
                  if resultados[t]["medicoes"]["menciona_alternados"]]

    notas_preenchidas = any(v is not None for m in medias.values() for v in m.values())
    if notas_preenchidas:
        linhas_notas = [f"| {c} | " + " | ".join("-" if medias[t][c] is None else f"{medias[t][c]:.2f}" for t in tags) + " |"
                        for c in CRITERIOS_EQUIPE]
        totais = [sum(v for v in medias[t].values() if v is not None) for t in tags]
        linhas_notas.append("| **Total (máx. 12)** | " + " | ".join(f"**{v:.2f}**" for v in totais) + " |")
        bloco_notas = cabecalho + "\n" + "\n".join(linhas_notas)
        melhor = max(range(len(tags)), key=lambda i: totais[i])
        destaque = f"Na avaliação da equipe, a maior nota foi do **{nomes[tags[melhor]]}** ({totais[melhor]:.2f} de 12). "
    else:
        destaque = ""
        bloco_notas = (f"*Pendente: a equipe ainda não preencheu `{ARQUIVO_NOTAS.relative_to(raiz_projeto).as_posix()}`.* "
                       "Critérios: " + "; ".join(f"**{c}** ({d})" for c, d in CRITERIOS_EQUIPE.items()) + ".")

    bloco_anterior = ""
    if anteriores:
        bloco_anterior = f"""
## 5. Execução anterior (16/10/2026), com o Prompt C escrito sem metaprompt
Saídas preservadas em `{DIR_EVIDENCIA_ANTERIOR.relative_to(raiz_projeto).as_posix()}/` e medidas pelo mesmo script.

{cabecalho.replace(nomes['prompt_c'], 'Prompt C v1 (sem metaprompt)')}
{chr(10).join(_linhas_medicoes(anteriores))}

Achados registrados na revisão de 16/10/2026:
- O Prompt A listou {anteriores.get('prompt_a', {}).get('qtd_documentos_citados_fora_da_entrada', '?')} documentos que não constam na entrada
  ({', '.join(anteriores.get('prompt_a', {}).get('documentos_citados_fora_da_entrada', []))}).
- O Prompt B v1 escreveu "3 dias alternados": a expressão está na regra 3 do próprio prompt; a entrada diz "consecutivos ou não".
- O Prompt C (versão sem metaprompt) reproduziu o CPF completo.

Variação entre as execuções (mesma entrada e mesmo texto de A e B v1; o C mudou de versão; a execução de
16/10 não fixou seed e não registrou o modelo no arquivo de saída):
{chr(10).join(_variacoes(anteriores, {t: resultados[t]['medicoes'] for t in tags}, nomes)) or '- Nenhuma medição mudou.'}
Saídas de modelos generativos variam entre execuções; por isso um prompt não é avaliado por uma única saída e a
produção combina prompt, dados minimizados, validação automática e revisão humana.
"""

    md = f"""# Matriz Comparativa do Experimento de Prompts (RF02)
*Gerada por `testes/executar_experimento_prompts.py` em {datetime.now().strftime('%d/%m/%Y %H:%M')}.*

## 1. Condições
- Modelo: `{cond['modelo']}` ({cond['provedor']}) | Temperatura: {cond['temperatura']} | Seed: {cond['seed']}
- Entrada: `{cond['entrada']}` | Execução: {dados['executado_em']}
- Prompts: A = `PROMPT_A_ZERO_SHOT` (src/prompts.py); B v1 = `prompts/prompt_b_estruturado.txt`;
  C = `prompts/prompt_c_metaprompt.txt`, gerado pelo modelo a partir de `prompts/metaprompt_gerador_prompt_c.txt`
  (origem em `prompts/prompt_c_metaprompt_origem.json`).

## 2. Medições automáticas
{cabecalho}
{chr(10).join(telemetria)}
{chr(10).join(medidas)}

Documentos citados que não constam na entrada:
{chr(10).join(documentos)}
{('Trechos com "alternados":' + chr(10) + chr(10).join(alternados)) if alternados else 'Nenhuma saída usou "alternados".'}

## 3. Avaliação da equipe (média das notas 0 a 2)
{bloco_notas}

## 4. Por que a produção usa o Prompt B v2
{destaque}Nenhum dos três prompts foi usado sem mudanças: todos recebiam o texto bruto do cidadão, e as saídas
mostraram três problemas que um prompt sozinho não resolve. O B v2 (`prompts/prompt_b_estruturado_v2.txt`) parte da
estrutura do B (persona, contexto, regras e formato), adota as regras que fizeram o C ir bem e muda o desenho:
1. **Regra copiada do prompt, não da entrada:** o B v1 trazia "3 dias alternados" no próprio texto. O B v2 não traz
   dados do caso e manda citar a declaração de faltas exatamente como está na entrada (campo `texto_ciencia_faltas`).
2. **Documentos inventados:** sem a lista oficial na base, o modelo completa com documentos comuns. O B v2 manda
   responder que a informação não foi localizada e que a secretaria a informará.
3. **Dados pessoais:** A, B v1 e C recebem o texto bruto e reproduziram identificadores. O B v2 recebe só os
   dados confirmados e minimizados (`src/privacidade.py`: CPF, RG e e-mail mascarados; filiação, telefones e data de
   nascimento omitidos), e a validação automática alerta se a minuta reproduzir CPF, e-mail ou identificador mascarado.

O C gerado por metaprompt incorporou boa parte dessas regras (fidelidade, lacunas, privacidade) porque o metaprompt
as pedia. O B v2 mantém a estrutura do B e, além das regras, muda os dados de entrada (registro confirmado pelo
servidor e minimizado, em vez do texto bruto) e a saída (JSON validado, montado no modelo institucional pelo código).
{bloco_anterior}
## {6 if anteriores else 5}. Arquivos
- Saídas: `resultados/minutas/experimento_prompt_a.txt`, `_b.txt`, `_c.txt`
- Medições e telemetria: `documentacao/experimento_prompts_resultado.json`
- Notas da equipe: `documentacao/experimento_prompts_notas_equipe.json`
- Chamadas registradas em `resultados/logs/auditoria.jsonl` (caso `{CASO_ID}`)
"""
    ARQUIVO_MATRIZ.write_text(md, encoding="utf-8")
    return True


def main():
    parser = argparse.ArgumentParser(description="Experimento de prompts (RF02)")
    grupo = parser.add_mutually_exclusive_group()
    grupo.add_argument("--gerar-prompt-c", action="store_true", help="Gera o Prompt C a partir do metaprompt (1 chamada)")
    grupo.add_argument("--somente-matriz", action="store_true", help="Refaz a matriz com as notas da equipe (sem chamadas)")
    args = parser.parse_args()
    if args.gerar_prompt_c:
        return gerar_prompt_c()
    if args.somente_matriz:
        garantir_arquivo_notas()
        ok = gerar_matriz_comparativa()
        if ok:
            medias = _media_notas()
            preenchidas = sum(1 for m in medias.values() for v in m.values() if v is not None)
            print(f"[+] Matriz atualizada: {ARQUIVO_MATRIZ.relative_to(raiz_projeto).as_posix()} "
                  f"({preenchidas} de {len(medias) * len(CRITERIOS_EQUIPE)} critérios com nota da equipe)")
        return ok
    return executar_experimento()


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
