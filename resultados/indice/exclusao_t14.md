# Exclusão de documento e derivados (RF24, T14)

- Pergunta de controle: Vai ter recesso no fim do ano? De quando até quando as aulas param?
- Antes da exclusão: o DOC-99 foi recuperado no top-4.
- Exclusão: 4 vetor(es) removido(s) (experimento_chunking_A: 0, experimento_chunking_B: 0, acervo_principal: 4); restantes: 0.
- Depois da exclusão: 0 trecho(s) do DOC-99 no top-4.
- Reindexação automática do acervo: DOC-99 ignorado por exclusão registrada: sim.
- Situação: confere com o T14

## Política de retenção e exclusão

- Vetores e entrada do manifesto do documento excluído são apagados de todas as coleções do índice.
- A exclusão fica registrada no manifesto e na auditoria (data, motivo, vetores removidos).
- O documento não volta ao índice numa reindexação automática; só por reinclusão explícita.
- Resultados derivados que citem o documento (respostas e minutas do RAG) devem ser apagados ou marcados no mesmo ato; até o Bloco 5 não há resultado derivado gravado por documento.
- O arquivo-fonte do acervo fictício continua versionado porque é recriado pelo gerador; num acervo real, o arquivo de origem seria removido no mesmo ato, conforme a tabela de temporalidade do órgão.
