#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
==============================================================================
LIMPEZA DOS RESULTADOS ANTES DA EXECUÇÃO FINAL
==============================================================================
Remove saídas do pipeline (dados processados, minutas, áudios, imagens,
decisões e o log das execuções) para que a entrega contenha apenas a execução
final feita pela equipe.

Preserva o experimento RF02: resultados/minutas/experimento_prompt_*.txt e as
linhas do log do caso RF02_EXPERIMENTO_PROMPTS (refazê-lo consome cota).
Não toca em dados/originais, dados/gabaritos, prompts nem documentacao.

Uso: python limpar_resultados.py          (pede confirmação)
     python limpar_resultados.py --sim    (sem confirmação)
==============================================================================
"""

import sys
import json
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
CASO_PRESERVADO = "RF02_EXPERIMENTO_PROMPTS"


def arquivos_a_remover():
    alvos = []
    alvos += [p for p in (RAIZ / "dados" / "processados").rglob("*") if p.is_file()]
    alvos += [p for p in (RAIZ / "resultados" / "minutas").glob("*") if p.is_file() and not p.name.startswith("experimento_")]
    alvos += [p for p in (RAIZ / "resultados" / "audios").glob("*") if p.is_file()]
    alvos += [p for p in (RAIZ / "resultados" / "imagens").glob("*") if p.is_file()]
    alvos += [p for p in (RAIZ / "resultados" / "logs").glob("decisoes_*.json")]
    return [p for p in alvos if not p.name.startswith(".")]


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
        if registro.get("caso_id") == CASO_PRESERVADO and "etapa" in registro:
            preservadas.append(linha)

    print(f"Arquivos a remover: {len(alvos)}")
    for alvo in alvos:
        print(f"  - {alvo.relative_to(RAIZ).as_posix()}")
    print(f"Log de auditoria: {len(linhas)} linha(s) -> {len(preservadas)} preservada(s) do experimento RF02")
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
    print("Limpeza concluída. Execute o fluxo final (README, seção 7) e depois: python resumir_auditoria.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
