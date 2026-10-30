# Comparação de chunking e recuperação (RF18, T07)

- Gerado em: 2026-10-30T10:42:03 | Embedding: text-embedding-3-small | top-k: 4 | mesmo vetor de consulta nas duas configurações
- Unidade: caracteres do conteúdo do trecho (o cabeçalho contextual não entra na conta); trechos não cruzam páginas nem seções; corte preferencial em fim de linha ou de frase.

| Indicador | Config. A | Config. B |
|---|---|---|
| Tamanho / sobreposição | 350 / 50 | 800 / 160 |
| Trechos (tamanho médio) | 59 (236.0) | 35 (372.1) |
| Acerto de recuperação | 5/5 | 5/5 |
| Referências essenciais no top-k | 7/8 | 7/8 |
| Cláusulas inteiras | 103/103 | 103/103 |
| MRR | 0.9 | 0.75 |
| Contexto médio no top-k (tokens, estimativa) | 404.2 | 575.4 |
| Similaridade top-1 média: respondíveis / sem resposta | 0.598 / 0.4937 | 0.5921 / 0.4729 |

## Resultado por pergunta

| Pergunta | Tipo | Config. A: posição do acerto (sim. top-1) | Config. B: posição do acerto (sim. top-1) |
|---|---|---|---|
| RAG-01 | respondivel | 1 (0.6192) | 4 (0.5849) |
| RAG-02 | respondivel | 1 (0.6515) | 1 (0.6474) |
| RAG-03 | respondivel | 2 (0.602) | 2 (0.5948) |
| RAG-04 | respondivel | 1 (0.5856) | 1 (0.59) |
| RAG-05 | respondivel | 1 (0.5315) | 1 (0.5436) |
| RAG-06 | sem_resposta | - (0.4961) | - (0.4795) |
| RAG-07 | sem_resposta | - (0.4912) | - (0.4663) |
| RAG-08 | contraditoria | - (0.5418) | - (0.4703) |

## Falhas de recuperação

Uma pergunta conta como acerto com qualquer trecho de referência no top-k (critério do RF18); a referência essencial é a que sustenta a resposta correta (ex.: a redação retificada, e não a original).

- Config. A, sem nenhuma referência no top-k: nenhuma
- Config. A, referência essencial fora do top-k: RAG-02 (1/2; top-k: DOC-01 4. DA MATRÍCULA E DOS DOCUMENTOS EXIGIDOS, DOC-01 2. DOS CURSOS E DAS VAGAS, DOC-01 1. DISPOSIÇÕES PRELIMINARES, DOC-01 4. DA MATRÍCULA E DOS DOCUMENTOS EXIGIDOS)
- Config. B, sem nenhuma referência no top-k: nenhuma
- Config. B, referência essencial fora do top-k: RAG-01 (0/1; top-k: DOC-03 4. VAGAS REMANESCENTES APÓS O INÍCIO DAS AULAS, DOC-01 5. DAS CHAMADAS E DAS VAGAS REMANESCENTES, DOC-03 2. FREQUÊNCIA NOS DEZ PRIMEIROS DIAS LETIVOS, DOC-01 3. DO CRONOGRAMA)

## Escolha

- Critério: 1) maior acerto de recuperação; 2) mais referências essenciais no top-k; 3) maior MRR; 4) mais cláusulas inteiras; 5) menor contexto enviado ao modelo (custo).
- Recomendada pelo experimento: **configuração A**. A escolha final e sua justificativa ficam registradas em config.json (chunking.configuracao_principal).
- A similaridade top-1 das perguntas sem resposta serve de referência para calibrar o limiar de abstenção do RAG (Bloco 6); similaridade alta não significa que o trecho responde à pergunta.

## Decisão registrada

- Configuração principal: **A**.
- Justificativa: Escolhida em 30/10/2026 pelo experimento do RF18 (resultados/metricas/comparacao_chunking_rf18.md): as duas acertaram 5/5, mas na pergunta sobre o prazo retificado (RAG-01) a A trouxe o DOC-02 em 1º lugar e a B não trouxe o DOC-02 no top-4, só a redação revogada do DOC-01; a A também teve MRR maior (0,90 x 0,75) e contexto menor (~404 x ~575 tokens). Limitação registrada: na RAG-02 a A dividiu a seção 4 e o início da lista de documentos (item 4.1) ficou fora do top-4.
- Com documentos estruturados e corte em fim de linha, as duas configurações preservaram todas as cláusulas inteiras; o critério que as separou foi a recuperação da redação vigente e a posição do trecho certo.
