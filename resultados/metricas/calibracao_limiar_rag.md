# Calibração do limiar de similaridade do RAG (RF19, guarda 1)

- Gerado em: 2026-10-30T12:12:46 | índice `acervo_principal` (chunking A, top-4) | modelo de embedding `text-embedding-3-small`
- Similaridade de cosseno entre o vetor da pergunta e o do trecho (1 - distância de cosseno do Chroma): perto de 1, sentidos próximos; perto de 0, sem relação. Mede proximidade de sentido, não veracidade nem vigência do trecho.
- Regra registrada antes da medição: O limiar é a rede grosseira da guarda 1 (Aula 12 §4.4) e não pode cortar pergunta com resposta. Valor = maior ponto da grade de 0,05 em 0,05 que fique pelo menos 0,05 abaixo da menor similaridade top-1 entre as perguntas respondíveis e a contraditória. A abstenção fina fica com o contrato do prompt (guarda 2) e com a ancoragem numérica (guarda 3).

## Similaridade do 1º trecho por pergunta

| Pergunta | Tipo | Top-1 | Top-k | Margem top-1 − top-k | Documento do top-1 |
|---|---|---:|---:|---:|---|
| RAG-01 | respondivel | 0.6192 | 0.5615 | 0.0577 | DOC-02 |
| RAG-02 | respondivel | 0.6515 | 0.5714 | 0.0801 | DOC-01 |
| RAG-03 | respondivel | 0.6020 | 0.5352 | 0.0668 | DOC-03 |
| RAG-04 | respondivel | 0.5862 | 0.5021 | 0.0841 | DOC-05 |
| RAG-05 | respondivel | 0.5315 | 0.5083 | 0.0232 | DOC-06 |
| RAG-06 | sem_resposta | 0.4961 | 0.4255 | 0.0706 | DOC-06 |
| RAG-07 | sem_resposta | 0.4911 | 0.3910 | 0.1001 | DOC-06 |
| RAG-08 | contraditoria | 0.5419 | 0.4325 | 0.1094 | DOC-04 |
| RAG-T14 | sem_resposta | 0.4677 | 0.4549 | 0.0128 | DOC-02 |

## Distribuição

- Com resposta no acervo (respondíveis e contraditória, n=6): mínimo 0.5315 | mediana 0.5941 | máximo 0.6515
- Sem resposta no acervo (n=3): mínimo 0.4677 | mediana 0.4911 | máximo 0.4961
- Sobreposição entre os grupos: não; distância entre o menor top-1 com resposta e o maior sem resposta: 0.0354

| Limiar | Corta perguntas com resposta | Corta perguntas sem resposta | Referência |
|---:|---:|---:|---|
| 0.20 | 0 | 0 |  |
| 0.25 | 0 | 0 | Aula 13 |
| 0.30 | 0 | 0 |  |
| 0.35 | 0 | 0 |  |
| 0.40 | 0 | 0 |  |
| 0.45 | 0 | 0 |  |
| 0.50 | 0 | 3 | Aula 12 |
| 0.55 | 2 | 3 |  |
| 0.60 | 3 | 3 |  |
| 0.65 | 5 | 3 |  |
| 0.70 | 6 | 3 |  |

## Decisão

- Limiar sugerido pela regra: **0.45** (folga 0.05 abaixo do menor top-1 com resposta).
- Limiar em uso (config.json, rag.limiar_similaridade): 0.45
- Com só 9 perguntas, qualquer separação observada vale para este acervo e este conjunto. A Aula 12 mostrou distribuições sobrepostas (respondível com 0,509 e sem resposta com 0,695): o limiar é rede grosseira e a abstenção fina fica com o contrato do prompt (guarda 2) e a ancoragem numérica (guarda 3).
- Margem mínima entre o 1º e o último trecho do top-k: 0.02 (abaixo disso a minuta recebe alerta de revisão adicional). Perguntas abaixo da margem nesta medição: RAG-T14.
