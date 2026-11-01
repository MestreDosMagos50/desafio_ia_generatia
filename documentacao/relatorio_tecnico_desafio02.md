# Relatório Técnico — Desafio Prático 02
**Central Inteligente de Atendimento e Comunicação Institucional — FIC_DEV (Aulas 08 a 14)**
*Cenário fictício: Secretaria Escolar da ETEC Cuiabá — SECITECI/MT. Todos os dados do Desafio 02 são fictícios.*

---

## 1. Continuidade do problema
O Desafio 01 transformava pedidos de matrícula (e-mail, voz e ficha manuscrita) em dados estruturados e numa minuta
revisada por pessoa. O Desafio 02 evolui a mesma central:
- **Contrato e compreensão:** contrato de dados versionado e ficha de compreensão (resumo, categoria, entidades).
- **Segurança:** guardrails em camadas.
- **Acervo:** acervo institucional indexado, com respostas que citam a fonte, recusam quando não há evidência e
  expõem conflitos.
- **Operação:** interface para o operador e painel de sentimentos das avaliações.
- **Auditoria:** registro que permite conferir a origem de cada minuta.

Nada é enviado automaticamente: toda minuta fica `PENDENTE_REVISAO_HUMANA` até a decisão do operador.

## 2. Arquitetura
```
entrada (texto, upload .txt/.pdf, OCR) ─ guardrails 1a (limites, regras) ─ 1b (moderação + política v1.1)
   │                                        bloqueio ⇒ fila do operador, sem minuta
   └─ contrato v2.0.0 (Structured Outputs) ─ regras de negócio em código ─ ficha (resumo ≤ 100 palavras)
        │                                     dado impossível ou sem lastro ⇒ bloqueio e revisão
        └─ fatos minimizados ─ busca top-4 (cosseno) + vizinhos + documento retificador ─ guardrail 2 (trechos)
             └─ guarda 1 (limiar 0,45) ─ guarda 2 (contrato do prompt, recusa fixa) ─ guarda 3 (ancoragem)
                  └─ guardrail 3 (segredo, dado pessoal, citação) ─ minuta com citações ─ fila do operador
avaliações ─ 1 chamada por avaliação (Literal) ─ rótulos CSV versionados ─ pandas (n/denominador, mínimo 10) ─ painel
tudo ─ auditoria.jsonl (ids, horários, versões, consulta mascarada, IDs recuperados, tokens, custo, decisão)
```

| Módulo | Responsabilidade |
| :--- | :--- |
| `src/adaptadores.py`, `src/llm_client.py` | Adaptadores OpenAI e simulado; timeout, 1 repetição, teto de chamadas e tokens, custo |
| `src/schemas.py`, `src/prompts.py` | Contratos e prompts versionados (`VERSOES_PROMPTS`) |
| `src/nlp.py` | Contrato, regras de negócio (data real, formato, ancoragem) e ficha de compreensão |
| `src/guardrails.py` | Camadas 1a, 1b, 2 (conteúdo recuperado) e 3 (saída) |
| `src/ingestion.py`, `src/embeddings.py` | Leitura por página, chunking, Chroma persistente, manifesto, exclusão |
| `src/rag.py` | Recuperação, três guardas, citações escritas pelo código, vigência e conflito |
| `src/sentiment.py`, `src/metrics.py` | Classificação de sentimentos e agregação determinística |
| `src/atendimento.py`, `src/app.py` | Fluxo integrado, fila de minutas, decisão do operador e interface Streamlit |
| `src/avaliacao.py`, `src/audit.py` | Matriz T01–T15, regressão T15, segunda geração e auditoria |

## 3. Provedor configurável (RF21)
| Configuração | Uso | Observação |
| :--- | :--- | :--- |
| `gpt-5.6-luna` (OpenAI) | Principal: contrato, ficha, política, RAG, sentimentos, OCR | US$ 0,20 / 1,20 por 1M tokens (entrada / saída) |
| `gpt-5.6-terra` (OpenAI) | 2ª configuração real, nas 8 perguntas do RAG | US$ 2,00 / 12,00 por 1M tokens |
| `text-embedding-3-small` | Embeddings do índice (1536 dimensões) | US$ 0,02 por 1M tokens |
| `omni-moderation-latest` | Moderação da entrada | Gratuita |
| Simulado | Testes offline e falha controlada (T12) | Sem rede, sem tokens, sem custo, **sem equivalência de qualidade** |
| Gemini (legado) | `--modo audio` do Desafio 01 | Fora das entregas do Desafio 02 |

- **Configuração:** provedor, modelos, parâmetros e preços ficam em `config.json`, e a chave só no `.env`.
- **Troca sem reindexar:** trocar a geração não toca no índice. No comparativo, o manifesto ficou idêntico, os 59
  vetores foram mantidos e só houve embeddings de consulta.
- **Falha do serviço:** a falha simulada virou a recusa padronizada (`FALHA_NA_GERACAO`), registrada com
  `sucesso=false`.
- **Guardrails na troca:** os guardrails de entrada continuam no cliente principal quando a geração é trocada.

## 4. Resultados medidos
Matriz completa em `documentacao/matriz_testes_rf23.md`: **12 CONFERE e 3 CONFERE_COM_RESSALVA**, nenhum PENDENTE nem
NAO_CONFERE. Os gabaritos foram elaborados antes de qualquer chamada ao modelo.

| Requisito | Medida | Resultado |
| :--- | :--- | :---: |
| RF14 (T01, T02) | Payloads inválidos rejeitados com o código certo; regras de negócio | 4/4; 2/2 |
| RF14 | JSON Mode genérico × Structured Outputs | JSON válido e fora do contrato (5 chaves extras) × válido |
| RF15 (T03) | Categoria; campos exatos; fatos essenciais; resumos ≤ 100 palavras | 6/6; 41/42; 21/22; 6/6 |
| RF16 (T04, T05) | Ataques; variantes; fora de escopo; limites; legítimas permitidas | 3/3; 4/4; 2/2; 2/2; 6/6 |
| RF17 (T06) | Reinício reutiliza o índice sem novo embedding | 7 docs reutilizados, 0 chamadas |
| RF18 (T07) | Acerto de recuperação A (350/50) × B (800/160); MRR | 5/5 × 5/5; 0,90 × 0,75 |
| RF19 (T08) | Respondíveis que conferem; afirmações essenciais; referências citadas | 4/5; 10/10; 8/8 |
| RF19 (T09, T10) | Abstenção nas sem resposta; conflito exposto | 2/2; 1/1 |
| RF20/RF24 (T11) | Decisões do operador na interface (APROVADA / REJEITADA / REVISAR) | 4 decisões (2 / 1 / 1) |
| RF21 (T12) | luna × terra nas mesmas perguntas | 4/5, 2/2, 1/1 nos dois |
| RF22 | Polaridade contra o gabarito; casos para revisão sinalizados | 11/12; 3/4 |
| RF23 (T13) | Filtro, duplicata e vazio nos rótulos reais | Totais certos, sem divisão por zero |
| RF24 (T14) | DOC-99 excluído deixa de ser recuperado e não volta sozinho | 0 trechos depois |
| RF23 (T15) | Texto e OCR do Desafio 01 até minuta e revisão | Os dois chegam; texto 24/26, OCR 21/26 |

**Métricas do RF23** (numerador / denominador):
- Acurácia de categorias: 6/6.
- Acerto de recuperação: 5/5.
- Respostas institucionais com todas as afirmações sustentadas: 5/6 na verificação automática (citação e números no
  trecho citado) e 5/6 na conferência humana (17/18 afirmações sustentadas; a meta-afirmação sem citação da RAG-08 foi
  reprovada).
- Abstenção correta: 2/2.
- Caso contraditório, registrado à parte: RAG-08 com os dois trechos expostos.
- Sentimentos: 11/12.

**Falhas e o que foi feito com elas** (o detalhe está em `resultados/metricas/` e em `historico/`):
- **RAG-01:**
  - *Falha:* aplica a retificação certa (30/10/2026), mas cita só o DOC-02. O luna e o terra cometeram o mesmo
    desvio, o que aponta para o prompt ou o contexto, e não para o modelo.
  - *Feito:* o prompt não foi ajustado sobre o conjunto de avaliação; o código passou a conferir a regra e manda a
    minuta à revisão prioritária (`CITACAO_DE_VIGENCIA_INCOMPLETA`). Uma nova versão do prompt fica como melhoria.
- **AV-12 ("Foi como eu esperava."):**
  - *Falha:* rotulada positiva em vez de indeterminada e fora da fila de revisão. A ambiguidade autodeclarada prioriza
    a revisão, mas não a delimita (Aula 14 §4.2).
- **OCR da ficha (T15):**
  - *Falha:* código e RG lidos errado sem marcação de incerteza (o mesmo "2024" que o Gemini leu no Desafio 01). No
    fluxo integrado, a leitura ia direto para a extração.
  - *Feito:* toda entrada de OCR passa a ter um alerta obrigatório e revisão prioritária. Na revisão da fila
    (`DEC-44785D43`), a minuta do OCR foi rejeitada após conferência na imagem original.
- **Política v1.0:**
  - *Falha:* bloqueou a ficha SOL-05 por ler a regra 3 como "contém dados pessoais".
  - *Feito:* a v1.1 esclarece a regra; a v1.0 e a execução anterior foram preservadas.
- **Variação entre execuções:** a extração do texto deu 25/26 e 24/26 no mesmo dia, e os campos marcados como incertos
  no OCR mudaram entre execuções. Uma execução isolada não mede a estabilidade.

## 5. Custos e desempenho (medidos no log)
- **Total do desenvolvimento:** o Desafio 02 inteiro, incluindo as execuções repetidas, custou cerca de US$ 0,13: luna
  US$ 0,061, terra US$ 0,073 e embeddings US$ 0,0005. O detalhe por etapa está em `documentacao/resumo_execucoes.md`.
- **Por resposta do RAG:** luna cerca de US$ 0,0009 e 4,0 s; terra cerca de US$ 0,008 e 2,9 s.
- **Por atendimento completo:** cerca de US$ 0,002 em 6 chamadas (moderação, política, contrato, ficha, embedding e
  minuta).
- **Lotes de avaliação:** as 12 avaliações de sentimento custaram US$ 0,0035; a avaliação dos guardrails, 28 chamadas
  e US$ 0,0043.
- **Simulado:** não mede tokens nem custo e aparece como "indisponível", nunca como zero.

## 6. Privacidade e governança (RF24)
- **Só dados fictícios:** os editais reais de `contexto/` serviram de inspiração; não foram copiados, não são
  versionados e não entram no zip. Um teste confere, por hash, que nomes e o endereço reais não aparecem em `dados/`.
- **Minimização:** o RAG recebe fatos minimizados (assunto, pedido, curso e data), sem nome, CPF ou contatos.
  Avaliações vão ao provedor só com o texto e o canal.
- **Logs:** credenciais removidas; CPF, e-mail e telefone mascarados; consulta gravada mascarada e truncada.
- **Exclusão:** remove os vetores de todas as coleções, fica registrada no manifesto e na auditoria e sobrevive à
  reconstrução do índice. O documento só volta por reinclusão explícita.
- **Retenção:** respostas já gravadas ficam como registro histórico.
- **Revisão humana obrigatória:**
  - estados `PENDENTE`, `APROVADA`, `REJEITADA` e `REVISAR`, com operador e justificativa;
  - a aprovação só libera o envio manual;
  - a participação da IA (provedor, modelo e prompt) fica no registro da decisão.

## 7. Limitações
1. **Corpus pequeno e sintético:** 6 solicitações, 7 documentos, 8 perguntas e 12 avaliações, escritos pela mesma
   equipe que fez os gabaritos. Acurácia alta aqui não prevê desempenho em material real.
2. **Limiar:** calibrado em 9 perguntas, sem sobreposição observada, mas com folga de só 0,035 entre os grupos. As
   abstenções vieram todas do prompt.
3. **Conferências indicativas:** marcadores e trechos literais apontam problemas, mas não substituem a leitura humana
   da sustentação de cada afirmação.
4. **Detector numérico:** acha número inventado, não número verdadeiro atribuído ao documento errado (Aula 12 §4.3).
5. **Leitura de manuscrito:** erra sem sinalizar; a ficha precisa de conferência humana na imagem.
6. **Áudio:** `--modo audio` depende do Gemini legado. O T15 usa o caso de OCR.
7. **Índice fora do pacote:** `indice/chroma` não vai no zip; numa instalação nova, `--modo indexar` recria o índice
   por menos de US$ 0,001, e as exclusões registradas no manifesto continuam valendo.

## 8. Uso de IA no desenvolvimento
- **Divisão de trabalho:** o plano foi elaborado com um agente do Gemini (Antigravity) e revisado com o Claude Code
  (Opus 5.5), que estudou o material, apontou problemas no plano e implementou os blocos sob orientação da equipe.
- **Registro completo:** solicitações, sugestões aceitas, modificadas e rejeitadas, erros encontrados e separação
  entre evidência real e simulada estão em `documentacao/uso_ia.md`.
