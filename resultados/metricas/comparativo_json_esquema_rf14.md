# Comparativo: JSON apenas sintático x saída validada por esquema (RF14, T01)

Caso: SOL-01 | Contrato: ContratoSolicitacaoV2 v2.0.0

## Mesmo caso nas três formas de saída

| Variante | Garantia da API | JSON válido | Válido no contrato | Erros por código | Chaves devolvidas |
|---|---|---|---|---|---|
| json_object_instrucao_generica | apenas sintaxe JSON | sim | não | CAMPO_OBRIGATORIO_AUSENTE: 8, CHAVE_EXTRA: 5 | canal, data_solicitacao, declaracao_frequencia, pendencia_solicitada, protocolo, solicitacao, solicitante |
| json_object_instrucoes_do_contrato | apenas sintaxe JSON | sim | não | TIPO_INCORRETO: 1 | assunto, campos_ausentes, categoria, curso, data_solicitacao, entidades, necessita_revisao, pedido, protocolo, solicitante_ficticio |
| structured_outputs_contrato | esquema (sintaxe, tipos e estrutura) | sim | sim | - | assunto, campos_ausentes, categoria, curso, data_solicitacao, entidades, necessita_revisao, pedido, protocolo, solicitante_ficticio |

## Payloads de teste (JSON válido fora do contrato)

| Caso | Descrição | Erros esperados | Erros obtidos | Confere |
|---|---|---|---|---|
| T01-A | JSON válido com uma chave extra | CHAVE_EXTRA | CHAVE_EXTRA | sim |
| T01-B | JSON válido com tipos incorretos (texto no lugar de booleano e de lista) | TIPO_INCORRETO | TIPO_INCORRETO | sim |
| T01-C | JSON válido sem um campo obrigatório (categoria) | CAMPO_OBRIGATORIO_AUSENTE | CAMPO_OBRIGATORIO_AUSENTE | sim |
| T01-D | JSON apenas sintático, com a estrutura escolhida pelo modelo (o que o json_object permite) | CHAVE_EXTRA, CAMPO_OBRIGATORIO_AUSENTE | CAMPO_OBRIGATORIO_AUSENTE, CHAVE_EXTRA | sim |

JSON Mode garante só a sintaxe: as chaves e os tipos ficam a critério do modelo. O esquema estrito restringe a geração; mesmo assim, toda saída é validada localmente antes de seguir (Aula 08 §4 e §5).
