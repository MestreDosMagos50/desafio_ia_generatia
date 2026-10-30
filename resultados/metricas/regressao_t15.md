# Regressão do Desafio 01 (RF23, T15)

- Executado em 2026-10-30T13:16:22 com openai/gpt-5.6-luna. Decisões da revisão do texto: SIMULADAS (--demo-avaliacao-humana), fora da taxa de aprovação.
- Evidências copiadas em `resultados/regressao/20261030-131546/`.

## Caso textual (`dados/originais/entrada_texto.txt`)

- Fluxo: pipeline do Desafio 01 (python -m src.main --modo texto); concluído: sim.
- Extração contra o gabarito do Desafio 01: 24/26 campos (92.31%); inventados: 0; omitidos: classificacao.urgencia; divergentes: classificacao.categoria.
- Minuta: `resultados/minutas/minuta_institucional_2026-000142_20261030-131555.txt`
- Revisão da minuta: APROVADO (SIMULADO - demonstração automatizada (sem revisão humana)), em `resultados/logs/decisoes_simuladas.json`.

## Caso de OCR (`dados/originais/entrada_pdf-imagem.pdf`)

- Fluxo: leitura da ficha (Desafio 01, src/vision.py) + atendimento integrado (Desafio 02).
- Leitura contra o gabarito do Desafio 01: 21/26 campos (80.77%); divergentes: codigo_matricula, solicitante.nome_completo, solicitante.data_nascimento, solicitante.rg, solicitante.email.
- Campos incertos esperados pelo gabarito e sinalizados pela leitura: cpf; não sinalizados: codigo.
- Atendimento `ATD-20261030-131610-4222`: guardrails PERMITIR, etapa MINUTA_GERADA, minuta SEM_EVIDENCIA_SUFICIENTE, encaminhamento REVISAO_HUMANA_PRIORITARIA, estado na fila do operador: PENDENTE.
- Campos que a leitura marcou como incertos: CPF, RG.
- Alertas que acompanham a minuta: ENTRADA_OCR_SEM_CONFIRMACAO_HUMANA, CAMPO_INCERTO_NA_LEITURA, CAMPO_INCERTO_NA_LEITURA.

## Resultado

- T15: CONFERE: as duas entradas anteriores seguiram até minuta e revisão.

## Falha crítica encontrada e correção

- A leitura do manuscrito errou campos que identificam o aluno (veja os divergentes acima), e parte deles não foi marcada como incerta: sem gabarito, esse erro não é detectável por código.
- No Desafio 01 a ficha só entra depois da confirmação humana dos campos críticos; no fluxo integrado do Desafio 02 a leitura ia direto para a extração. Correção: todo atendimento vindo de OCR leva o alerta ENTRADA_OCR_SEM_CONFIRMACAO_HUMANA (e um alerta por campo marcado como incerto) e vai à revisão prioritária.
- Pendência declarada: a conferência campo a campo na imagem continua sendo humana; ela não é substituída pelo alerta.
