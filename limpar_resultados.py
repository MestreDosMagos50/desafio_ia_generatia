#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
==============================================================================
LIMPEZA DOS ARTEFATOS DO PIPELINE DO DESAFIO 01 ANTES DE UMA NOVA EXECUÇÃO
==============================================================================
Remove saídas do pipeline do Desafio 01 (dados processados, minutas, áudios,
imagens, decisões do Desafio 01 e as linhas do log desses casos) para que a
execução seguinte do pipeline comece limpa.

Preserva:
- o experimento RF02 (resultados/minutas/experimento_prompt_*.txt e as linhas
  do caso RF02_EXPERIMENTO_PROMPTS; refazê-lo consome cota);
- toda a evidência do Desafio 02: resultados/nlp, metricas (com historico),
  guardrails, indice, rag, sentimentos, atendimentos e regressao, o índice
  (indice/), as decisões do operador (decisoes_humanas_desafio02.json) e as
  linhas do log que não são dos casos do pipeline do Desafio 01.
As linhas removidas são as dos casos CASO_* e RF10_CARTAZ. Rodar depois da
regressão T15 apaga as linhas e os intermediários dela; o resumo e as cópias
das evidências ficam em resultados/metricas/regressao_t15.* e
resultados/regressao/. Não toca em dados/originais, gabaritos, prompts nem
documentacao.

Uso: python limpar_resultados.py          (pede confirmação)
     python limpar_resultados.py --sim    (sem confirmação)
==============================================================================
"""

import sys
import json
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
PREFIXOS_DO_PIPELINE_DESAFIO01 = ("CASO_", "RF10_CARTAZ")
DECISOES_PRESERVADAS = ("decisoes_humanas_desafio02.json",)


def arquivos_a_remover():
    alvos = []
    alvos += [p for p in (RAIZ / "dados" / "processados").rglob("*") if p.is_file()]
    alvos += [p for p in (RAIZ / "resultados" / "minutas").glob("*") if p.is_file() and not p.name.startswith("experimento_")]
    alvos += [p for p in (RAIZ / "resultados" / "audios").glob("*") if p.is_file()]
    alvos += [p for p in (RAIZ / "resultados" / "imagens").glob("*") if p.is_file()]
    alvos += [p for p in (RAIZ / "resultados" / "logs").glob("decisoes_*.json") if p.name not in DECISOES_PRESERVADAS]
    return [p for p in alvos if not p.name.startswith(".")]


def linha_do_pipeline_desafio01(registro: dict) -> bool:
    return str(registro.get("caso_id") or "").startswith(PREFIXOS_DO_PIPELINE_DESAFIO01)


def main() -> int:
    alvos = arquivos_a_remover()
    log = RAIZ / "resultados" / "logs" / "auditoria.jsonl"
    linhas = log.read_text(encoding="utf-8").splitlines() if log.exists() else []
    preservadas = []
    for linha in linhas:
        try:
            registro = json.loads(linha)
        except json.JSONDecodeError:
            continue
        if "etapa" in registro and not linha_do_pipeline_desafio01(registro):
            preservadas.append(linha)

    print(f"Arquivos a remover: {len(alvos)}")
    for alvo in alvos:
        print(f"  - {alvo.relative_to(RAIZ).as_posix()}")
    print(f"Log de auditoria: {len(linhas)} linha(s) -> {len(preservadas)} preservada(s) "
          "(experimento RF02 e evidências do Desafio 02)")
    if "--sim" not in sys.argv and input("Confirmar a limpeza? [s/n]: ").strip().lower() != "s":
        print("Nada foi alterado.")
        return 1

    for alvo in alvos:
        alvo.unlink()
    if log.exists():
        log.write_text("".join(l + "\n" for l in preservadas), encoding="utf-8")
    (RAIZ / "resultados" / "logs" / "decisoes_humanas.json").write_text("[]\n", encoding="utf-8")

    sys.path.insert(0, str(RAIZ))
    from src.audit import AuditManager
    AuditManager().gerar_relatorio_qualidade()
    print("Limpeza concluída. Execute o pipeline do Desafio 01 (README) e depois: python resumir_auditoria.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
