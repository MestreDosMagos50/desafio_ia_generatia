# Roteiro da Apresentação — Desafio 02 (até 15 minutos)
*Distribuição da Seção 14 do enunciado. Qualquer integrante pode ser chamado a executar um teste ou explicar uma
decisão; a seção final lista os comandos e as respostas que convém ter prontos.*

**Antes de começar:**
- `python -m src.main --check-env` deve mostrar o índice COMPATIVEL.
- `streamlit run src/app.py` aberto no navegador.
- `documentacao/matriz_testes_rf23.md` aberto numa aba.

---

## 1. Continuidade do problema e arquitetura (1 min)
- **Fala:** a mesma central do Desafio 01. Entra a solicitação e sai uma minuta revisada por pessoa; agora com acervo
  indexado, respostas com fonte, guardrails, painel e auditoria. Nada é enviado automaticamente.
- **Mostrar:**
  - o diagrama do relatório técnico (§2);
  - a troca de provedor em `config.json` (`llm.openai`): luna principal, terra como 2ª configuração e simulado
    identificado.

## 2. Extração, validação e NLP (2 min)
- **Fala:**
  - *contrato v2.0.0:* ausência é `null` com `campos_ausentes`, e a interface mostra "não localizado";
  - *T01:* JSON válido não basta. O JSON Mode genérico deu JSON válido e fora do contrato (5 chaves extras); o
    Structured Outputs deu um contrato válido;
  - *T02:* a regra de negócio em código bloqueia data impossível (31/02/2026) e valor sem lastro no texto.
- **Mostrar:** `resultados/metricas/avaliacao_nlp_rf15.md`.
  - **Resultados:** categoria 6/6, campos 41/42, fatos 21/22, resumos ≤ 100 palavras 6/6.
  - **Falha:** dizer qual foi a divergência e que a conferência humana do resumo está registrada.

## 3. Índice, RAG com fontes, ausência de evidência e revisão (5 min)
- **Índice (T06, T07):**
  - **Fala:** Chroma em cosseno com embeddings gerados no código; o manifesto guarda modelo, chunking e hash.
  - **Mostrar:** rodar `--modo indexar` duas vezes (reuso, 0 embeddings) e o chunking A × B (5/5 nos dois; A com MRR
    0,90 e o retificador em 1º lugar).
- **RAG (T08–T10):** na interface, aba *Atendimento e revisão*, processar a SOL-01, ou rodar
  `python -m src.main --modo responder --consulta "Qual é o valor do auxílio-transporte?"`.
  - **Citação:** cada citação é escrita pelo código a partir do índice. Abrir o expansor de trechos.
  - **Ausência de evidência:** RAG-06 e RAG-07 recebem a recusa padronizada, que vem do prompt (o limiar 0,45 não
    corta nenhuma pergunta). O painel de trechos aparece também na recusa.
  - **Conflito:** a RAG-08 expõe 5 dias úteis (DOC-04) e 15 dias corridos (DOC-05), sem escolher.
  - **Falha:** a RAG-01 aplica a retificação, mas cita só o DOC-02; o luna e o terra cometeram o mesmo desvio. O
    alerta `CITACAO_DE_VIGENCIA_INCOMPLETA` manda a minuta à revisão prioritária.
- **Revisão (T11):** na fila de minutas, aprovar uma minuta e rejeitar outra com justificativa. Mostrar que a
  aprovação só libera o envio manual.
- **Exclusão (T14):** excluir um documento na aba *Acervo e índice*, ou mostrar `resultados/indice/exclusao_t14.md`.
  O DOC-99 deixa de ser recuperado e não volta numa reindexação.

## 4. Guardrails, ataque e auditoria (3 min)
- **Fala:** camadas em ordem de custo:
  - 1a: limites e regras locais;
  - 1b: moderação e classificador de política numerada (v1.1);
  - 2: trechos do acervo com instrução ao sistema são neutralizados;
  - 3: segredo e dado pessoal na saída.
  Camada que não executa leva à revisão, nunca libera.
- **Mostrar:** `resultados/guardrails/avaliacao_guardrails_rf16.md`.
  - **Resultados:** ataques 3/3, variantes 4/4, fora de escopo 2/2, limites 2/2, legítimas 6/6.
  - **Ponto honesto:** a moderação não pegou nenhum ataque (0/6), e as regras locais pegaram 4/6. Por isso a
    política existe.
  - **Histórico:** a v1.0 da política gerou falso positivo e foi preservada.
- **Auditoria (T12):** aba *Provedor e auditoria*.
  - Trocar para "simulado com falha" e processar: sai a recusa `FALHA_NA_GERACAO`, com `sucesso=false` no log.
  - O índice continua o mesmo objeto. No comparativo luna × terra, o manifesto não mudou.
  - Uma linha do log tem consulta mascarada, IDs recuperados, versões, tokens e custo.

## 5. Sentimentos e agregação (2 min)
- **Fala:**
  - uma avaliação por chamada, com `Literal` em todo campo e sem confiança numérica;
  - mista, irônica ou sem contexto é "indeterminada";
  - o modelo classifica e o código conta.
- **Mostrar:** aba *Painel de sentimentos*.
  - **Ficha técnica no topo:** N=12, censo, acurácia 11/12.
  - **Filtro presencial:** com 5 avaliações, o percentual some.
  - **Fila de revisão.**
  - **Falha:** a AV-12 ("Foi como eu esperava.") saiu positiva e ficou fora da fila; a ambiguidade autodeclarada não
    delimita a revisão.

## 6. Métricas, limitações e uso de IA (2 min)
- **Mostrar:** `documentacao/matriz_testes_rf23.md`.
  - **Matriz:** 11 CONFERE, 3 CONFERE_COM_RESSALVA e o T11, que depende das decisões feitas ao vivo.
  - **Métricas do RF23:** categorias 6/6, recuperação 5/5, sustentação 5/6 automática (mais a conferência humana),
    abstenção 2/2, conflito à parte, sentimentos 11/12.
- **Regressão (T15):**
  - **Resultado:** texto e OCR do Desafio 01 chegam à minuta e à revisão.
  - **Falha:** o OCR leu o código como "2024" sem marcar incerteza.
  - **Correção:** alerta obrigatório e revisão prioritária para toda entrada de OCR.
- **Limitações:** corpus pequeno e sintético; limiar com folga de 0,035; conferências por marcador são indicativas;
  `--modo audio` depende do Gemini legado.
- **Uso de IA:**
  - *Divisão:* plano com um agente do Gemini, revisão e implementação com o Claude Code.
  - *Exemplo modificado:* decisões do Desafio 02 em arquivo próprio.
  - *Exemplo rejeitado:* ajustar o prompt ao conjunto de avaliação.
  - *Evidência:* separação entre real e simulada em `documentacao/uso_ia.md`.

---

## Verificação prática: comandos e respostas prontas
| Pedido provável | Comando ou resposta |
| :--- | :--- |
| Rodar os testes | `pytest` (offline, sem custo) |
| Mostrar que o índice é reutilizado | `python -m src.main --modo indexar` (2ª vez: 0 chamadas de embedding) |
| Fazer uma pergunta sem resposta | `python -m src.main --modo responder --consulta "A escola tem intercâmbio no exterior?"` |
| Provar que a troca de geração não reindexa | `resultados/metricas/comparativo_geracao_rf21.md` (manifesto idêntico, 59 vetores) |
| Mostrar a exclusão | `python -m src.main --modo demonstrar-exclusao` ou a aba *Acervo e índice* |
| Refazer a matriz | `python -m src.main --modo avaliacao-integrada` (sem chamadas ao modelo) |
| Conferir segredos | `python verificar_entrega.py` |
| Por que 0,45 e não 0,50? | Regra registrada antes da medição: não cortar pergunta com resposta, com folga de 0,05 |
| Por que a confiança não é número? | Aula 14: escala ordinal; a ambiguidade autodeclarada é estimativa não calibrada |
| Por que o OCR não vai direto? | Erra sem marcar incerteza; precisa de conferência humana na imagem |
