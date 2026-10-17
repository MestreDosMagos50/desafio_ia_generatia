# Resumo das Execuções (gerado do log de auditoria)
*Gerado por `resumir_auditoria.py` em 17/10/2026 10:51 a partir de `resultados/logs/auditoria.jsonl`.*

- Período coberto: 2026-10-17T10:18:17 a 2026-10-17T10:45:59
- Registros: 11 | chamadas a modelo de IA com sucesso: 8 | falhas: 0
- Minutas geradas: 1
- Preço usado no custo estimado: US$ 0.00075 (entrada) e US$ 0.00375 (saída e raciocínio)
  por 1.000 tokens (https://ai.google.dev/gemini-api/docs/pricing, consultado em 2026-10-16). No nível gratuito o custo efetivo é zero.

## Por etapa
| Etapa | Registros | Provedor/modelo | Prompt (versão) | Latência média | Tokens entrada | Tokens saída | Tokens raciocínio | Custo estimado (USD) |
| :--- | :---: | :--- | :--- | :---: | ---: | ---: | ---: | ---: |
| conferencia_cruzada | 2 (0 falha) | sem modelo | - | 0.0 s | 0 | 0 | 0 | 0.000000 |
| experimento_prompt_a | 1 (0 falha) | google/gemini-3.8-flash | PROMPT_A_ZERO_SHOT v1.0 | 15.4 s | 310 | 672 | 1187 | 0.007204 |
| experimento_prompt_b | 1 (0 falha) | google/gemini-3.8-flash | PROMPT_B_ESTRUTURADO v1.0 | 16.6 s | 780 | 923 | 1563 | 0.009908 |
| experimento_prompt_c | 1 (0 falha) | google/gemini-3.8-flash | PROMPT_C_METAPROMPT v2.0 | 30.7 s | 739 | 356 | 1403 | 0.007150 |
| extracao_estruturada | 1 (0 falha) | google/gemini-3.8-flash | PROMPT_EXTRACAO_JSON v1.1 | 12.5 s | 661 | 416 | 1132 | 0.006301 |
| geracao_minuta | 1 (0 falha) | google/gemini-3.8-flash | PROMPT_PRODUCAO_SISTEMA+PROMPT_B_ESTRUTURADO_V2 v1.1+2.0 | 51.4 s | 1276 | 321 | 1028 | 0.006016 |
| geracao_prompt_c_por_metaprompt | 1 (0 falha) | google/gemini-3.8-flash | METAPROMPT_GERADOR_PROMPT_C v1.0 | 12.3 s | 358 | 460 | 963 | 0.005605 |
| ocr_visao | 1 (0 falha) | google/gemini-3.8-flash | PROMPT_LEITURA_FICHA v1.0 | 37.8 s | 1488 | 1585 | 3593 | 0.020533 |
| sintese_voz | 1 (0 falha) | microsoft-edge-tts/pt-BR-FranciscaNeural | - | 6.9 s | 0 | 0 | 0 | 0.000000 |
| verificacao_tts | 1 (0 falha) | google/gemini-3.8-flash | PROMPT_TRANSCRICAO_AUDIO v1.0 | 8.4 s | 2964 | 413 | 589 | 0.005980 |

**Total estimado:** US$ 0.068697 em
25180 tokens.

## Falhas registradas
Nenhuma.
