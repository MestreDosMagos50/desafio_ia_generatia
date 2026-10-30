# 1ª execução do RAG (30/10/2026) — PROMPT_RAG v1.0, limiar 0,45

Resultado medido: 7/8 conferem com o gabarito (T08 4/5, T09 2/2, T10 1/1), sem recusa indevida.

Falha: na RAG-01 a resposta aplicou a retificação (30/10/2026) e citou só o DOC-02. O trecho original do DOC-01
estava no contexto (busca de vigência) e não foi citado; o gabarito exige as duas fontes.

Ajuste depois desta execução, sem mudar o prompt nem o gabarito: o código passou a conferir a regra 4 do prompt
(alertas CITACAO_DE_VIGENCIA_INCOMPLETA e VIGENCIA_A_CONFERIR, que levam a minuta à revisão prioritária) e a
contagem de chamadas passou a incluir a do controle do T14 (aqui aparecem 8; foram 9).
