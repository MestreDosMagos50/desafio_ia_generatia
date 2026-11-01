# Central Inteligente de Atendimento e Comunicação Institucional
**Programa FIC_DEV — Programador de Sistemas com IA**
*Desafio Prático 2: Inteligência Artificial Generativa (Aulas 08 a 14), evolução do Desafio Prático 1 (Aulas 01 a 07)*
*Cenário fictício: Secretaria Escolar da ETEC Cuiabá / SECITECI — Governo de Mato Grosso. Todos os dados do Desafio 02 são fictícios.*

---

## 1. O que o sistema faz

A central recebe a solicitação do cidadão e entrega ao servidor uma **minuta revisável**, sempre com as fontes à
vista. **Nada é enviado automaticamente.**

1. **Proteção da entrada (RF16):** a entrada passa pelas camadas 1a e 1b:
   - **1a:** limites de arquivo e texto e regras locais contra ofuscação;
   - **1b:** moderação (`omni-moderation-latest`) e um classificador de política numerada e versionada.

   Entrada bloqueada não gera minuta e vai para o operador.
2. **Compreensão (RF14, RF15):** contrato de dados v2.0.0 por Structured Outputs. Ausência é `null` e aparece como
   "não localizado". Regras de negócio em código conferem data real, formato e ancoragem no texto original. A ficha
   traz resumo (até 100 palavras), categoria e entidades literais separadas das inferidas.
3. **Acervo e RAG (RF17–RF19):**
   - *Acervo:* 7 documentos fictícios em Chroma persistente (cosseno, `text-embedding-3-small`).
   - *Contexto:* top-4, mais os vizinhos da mesma seção e o documento retificador.
   - *Três guardas:* limiar calibrado, contrato do prompt com recusa fixa e ancoragem numérica.
   - *Citações:* escritas pelo código a partir do índice.
   - *Conflito:* fontes divergentes sem regra escrita viram `CONFLITO_DE_FONTES`.
4. **Revisão humana (RF20, RF24):** cada minuta entra na fila do operador e recebe uma decisão: `PENDENTE`,
   `APROVADA`, `REJEITADA` ou `REVISAR`, com justificativa. Aprovar só libera o envio manual.
5. **Sentimentos (RF22):** as 12 avaliações são classificadas uma por chamada, com rótulos fechados e sem confiança
   numérica. Toda conta é feita em pandas, com denominador, e o percentual só aparece com base de pelo menos 10.
6. **Auditoria (RF21):** cada chamada fica em `resultados/logs/auditoria.jsonl` com:
   - versões do esquema, do prompt e do índice;
   - consulta mascarada e IDs recuperados;
   - tokens, custo e erros;
   - vínculo com a decisão humana.
7. **Desafio 01 preservado:** texto, ficha, minuta, voz e cartaz continuam funcionando (`--modo texto|visao|...`). A
   regressão T15 reexecuta o texto e o OCR da ficha.

---

## 2. Requisitos e versões

- **Python 3.12** (testado com 3.12.10 no Windows 11). Versões fixadas em `requirements.txt`:

| Biblioteca | Versão | Uso |
| :--- | :--- | :--- |
| `openai` | 3.41.0 | Geração, embeddings e moderação (Desafio 02) |
| `chromadb` | 1.5.9 | Índice vetorial persistente |
| `pymupdf` | 2.0 | Leitura de PDF por página; PDF → PNG para a visão |
| `streamlit` | 1.62.0 | Interface do assistente |
| `pandas` | 3.1.0 | Agregação determinística |
| `pydantic` | 2.14.1 | Contratos e esquemas |
| `python-dotenv`, `httpx` | 1.2.3, 0.28.1 | `.env` e transporte HTTP |
| `google-genai`, `edge-tts`, `mutagen`, `pillow`, `gradio_client`, `pypdf`, `python-docx` | ver arquivo | Desafio 01 (Gemini legado, voz, cartaz, minuta `.docx`) |
| `pytest` | 9.1.1 | Testes |

- **Modelos** (`config.json`, bloco `llm.openai`; consumo real em `documentacao/resumo_execucoes.md`):

| Configuração | Modelo | Preço por 1M tokens (entrada / saída) |
| :--- | :--- | :--- |
| Principal | `gpt-5.6-luna` | US$ 0,20 / 1,20 |
| 2ª configuração real (RF21) | `gpt-5.6-terra` | US$ 2,00 / 12,00 |
| Embeddings | `text-embedding-3-small` (1536 dimensões) | US$ 0,02 |
| Moderação | `omni-moderation-latest` | gratuita |
| Simulado | local, sem rede | sem tokens nem custo; **sem equivalência de qualidade** |
| Legado do Desafio 01 | Gemini (`LLM_PROVIDER=google`) | só para `--modo audio` e cartaz |

---

## 3. Instalação

```bash
cd desafio_ia_generativa
python -m venv venv
.\venv\Scripts\activate          # Windows  (Linux/macOS: source venv/bin/activate)
pip install -r requirements.txt
copy .env.example .env           # Linux/macOS: cp .env.example .env
```

No `.env`, preencha só a chave (`LLM_PROVIDER=openai` já é o padrão):
```env
OPENAI_API_KEY=sua_chave          # https://platform.openai.com/api-keys
```
O `.env` está no `.gitignore` e fica fora do pacote. Nunca cole a chave em código, chat ou log.

```bash
python -m src.main --check-env        # ambiente, arquivos e situação do índice, sem rede
python -m src.main --testar-conexao   # confere a chave com 5 chamadas mínimas (frações de centavo)
```

---

## 4. Índice vetorial: criar, reutilizar e excluir

```bash
python -m src.main --modo indexar                # cria o índice; na 2ª vez reutiliza sem novo embedding (T06)
python -m src.main --modo buscar --consulta "Até quando posso fazer a matrícula?"
python -m src.main --modo experimento-chunking   # compara as configurações A (350/50) e B (800/160) (T07)
python -m src.main --modo demonstrar-exclusao    # exclui o DOC-99 e mostra que deixa de ser recuperado (T14)
```
- **O que vai no pacote:** `indice/chroma/` não é versionado nem empacotado; `indice/manifesto_indice.json` é.
- **Instalação nova:** `--modo indexar` recria o índice por menos de US$ 0,001. O que o manifesto registra continua
  valendo: o DOC-99 excluído não volta.
- **Quando reindexar:** mudar o modelo de embedding, a dimensão, o chunking ou `indice.versao_indice` exige
  reindexação completa. Documento com o mesmo hash é reutilizado.
- **Acervo:** é gerado de forma determinística por `python scripts/gerar_acervo_ficticio.py`.

---

## 5. Como executar

### 5.1. Interface (RF20)
```bash
streamlit run src/app.py
```
| Aba | O que faz |
| :--- | :--- |
| Acervo e índice | Situação de cada documento (aviso de índice desatualizado), reindexação, inclusão de `.txt`/`.pdf` (apenas fictícios; o temporário é apagado), busca top-k com a similaridade explicada e exclusão auditada |
| Atendimento e revisão | Solicitação de teste ou digitada → guardrails → contrato → ficha → minuta com os trechos consultados (também na recusa); fila de minutas com decisão e justificativa |
| Painel de sentimentos | Ficha técnica no topo, filtros, contagens com denominador e fila de revisão; sem chamada de API |
| Provedor e auditoria | Configuração em uso (troca na barra lateral: luna, terra, simulado ou simulado com falha), índice preservado, uso por modelo, log sanitizado e relatórios |

Cada consulta é independente: não há memória de conversa (Aula 15 fora do escopo).

### 5.2. Linha de comando (Desafio 02)
| Comando | O que faz | Chamadas (aprox.) |
| :--- | :--- | :---: |
| `--modo avaliar-nlp` | Contrato, regras de negócio e ficha das 6 solicitações contra o gabarito (T01–T03) | 16 |
| `--modo avaliar-guardrails` | Ataques, variantes, fora de escopo, limites e filtro de saída (T04, T05) | ~30 |
| `--modo calibrar-limiar` | Similaridade top-1 das perguntas e limiar sugerido pela regra registrada | 1 embedding |
| `--modo avaliar-rag` | 8 perguntas e controle do T14 contra o gabarito (T08–T10) | 9 |
| `--modo responder --consulta "..."` | Guardrails de entrada e resposta com fontes | ~4 |
| `--modo sentimentos` | 12 avaliações, conferência com o gabarito e indicadores (RF22) | 12 |
| `--modo comparar-geracao` | 8 perguntas no `gpt-5.6-terra` sobre o mesmo índice e falha simulada (RF21, T12) | 9 (≈ US$ 0,08) |
| `--modo regressao` | Texto e OCR do Desafio 01 até minuta e revisão (T15); revisão do texto no terminal | ~9 |
| `--modo avaliacao-integrada` | Matriz T01–T15 e métricas do RF23 a partir das evidências; `--reexecutar` refaz tudo antes | 0 |

Com `--demo-avaliacao-humana`, as decisões de revisão do Desafio 01 (inclusive na regressão) são **simuladas**:
ficam em `resultados/logs/decisoes_simuladas.json`, fora da taxa de aprovação.

### 5.3. Desafio 01 (preservado)
| Comando | O que faz |
| :--- | :--- |
| `python -m src.main --modo texto` | Extração, conferência, minuta, revisão no terminal e voz |
| `python -m src.main --modo visao` | Leitura da ficha manuscrita e confirmação humana dos campos críticos |
| `python -m src.main --modo audio` / `--modo cartaz` | Exigem o Gemini legado (`LLM_PROVIDER=google`) |
| `python -m src.main --modo texto --entrada-texto dados/originais/entrada_texto_injection.txt` | Caso de prompt injection (RF03) |
| `python -m src.main --modo experimento-prompts` | Experimento RF02 |

A revisão no terminal não tem opção padrão. As decisões do Desafio 01 ficam em `resultados/logs/decisoes_humanas.json`
e alimentam `documentacao/relatorio_avaliacao_qualidade.md`.

---

## 6. Testes

```bash
pytest                                             # offline: adaptador simulado, SDK e embeddings falsos, pastas temporárias
$env:RODAR_TESTES_INTEGRACAO="1"; pytest           # PowerShell: inclui o teste com o modelo real
```
Resultado atual: **292 testes passando e 1 pulado** (o de integração).

**O que a suíte cobre:**
- *Contratos e guardrails:* contrato e T01/T02; ficha e avaliação contra o gabarito; guardrails por camada; limites e
  orçamento.
- *Índice:* reuso, exclusão e instalação nova.
- *RAG:* guardas, citações, vigência e conflito.
- *Sentimentos e agregação:* regras e T13.
- *Fluxo e interface:* fluxo integrado; T11 pela própria interface (`AppTest`); T12; campos do RF21 no log.
- *Integração e legado:* matriz T01–T15 e os 60 testes do Desafio 01.

---

## 7. Estrutura

```
desafio_ia_generativa/
├── config.json, requirements.txt, .env.example, pytest.ini, AGENTS.md
├── src/
│   ├── main.py            # Ponto de entrada (python -m src.main), modos do Desafio 01 e 02
│   ├── adaptadores.py     # OpenAI e simulado (RF21)        ├── llm_client.py  # timeout, repetição, orçamento, Gemini legado
│   ├── schemas.py         # Contratos versionados          ├── prompts.py     # Prompts versionados
│   ├── nlp.py             # Contrato, regras e ficha       ├── guardrails.py  # Camadas 1a, 1b, 2 e 3
│   ├── ingestion.py       # Leitura e chunking             ├── embeddings.py  # Índice, manifesto e exclusão
│   ├── rag.py             # RAG fundamentado               ├── sentiment.py   # Sentimentos
│   ├── metrics.py         # Agregação em pandas            ├── atendimento.py # Fluxo integrado e serviços
│   ├── app.py             # Interface Streamlit            ├── avaliacao.py   # Matriz, T15 e RF21
│   ├── audit.py           # Log, decisões e relatório      └── (Desafio 01) parsers, audio, vision, conferencia,
│   │                                                         revisao_humana, image_generation, privacidade
├── prompts/               # Prompts do Desafio 01 e política de escopo v1.0 e v1.1
├── dados/                 # originais/ (Desafio 01), acervo/, solicitacoes/, avaliacoes/, adversariais/, gabaritos/
├── indice/                # manifesto_indice.json (versionado) e chroma/ (local)
├── resultados/            # nlp/, metricas/ (com historico/), guardrails/, indice/, rag/, sentimentos/,
│                          # atendimentos/, regressao/, logs/, minutas/
├── scripts/               # gerar_acervo_ficticio.py
├── testes/                # pytest
├── documentacao/          # matriz T01–T15, relatórios técnicos, uso de IA, roteiros
├── resumir_auditoria.py   # documentacao/resumo_execucoes.md a partir do log
├── limpar_resultados.py   # limpa o pipeline do Desafio 01 e preserva o Desafio 02
├── verificar_entrega.py   # entregáveis, matriz, pendências humanas e vazamento de chaves
└── empacotar_entrega.py   # .zip sem .env, .streamlit, contexto/ e caches
```

---

## 8. Avaliação final e entrega

1. **Etapas humanas** (o `verificar_entrega.py` mostra as que faltam):
   - revisar os 4 gabaritos do Desafio 02 (`revisao_humana` em `dados/gabaritos/`) e a política de escopo v1.1;
   - preencher `resultados/nlp/conferencia_humana_rf15.json` e `resultados/metricas/conferencia_sustentacao_rag.json`
     (campo `sustentada` de cada afirmação);
   - na interface, aprovar ao menos uma minuta e rejeitar ou mandar para revisão outra (RF24, T11);
   - opcional: `python -m src.main --modo regressao` no terminal, para a decisão humana da revisão do texto do T15.
2. **Matriz:** `python -m src.main --modo avaliacao-integrada` (refaz a matriz e as métricas do RF23).
3. **Conferências:** `python resumir_auditoria.py`, `pytest` e `python verificar_entrega.py`.
4. **Empacotamento:** `python empacotar_entrega.py`. Depois, descompactar em pasta nova, instalar e rodar
   `--check-env`, `--modo indexar` e `pytest`.
5. **Envio:** o `.zip` vai para ficdev00@gmail.com com o assunto `Desafio02-FICDEV-IAGenerativa`, no prazo do
   comunicado oficial.

---

## 9. Custos medidos

Cifras estimadas pelo adaptador com os preços do `config.json` e somadas do log (`documentacao/resumo_execucoes.md`):

| Operação | Custo aproximado |
| :--- | :--- |
| Resposta do RAG (`gpt-5.6-luna`) | US$ 0,0009 e 4,0 s |
| Resposta do RAG (`gpt-5.6-terra`) | US$ 0,008 e 2,9 s |
| Atendimento completo (6 chamadas) | US$ 0,002 |
| 12 avaliações de sentimento | US$ 0,0035 |
| Indexação do acervo (59 vetores) | US$ 0,0002 |
| Todo o desenvolvimento do Desafio 02 (com repetições) | cerca de US$ 0,13 |

---

## 10. Limitações conhecidas

1. **Corpus pequeno e sintético:** 6 solicitações, 7 documentos, 8 perguntas e 12 avaliações, escritos pela mesma
   equipe dos gabaritos. Os resultados não preveem o desempenho em material real.
2. **Variação entre execuções:** a extração do texto do Desafio 01 deu 25/26 e 24/26 no mesmo dia. Uma execução
   isolada não mede estabilidade.
3. **RAG-01:**
   - *Falha:* a retificação é aplicada, mas a resposta cita só o DOC-02, no luna e no terra.
   - *Hoje:* o alerta `CITACAO_DE_VIGENCIA_INCOMPLETA` manda a minuta à revisão prioritária.
   - *Melhoria futura:* nova versão do prompt.
4. **Limiar 0,45:** calibrado em 9 perguntas, com só 0,035 entre os grupos; a abstenção depende do prompt.
5. **Conferências automáticas indicativas:** marcadores, trechos literais e ancoragem numérica apontam problemas. A
   ancoragem acha número inventado, não número verdadeiro do documento errado. A sustentação final é humana.
6. **Sentimentos:** a AV-12 sem contexto foi rotulada como positiva e ficou fora da fila de revisão. A ambiguidade
   autodeclarada não delimita a revisão.
7. **OCR de manuscrito:** erra sem marcar incerteza (código "2024-000142"). Toda entrada de OCR recebe alerta e
   revisão prioritária, e a conferência na imagem é humana.
8. **Moderação:** não detectou nenhum dos ataques de injeção (0/6). A proteção vem das regras locais e do
   classificador de política.
9. **Legado e serviços externos:** `--modo audio` e o cartaz dependem do Gemini legado e de cota externa; a voz
   (`edge-tts`) depende de internet.
10. **Upload pela interface:** o documento entra no índice principal e também na avaliação do RAG. A lista de
    documentos do índice fica registrada em cada avaliação, e a exclusão o retira.
