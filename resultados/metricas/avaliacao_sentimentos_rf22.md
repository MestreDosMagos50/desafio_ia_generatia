# Classificação de sentimentos das avaliações de atendimento (RF22)

## Ficha técnica

- Avaliações: **12** (censo do lote fictício avaliado; intervalo de confiança: não se aplica (sem margem amostral no censo)) | atendimentos avaliados: 12 | atendimentos do período: não localizado (taxa de resposta não calculável)
- Período das avaliações: 2026-10-05 a 2026-10-21 | modelo: gpt-5.6-luna | prompt PROMPT_SENTIMENTO v1.0 | esquema 1.0.0 | classificado em 2026-10-30T12:50:28
- Acurácia da polaridade contra o gabarito v1.0.0 (revisão humana: PENDENTE): **11/12**
- Limítrofes: 5/12 (41,7%) | para revisão: 6/12 (50,0%) | sem rótulo válido: 0/12 (0,0%)
- Percentual só com base de pelo menos 10 avaliações.
- Os rótulos descrevem o texto de cada avaliação, não o autor: não se infere personalidade, estado emocional, diagnóstico ou característica sensível. A ambiguidade é autodeclarada pelo modelo, uma estimativa não calibrada que orienta a revisão e não é probabilidade de acerto. O percentual descreve quem avaliou, não todos os atendidos (viés de resposta).

## Distribuição da polaridade (calculada em pandas)

| Polaridade | Avaliações |
|---|---:|
| positiva | 4/12 (33,3%) |
| negativa | 3/12 (25,0%) |
| neutra | 3/12 (25,0%) |
| indeterminada | 2/12 (16,7%) |

Por canal (percentual omitido abaixo do mínimo):

| Canal | n | positiva | negativa | neutra | indeterminada |
|---|---:|---:|---:|---:|---:|
| aplicativo | 2 | 1/2 | 0/2 | 0/2 | 1/2 |
| e-mail | 2 | 1/2 | 1/2 | 0/2 | 0/2 |
| formulario_site | 2 | 0/2 | 0/2 | 2/2 | 0/2 |
| presencial | 5 | 2/5 | 1/5 | 1/5 | 1/5 |
| telefone | 1 | 0/1 | 1/1 | 0/1 | 0/1 |

## Conferência contra o gabarito

- Saídas válidas: 12/12 | trechos determinantes literais: 12/12
- Acurácia: polaridade 11/12 | ambiguidade 9/12 | tema 9/12 | intensidade 10/12
- Casos que o gabarito manda revisar e que foram sinalizados: 3/4 (AV-06, AV-10, AV-11, AV-12); sinalizados além do esperado: AV-01, AV-04, AV-05

Matriz de confusão da polaridade (linhas: gabarito; colunas: modelo):

| gabarito \ modelo | indeterminada | negativa | neutra | positiva |
|---|---:|---:|---:|---:|
| indeterminada | 2 | 0 | 0 | 1 |
| negativa | 0 | 3 | 0 | 0 |
| neutra | 0 | 0 | 3 | 0 |
| positiva | 0 | 0 | 0 | 3 |

## Por avaliação

| ID | Esperada | Obtida | Ambiguidade (esp./obt.) | Tema (esp./obt.) | Revisão | Trecho determinante | Confere |
|---|---|---|---|---|---|---|---|
| AV-01 | positiva | positiva | clara/clara | atendimento/informacao_e_orientacao | sim | A atendente explicou com calma todos os documentos da matrícula e resolveu tudo em poucos minutos. | sim |
| AV-02 | positiva | positiva | clara/clara | documentacao/documentacao | não | recebi no mesmo dia. Muito prático. | sim |
| AV-03 | positiva | positiva | clara/clara | informacao_e_orientacao/informacao_e_orientacao | não | Gostei do atendimento na secretaria, fui bem orientado | sim |
| AV-04 | negativa | negativa | clara/limitrofe | prazo_e_demora/prazo_e_demora | sim | Fiquei mais de duas horas na fila e no fim disseram que o sistema estava fora do ar. | sim |
| AV-05 | negativa | negativa | clara/limitrofe | informacao_e_orientacao/informacao_e_orientacao | sim | A informação passada por telefone estava errada e por isso perdi o prazo | sim |
| AV-06 | negativa | negativa | limitrofe/limitrofe | prazo_e_demora/prazo_e_demora | sim | pedido de histórico escolar que fiz há 20 dias e que ainda não foi entregue | sim |
| AV-07 | neutra | neutra | clara/clara | documentacao/documentacao | não | Gostaria de saber se a declaração de matrícula também pode ser retirada por um familiar. | sim |
| AV-08 | neutra | neutra | clara/clara | informacao_e_orientacao/informacao_e_orientacao | não | Sugiro colocar na entrada do bloco um aviso com o horário de funcionamento da secretaria. | sim |
| AV-09 | neutra | neutra | clara/clara | atendimento/atendimento | não | recebi o número de protocolo do pedido | sim |
| AV-10 | indeterminada | indeterminada | limitrofe/limitrofe | prazo_e_demora/documentacao | sim | só precisei voltar quatro vezes para entregar o mesmo documento | sim |
| AV-11 | indeterminada | indeterminada | limitrofe/limitrofe | sistema_e_tecnologia/sistema_e_tecnologia | sim | foi muito atenciosa e resolveu minha dúvida, mas o sistema caiu duas vezes | sim |
| AV-12 | indeterminada | positiva | limitrofe/clara | outro/atendimento | não | Foi como eu esperava. | NÃO |

## Casos ambíguos e divergências

- **AV-06** — gabarito: negativa (R5: tom cordial ('por gentileza'), mas relata pedido atrasado há 20 dias; outro leitor poderia rotular como neutra.) | modelo: negativa (O texto relata demora de 20 dias na entrega do histórico escolar e solicita retorno.)
- **AV-10** — gabarito: indeterminada (R3: 'Parabéns pela agilidade' com relato de quatro retornos sugere ironia; a leitura irônica é provável, mas cabe ao revisor confirmar.) | modelo: indeterminada (A mensagem usa elogio aparente, mas relata repetidas idas para entregar o mesmo documento, sugerindo crítica ao atendimento.)
- **AV-11** — gabarito: indeterminada (R2: elogio à atendente e crítica à falha do sistema com prejuízo; mensagem mista.) | modelo: indeterminada (O texto elogia a atenção e a resolução da dúvida, mas relata quedas do sistema e perda de tempo.)
- **AV-12** — gabarito: indeterminada (R4: sem contexto para saber se a expectativa era boa ou ruim.) | modelo: positiva (O texto avalia que o atendimento correspondeu às expectativas.)

## Limites

- Corpus sintético de 12 avaliações, escrito pela mesma equipe que fez o gabarito: textos mais limpos que os reais; acurácia alta aqui não prevê desempenho em avaliações reais (Aula 14 §4.3).
- Uma única execução: a concordância entre execuções (Aula 14 §4.1) não foi medida; os casos limítrofes são os que mais oscilam.
- A ambiguidade autodeclarada prioriza a revisão, mas não a delimita: o modelo pode acertar o rótulo sem perceber que o caso era disputável.
- Rótulos: resultados/sentimentos/rotulos_sentimentos_20261030-125054.csv | chamadas: 12 | custo estimado: US$ 0.003527
