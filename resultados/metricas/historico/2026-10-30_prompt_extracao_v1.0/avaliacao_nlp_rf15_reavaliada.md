# Avaliação da extração estruturada e da ficha de compreensão (RF14, RF15, T03)

- Gerado em: 2026-10-30T01:01:11 | Provedor/modelo: openai / gpt-5.6-luna
- Gabarito: v1.1.0 (revisão humana: PENDENTE) | Esquema: v2.0.0 | Custo estimado da execução: US$ 0.007068

## Indicadores

| Indicador | Numerador | Denominador | Valor |
|---|---|---|---|
| acuracia_categoria | 6 | 6 | 100.0% |
| contratos_validos | 6 | 6 | 100.0% |
| campos_exatos_corretos | 41 | 42 | 97.6% |
| assunto_e_pedido_com_presenca_correta | 11 | 12 | 91.7% |
| entidades_omitidas | 0 | 36 | 0.0% |
| entidades_sem_suporte | 0 | - | - |
| entidades_nao_esperadas | 1 | - | - |
| resumos_no_limite_de_100_palavras | 6 | 6 | 100.0% |
| fatos_essenciais_preservados | 22 | 22 | 100.0% |
| resumos_com_termo_proibido | 0 | - | - |
| resumos_com_numero_sem_lastro | 0 | - | - |
| decisoes_corretas | 6 | 6 | 100.0% |

## Por solicitação

| Caso | Tipo | Categoria (esperada -> obtida) | Decisão (esperada -> obtida) | Campos divergentes | Entidades omitidas / sem suporte / não esperadas | Palavras | Fatos preservados |
|---|---|---|---|---|---|---|---|
| SOL-01 | completa | MATRICULA_INICIAL -> MATRICULA_INICIAL | GERAR_MINUTA_PARA_REVISAO -> GERAR_MINUTA_PARA_REVISAO | - | 0 / 0 / 0 | 66 | 4/4 |
| SOL-02 | completa | MATRICULA_INICIAL -> MATRICULA_INICIAL | GERAR_MINUTA_PARA_REVISAO -> GERAR_MINUTA_PARA_REVISAO | - | 0 / 0 / 0 | 63 | 4/4 |
| SOL-03 | completa | ESTAGIO_SUPERVISIONADO -> ESTAGIO_SUPERVISIONADO | GERAR_MINUTA_PARA_REVISAO -> GERAR_MINUTA_PARA_REVISAO | - | 0 / 0 / 0 | 69 | 4/4 |
| SOL-04 | completa | ASSISTENCIA_ESTUDANTIL -> ASSISTENCIA_ESTUDANTIL | GERAR_MINUTA_PARA_REVISAO -> GERAR_MINUTA_PARA_REVISAO | - | 0 / 0 / 0 | 51 | 3/3 |
| SOL-05 | incompleta | MATRICULA_INICIAL -> MATRICULA_INICIAL | ENCAMINHAR_REVISAO_HUMANA -> ENCAMINHAR_REVISAO_HUMANA | campos_ausentes | 0 / 0 / 1 | 88 | 4/4 |
| SOL-06 | ambigua | REVISAO -> REVISAO | ENCAMINHAR_REVISAO_HUMANA -> ENCAMINHAR_REVISAO_HUMANA | - | 0 / 0 / 0 | 55 | 3/3 |

## Erros registrados

- **SOL-01**: nenhum erro automático
- **SOL-02**: nenhum erro automático
- **SOL-03**: nenhum erro automático
- **SOL-04**: nenhum erro automático
- **SOL-05**: campo campos_ausentes: esperado ['pedido'], obtido []; campo pedido: esperado null, obtido 'Efetivação da matrícula no curso Técnico em Enfermagem.' (valor deduzido, não escrito no texto); entidade não esperada - orgaos: SECRETARIA ESCOLAR
- **SOL-06**: nenhum erro automático

## Limitações

- A preservação dos fatos é conferida por marcadores definidos no gabarito antes da execução: é indicativa e não substitui a leitura do resumo, registrada em resultados/nlp/conferencia_humana_rf15.json.
- Seis solicitações formam um conjunto pequeno: os números servem para detectar regressões, não para certificar o extrator (Aula 09 §5.2).
- O esquema garante a forma dos dados, não a verdade; a ancoragem confere presença no texto, não a atribuição correta de cada valor.
