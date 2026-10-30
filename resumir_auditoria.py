#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
==============================================================================
RESUMO DA AUDITORIA: MODELOS, VERSÕES, TOKENS E CUSTOS REAIS (RF11, RF21)
==============================================================================
Lê resultados/logs/auditoria.jsonl e gera documentacao/resumo_execucoes.md com:
- chamadas, falhas, tokens e custo por provedor e modelo (Desafio 01 e 02);
- modelos e provedores efetivamente chamados, por etapa;
- versões dos prompts usadas;
- latência, tokens e custo estimado (somados e médios) por etapa;
- falhas registradas.
Os números vêm só do log; nada é estimado por fora.
Uso: python resumir_auditoria.py
==============================================================================
"""

import json
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

RAIZ = Path(__file__).resolve().parent
ARQUIVO_LOG = RAIZ / "resultados" / "logs" / "auditoria.jsonl"
ARQUIVO_SAIDA = RAIZ / "documentacao" / "resumo_execucoes.md"


def carregar_registros() -> List[Dict[str, Any]]:
    """Registros no formato atual (com 'etapa'); linhas inválidas são ignoradas."""
    if not ARQUIVO_LOG.exists():
        return []
    registros = []
    for linha in ARQUIVO_LOG.read_text(encoding="utf-8").splitlines():
        try:
            registro = json.loads(linha)
        except json.JSONDecodeError:
            continue
        if "etapa" in registro:
            registros.append(registro)
    return registros


def _soma(valores) -> float:
    return sum(v for v in valores if isinstance(v, (int, float)))


def _custo(registros: List[Dict[str, Any]]) -> str:
    """Soma dos custos conhecidos; chamadas a modelo sem preço configurado não viram zero."""
    com_ia = [r for r in registros if r.get("usou_modelo_ia") and r.get("tokens_total") is not None]
    sem_preco = [r for r in com_ia if r.get("custo_estimado_usd") is None]
    conhecidos = [r["custo_estimado_usd"] for r in com_ia if r.get("custo_estimado_usd") is not None]
    if com_ia and not conhecidos:
        return "não estimado (modelo sem preço configurado)"
    texto = f"US$ {sum(conhecidos):.6f}"
    if sem_preco:
        texto += f" (parcial: {len(sem_preco)} chamada(s) sem preço configurado)"
    return texto


def gerar_resumo() -> str:
    registros = carregar_registros()
    if not registros:
        return "# Resumo das Execuções\n\nNenhum registro em `resultados/logs/auditoria.jsonl`.\n"

    por_etapa: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for r in registros:
        por_etapa[r["etapa"]].append(r)

    linhas_etapas = []
    for etapa, itens in sorted(por_etapa.items()):
        sucesso = [i for i in itens if i.get("sucesso")]
        modelos = sorted({f"{i.get('provedor')}/{i.get('modelo')}" for i in itens if i.get("modelo")}) or ["sem modelo"]
        prompts = sorted({f"{i['prompt']['id']} v{i['prompt']['versao']}" for i in itens if i.get("prompt") and i["prompt"].get("id")})
        latencias = [i["duracao_ms"] for i in sucesso if isinstance(i.get("duracao_ms"), (int, float))]
        latencia = f"{sum(latencias) / len(latencias) / 1000:.1f} s" if latencias else "-"
        colunas = [
            etapa,
            f"{len(itens)} ({len(itens) - len(sucesso)} falha)",
            ", ".join(modelos),
            ", ".join(prompts) or "-",
            latencia,
            str(int(_soma(i.get("tokens_prompt") for i in sucesso))),
            str(int(_soma(i.get("tokens_resposta") for i in sucesso))),
            str(int(_soma(i.get("tokens_raciocinio") for i in sucesso))),
            _custo(sucesso),
        ]
        linhas_etapas.append("| " + " | ".join(colunas) + " |")

    chamadas_ia = [r for r in registros if r.get("usou_modelo_ia") and r.get("sucesso") and r.get("tokens_total") is not None]
    falhas = [r for r in registros if not r.get("sucesso")]
    linhas_falhas = [f"| {r['timestamp'][:19]} | {r['etapa']} | {r.get('modelo') or '-'} | {r.get('codigo_erro')} | "
                     f"{str(r.get('mensagem_erro') or '')[:90].replace('|', '/')} |" for r in falhas]

    execucoes_minuta = [r for r in registros if r["etapa"] in ("geracao_minuta", "rag_resposta") and r.get("sucesso")]

    por_modelo: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for r in registros:
        if r.get("provedor") not in (None, "nenhum"):
            por_modelo[f"{r['provedor']}/{r.get('modelo') or '-'}"].append(r)
    linhas_modelos = []
    for chave, itens in sorted(por_modelo.items()):
        sucesso = [i for i in itens if i.get("sucesso")]
        custo = "indisponível (simulado: sem tokens nem custo)" if chave.startswith("simulado/") else _custo(sucesso)
        linhas_modelos.append(f"| {chave} | {len(itens)} | {len(itens) - len(sucesso)} | "
                              f"{int(_soma(i.get('tokens_total') for i in sucesso))} | {custo} |")

    inicio = min(r["timestamp"] for r in registros)[:19]
    fim = max(r["timestamp"] for r in registros)[:19]
    configuracao = json.loads((RAIZ / "config.json").read_text(encoding="utf-8")).get("llm", {})
    precos = configuracao.get("custo_estimado_por_1k_tokens", {})
    modelo_precificado = precos.get("modelo", configuracao.get("modelo_padrao"))
    openai = configuracao.get("openai", {})
    precos_openai = "; ".join(f"`{m}` US$ {p['entrada']} / {p['saida']}" for m, p in openai.get("precos_por_1m_tokens_usd", {}).items())

    return f"""# Resumo das Execuções (gerado do log de auditoria)
*Gerado por `resumir_auditoria.py` em {datetime.now().strftime('%d/%m/%Y %H:%M')} a partir de `resultados/logs/auditoria.jsonl`.*

- Período coberto: {inicio} a {fim}
- Registros: {len(registros)} | chamadas a modelo de IA com sucesso: {len(chamadas_ia)} | falhas: {len(falhas)}
- Minutas e respostas do RAG geradas: {len(execucoes_minuta)}
- Desafio 02 (OpenAI): custo estimado pelo próprio adaptador com os preços do `config.json` por 1M de tokens
  (entrada / saída, raciocínio cobrado como saída): {precos_openai} ({openai.get('fonte_precos')}).
  O adaptador simulado não mede tokens nem custo: aparece como "indisponível", nunca como zero.
- Desafio 01 (Gemini, legado): preço só para `{modelo_precificado}`: US$ {precos.get('input_usd')} (entrada) e
  US$ {precos.get('output_usd')} (saída e raciocínio) por 1.000 tokens ({precos.get('fonte')}, consultado em
  {precos.get('consultado_em')}). No nível gratuito o custo efetivo é zero.

## Por provedor e modelo
| Provedor/modelo | Registros | Falhas | Tokens | Custo estimado (USD) |
| :--- | ---: | ---: | ---: | ---: |
{chr(10).join(linhas_modelos)}

## Por etapa
| Etapa | Registros | Provedor/modelo | Prompt (versão) | Latência média | Tokens entrada | Tokens saída | Tokens raciocínio | Custo estimado (USD) |
| :--- | :---: | :--- | :--- | :---: | ---: | ---: | ---: | ---: |
{chr(10).join(linhas_etapas)}

**Total estimado:** {_custo([r for r in registros if r.get('sucesso')])} em
{int(_soma(r.get('tokens_total') for r in chamadas_ia))} tokens.

## Falhas registradas
Inclui as falhas provocadas de propósito para testar limites e a falha do serviço (T05, T12); cada uma foi tratada
(bloqueio ou recusa padronizada) e está registrada com código e mensagem.

{('| Data | Etapa | Modelo | Código | Mensagem |' + chr(10) + '| :--- | :--- | :--- | :--- | :--- |' + chr(10) + chr(10).join(linhas_falhas)) if linhas_falhas else 'Nenhuma.'}
"""


def main() -> int:
    conteudo = gerar_resumo()
    ARQUIVO_SAIDA.write_text(conteudo, encoding="utf-8")
    print(conteudo)
    print(f"[+] Resumo gravado em {ARQUIVO_SAIDA.relative_to(RAIZ).as_posix()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
