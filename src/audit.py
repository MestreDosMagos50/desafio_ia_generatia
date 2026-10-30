#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
==============================================================================
MÓDULO DE AUDITORIA, RASTREABILIDADE E REVISÃO HUMANA (RF11 e RF13)
==============================================================================
Funcionalidades:
- Registro estruturado em JSON Lines (.jsonl) sem credenciais e com CPF e
  e-mail mascarados (RF11 / RF12);
- Telemetria técnica (modelo, parâmetros, hash do prompt, tokens, latência);
- Protocolo de avaliação humana: fidelidade, completude, segurança (RF13);
- Registro de decisões humanas (Aprovação, Rejeição com justificativa, Correção);
- Cálculo automático da taxa de aprovação e relatório de riscos residuais.
==============================================================================
"""

import os
import re
import json
import uuid
import shutil
import hashlib
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple, Union, TYPE_CHECKING

from src.privacidade import mascarar_texto


def nome_versionado(diretorio: Path, prefixo: str, sufixos: List[str]) -> str:
    """
    Nome-base único para os arquivos de uma execução: '<prefixo>_AAAAMMDD-HHMMSS' (com '-2', '-3'... se já existir).
    Cada geração grava arquivos novos; versões anteriores nunca são sobrescritas e os hashes do log continuam válidos.
    """
    base = f"{prefixo}_{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    nome, n = base, 1
    while any((diretorio / f"{nome}{sufixo}").exists() for sufixo in sufixos):
        n += 1
        nome = f"{base}-{n}"
    return nome

if TYPE_CHECKING:
    from src.llm_client import LLMResponse


class AuditManager:
    """Gerenciador de logs de auditoria forense e protocolo de qualidade."""

    PADRAO_SEGREDO = re.compile(r'(AIza[0-9A-Za-z_-]{20,}|AQ\.[0-9A-Za-z_-]{20,}|sk-[A-Za-z0-9_-]{20,}|hf_[A-Za-z0-9]{20,})')
    PADRAO_TELEFONE = re.compile(r"\(?\b\d{2}\)?\s?9?\d{4}[-\s]?\d{4}\b")
    CHAVES_SENSIVEIS = ("api_key", "apikey", "secret", "senha", "password", "authorization", "credential")

    def __init__(self, config_path: str = "config.json", dir_logs: Optional[Union[str, Path]] = None):
        """`dir_logs` troca a pasta dos registros (testes offline gravam em pasta temporária)."""
        self.raiz_projeto = Path(__file__).resolve().parent.parent
        self.dir_logs = Path(dir_logs) if dir_logs else self.raiz_projeto / "resultados" / "logs"
        self.dir_logs.mkdir(parents=True, exist_ok=True)
        self.arquivo_log_jsonl = self.dir_logs / "auditoria.jsonl"
        self.arquivo_decisoes_json = self.dir_logs / "decisoes_humanas.json"
        # Decisões do modo --demo-avaliacao-humana: separadas e fora da taxa de aprovação
        self.arquivo_decisoes_simuladas = self.dir_logs / "decisoes_simuladas.json"
        # Desafio 02 (RF20, RF24): estados PENDENTE/APROVADA/REJEITADA/REVISAR, fora da taxa de aprovação do RF13
        self.arquivo_decisoes_minutas = self.dir_logs / "decisoes_humanas_desafio02.json"
        self.caminho_relatorio = self.raiz_projeto / "documentacao" / "relatorio_avaliacao_qualidade.md"

    def _sanitizar(self, obj: Any) -> Any:
        """Sanitização recursiva: remove chaves de API e mascara CPF e e-mail (RF11 / RF12)."""
        if isinstance(obj, str):
            return self.PADRAO_TELEFONE.sub("[TELEFONE_REMOVIDO]", mascarar_texto(self.PADRAO_SEGREDO.sub("[REDACTED_SECRET]", obj)))
        if isinstance(obj, dict):
            return {
                k: self._sanitizar(v) for k, v in obj.items()
                if not any(s in str(k).lower() for s in self.CHAVES_SENSIVEIS)
            }
        if isinstance(obj, list):
            return [self._sanitizar(elem) for elem in obj]
        return obj

    @staticmethod
    def sha256_texto(texto: str) -> str:
        return hashlib.sha256(texto.encode("utf-8")).hexdigest()

    @staticmethod
    def sha256_arquivo(caminho: Path) -> Optional[str]:
        if not caminho.is_file():
            return None
        h = hashlib.sha256()
        with open(caminho, "rb") as f:
            while chunk := f.read(8192):
                h.update(chunk)
        return h.hexdigest()

    def _relativo(self, caminho: Union[str, Path]) -> Path:
        """Normaliza o caminho para relativo à raiz do projeto quando possível."""
        p = Path(caminho)
        if p.is_absolute():
            try:
                return p.relative_to(self.raiz_projeto)
            except ValueError:
                return p
        return p

    def _copia_imutavel(self, caminho_rel: Path, id_execucao: str) -> Path:
        """
        Copia um arquivo de dados/processados para dados/processados/versoes/<id_execucao>__<nome> e devolve o caminho
        da cópia. Assim o hash registrado continua correspondendo a um arquivo mesmo após novas execuções.
        Outros caminhos (originais, resultados versionados) são devolvidos sem alteração.
        """
        if Path(caminho_rel).is_absolute() or tuple(Path(caminho_rel).parts[:2]) != ("dados", "processados") \
                or "versoes" in Path(caminho_rel).parts:
            return caminho_rel
        origem = self.raiz_projeto / caminho_rel
        if not origem.is_file():
            return caminho_rel
        destino_rel = Path("dados", "processados", "versoes", f"{id_execucao}__{Path(caminho_rel).name}")
        (self.raiz_projeto / destino_rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(origem, self.raiz_projeto / destino_rel)
        return destino_rel

    def registrar_execucao(
        self,
        caso_id: str,
        etapa: str,
        modalidade: str,
        arquivo_origem: str,
        resposta: Optional["LLMResponse"] = None,
        prompt_id: Optional[str] = None,
        prompt_versao: Optional[str] = None,
        prompt_texto: Optional[str] = None,
        arquivo_saida: Optional[Union[str, Path]] = None,
        resumo_saida: Optional[str] = None,
        duracao_ms: Optional[float] = None,
        provedor: Optional[str] = None,
        modelo: Optional[str] = None,
        parametros: Optional[Dict[str, Any]] = None,
        sucesso: bool = True,
        erro: Optional[str] = None,
        observacao: Optional[str] = None,
        id_execucao_anterior: Optional[str] = None,
        consulta: Optional[str] = None
    ) -> str:
        """
        Registra uma execução relevante em arquivo estruturado JSONL (RF11).

        - Com `resposta` (LLMResponse), provedor, modelo, parâmetros, tempo, tokens,
          custo e erros vêm da chamada real ao modelo.
        - Sem `resposta`, registra etapas sem LLM (ex.: síntese de voz, composição
          local); tokens e custo ficam nulos.
        `id_execucao_anterior` liga uma nova geração (ex.: minuta refeita após correção) à execução que ela substitui.
        `consulta` (RF21) é gravada mascarada e truncada; versão do esquema, versão do índice e IDs recuperados saem
        dos parâmetros para o nível principal da linha.
        Retorna o identificador único da execução.
        """
        id_execucao = f"EXEC-{uuid.uuid4().hex[:8].upper()}"

        # Intermediários (dados/processados) são regravados a cada execução: o log aponta para uma cópia imutável
        origem_rel = self._copia_imutavel(self._relativo(arquivo_origem), id_execucao)
        saida_rel = self._copia_imutavel(self._relativo(arquivo_saida), id_execucao) if arquivo_saida else None

        if resposta is not None:
            provedor = resposta.provedor
            modelo = resposta.modelo
            parametros = resposta.parametros
            duracao_ms = resposta.latencia_ms
            sucesso = resposta.sucesso
            erro = resposta.erro
            if resumo_saida is None:
                resumo_saida = resposta.conteudo

        prompt_info = None
        if prompt_id or prompt_texto:
            prompt_info = {
                "id": prompt_id,
                "versao": prompt_versao,
                "sha256": self.sha256_texto(prompt_texto) if prompt_texto else None,
                "tamanho_chars": len(prompt_texto) if prompt_texto else None
            }

        resumo_saida = resumo_saida or ""
        agora = datetime.now()
        parametros = parametros or {}
        entrada_log = {
            "id_execucao": id_execucao,
            "id_execucao_anterior": id_execucao_anterior,
            "timestamp": agora.isoformat(),
            "inicio": (agora - timedelta(milliseconds=duracao_ms)).isoformat() if duracao_ms is not None else None,
            "caso_id": caso_id,
            "etapa": etapa,
            "modalidade_entrada": modalidade,
            "arquivo_origem": origem_rel.as_posix(),
            "sha256_origem": self.sha256_arquivo(self.raiz_projeto / origem_rel),
            "usou_modelo_ia": resposta is not None or modelo is not None,
            "provedor": provedor or "nenhum",
            "modelo": modelo,
            "parametros": self._sanitizar(parametros),
            "prompt": prompt_info,
            "versao_esquema": parametros.get("versao_esquema"),
            "versao_indice": parametros.get("versao_indice"),
            "ids_recuperados": parametros.get("ids_recuperados"),
            "consulta": self._sanitizar(consulta[:300] + ("..." if len(consulta) > 300 else "")) if consulta else None,
            "arquivo_saida": saida_rel.as_posix() if saida_rel else None,
            "sha256_saida": self.sha256_arquivo(self.raiz_projeto / saida_rel) if saida_rel else None,
            "resumo_saida": self._sanitizar(resumo_saida[:200] + ("..." if len(resumo_saida) > 200 else "")),
            "duracao_ms": round(duracao_ms, 2) if duracao_ms is not None else None,
            "tentativas": resposta.tentativas if resposta is not None else None,
            "tokens_prompt": resposta.tokens_prompt if resposta is not None else None,
            "tokens_resposta": resposta.tokens_resposta if resposta is not None else None,
            "tokens_raciocinio": resposta.tokens_raciocinio if resposta is not None else None,
            "tokens_total": resposta.tokens_total if resposta is not None else None,
            "custo_estimado_usd": (
                round(resposta.custo_estimado_usd, 6)
                if resposta is not None and resposta.custo_estimado_usd is not None else None
            ),
            "sucesso": sucesso,
            "codigo_erro": resposta.codigo_erro if resposta is not None else (None if sucesso else "ERRO_ETAPA"),
            "mensagem_erro": self._sanitizar(erro) if erro else None,
            "observacao": self._sanitizar(observacao)
        }

        with open(self.arquivo_log_jsonl, "a", encoding="utf-8") as f:
            f.write(json.dumps(entrada_log, ensure_ascii=False) + "\n")

        return id_execucao

    @staticmethod
    def _ler_lista(caminho: Path) -> List[Dict[str, Any]]:
        if not caminho.exists():
            return []
        try:
            with open(caminho, "r", encoding="utf-8") as f:
                dados = json.load(f)
            return dados if isinstance(dados, list) else []
        except (OSError, json.JSONDecodeError):
            return []

    def registrar_decisao_humana(
        self,
        id_execucao: str,
        caso_id: str,
        objeto: str,
        decisao: str,
        operador: str,
        justificativa: str,
        gravidade_erros_detectados: str = "NENHUMA",
        simulada: bool = False,
        alteracoes: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        Registra a decisão sobre uma saída (RF13).
        objeto: transcricao_audio, ficha, conferencia_cruzada, minuta ou cartaz.
        decisao: APROVADO, REJEITADO, CORRIGIDO_MANUALMENTE ou NOVA_GERACAO.
        gravidade: NENHUMA, BAIXA, MEDIA, ALTA ou CRITICA.
        Decisões simuladas (--demo-avaliacao-humana) vão para arquivo separado.
        """
        registro = {
            "id_registro": f"DEC-{uuid.uuid4().hex[:8].upper()}",
            "id_execucao_referencia": id_execucao,
            "caso_id": caso_id,
            "objeto_revisado": objeto,
            "timestamp_decisao": datetime.now().isoformat(),
            "operador_responsavel": operador,
            "simulada": simulada,
            "decisao": decisao,
            "justificativa": self._sanitizar(justificativa),
            "alteracoes": self._sanitizar(alteracoes or []),
            "gravidade_erros": gravidade_erros_detectados
        }
        arquivo = self.arquivo_decisoes_simuladas if simulada else self.arquivo_decisoes_json
        decisoes = self._ler_lista(arquivo)
        decisoes.append(registro)
        with open(arquivo, "w", encoding="utf-8") as f:
            json.dump(decisoes, f, indent=2, ensure_ascii=False)

        self.gerar_relatorio_qualidade()
        return registro

    def registrar_decisao_minuta(self, caso_id: str, estado: str, operador: str, justificativa: str,
                                 id_execucao: Optional[str] = None, minuta: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Decisão do operador sobre uma minuta do Desafio 02 (RF20, RF24, T11). Operador e justificativa são
        obrigatórios, exceto em PENDENTE, que só registra a entrada na fila. APROVADA libera o envio manual pelo
        operador; o sistema nunca envia sozinho. A participação da IA (provedor, modelo, prompt) fica no registro.
        """
        estado = (estado or "").strip().upper()
        if estado not in ESTADOS_REVISAO_MINUTA:
            raise ValueError(f"Estado inválido: {estado!r}; use {', '.join(ESTADOS_REVISAO_MINUTA)}.")
        if not (operador or "").strip():
            raise ValueError("Identifique o operador responsável pela decisão.")
        if estado != "PENDENTE" and not (justificativa or "").strip():
            raise ValueError("A justificativa é obrigatória para aprovar, rejeitar ou pedir revisão.")
        minuta = minuta or {}
        texto_minuta = minuta.get("minuta") or minuta.get("resposta") or ""
        registro = {
            "id_registro": f"DEC-{uuid.uuid4().hex[:8].upper()}",
            "caso_id": caso_id,
            "id_execucao_referencia": id_execucao,
            "estado": estado,
            "operador": self._sanitizar(operador.strip()),
            "justificativa": self._sanitizar((justificativa or "").strip()),
            "registrado_em": datetime.now().isoformat(timespec="seconds"),
            "envio_automatico_bloqueado": True,
            "liberada_para_envio_manual": estado == "APROVADA",
            "participacao_ia": {"provedor": minuta.get("provedor"), "modelo": minuta.get("modelo"),
                                "prompt": minuta.get("prompt"), "status_da_minuta": minuta.get("status")},
            "sha256_minuta": self.sha256_texto(texto_minuta) if texto_minuta else None,
        }
        decisoes = self._ler_lista(self.arquivo_decisoes_minutas)
        decisoes.append(registro)
        with open(self.arquivo_decisoes_minutas, "w", encoding="utf-8") as f:
            json.dump(decisoes, f, indent=2, ensure_ascii=False)
        self.registrar_execucao(
            caso_id=caso_id, etapa="decisao_humana_minuta", modalidade="revisao_humana",
            arquivo_origem=self.arquivo_decisoes_minutas, resumo_saida=f"estado={estado}; id_registro={registro['id_registro']}",
            observacao=registro["justificativa"], id_execucao_anterior=id_execucao)
        return registro

    def decisoes_minutas(self) -> List[Dict[str, Any]]:
        return self._ler_lista(self.arquivo_decisoes_minutas)

    def estado_das_minutas(self) -> Dict[str, Dict[str, Any]]:
        """Última decisão de cada minuta (caso_id); minuta sem registro está PENDENTE."""
        ultimas: Dict[str, Dict[str, Any]] = {}
        for d in sorted(self.decisoes_minutas(), key=lambda d: d.get("registrado_em", "")):
            ultimas[d["caso_id"]] = d
        return ultimas

    def _decisoes_esperadas(self) -> Dict[str, Dict[str, Any]]:
        """Decisão humana esperada por caso, lida dos gabaritos ({caso_id: {decisao, objeto_final, motivo}})."""
        esperadas = {}
        caminho_config = self.raiz_projeto / "config.json"
        if not caminho_config.exists():
            return esperadas
        config = json.loads(caminho_config.read_text(encoding="utf-8"))
        for caminho_gabarito in config.get("gabaritos", {}).values():
            arquivo = self.raiz_projeto / caminho_gabarito
            if arquivo.exists():
                gabarito = json.loads(arquivo.read_text(encoding="utf-8"))
                if gabarito.get("decisao_humana_esperada"):
                    esperadas[gabarito.get("caso_id")] = gabarito["decisao_humana_esperada"]
        return esperadas

    @staticmethod
    def ultimas_decisoes(decisoes: List[Dict[str, Any]]) -> Dict[Tuple[str, str], Dict[str, Any]]:
        """
        Última decisão de cada (caso, objeto revisado): novas execuções substituem as anteriores.
        'houve_correcao' indica se, desde a última rejeição, houve correção manual ou nova geração no mesmo objeto
        (ex.: minuta corrigida e depois aprovada conta como aprovada com correção).
        """
        ultimas: Dict[Tuple[str, str], Dict[str, Any]] = {}
        correcao: Dict[Tuple[str, str], bool] = {}
        for d in sorted(decisoes, key=lambda d: d.get("timestamp_decisao", "")):
            chave = (d.get("caso_id"), d.get("objeto_revisado", "minuta"))
            if d.get("decisao") == "REJEITADO":
                correcao[chave] = False
            elif d.get("decisao") in ("CORRIGIDO_MANUALMENTE", "NOVA_GERACAO"):
                correcao[chave] = True
            ultimas[chave] = {**d, "houve_correcao": correcao.get(chave, False)}
        return ultimas

    @staticmethod
    def resultado_do_caso(ultimas_do_caso: Dict[str, Dict[str, Any]], objeto_final: str) -> Optional[str]:
        """
        Resultado do caso a partir das últimas decisões de cada objeto:
        REJEITADO se o objeto final foi rejeitado; CORRIGIDO_MANUALMENTE se o objeto final foi aprovado
        mas houve correção em alguma etapa; APROVADO caso contrário. None se o objeto final não foi decidido.
        """
        final = ultimas_do_caso.get(objeto_final)
        if final is None or final["decisao"] not in ("APROVADO", "REJEITADO", "CORRIGIDO_MANUALMENTE"):
            return None
        if final["decisao"] == "REJEITADO":
            return "REJEITADO"
        if any(d["decisao"] == "CORRIGIDO_MANUALMENTE" or d.get("houve_correcao") for d in ultimas_do_caso.values()):
            return "CORRIGIDO_MANUALMENTE"
        return final["decisao"]

    def gerar_relatorio_qualidade(self):
        """
        Relatório de avaliação de qualidade (RF13) com as decisões humanas reais:
        taxa de aprovação pela última decisão de cada caso, esperado × obtido e gravidade.
        """
        decisoes = self._ler_lista(self.arquivo_decisoes_json)
        simuladas = self._ler_lista(self.arquivo_decisoes_simuladas)
        esperadas = self._decisoes_esperadas()
        ultimas = self.ultimas_decisoes(decisoes)

        por_caso: Dict[str, Dict[str, Dict[str, Any]]] = {}
        for (caso, objeto), d in ultimas.items():
            por_caso.setdefault(caso, {})[objeto] = d

        linhas_casos, resultados = [], {}
        for caso in sorted(set(por_caso) | set(esperadas)):
            esperado = esperadas.get(caso, {})
            ultimas_caso = por_caso.get(caso, {})
            # Sem gabarito: o objeto final é a minuta, ou o único objeto revisado (ex.: cartaz)
            objeto_final = esperado.get("objeto_final") or ("minuta" if "minuta" in ultimas_caso or not ultimas_caso
                                                            else next(iter(ultimas_caso)))
            obtido = self.resultado_do_caso(ultimas_caso, objeto_final)
            if obtido:
                resultados[caso] = obtido
            gravidades = [d["gravidade_erros"] for d in ultimas_caso.values()]
            gravidade = max(gravidades, key=lambda g: ORDEM_GRAVIDADE.get(g, 0)) if gravidades else "-"
            confere = "-" if not (obtido and esperado.get("decisao")) else ("sim" if obtido == esperado["decisao"] else "**não**")
            linhas_casos.append(
                f"| `{caso}` | {objeto_final} | {esperado.get('decisao', '-')} | {obtido or 'sem decisão'} | {confere} | {gravidade} |"
            )

        linhas_decisoes = [
            f"| `{d['caso_id']}` | {d.get('objeto_revisado', 'minuta')} | **{d['decisao']}** | {d['gravidade_erros']} | "
            f"{str(d['justificativa']).replace('|', '/')} | {d['operador_responsavel']} |"
            for d in sorted(ultimas.values(), key=lambda d: (d["caso_id"], d.get("objeto_revisado", "")))
        ]

        total = len(resultados)
        aprovados = sum(1 for r in resultados.values() if r == "APROVADO")
        corrigidos = sum(1 for r in resultados.values() if r == "CORRIGIDO_MANUALMENTE")
        rejeitados = sum(1 for r in resultados.values() if r == "REJEITADO")
        taxa = f"{100.0 * aprovados / total:.1f}%" if total else "sem casos decididos"
        taxa_com_correcao = f"{100.0 * (aprovados + corrigidos) / total:.1f}%" if total else "sem casos decididos"

        conteudo = f"""# Relatório de Avaliação de Qualidade e Revisão Humana (RF13)
**Central Inteligente de Atendimento e Comunicação Institucional — FIC_DEV**

Gerado automaticamente em {datetime.now().strftime('%d/%m/%Y %H:%M')} a partir de `resultados/logs/decisoes_humanas.json`.

---

## 1. Protocolo de avaliação
Cada saída revisada recebe uma decisão do revisor: **APROVADO**, **REJEITADO** (justificativa obrigatória),
**CORRIGIDO_MANUALMENTE** (campo editado e minuta gerada de novo) ou **NOVA_GERACAO** (nova execução ligada à anterior).
Objetos revisados: transcrição do áudio, leitura da ficha, conferência cruzada, minuta e cartaz.
Critérios observados: fidelidade às fontes, completude (lacunas marcadas como "não localizado"),
formato institucional, proteção de dados pessoais e ausência de decisão automática.

## 2. Taxa de aprovação
Conta apenas a **última decisão de cada caso** (execuções repetidas não se acumulam).
Decisões simuladas (`--demo-avaliacao-humana`) ficam em `decisoes_simuladas.json` e não entram no cálculo
({len(simuladas)} registro(s) simulado(s) excluído(s)).

- Casos com decisão final: **{total}**
- Aprovados sem correção: {aprovados}
- Aprovados após correção manual: {corrigidos}
- Rejeitados: {rejeitados}
- **Taxa de aprovação sem correção: {taxa}**
- Taxa de aprovação incluindo correções: {taxa_com_correcao}

## 3. Esperado × obtido por caso
"Esperado" vem do campo `decisao_humana_esperada` de cada gabarito; "obtido" é o resultado da última decisão
sobre o objeto final do caso (REJEITADO se o objeto final foi rejeitado; CORRIGIDO_MANUALMENTE se houve correção
em alguma etapa). A gravidade é a maior entre as últimas decisões do caso.

| Caso | Objeto final | Esperado | Obtido | Confere | Gravidade |
| :--- | :--- | :---: | :---: | :---: | :---: |
{chr(10).join(linhas_casos) if linhas_casos else '| - | - | - | - | - | - |'}

## 4. Última decisão por caso e objeto
| Caso | Objeto | Decisão | Gravidade | Justificativa | Revisor |
| :--- | :--- | :---: | :---: | :--- | :--- |
{chr(10).join(linhas_decisoes) if linhas_decisoes else '| - | - | - | - | - | - |'}

## 5. Escala de gravidade
- **BAIXA:** pontuação ou formatação que não muda o sentido.
- **MEDIA:** campo secundário ausente ou divergente entre canais (ex.: e-mail transcrito diferente).
- **ALTA:** dado crítico errado (CPF, nome, curso) ou informação inventada na minuta.
- **CRITICA:** instrução maliciosa acolhida pelo modelo ou comunicação de decisão que não foi tomada.

## 6. Riscos residuais
1. O revisor pode aprovar por desatenção uma minuta com dado divergente; a conferência cruzada e os alertas
   automáticos reduzem, mas não eliminam, esse risco.
2. Áudio com ruído pode gerar erros em nomes e e-mails; os dados do áudio só entram após aprovação da transcrição.
"""
        self.caminho_relatorio.parent.mkdir(parents=True, exist_ok=True)
        with open(self.caminho_relatorio, "w", encoding="utf-8") as f:
            f.write(conteudo)


ESTADOS_REVISAO_MINUTA = ("PENDENTE", "APROVADA", "REJEITADA", "REVISAR")
ORDEM_GRAVIDADE = {"NENHUMA": 0, "BAIXA": 1, "MEDIA": 2, "ALTA": 3, "CRITICA": 4}
