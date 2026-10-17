# Central Inteligente de Atendimento e Comunicação Institucional
**Programa FIC_DEV — Programador de Sistemas com IA**
*Desafio Prático 1: Inteligência Artificial Generativa (Aulas 01 a 07)*
*Cenário fictício: Escola Técnica Estadual de Cuiabá / SECITECI — Governo de Mato Grosso*

---

## 1. O que o sistema faz

Protótipo que recebe uma solicitação de matrícula por três canais — **texto (e-mail), mensagem de voz e ficha
manuscrita digitalizada** — e produz uma **minuta de resposta** para um servidor revisar. Nada é enviado
automaticamente.

1. **Extração (RF05):** o modelo converte cada canal em JSON validado por esquema; campos ausentes ficam
   `"não localizado"`. A transcrição do áudio (RF06) e a leitura da ficha (RF08) preservam a versão bruta e marcam
   trechos incertos.
2. **Revisão humana (RF13):** o revisor aprova a transcrição, confirma a leitura da ficha e decide os campos
   divergentes entre canais (conferência cruzada) **antes** da minuta.
3. **Minuta (RF09):** redigida com o Prompt B v2 a partir dos dados confirmados e minimizados (RF12), montada no
   modelo institucional (`.txt` e `.docx` com brasão) e validada automaticamente (CPF, e-mail, normas, prazos ou
   documentos que não constam nas fontes).
4. **Decisão:** aprovar, rejeitar (justificativa obrigatória), corrigir um campo (a minuta é gerada de novo) ou
   pedir nova geração. Só a minuta aprovada vira áudio acessível (RF07).
5. **Peça visual (RF10):** ilustração gerada por IA, sem texto, editada com brasão, textos conferidos e tarja de
   proveniência; também passa por revisão humana.
6. **Auditoria (RF11):** cada chamada fica em `resultados/logs/auditoria.jsonl` com modelo, parâmetros, versão e
   hash do prompt, tokens, custo, duração e erros — sem chaves de API e com CPF/e-mail mascarados.

---

## 2. Requisitos e versões

- **Python 3.12** (testado com 3.12.10 no Windows 11)
- **Bibliotecas** (versões fixadas em `requirements.txt`):

| Biblioteca | Versão | Uso |
| :--- | :--- | :--- |
| `google-genai` | 2.31.0 | Chamadas ao Gemini (texto, áudio, PDF e imagem) |
| `httpx` | 0.28.1 | Transporte HTTP; timeout; chamada ao Hugging Face |
| `python-dotenv` | 1.2.3 | Leitura do `.env` |
| `pydantic` | 2.14.1 | Esquemas JSON da extração e da minuta |
| `mutagen` | 1.48.1 | Metadados do áudio |
| `edge-tts` | 7.3.1 | Síntese de voz pt-BR |
| `pillow` | 12.3.0 | Edição do cartaz |
| `gradio_client` | 2.7.2 | Chamada ao Space do modelo aberto de imagem |
| `pypdf` | 6.21.0 | Leitura do PDF |
| `python-docx` | 1.2.0 | Minuta `.docx` com brasão |
| `pytest` | 9.1.1 | Testes |

- **Modelos usados de fato** (confira em `documentacao/resumo_execucoes.md`, gerado a partir do log):

| Etapa | Provedor / modelo | Observação |
| :--- | :--- | :--- |
| Extração, transcrição, leitura da ficha, minuta, experimento RF02 | Google `gemini-3.8-flash` | `config.json` ou `GEMINI_MODEL`; temperatura 0.2 |
| Alternativos (429/503 no principal) | Google `gemini-3.5-flash`, depois `gemini-3.1-flash-lite` | Mesma chave, cota própria por modelo; o log registra o modelo que respondeu. Não usados no experimento RF02 |
| Ilustração do cartaz | Google `gemini-3.1-flash-image` → alternativa aberta `black-forest-labs/FLUX.1-schnell` no Space oficial do Hugging Face (`gradio_client`) | O nível gratuito do Gemini não inclui imagem (HTTP 429 com cota zero); a API paga do HF exige créditos (402); o Space usa a cota gratuita de GPU. A troca fica registrada nos metadados |
| Voz da minuta | Microsoft `edge-tts`, voz `pt-BR-FranciscaNeural` | Velocidade −5% |

---

## 3. Instalação

```bash
cd desafio_ia_generativa
python -m venv venv
.\venv\Scripts\activate          # Windows  (Linux/macOS: source venv/bin/activate)
pip install -r requirements.txt
copy .env.example .env           # Linux/macOS: cp .env.example .env
```

Preencha o `.env`:
```env
GEMINI_API_KEY=sua_chave          # https://aistudio.google.com/
GEMINI_MODEL=gemini-3.8-flash
HF_TOKEN=hf_...                   # opcional: só para gerar o cartaz (huggingface.co/settings/tokens, tipo "Read")
```
O `.env` está no `.gitignore` e é excluído do pacote de entrega.

Verifique o ambiente (RF01):
```bash
python -m src.main --check-env
```

---

## 4. Como executar

Cada modo pede as decisões do revisor no terminal. O número de chamadas ao Gemini importa no nível gratuito:

| Comando | O que faz | Chamadas (aprox.) |
| :--- | :--- | :---: |
| `python -m src.main --modo texto` | Extração, conferência, minuta, revisão e áudio | 3 |
| `python -m src.main --modo audio` | Transcrição bruta e revisada, extração, conferência, minuta, revisão e áudio | 5 |
| `python -m src.main --modo visao` | Leitura da ficha e confirmação humana | 1 |
| `python -m src.main --modo cartaz` | Ilustração + edição do cartaz e revisão (usa o último registro confirmado) | 1 de imagem |
| `python -m src.main --modo completo` | Os três canais com conferência cruzada, minuta e cartaz | ~8 |
| `python -m src.main --modo texto --entrada-texto dados/originais/entrada_texto_injection.txt` | Caso de prompt injection (RF03) | 2 |
| `python -m src.main --modo experimento-prompts` | Experimento RF02 (A, B v1 e C) | 3 |

Cada correção ou nova geração da minuta custa mais 1 chamada; a verificação do áudio (`audio.verificar_tts` no
`config.json`) custa 1 e pode ser desligada.

**`--demo-avaliacao-humana`**: executa sem perguntas, com decisões **simuladas** gravadas em
`resultados/logs/decisoes_simuladas.json`, fora da taxa de aprovação. Na demonstração a minuta não é liberada e a voz
não é sintetizada (o áudio afirmaria uma aprovação humana que não ocorreu); a validação da minuta registra `simulada: true`.

**Arquivos versionados:** minutas, áudios e cartazes são gravados com data e hora no nome
(ex.: `minuta_institucional_2026-000142_20261017-153012.txt`). Uma nova geração cria arquivos novos e preserva os
anteriores. Os intermediários de `dados/processados` (extrações, transcrições, conferência, registro confirmado) são
regravados a cada execução, mas o log aponta para uma cópia imutável em `dados/processados/versoes/`; assim todo hash
registrado corresponde a um arquivo existente.

**Correções do revisor:** ao corrigir um campo na conferência, as menções ao valor antigo no assunto e no pedido são
trocadas por `[novo valor — corrigido pelo revisor]` e a lista de correções vai ao modelo; o texto original do cidadão
fica preservado e não é enviado.

**Execução incompleta:** se uma etapa obrigatória falhar (extração, transcrição, leitura da ficha, minuta, voz ou cartaz),
o comando termina com `EXECUÇÃO INCOMPLETA`, lista as pendências e retorna código de erro.

### 4.1. Revisão humana no terminal
- Os menus não têm opção padrão: resposta vazia repete a pergunta.
- O revisor se identifica uma vez por execução (ou pela variável `REVISOR`), sem dados pessoais reais
  (ex.: `Estudante 1 - revisor`).
- Decisões registradas em `resultados/logs/decisoes_humanas.json`, por objeto: `transcricao_audio`, `ficha`,
  `conferencia_cruzada`, `minuta` e `cartaz`. O relatório `documentacao/relatorio_avaliacao_qualidade.md` é refeito
  a cada decisão: taxa de aprovação pela última decisão de cada caso e esperado × obtido (gabaritos).

### 4.2. Experimento de prompts (RF02)
```bash
python testes/executar_experimento_prompts.py --gerar-prompt-c   # metaprompt -> Prompt C (1 chamada)
python testes/executar_experimento_prompts.py                    # A, B v1 e C com mesma seed (3 chamadas)
python testes/executar_experimento_prompts.py --somente-matriz   # refaz a matriz com as notas da equipe (0 chamadas)
```
O script mede latência, tokens, custo, exposição de dados pessoais, uso de "não localizado", "alternados" e
documentos citados fora da entrada. Os critérios subjetivos (0 a 2) são da equipe, em
`documentacao/experimento_prompts_notas_equipe.json`.

---

## 5. Testes

```bash
pytest                                             # testes offline (mocks e pastas temporárias), sem consumir cota
$env:RODAR_TESTES_INTEGRACAO="1"; pytest           # PowerShell: inclui o teste com o modelo real (2 chamadas)
RODAR_TESTES_INTEGRACAO=1 pytest                   # Linux/macOS
```
Cobrem: chave ausente, 401/400, 429 com nova tentativa, 503, timeout, resposta vazia, JSON fora do esquema,
sanitização de chaves e dados pessoais nos logs, extração com lacunas, leitura da ficha × gabarito, texto falado,
cartaz (medição de textos, glifos, substituição de modelo), menus de revisão, relatório de qualidade e minimização.

---

## 6. Estrutura

```
desafio_ia_generativa/
├── config.json, requirements.txt, .env.example, pytest.ini, AGENTS.md
├── src/
│   ├── main.py              # Ponto de entrada e orquestração (python -m src.main)
│   ├── llm_client.py        # Cliente Gemini: timeout, novas tentativas, erros, telemetria, imagem
│   ├── prompts.py           # Prompts versionados (A, B v1, B v2, extração, áudio, ficha, ilustração)
│   ├── parsers.py           # Esquemas, extração (RF05) e minuta (RF09)
│   ├── audio.py             # Transcrição (RF06) e voz (RF07)
│   ├── vision.py            # Leitura da ficha (RF08)
│   ├── conferencia.py       # Gabaritos, WER, conferência cruzada, injeção (sem IA)
│   ├── revisao_humana.py    # Menus de revisão (RF13)
│   ├── image_generation.py  # Cartaz (RF10)
│   ├── privacidade.py       # Minimização e máscaras (RF12)
│   └── audit.py             # Log JSONL, decisões e relatório de qualidade (RF11, RF13)
├── prompts/                 # A, B v1, B v2, metaprompt e C gerado (+ origem)
├── dados/originais/         # Entradas (não alteradas) | dados/gabaritos/ | dados/processados/
├── resultados/              # minutas/, audios/, imagens/, logs/
├── testes/                  # pytest + script do experimento RF02
├── documentacao/            # Relatórios, matriz, LGPD, uso de IA, roteiros, evidências
├── resumir_auditoria.py     # Gera documentacao/resumo_execucoes.md a partir do log
├── limpar_resultados.py     # Limpa resultados antes da execução final (preserva o RF02)
├── verificar_entrega.py     # Checa entregáveis, decisões humanas e vazamento de chaves
└── empacotar_entrega.py     # Gera o .zip sem .env e caches
```

---

## 7. Execução final e entrega

O passo a passo detalhado está em `documentacao/roteiro_testes_manuais.md`. Resumo:
1. `python limpar_resultados.py`
2. Rodar, revisando de verdade: `--modo audio` (corrigir o e-mail), caso de injection (rejeitar), `--modo visao`,
   `--modo texto` (aprovar) e `--modo cartaz`.
3. Preencher as notas do experimento e rodar `--somente-matriz`.
4. `python resumir_auditoria.py`, `pytest` e `python verificar_entrega.py`.
5. `python empacotar_entrega.py`, descompactar em pasta nova, criar venv novo, instalar e rodar `--check-env` e `pytest`.
6. Enviar o `.zip` para ficdev00@gmail.com (assunto `Desafio01-FICDEV-IAGenerativa`) até 18/10/2026 23:59.

---

## 8. Custos

Preço do `gemini-3.8-flash` no nível pago (consultado em 16/10/2026, <https://ai.google.dev/gemini-api/docs/pricing>):
US$ 0,75 por 1M de tokens de entrada e US$ 3,75 por 1M de saída; tokens de raciocínio são cobrados como saída.
No nível gratuito o custo efetivo é zero. Valores medidos no log em 17/10/2026 (custo estimado no nível pago):

| Etapa | Latência | Tokens entrada / saída / raciocínio | Custo (USD) |
| :--- | :---: | :---: | :---: |
| Extração do texto | 12,5 s | 661 / 416 / 1.132 | 0,0063 |
| Minuta (Prompt B v2) | 51,4 s | 1.276 / 321 / 1.028 | 0,0060 |
| Leitura da ficha | 37,8 s | 1.488 / 1.585 / 3.593 | 0,0205 |
| Verificação do áudio sintetizado | 8,4 s | 2.964 / 413 / 589 | 0,0060 |

Os tokens de raciocínio respondem pela maior parte do custo. Um atendimento por texto (extração, minuta e
verificação do áudio) custou cerca de US$ 0,018. Os números da execução final ficam em
`documentacao/resumo_execucoes.md` (`python resumir_auditoria.py`).

---

## 9. Limitações conhecidas

1. **Leitura de manuscrito:** em teste real o modelo leu "2024" no código, "14/01/2026" na data e "MARCUS" no nome;
   parte foi marcada como incerta, parte não. Por isso a leitura da ficha só entra na conferência após confirmação humana.
2. **Variação entre execuções:** o mesmo prompt produziu "3 dias alternados" em 16/10 e não em 17/10. Uma saída
   isolada não prova a qualidade de um prompt.
3. **Cartaz depende do `HF_TOKEN` e da cota gratuita de GPU do Hugging Face:** sem cota de imagem no Gemini e sem
   token (ou com a cota do Space esgotada), o cartaz não é gerado (falha registrada, sem imagem substituta).
4. **Dados completos no provedor:** extração, transcrição e leitura da ficha enviam o documento inteiro ao Gemini; a
   minimização vale a partir da minuta (ver `documentacao/lgpd_mapeamento.md`).
5. **Voz:** `edge-tts` usa um serviço on-line não oficial; sem internet o áudio não é gerado.
6. **Versões da minuta:** uma nova geração sobrescreve o arquivo da minuta; as versões anteriores ficam rastreáveis
   pelo hash e pelo `id_execucao_anterior` no log, não pelo conteúdo.
7. **Latência:** o modelo usa raciocínio; cada chamada leva de 8 a 50 s.
8. **Cota:** o nível gratuito tem poucas chamadas por dia. Com 429 ou 503 no modelo principal, o sistema usa os
   modelos alternativos do `config.json`; as respostas podem variar de qualidade entre modelos, e o custo dessas chamadas
   não é estimado. Os testes de integração só rodam quando pedidos.
9. **IA local (melhoria futura):** um modelo local (ex.: via Ollama) eliminaria a dependência de cota e manteria os
   dados na instituição, mas exigiria transcrição local (Whisper), conversão do PDF e um modelo de visão capaz de ler
   manuscrito; não foi adotado por custo de instalação e qualidade da leitura.
