# Segunda configuração de geração sobre o mesmo índice (RF21, T12)

- Gerado em 2026-10-30T13:12:54. Execuções: gpt-5.6-luna em 2026-10-30T12:16:20; gpt-5.6-terra em 2026-10-30T13:12:53. Mesmo índice, mesmo prompt (PROMPT_RAG), mesmas perguntas e mesmo limiar.
- Índice: manifesto `77c76879b170feaf…` antes e `77c76879b170feaf…` depois; vetores 59 -> 59; chamadas de embedding nesta execução: 2, todas de consulta. **Preservado: sim.**

## Resultado por configuração

| Medida | gpt-5.6-luna | gpt-5.6-terra |
|---|---:|---:|
| T08: respondíveis que conferem | 4/5 | 4/5 |
| T08: afirmações essenciais | 10/10 | 9/10 |
| T08: referências essenciais citadas | 8/8 | 8/8 |
| T09: abstenção correta | 2/2 | 2/2 |
| T10: conflito tratado | 1/1 | 1/1 |
| Recusas indevidas | 0/6 | 0/6 |
| Tokens de geração (9 perguntas) | 27418 | 27009 |
| Custo estimado (US$) | 0.007781 | 0.072898 |
| Latência média por resposta (ms) | 4040.0 | 2929.3 |

## Por pergunta

| Pergunta | Esperado | gpt-5.6-luna | gpt-5.6-terra |
|---|---|---|---|
| RAG-01 | FUNDAMENTADA | FUNDAMENTADA (NÃO confere; 1 alerta(s)) | FUNDAMENTADA (NÃO confere; 1 alerta(s)) |
| RAG-02 | FUNDAMENTADA | FUNDAMENTADA (confere; 1 alerta(s)) | FUNDAMENTADA (confere; 1 alerta(s)) |
| RAG-03 | FUNDAMENTADA | FUNDAMENTADA (confere; 0 alerta(s)) | FUNDAMENTADA (confere; 0 alerta(s)) |
| RAG-04 | FUNDAMENTADA | FUNDAMENTADA (confere; 0 alerta(s)) | FUNDAMENTADA (confere; 0 alerta(s)) |
| RAG-05 | FUNDAMENTADA | FUNDAMENTADA (confere; 0 alerta(s)) | FUNDAMENTADA (confere; 0 alerta(s)) |
| RAG-06 | SEM_EVIDENCIA_SUFICIENTE | SEM_EVIDENCIA_SUFICIENTE (confere; 0 alerta(s)) | SEM_EVIDENCIA_SUFICIENTE (confere; 0 alerta(s)) |
| RAG-07 | SEM_EVIDENCIA_SUFICIENTE | SEM_EVIDENCIA_SUFICIENTE (confere; 0 alerta(s)) | SEM_EVIDENCIA_SUFICIENTE (confere; 0 alerta(s)) |
| RAG-08 | CONFLITO_DE_FONTES | CONFLITO_DE_FONTES (confere; 1 alerta(s)) | CONFLITO_DE_FONTES (confere; 2 alerta(s)) |

## Falha do serviço de geração (T12)

- Configuração simulada com falha `INDISPONIVEL`, mesmo índice: status SEM_EVIDENCIA_SUFICIENTE (FALHA_NA_GERACAO); resposta é a recusa padronizada: sim; trechos consultados visíveis: 8.
- Auditoria (`EXEC-86DCC6B4`): sucesso=False, codigo_erro=INDISPONIVEL, provedor=simulado.

## Como ler

- Oito perguntas não bastam para dizer que um modelo é melhor que o outro: as diferenças são indicativas e a variação entre execuções do mesmo modelo é da mesma ordem. O que o RF21 exige — trocar a geração sem reconstruir o índice e tratar a falha — é o que esta execução demonstra.
- O simulado não entra na comparação de qualidade; ele só demonstra a falha controlada.
