# Resumo das Execuções (gerado do log de auditoria)
*Gerado por `resumir_auditoria.py` em 30/10/2026 13:26 a partir de `resultados/logs/auditoria.jsonl`.*

- Período coberto: 2026-10-17T10:44:53 a 2026-10-30T13:16:22
- Registros: 203 | chamadas a modelo de IA com sucesso: 160 | falhas: 1
- Minutas e respostas do RAG geradas: 34
- Desafio 02 (OpenAI): custo estimado pelo próprio adaptador com os preços do `config.json` por 1M de tokens
  (entrada / saída, raciocínio cobrado como saída): `gpt-5.6-luna` US$ 0.2 / 1.2; `gpt-5.6-terra` US$ 2.0 / 12.0; `text-embedding-3-small` US$ 0.02 / 0.0; `omni-moderation-latest` US$ 0.0 / 0.0 (https://developers.openai.com/api/docs/pricing (valores de ago/2026 reproduzidos nas apostilas FIC_DEV, Aulas 08, 09 e 11)).
  O adaptador simulado não mede tokens nem custo: aparece como "indisponível", nunca como zero.
- Desafio 01 (Gemini, legado): preço só para `gemini-3.8-flash`: US$ 0.00075 (entrada) e
  US$ 0.00375 (saída e raciocínio) por 1.000 tokens (https://ai.google.dev/gemini-api/docs/pricing, consultado em
  2026-10-16). No nível gratuito o custo efetivo é zero.

## Por provedor e modelo
| Provedor/modelo | Registros | Falhas | Tokens | Custo estimado (USD) |
| :--- | ---: | ---: | ---: | ---: |
| google/gemini-3.8-flash | 4 | 0 | 9714 | US$ 0.029867 |
| openai/gpt-5.6-luna | 114 | 0 | 200574 | US$ 0.060613 |
| openai/gpt-5.6-terra | 9 | 0 | 27009 | US$ 0.072898 |
| openai/text-embedding-3-small | 33 | 0 | 25170 | US$ 0.000503 |
| simulado/simulado-deterministico | 1 | 1 | 0 | indisponível (simulado: sem tokens nem custo) |

## Por etapa
| Etapa | Registros | Provedor/modelo | Prompt (versão) | Latência média | Tokens entrada | Tokens saída | Tokens raciocínio | Custo estimado (USD) |
| :--- | :---: | :--- | :--- | :---: | ---: | ---: | ---: | ---: |
| calibracao_limiar_rag | 3 (0 falha) | openai/text-embedding-3-small | - | 2.1 s | 744 | 0 | 0 | US$ 0.000015 |
| classificacao_sentimento | 12 (0 falha) | openai/gpt-5.6-luna | PROMPT_SENTIMENTO v1.0 | 2.4 s | 10790 | 1098 | 43 | US$ 0.003528 |
| comparativo_json_object_instrucao_generica | 2 (0 falha) | openai/gpt-5.6-luna | PROMPT_EXTRACAO_JSON_GENERICO v1.0 | 3.5 s | 582 | 636 | 0 | US$ 0.000880 |
| comparativo_json_object_instrucoes_do_contrato | 2 (0 falha) | openai/gpt-5.6-luna | PROMPT_EXTRACAO_V2 v1.0, PROMPT_EXTRACAO_V2 v1.1 | 2.5 s | 1787 | 421 | 0 | US$ 0.000863 |
| comparativo_structured_outputs_contrato | 2 (0 falha) | openai/gpt-5.6-luna | PROMPT_EXTRACAO_V2 v1.0, PROMPT_EXTRACAO_V2 v1.1 | 2.3 s | 3327 | 408 | 0 | US$ 0.001155 |
| conferencia_cruzada | 3 (0 falha) | sem modelo | - | 0.0 s | 0 | 0 | 0 | US$ 0.000000 |
| consulta | 1 (0 falha) | openai/text-embedding-3-small | - | 0.4 s | 20 | 0 | 0 | US$ 0.000000 |
| consulta_rag | 8 (0 falha) | openai/text-embedding-3-small | - | 1.4 s | 905 | 0 | 0 | US$ 0.000018 |
| consulta_t14 | 1 (0 falha) | openai/text-embedding-3-small | - | 0.4 s | 19 | 0 | 0 | US$ 0.000000 |
| exclusao_documento | 1 (0 falha) | sem modelo | - | - | 0 | 0 | 0 | US$ 0.000000 |
| experimento_chunking_perguntas | 1 (0 falha) | openai/text-embedding-3-small | - | 2.6 s | 229 | 0 | 0 | US$ 0.000005 |
| experimento_prompt_a | 1 (0 falha) | google/gemini-3.8-flash | PROMPT_A_ZERO_SHOT v1.0 | 15.4 s | 310 | 672 | 1187 | US$ 0.007204 |
| experimento_prompt_b | 1 (0 falha) | google/gemini-3.8-flash | PROMPT_B_ESTRUTURADO v1.0 | 16.6 s | 780 | 923 | 1563 | US$ 0.009908 |
| experimento_prompt_c | 1 (0 falha) | google/gemini-3.8-flash | PROMPT_C_METAPROMPT v2.0 | 30.7 s | 739 | 356 | 1403 | US$ 0.007150 |
| extracao_contrato_v2 | 17 (0 falha) | openai/gpt-5.6-luna | PROMPT_EXTRACAO_V2 v1.0, PROMPT_EXTRACAO_V2 v1.1 | 2.7 s | 28341 | 3391 | 0 | US$ 0.009737 |
| extracao_estruturada | 3 (0 falha) | openai/gpt-5.6-luna | PROMPT_EXTRACAO_JSON v1.1 | 4.8 s | 4383 | 1174 | 253 | US$ 0.002589 |
| ficha_nlp | 15 (0 falha) | openai/gpt-5.6-luna | PROMPT_FICHA_NLP v1.0 | 2.6 s | 11028 | 2069 | 85 | US$ 0.004791 |
| geracao_minuta | 3 (0 falha) | openai/gpt-5.6-luna | PROMPT_PRODUCAO_SISTEMA+PROMPT_B_ESTRUTURADO_V2 v1.1+2.1 | 3.5 s | 4227 | 718 | 93 | US$ 0.001818 |
| geracao_prompt_c_por_metaprompt | 1 (0 falha) | google/gemini-3.8-flash | METAPROMPT_GERADOR_PROMPT_C v1.0 | 12.3 s | 358 | 460 | 963 | US$ 0.005605 |
| guardrail_classificador_politica | 34 (0 falha) | openai/gpt-5.6-luna | PROMPT_CLASSIFICADOR_POLITICA v1.0 | 1.7 s | 37378 | 1767 | 83 | US$ 0.009696 |
| guardrail_entrada | 38 (0 falha) | sem modelo | - | 2.1 s | 0 | 0 | 0 | US$ 0.000000 |
| indexacao_acervo_principal | 7 (0 falha) | openai/text-embedding-3-small | - | 1.1 s | 8643 | 0 | 0 | US$ 0.000173 |
| indexacao_experimento_chunking_A | 6 (0 falha) | openai/text-embedding-3-small | - | 1.2 s | 8225 | 0 | 0 | US$ 0.000165 |
| indexacao_experimento_chunking_B | 6 (0 falha) | openai/text-embedding-3-small | - | 1.0 s | 6385 | 0 | 0 | US$ 0.000127 |
| ocr_visao | 2 (0 falha) | openai/gpt-5.6-luna | PROMPT_LEITURA_FICHA v1.0 | 13.9 s | 15966 | 1900 | 630 | US$ 0.006229 |
| rag_resposta | 32 (1 falha) | openai/gpt-5.6-luna, openai/gpt-5.6-terra, simulado/simulado-deterministico | PROMPT_RAG v1.0 | 3.8 s | 87388 | 6709 | 908 | US$ 0.092225 |

**Total estimado:** US$ 0.163881 em
262467 tokens.

## Falhas registradas
Inclui as falhas provocadas de propósito para testar limites e a falha do serviço (T05, T12); cada uma foi tratada
(bloqueio ou recusa padronizada) e está registrada com código e mensagem.

| Data | Etapa | Modelo | Código | Mensagem |
| :--- | :--- | :--- | :--- | :--- |
| 2026-10-30T13:12:54 | rag_resposta | simulado-deterministico | INDISPONIVEL | Falha simulada do serviço de geração (INDISPONIVEL), injetada para o teste de troca de pro |
