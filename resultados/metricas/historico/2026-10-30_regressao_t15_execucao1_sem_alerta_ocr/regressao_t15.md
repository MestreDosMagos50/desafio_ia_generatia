# Regressão do Desafio 01 (RF23, T15)

- Executado em 2026-10-30T13:13:53 com openai/gpt-5.6-luna. Decisões da revisão do texto: SIMULADAS (--demo-avaliacao-humana), fora da taxa de aprovação.
- Evidências copiadas em `resultados/regressao/20261030-131316/`.

## Caso textual (`dados/originais/entrada_texto.txt`)

- Fluxo: pipeline do Desafio 01 (python -m src.main --modo texto); concluído: sim.
- Extração contra o gabarito do Desafio 01: 24/26 campos (92.31%); inventados: 0; omitidos: nenhum; divergentes: classificacao.categoria, classificacao.urgencia.
- Minuta: `resultados/minutas/minuta_institucional_2026-000142_20261030-131324.txt`
- Revisão da minuta: APROVADO (SIMULADO - demonstração automatizada (sem revisão humana)), em `resultados/logs/decisoes_simuladas.json`.

## Caso de OCR (`dados/originais/entrada_pdf-imagem.pdf`)

- Fluxo: leitura da ficha (Desafio 01, src/vision.py) + atendimento integrado (Desafio 02).
- Leitura contra o gabarito do Desafio 01: 21/26 campos (80.77%); divergentes: codigo_matricula, solicitante.nome_completo, solicitante.data_nascimento, solicitante.rg, solicitante.email.
- Campos incertos esperados pelo gabarito e sinalizados pela leitura: nenhum; não sinalizados: codigo, cpf.
- Atendimento `ATD-20261030-131339-2B2F`: guardrails PERMITIR, etapa MINUTA_GERADA, minuta SEM_EVIDENCIA_SUFICIENTE, estado na fila do operador: PENDENTE.

## Resultado

- T15: CONFERE: as duas entradas anteriores seguiram até minuta e revisão.
- A leitura de manuscrito continua sujeita a erro: os campos divergentes acima são conferidos pela pessoa antes de qualquer uso, como no Desafio 01.
