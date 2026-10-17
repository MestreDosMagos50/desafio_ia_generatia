#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
==============================================================================
INTERFACE DE REVISÃO HUMANA NO TERMINAL (HUMAN-IN-THE-LOOP)
Atende aos requisitos RF06, RF07, RF08, RF09, RF10 e RF13.
==============================================================================
Decisões registradas (objeto revisado):
- transcricao_audio: aprovação ou rejeição da transcrição revisada;
- ficha: confirmação, correção ou rejeição da leitura da ficha manuscrita;
- conferencia_cruzada: valores confirmados dos campos críticos entre canais;
- minuta: aprovar, rejeitar, corrigir um campo (minuta gerada de novo) ou
  pedir nova geração; cada nova geração é uma execução ligada à anterior;
- cartaz: checklist visual e aprovação ou rejeição da peça.
Os menus não têm opção padrão: resposta vazia repete a pergunta.
No modo demonstração as decisões são simuladas, identificadas como SIMULADO
e gravadas em arquivo separado (fora da taxa de aprovação).
==============================================================================
"""

import os
import re
import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from src.conferencia import NAO_LOCALIZADO, obter, definir
from src.prompts import PROMPT_TRANSCRICAO_AUDIO, VERSOES_PROMPTS

OPERADOR_DEMO = "SIMULADO - demonstração automatizada (sem revisão humana)"
ROTULOS_FONTE = {"texto": "Texto", "ficha": "Ficha", "audio": "Áudio"}
TERMOS_BLOQUEANTES_DEMO = ("inventada", "CPF", "e-mail", "termo de decisão", "prompt injection")
GRAVIDADES = ("BAIXA", "MEDIA", "ALTA", "CRITICA")

# Campos da ficha mostrados na confirmação humana: identificador -> caminho na versão revisada
CAMPOS_CRITICOS_FICHA = {
    "codigo": "codigo_matricula",
    "data_matricula": "data_matricula",
    "nome": "solicitante.nome_completo",
    "data_nascimento": "solicitante.data_nascimento",
    "cpf": "solicitante.cpf",
    "rg": "solicitante.rg",
    "nome_mae": "solicitante.nome_mae",
    "email": "solicitante.email",
    "curso": "curso.nome",
    "turno": "curso.turno",
    "inicio_curso": "curso.inicio_curso",
}

# Campos do registro que o revisor pode corrigir antes de gerar a minuta de novo
CAMPOS_EDITAVEIS_MINUTA = [
    "protocolo", "data_solicitacao",
    "solicitante.nome_completo", "solicitante.data_nascimento", "solicitante.cpf", "solicitante.rg",
    "solicitante.orgao_expedidor", "solicitante.uf", "solicitante.nome_mae", "solicitante.nome_pai",
    "solicitante.email", "solicitante.telefone_celular", "solicitante.telefone_residencial",
    "curso.nome", "curso.eixo_tecnologico", "curso.carga_horaria", "curso.turno", "curso.data_inicio",
    "texto_ciencia_faltas",
]

CHECKLIST_CARTAZ = {
    "ilustracao_sem_texto_letras_ou_logotipos": "A ilustração não contém texto, letras, números ou logotipos?",
    "objetos_e_formas_coerentes": "Objetos e formas estão coerentes (sem deformações, mãos ou objetos impossíveis)?",
    "sem_pessoa_real_ou_rosto_identificavel": "Não há pessoa real ou rosto identificável?",
    "brasao_e_cores_institucionais_corretos": "O brasão e as cores institucionais estão corretos e sem distorção?",
    "textos_conferidos_com_as_fontes": "Os textos do cartaz conferem com as fontes (dados confirmados e ficha)?",
}

_operador_identificado: Optional[str] = None


# ------------------------------------------------------------------------------
# Entrada no terminal
# ------------------------------------------------------------------------------
def _perguntar(mensagem: str, opcoes: Tuple[str, ...]) -> str:
    """Repete a pergunta até receber uma das opções válidas (sem resposta padrão)."""
    while True:
        resposta = input(mensagem).strip().lower()
        if resposta in opcoes:
            return resposta
        print(f"  Opção inválida. Responda com: {', '.join(opcoes)}")


def _texto_obrigatorio(mensagem: str) -> str:
    while True:
        resposta = input(mensagem).strip()
        if resposta:
            return resposta
        print("  Este campo é obrigatório.")


def _perguntar_gravidade() -> str:
    print("  Gravidade do problema: [1] BAIXA  [2] MEDIA  [3] ALTA  [4] CRITICA")
    return GRAVIDADES[int(_perguntar("  Gravidade [1-4]: ", ("1", "2", "3", "4"))) - 1]


def obter_operador(auto_demo: bool) -> str:
    """Identificação do revisor (pedida uma vez por execução; pode vir da variável REVISOR)."""
    global _operador_identificado
    if auto_demo:
        return OPERADOR_DEMO
    if _operador_identificado is None:
        _operador_identificado = os.getenv("REVISOR", "").strip() or _texto_obrigatorio(
            "\n  Identificação do revisor (ex.: Estudante 1 - revisor; não use dados pessoais reais): "
        )
    return _operador_identificado


def _registrar(audit, id_execucao: str, caso_id: str, objeto: str, decisao: str, justificativa: str,
               gravidade: str, auto_demo: bool, alteracoes: Optional[List[str]] = None) -> str:
    operador = obter_operador(auto_demo)
    audit.registrar_decisao_humana(
        id_execucao=id_execucao, caso_id=caso_id, objeto=objeto, decisao=decisao, operador=operador,
        justificativa=justificativa, gravidade_erros_detectados=gravidade, simulada=auto_demo, alteracoes=alteracoes
    )
    print(f"  -> Decisão registrada ({objeto}): {decisao} | {operador}")
    return decisao


def _editar_campo(dados: Dict[str, Any], caminhos: List[str], rotulo: Callable[[str], str] = lambda c: c) -> Optional[str]:
    """
    Mostra os campos numerados, pede o campo e o novo valor e aplica em `dados`.
    Retorna a descrição da alteração ou None se o valor digitado for igual ao atual.
    """
    for indice, caminho in enumerate(caminhos, 1):
        print(f"   [{indice:2}] {rotulo(caminho):28} {str(obter(dados, caminho, NAO_LOCALIZADO))[:60]}")
    escolha = _perguntar("  Número do campo: ", tuple(str(i) for i in range(1, len(caminhos) + 1)))
    caminho = caminhos[int(escolha) - 1]
    antigo = str(obter(dados, caminho, NAO_LOCALIZADO))
    novo = _texto_obrigatorio(f"  Novo valor para {rotulo(caminho)} (digite 'não localizado' se ausente): ")
    if novo == antigo:
        print("  Valor igual ao atual: nada foi alterado.")
        return None
    definir(dados, caminho, novo)
    return f"{caminho}: '{antigo}' -> '{novo}'"


# ------------------------------------------------------------------------------
# Transcrição do áudio (RF06)
# ------------------------------------------------------------------------------
def revisar_transcricao_audio(audit, res_audio: Dict[str, Any], id_execucao: str, caso_id: str, auto_demo: bool) -> str:
    """Decisão humana sobre a transcrição revisada (RF06). Retorna APROVADO ou REJEITADO."""
    comparacao = res_audio.get("comparacao_gabarito", {})
    erros = comparacao.get("erros_relevantes_revisada", [])
    revisada = res_audio.get("transcricao_revisada", "")

    print("\n[REVISÃO HUMANA - TRANSCRIÇÃO DO ÁUDIO (RF06)]")
    print("• Arquivos: dados/processados/transcricao_bruta.txt e transcricao_revisada.txt")
    print(f"• WER em relação à referência: bruta {comparacao.get('wer_bruta_pct')}% | revisada {comparacao.get('wer_revisada_pct')}%")
    print(f"• Diferenças relevantes na versão revisada (números, e-mail, nomes): {len(erros)}")
    for erro in erros[:10]:
        print(f"  - {erro['tipo']}: referência '{erro['referencia']}' | transcrição '{erro['transcricao']}'")
    marcacoes = revisada.count("[INCERTO") + revisada.count("[INAUDÍVEL")
    if marcacoes:
        print(f"• Trechos marcados como incertos ou inaudíveis: {marcacoes}")

    if auto_demo:
        if erros:
            return _registrar(audit, id_execucao, caso_id, "transcricao_audio", "REJEITADO",
                              f"Política simulada: {len(erros)} diferença(s) relevante(s) em relação à referência.", "MEDIA", True)
        return _registrar(audit, id_execucao, caso_id, "transcricao_audio", "APROVADO",
                          "Política simulada: sem diferenças relevantes em relação à referência.", "NENHUMA", True)

    print(f"\n  Transcrição revisada:\n  {revisada}\n")
    print("  [1] Aprovar a transcrição revisada (os dados do áudio entram na conferência)")
    print("  [2] Rejeitar (os dados do áudio não serão usados)")
    if _perguntar("  Sua decisão [1 ou 2]: ", ("1", "2")) == "1":
        justificativa = input("  Observação (opcional): ").strip() or "Transcrição revisada conferida pelo revisor."
        return _registrar(audit, id_execucao, caso_id, "transcricao_audio", "APROVADO", justificativa,
                          "BAIXA" if erros else "NENHUMA", False)
    justificativa = _texto_obrigatorio("  Justificativa da rejeição: ")
    return _registrar(audit, id_execucao, caso_id, "transcricao_audio", "REJEITADO", justificativa, _perguntar_gravidade(), False)


# ------------------------------------------------------------------------------
# Leitura da ficha (RF08)
# ------------------------------------------------------------------------------
def revisar_ficha(audit, res_visao: Dict[str, Any], id_execucao: str, caso_id: str, auto_demo: bool,
                  dir_processados: Path) -> Optional[Dict[str, Any]]:
    """
    Confirmação humana dos dados críticos lidos da ficha (critério de aceite do RF08).
    Retorna a versão confirmada (salva em visao_confirmada.json) ou None se a leitura for rejeitada.
    """
    revisada = json.loads(json.dumps(res_visao["dados_revisados"]))
    incertos = {t["campo"]: t for t in revisada.get("trechos_incertos", [])}
    nao_sinalizados = res_visao.get("comparacao_gabarito", {}).get("incertos_esperados", {}).get("nao_sinalizados", [])

    print("\n[CONFIRMAÇÃO HUMANA - LEITURA DA FICHA MANUSCRITA (RF08)]")
    print("• Imagem original: dados/originais/entrada_pdf-imagem.pdf | leitura: dados/processados/visao_bruta.txt")
    for campo, caminho in CAMPOS_CRITICOS_FICHA.items():
        situacao = f"[{incertos[campo]['situacao']}] {incertos[campo]['observacao']}" if campo in incertos else ""
        print(f"  {campo:16} {str(obter(revisada, caminho, NAO_LOCALIZADO))[:45]:47}{situacao}")
    if nao_sinalizados:
        print(f"  [!] O gabarito espera dúvida de leitura em: {', '.join(nao_sinalizados)} (o modelo não sinalizou). Confira na imagem.")

    alteracoes: List[str] = []
    pendentes: List[str] = []
    if auto_demo:
        decisao = _registrar(audit, id_execucao, caso_id, "ficha", "APROVADO",
                             f"Política simulada: leitura aceita sem conferência visual ({len(incertos)} campo(s) incerto(s)).",
                             "BAIXA" if incertos else "NENHUMA", True)
    else:
        # Campos com dúvida (sinalizados pelo modelo ou esperados pelo gabarito): conferência obrigatória, um a um
        duvidosos = [c for c in CAMPOS_CRITICOS_FICHA if c in incertos or c in nao_sinalizados]
        if duvidosos:
            print("\n  Confira na imagem cada campo com dúvida de leitura:")
        for campo in duvidosos:
            caminho = CAMPOS_CRITICOS_FICHA[campo]
            atual = str(obter(revisada, caminho, NAO_LOCALIZADO))
            print(f"\n  {campo}: '{atual}'" + (f" — {incertos[campo]['observacao']}" if campo in incertos else ""))
            escolha = _perguntar("  [s] confere com a imagem  [c] corrigir  [p] deixar pendente: ", ("s", "c", "p"))
            if escolha == "c":
                novo = _texto_obrigatorio(f"  Valor correto de {campo}: ")
                if novo != atual:
                    definir(revisada, caminho, novo)
                    alteracoes.append(f"{caminho}: '{atual}' -> '{novo}'")
            elif escolha == "p":
                pendentes.append(campo)
        while True:
            print("\n  [1] Confirmar a leitura  [2] Corrigir um campo  [3] Rejeitar a leitura (a ficha não entra na conferência)")
            escolha = _perguntar("  Sua decisão [1, 2 ou 3]: ", ("1", "2", "3"))
            if escolha == "2":
                alteracao = _editar_campo(revisada, list(CAMPOS_CRITICOS_FICHA.values()), lambda c: c.split(".")[-1])
                if alteracao:
                    alteracoes.append(alteracao)
                continue
            if escolha == "3":
                justificativa = _texto_obrigatorio("  Justificativa da rejeição: ")
                _registrar(audit, id_execucao, caso_id, "ficha", "REJEITADO", justificativa, _perguntar_gravidade(), False)
                return None
            break
        sufixo = f" Pendentes de confirmação: {', '.join(pendentes)}." if pendentes else ""
        if pendentes:
            # Campo pendente não é aprovado: a decisão fica PENDENTE (não final) e o campo sai da conferência
            justificativa = ((input("  Observação (opcional): ").strip() or "Leitura conferida com a imagem.")
                             + (" Campos corrigidos: " + "; ".join(alteracoes) + "." if alteracoes else "") + sufixo)
            decisao = _registrar(audit, id_execucao, caso_id, "ficha", "PENDENTE", justificativa, "BAIXA", False, alteracoes)
            print("  -> Campos pendentes ficam como 'não localizado' até nova conferência: " + ", ".join(pendentes))
        elif alteracoes:
            justificativa = "Leitura conferida com a imagem; campos corrigidos: " + "; ".join(alteracoes) + sufixo
            decisao = _registrar(audit, id_execucao, caso_id, "ficha", "CORRIGIDO_MANUALMENTE", justificativa,
                                 _perguntar_gravidade(), False, alteracoes)
        else:
            justificativa = (input("  Observação (opcional): ").strip() or "Campos críticos conferidos com a imagem da ficha.") + sufixo
            decisao = _registrar(audit, id_execucao, caso_id, "ficha", "APROVADO", justificativa,
                                 "BAIXA" if pendentes else "NENHUMA", False)

    valores_pendentes = {}
    for campo in pendentes:
        valores_pendentes[campo] = obter(revisada, CAMPOS_CRITICOS_FICHA[campo], NAO_LOCALIZADO)
        definir(revisada, CAMPOS_CRITICOS_FICHA[campo], NAO_LOCALIZADO)
    revisada["confirmacao_humana"] = {"decisao": decisao, "alteracoes": alteracoes, "pendentes": pendentes,
                                      "valores_lidos_pendentes": valores_pendentes, "simulada": auto_demo,
                                      "revisor": obter_operador(auto_demo), "data": datetime.now().isoformat(timespec="seconds")}
    (dir_processados / "visao_confirmada.json").write_text(json.dumps(revisada, indent=2, ensure_ascii=False), encoding="utf-8")
    return revisada


# ------------------------------------------------------------------------------
# Conferência cruzada (RF06 / RF08)
# ------------------------------------------------------------------------------
def conferir_dados_criticos(
    audit,
    conferencia: List[Dict[str, Any]],
    pontos_atencao: List[str],
    id_execucao: str,
    caso_id: str,
    auto_demo: bool
) -> Dict[str, Any]:
    """Conferência humana dos campos críticos entre canais antes da minuta. Retorna {campo: valor confirmado}."""
    fontes = [f for f in ("texto", "ficha", "audio") if any(f in c["valores"] for c in conferencia)]
    print("\n[CONFERÊNCIA HUMANA DOS DADOS CRÍTICOS (RF06 / RF08)]")
    print("  " + f"{'Campo':17}" + "".join(f"{ROTULOS_FONTE[f]:36}" for f in fontes) + "Situação")
    for item in conferencia:
        valores = "".join(f"{str(item['valores'].get(f, '-'))[:34]:36}" for f in fontes)
        print(f"  {item['campo']:17}{valores}{item['status']}")
    if pontos_atencao:
        print("\n  Pontos de atenção:")
        for ponto in pontos_atencao:
            print(f"  [!] {ponto}")

    confirmados = {item["campo"]: item["valor_sugerido"] for item in conferencia}
    divergentes = [item for item in conferencia if item["status"] == "DIVERGENTE"]
    alteracoes: List[str] = []

    if auto_demo:
        justificativa = "Política simulada: valores sugeridos (maioria entre os canais) aceitos automaticamente."
        if divergentes:
            justificativa += f" Divergências: {', '.join(item['campo'] for item in divergentes)}."
        _registrar(audit, id_execucao, caso_id, "conferencia_cruzada", "APROVADO", justificativa,
                   "MEDIA" if divergentes else "NENHUMA", True)
        return confirmados

    for item in divergentes:
        print(f"\n  Divergência em '{item['campo']}':")
        opcoes = []
        for valor in item["valores"].values():
            if valor != NAO_LOCALIZADO and valor not in opcoes:
                opcoes.append(valor)
        for indice, valor in enumerate(opcoes, 1):
            origens = [ROTULOS_FONTE[f] for f, v in item["valores"].items() if v == valor]
            print(f"   [{indice}] {valor}  ({', '.join(origens)})")
        print("   [0] Digitar outro valor")
        escolha = _perguntar("  Valor correto: ", tuple(str(i) for i in range(len(opcoes) + 1)))
        valor = _texto_obrigatorio("  Valor: ") if escolha == "0" else opcoes[int(escolha) - 1]
        if valor != item["valor_sugerido"]:
            alteracoes.append(f"{item['campo']}: '{item['valor_sugerido']}' -> '{valor}'")
        confirmados[item["campo"]] = valor

    campos = list(confirmados)
    while _perguntar("\n  Confirmar os dados críticos? [s] confirmar / [e] editar um campo: ", ("s", "e")) == "e":
        alteracao = _editar_campo(confirmados, campos)
        if alteracao:
            alteracoes.append(alteracao)

    if alteracoes:
        _registrar(audit, id_execucao, caso_id, "conferencia_cruzada", "CORRIGIDO_MANUALMENTE",
                   "Campos críticos conferidos; alterações: " + "; ".join(alteracoes), _perguntar_gravidade(), False, alteracoes)
    else:
        _registrar(audit, id_execucao, caso_id, "conferencia_cruzada", "APROVADO",
                   "Campos críticos conferidos pelo revisor.", "MEDIA" if divergentes else "NENHUMA", False)
    return confirmados


# ------------------------------------------------------------------------------
# Minuta (RF09 / RF13) e síntese de voz (RF07)
# ------------------------------------------------------------------------------
def sintetizar_e_registrar(audit, audio_proc, minuta: Dict[str, Any], registro, caso_id: str) -> bool:
    """
    Gera o áudio acessível da minuta aprovada (RF07) a partir dos campos aprovados e
    registra a execução (RF11). Se audio.verificar_tts estiver ativo no config.json,
    transcreve o MP3 e compara com o texto enviado ao sintetizador.
    """
    print("  -> Sintetizando versão em áudio (TTS) para acessibilidade da minuta aprovada (RF07)...")
    inicio = time.perf_counter()
    protocolo_arquivo = re.sub(r"[^\w.-]", "_", minuta["protocolo"])
    res_tts = audio_proc.sintetizar_minuta_acessivel(registro, minuta["conteudo_gerado"], protocolo_arquivo)
    id_tts = audit.registrar_execucao(
        caso_id=caso_id,
        etapa="sintese_voz",
        modalidade="texto",
        arquivo_origem=res_tts["caminho_texto"],
        arquivo_saida=res_tts["caminho_audio"] if res_tts["sucesso"] else None,
        resumo_saida=f"voz={res_tts['voz_utilizada']}; {len(res_tts['texto_locucao'].split())} palavras; tamanho={res_tts['tamanho_bytes']} bytes",
        duracao_ms=(time.perf_counter() - inicio) * 1000.0,
        provedor="microsoft-edge-tts",
        modelo=res_tts["voz_utilizada"],
        parametros=res_tts["parametros"],
        sucesso=res_tts["sucesso"],
        erro=None if res_tts["sucesso"] else res_tts["mensagem"],
        observacao=f"Texto falado montado a partir dos campos aprovados da minuta {minuta['caminho_arquivo']}."
    )
    if not res_tts["sucesso"]:
        print(f"  [ERRO] {res_tts['mensagem']}")
        return False
    print(f"  -> Áudio MP3 gerado: {res_tts['caminho_audio']} ({res_tts['tamanho_bytes']} bytes)")
    print(f"  -> Texto da locução: {res_tts['caminho_texto']}")

    if audio_proc.audio_cfg.get("verificar_tts", False):
        verificacao, resposta = audio_proc.verificar_locucao(res_tts["caminho_audio"], res_tts["texto_locucao"])
        audit.registrar_execucao(
            caso_id=caso_id,
            etapa="verificacao_tts",
            modalidade="audio",
            arquivo_origem=res_tts["caminho_audio"],
            resposta=resposta,
            prompt_id="PROMPT_TRANSCRICAO_AUDIO",
            prompt_versao=VERSOES_PROMPTS["PROMPT_TRANSCRICAO_AUDIO"],
            prompt_texto=PROMPT_TRANSCRICAO_AUDIO,
            arquivo_saida=verificacao.get("caminho_verificacao"),
            resumo_saida=(f"wer={verificacao['wer_pct']}%; trechos_acrescentados={len(verificacao['trechos_acrescentados'])}"
                          if verificacao["sucesso"] else ""),
            observacao=f"Verificação do áudio da execução {id_tts}: transcrição do MP3 comparada ao texto da locução."
        )
        if verificacao["sucesso"]:
            print(f"  -> Verificação do áudio: WER {verificacao['wer_pct']}% em relação ao texto da locução | "
                  f"trechos acrescentados: {len(verificacao['trechos_acrescentados'])}")
            for trecho in verificacao["trechos_acrescentados"][:5]:
                print(f"     + '{trecho['transcricao']}'")
        else:
            print(f"  [AVISO] Verificação do áudio não realizada: {verificacao['erro']}")
    return True


def _exibir_minuta(minuta: Dict[str, Any], mostrar_texto: bool):
    alertas = minuta.get("alertas", [])
    print("\n[REVISÃO HUMANA - MINUTA INSTITUCIONAL (RF09 / RF13)]")
    print(f"• Minuta: {minuta['caminho_arquivo']}")
    if minuta.get("caminho_docx"):
        print(f"• Versão com brasão: {minuta['caminho_docx']}")
    if mostrar_texto:
        print("\n" + minuta["conteudo_minuta"])
    if alertas:
        print("• Alertas da validação automática:")
        for alerta in alertas:
            print(f"  [!] {alerta}")
    else:
        print("• Validação automática: nenhum alerta.")


def _registrar_decisao_na_minuta(minuta: Dict[str, Any], decisao: str, operador: str, id_execucao: str, justificativa: str,
                                simulada: bool = False):
    """Grava a decisão no arquivo de validação da minuta (o texto aprovado não é alterado depois da decisão)."""
    caminho = minuta.get("caminho_validacao")
    if not caminho or not Path(caminho).exists():
        return
    dados = json.loads(Path(caminho).read_text(encoding="utf-8"))
    dados["decisao_humana"] = {"decisao": decisao, "revisor": operador, "id_execucao": id_execucao, "simulada": simulada,
                               "justificativa": justificativa, "data": datetime.now().isoformat(timespec="seconds")}
    if simulada:
        dados["observacao"] = "Decisão SIMULADA (--demo-avaliacao-humana): não houve revisão humana."
    Path(caminho).write_text(json.dumps(dados, indent=2, ensure_ascii=False), encoding="utf-8")


def revisar_minuta(audit, id_execucao: str, caso_id: str, registro, minuta: Dict[str, Any], audio_proc, auto_demo: bool,
                   regerar: Optional[Callable[[Dict[str, Any], str, str], Tuple[Any, Dict[str, Any], str]]] = None,
                   pendencias: Optional[List[str]] = None) -> str:
    """
    Decisão humana sobre a minuta (RF09 / RF13) e síntese de voz da minuta aprovada (RF07).
    `regerar(dados, id_execucao_anterior, motivo)` gera a minuta de novo e devolve (registro, minuta, id_execucao).
    Falhas (nova geração ou voz) são acrescentadas a `pendencias`.
    No modo demonstração não há síntese de voz: o áudio afirmaria uma aprovação humana que não ocorreu.
    Retorna a decisão final (APROVADO ou REJEITADO) ou NAO_CONCLUIDO se uma nova geração falhar.
    """
    pendencias = pendencias if pendencias is not None else []
    while True:
        _exibir_minuta(minuta, mostrar_texto=not auto_demo)
        alertas = minuta.get("alertas", [])

        if auto_demo:
            bloqueantes = [a for a in alertas if any(t in a for t in TERMOS_BLOQUEANTES_DEMO)]
            decisao = "REJEITADO" if bloqueantes else "APROVADO"
            justificativa = ("Política simulada: rejeição por alerta bloqueante - " + "; ".join(bloqueantes)
                             if bloqueantes else "Política simulada: aprovação sem alertas bloqueantes.")
            gravidade = "ALTA" if bloqueantes else ("BAIXA" if alertas else "NENHUMA")
            break

        print("\n  [1] Aprovar a minuta")
        print("  [2] Rejeitar a minuta (justificativa obrigatória)")
        opcoes = ("1", "2")
        if regerar is not None:
            print("  [3] Corrigir um campo e gerar a minuta de novo")
            print("  [4] Gerar uma nova versão da minuta com os mesmos dados")
            opcoes = ("1", "2", "3", "4")
        escolha = _perguntar(f"  Sua decisão [{', '.join(opcoes)}]: ", opcoes)

        if escolha == "1":
            decisao = "APROVADO"
            justificativa = input("  Observação (opcional): ").strip() or "Minuta conferida com as fontes e aprovada."
            gravidade = "NENHUMA"
            break
        if escolha == "2":
            decisao = "REJEITADO"
            justificativa = _texto_obrigatorio("  Justificativa da rejeição: ")
            gravidade = _perguntar_gravidade()
            break

        dados = registro.model_dump()
        if escolha == "3":
            alteracoes = []
            while True:
                alteracao = _editar_campo(dados, CAMPOS_EDITAVEIS_MINUTA)
                if alteracao:
                    alteracoes.append(alteracao)
                if _perguntar("  Corrigir outro campo? [s/n]: ", ("s", "n")) == "n":
                    break
            if not alteracoes:
                print("  Nenhum campo foi alterado; a minuta não será gerada de novo.")
                continue
            motivo = "Campos corrigidos pelo revisor: " + "; ".join(alteracoes)
            _registrar(audit, id_execucao, caso_id, "minuta", "CORRIGIDO_MANUALMENTE", motivo + ". Minuta gerada de novo.",
                       _perguntar_gravidade(), False, alteracoes)
        else:
            motivo = _texto_obrigatorio("  Motivo da nova geração: ")
            _registrar(audit, id_execucao, caso_id, "minuta", "NOVA_GERACAO", motivo, "BAIXA", False)

        print("  -> Gerando a minuta de novo...")
        registro, minuta, id_execucao = regerar(dados, id_execucao, motivo)
        if not minuta.get("sucesso"):
            print(f"  [ERRO] Nova geração falhou: {minuta.get('erro')}. Execute o pipeline novamente.")
            pendencias.append(f"Nova geração da minuta falhou ({minuta.get('erro')})")
            return "NAO_CONCLUIDO"
        print(f"  -> Nova execução registrada: {id_execucao}")

    _registrar(audit, id_execucao, caso_id, "minuta", decisao, justificativa, gravidade, auto_demo)
    _registrar_decisao_na_minuta(minuta, decisao, obter_operador(auto_demo), id_execucao, justificativa, simulada=auto_demo)

    if decisao == "APROVADO" and auto_demo:
        print("\n  [DEMONSTRAÇÃO] Aprovação SIMULADA: nada é liberado para envio e a voz não é sintetizada,")
        print("  porque o áudio afirmaria uma aprovação humana que não ocorreu.")
    elif decisao == "APROVADO":
        print("\n  [MINUTA APROVADA] Liberada para envio pelo servidor responsável.")
        if not sintetizar_e_registrar(audit, audio_proc, minuta, registro, caso_id):
            pendencias.append("Síntese de voz da minuta aprovada falhou (RF07)")
    else:
        print(f"\n  [ENVIO BLOQUEADO] Minuta retida com status {decisao}. Nenhum envio disparado.")
    return decisao


# ------------------------------------------------------------------------------
# Cartaz (RF10)
# ------------------------------------------------------------------------------
def revisar_cartaz(audit, res_img: Dict[str, Any], id_execucao: str, caso_id: str, auto_demo: bool) -> str:
    """Revisão visual do cartaz com checklist (critério de aceite do RF10). Atualiza o status nos metadados."""
    caminho_meta = Path(res_img["caminho_metadados"])
    meta = json.loads(caminho_meta.read_text(encoding="utf-8"))
    verificacoes = meta.get("verificacoes_automaticas", {})

    print("\n[REVISÃO HUMANA - PEÇA VISUAL (RF10)]")
    print(f"• Cartaz: {res_img['caminho_imagem']}")
    print(f"• Ilustração original do modelo: {res_img['caminho_ilustracao']}")
    print(f"• Verificações automáticas: textos dentro das áreas = {verificacoes.get('textos_dentro_das_areas')}; "
          f"glifos ausentes = {verificacoes.get('glifos_ausentes_na_fonte') or 'nenhum'}")

    if auto_demo:
        ok = verificacoes.get("textos_dentro_das_areas") and not verificacoes.get("glifos_ausentes_na_fonte")
        decisao = _registrar(audit, id_execucao, caso_id, "cartaz", "APROVADO" if ok else "REJEITADO",
                             "Política simulada: apenas verificações automáticas; checklist visual não avaliado.",
                             "NENHUMA" if ok else "MEDIA", True)
        meta["revisao_simulada"] = {"decisao": decisao, "observacao": "Sem revisão humana: status permanece PENDENTE."}
        caminho_meta.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
        return decisao

    print("  Abra o cartaz e responda ao checklist:")
    checklist = {}
    for chave, pergunta in CHECKLIST_CARTAZ.items():
        checklist[chave] = _perguntar(f"  {pergunta} [s/n]: ", ("s", "n")) == "s"
    reprovados = [CHECKLIST_CARTAZ[c] for c, ok in checklist.items() if not ok]

    if reprovados:
        print("  Itens reprovados: " + "; ".join(reprovados))
        decisao, justificativa, gravidade = "REJEITADO", _texto_obrigatorio("  Justificativa da rejeição: "), _perguntar_gravidade()
    elif _perguntar("  [1] Aprovar o cartaz  [2] Rejeitar: ", ("1", "2")) == "1":
        decisao, justificativa, gravidade = "APROVADO", "Checklist visual conferido; todos os itens atendidos.", "NENHUMA"
    else:
        decisao, justificativa, gravidade = "REJEITADO", _texto_obrigatorio("  Justificativa da rejeição: "), _perguntar_gravidade()

    _registrar(audit, id_execucao, caso_id, "cartaz", decisao, justificativa, gravidade, False)
    meta["checklist_revisao_humana"] = checklist
    meta["status_revisao"] = decisao
    meta["revisao_humana"] = {"revisor": obter_operador(False), "data": datetime.now().isoformat(timespec="seconds"),
                              "justificativa": justificativa}
    caminho_meta.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    return decisao
