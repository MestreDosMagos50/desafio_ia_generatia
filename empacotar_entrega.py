#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
==============================================================================
EMPACOTADOR AUTOMATIZADO DO PROJETO PARA ENTREGA (.ZIP)
==============================================================================
Gera o pacote final 'Desafio02-FICDEV-IAGenerativa.zip' excluindo estritamente:
- Arquivos de credenciais (.env) e configuração local do Streamlit (.streamlit);
- Documentos reais de referência (contexto/): não podem ir junto ao índice;
- Banco local do índice (indice/chroma/): recriado com python -m src.main --modo indexar
  (o manifesto vai no pacote e mantém as exclusões registradas);
- Diretórios de cache (__pycache__, .pytest_cache);
- Ambientes virtuais (venv, .venv);
- Repositório local (.git).
==============================================================================
"""

import os
import zipfile
from pathlib import Path

raiz_projeto = Path(__file__).resolve().parent
dir_workspace = raiz_projeto.parent
caminho_zip = dir_workspace / "Desafio02-FICDEV-IAGenerativa.zip"

PADROES_IGNORADOS = [
    ".env",
    "contexto",
    ".streamlit",
    "__pycache__",
    ".pytest_cache",
    ".git",
    "venv",
    ".venv",
    ".DS_Store",
    "Thumbs.db",
    "*.pyc"
]


def deve_ignorar(caminho: Path) -> bool:
    nome = caminho.name
    partes = caminho.relative_to(raiz_projeto).parts if caminho.is_relative_to(raiz_projeto) else caminho.parts
    if nome == ".env" or nome.endswith(".env"):
        return True
    if any(p in partes for p in ["contexto", ".streamlit", "__pycache__", ".pytest_cache", ".git", "venv", ".venv"]):
        return True
    if "indice" in partes and "chroma" in partes:
        return True
    if nome.endswith(".pyc") or nome in [".DS_Store", "Thumbs.db"]:
        return True
    return False


def empacotar():
    print("=" * 75)
    print("  EMPACOTAMENTO DO DESAFIO PRÁTICO 2 (FIC_DEV)")
    print("=" * 75)
    print(f"• Origem: {raiz_projeto}")
    print(f"• Destino do Arquivo Compactado: {caminho_zip}")

    total_arquivos = 0
    tamanho_total = 0

    with zipfile.ZipFile(caminho_zip, "w", zipfile.ZIP_DEFLATED) as zipf:
        for root, dirs, files in os.walk(raiz_projeto):
            # Filtra diretórios ignorados
            dirs[:] = [d for d in dirs if not deve_ignorar(Path(root) / d)]

            for file in files:
                caminho_completo = Path(root) / file
                if deve_ignorar(caminho_completo):
                    print(f"  [IGNORADO POR SEGURANÇA] {caminho_completo.name}")
                    continue

                # Caminho relativo dentro do ZIP (iniciando em desafio_ia_generativa/)
                rel_path = caminho_completo.relative_to(raiz_projeto)
                zip_path = Path("desafio_ia_generativa") / rel_path

                zipf.write(caminho_completo, arcname=str(zip_path))
                total_arquivos += 1
                tamanho_total += caminho_completo.stat().st_size

    tamanho_zip_mb = caminho_zip.stat().st_size / (1024 * 1024)
    print(f"\n[SUCESSO] Pacote gerado com êxito!")
    print(f"• Total de arquivos incluídos: {total_arquivos}")
    print(f"• Tamanho compactado (.zip): {tamanho_zip_mb:.2f} MB")
    print("=" * 75)
    print("INSTRUÇÕES DE ENVIO POR E-MAIL:")
    print("  • Destinatário: ficdev00@gmail.com")
    print("  • Assunto do E-mail: Desafio02-FICDEV-IAGenerativa")
    print("  • Anexo: Desafio02-FICDEV-IAGenerativa.zip")
    print("  • Prazo Limite: conforme o comunicado oficial do Desafio 02 (não informado no enunciado)")
    print("=" * 75)


if __name__ == "__main__":
    empacotar()
