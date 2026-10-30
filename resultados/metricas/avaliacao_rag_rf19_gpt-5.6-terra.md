# Avaliação do RAG fundamentado (RF19: T08, T09, T10)

- Gerado em: 2026-10-30T13:12:53 | provedor `openai` | modelo `gpt-5.6-terra` | prompt PROMPT_RAG v1.0 | esquema 1.0.0
- Índice `acervo_principal` v1.0.0 (chunking A, top-4, vizinhos 1, limiar 0.45, margem mínima 0.02)
- Gabarito v1.1.0 (revisão humana: PENDENTE), elaborado antes da execução.
- Chamadas ao modelo: 9 de geração + 1 de embedding | tokens: 27257 | custo estimado: US$ 0.072903

## Resultado

| Teste | Medida | Resultado |
|---|---|---:|
| T08 | Respondíveis que conferem com o gabarito (status, fontes, afirmações e referências citadas) | 4/5 |
| T08 | Status FUNDAMENTADA | 5/5 |
| T08 | Afirmações essenciais presentes (marcadores) | 9/10 |
| T08 | Referências essenciais citadas | 8/8 |
| T08 | Referências essenciais no contexto enviado ao modelo | 8/8 |
| T08 | Referências essenciais já no top-k (sem vizinhos nem vigência) | 7/8 |
| T08 | Fontes exigidas citadas | 4/5 |
| T09 | Abstenção correta (recusa padronizada exata e encaminhamento) | 2/2 |
| T10 | Conflito tratado (status, dois trechos expostos, sem escolher prazo) | 1/1 |
| — | Recusas indevidas (pergunta com resposta recusada) | 0/6 |
| — | Afirmações do modelo com citação | 17/18 |
| — | Afirmações citadas e com os números no próprio trecho citado | 16/18 |
| — | Respostas convertidas em recusa pela ancoragem numérica | 0 |

## Por pergunta

| Pergunta | Tipo | Esperado | Obtido | Motivo | Top-1 | Citados | Confere |
|---|---|---|---|---|---:|---|---|
| RAG-01 | respondivel | FUNDAMENTADA | FUNDAMENTADA | FUNDAMENTADA | 0.6192 | DOC-02, v1.0, p. 1, Art. 1º | NÃO |
| RAG-02 | respondivel | FUNDAMENTADA | FUNDAMENTADA | FUNDAMENTADA | 0.6515 | DOC-01, v1.0, p. 2, seção 4 | sim |
| RAG-03 | respondivel | FUNDAMENTADA | FUNDAMENTADA | FUNDAMENTADA | 0.6019 | DOC-03, v1.0, seção 2 | sim |
| RAG-04 | respondivel | FUNDAMENTADA | FUNDAMENTADA | FUNDAMENTADA | 0.5856 | DOC-05, v1.0, p. 1, seção 1; DOC-05, v1.0, p. 1, seção 2 | sim |
| RAG-05 | respondivel | FUNDAMENTADA | FUNDAMENTADA | FUNDAMENTADA | 0.5315 | DOC-06, v1.0, seção 1 | sim |
| RAG-06 | sem_resposta | SEM_EVIDENCIA_SUFICIENTE | SEM_EVIDENCIA_SUFICIENTE | MODELO_DECLAROU_SEM_EVIDENCIA | 0.4961 | - | sim |
| RAG-07 | sem_resposta | SEM_EVIDENCIA_SUFICIENTE | SEM_EVIDENCIA_SUFICIENTE | MODELO_DECLAROU_SEM_EVIDENCIA | 0.4912 | - | sim |
| RAG-08 | contraditoria | CONFLITO_DE_FONTES | CONFLITO_DE_FONTES | CONFLITO_SEM_REGRA_DE_PREVALENCIA | 0.5418 | DOC-04, v1.0, seção 2; DOC-05, v1.0, p. 2, seção 3 | sim |

## Falhas e pontos de atenção

- **RAG-01**: afirmação ausente: "O prazo original de 20/10/2026 foi retificado."; fontes exigidas ['DOC-02', 'DOC-01'], citadas ['DOC-02']

Alertas emitidos para o operador:
- RAG-01: CITACAO_DE_VIGENCIA_INCOMPLETA: a resposta cita o DOC-02, que retifica o DOC-01, sem citar o trecho do DOC-01 que está no contexto.
- RAG-02: VIGENCIA_A_CONFERIR: a resposta cita o DOC-01, que tem itens retificados pelo DOC-02, sem citar o DOC-02; confira se o item usado não foi alterado.
- RAG-08: NUMERO_FORA_DO_TRECHO_CITADO: 02/2026 em "O Comunicado nº 02/2026 estabelece que o termo de compromisso assinado deve ser entregue com antecedência mínima de 5 (cinco) dias úteis do início das atividades no campo de estágio." está em outro trecho do contexto, não no citado.
- RAG-08: AFIRMACAO_SEM_CITACAO: "Não há prevalência declarada entre os documentos consultados."

## Controle do T14 (documento excluído)

- RAG-T14: DOC-99 excluído; esperado SEM_EVIDENCIA_SUFICIENTE, obtido SEM_EVIDENCIA_SUFICIENTE (MODELO_DECLAROU_SEM_EVIDENCIA); DOC-99 nos trechos consultados: não; confere.

## Como ler

- Afirmações e referências são conferidas por marcadores e trechos literais definidos no gabarito antes da execução: a conferência é indicativa. A sustentação de cada afirmação contra a passagem citada é feita pela equipe em resultados/metricas/conferencia_sustentacao_rag.json (RF23), sem LLM-juiz.
- Toda resposta, inclusive as recusas, fica PENDENTE_REVISAO_HUMANA com envio automático bloqueado; a decisão esperada do operador está no gabarito (aprovada ou revisar).
- Registros completos (trechos consultados, guardas, saída do modelo e minuta): resultados/rag/respostas/.
