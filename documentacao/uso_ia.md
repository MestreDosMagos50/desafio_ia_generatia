# Registro de Transparência do Uso de Inteligência Artificial no Desenvolvimento
**Atendimento à Seção 10 do Edital — Desafio Prático 1 (FIC_DEV)**

---

## 1. Ferramentas, Modelos e Versões Utilizados

- **Geração inicial do código:** Antigravity IDE, com Gemini 3.8 Flash (High) e Gemini 2.5 Flash
- **Revisão e correção (16 e 17/10/2026):** Claude Code (Anthropic), modelo Claude Opus 5.5, usado como revisor e
  para implementar as correções descritas na seção 4.1, sob orientação da equipe
- **Modelos usados pela solução em execução:** `gemini-3.8-flash`, `gemini-3.1-flash-image` (sem cota no nível
  gratuito) com alternativa `FLUX.1-schnell`, e `edge-tts` (`pt-BR-FranciscaNeural`)
- **Ambiente de Execução e Linguagem:** Python 3.12.10 (x64) sobre Windows 11
- **Bibliotecas Principais:** `google-genai` (v2.31), `pydantic` (v2.14), `edge-tts` (v7.3), `pillow` (v12.3), `pytest` (v9.1)

---

## 2. Três Solicitações Relevantes Feitas à IA

### Solicitação 1: Arquitetura Modular e Plano em Blocos Lógicos
- **Prompt do Usuário:** *"analise os arquivos dessa pasta de desafio, preciso que faça um plano de implementação que divida esse plano em blocos lógicos de execução, faça esse plano diretamente para um IA, o humano no caso eu só fará as partes necessarias que o desafio exige um humano"*
- **Ação Executada:** A IA mapeou o PDF oficial do edital e todos os arquivos de entrada, elaborando um plano de 11 blocos de execução, com matriz de responsabilidades clara separando o trabalho autônomo da IA das 4 intervenções estritamente humanas (H1 a H4).

### Solicitação 2: Isolamento de Segredos e Blindagem contra Injeção de Prompt
- **Prompt/Diretriz:** *"Implementar cliente de API resiliente com retry, sem registrar chaves nos logs e com prompt blindado contra ataques de prompt injection."*
- **Ação Executada:** Criação de `src/llm_client.py` com regex sanitizador e de `src/prompts.py` com delimitação de blocos `<DADOS_EXTERNOS_NAO_CONFIAVEIS>`, instruindo o modelo a tratar documentos como texto inerte e forçando a cláusula mandatória `"não localizado"`.

### Solicitação 3: Geração de Mídia Acessível e Peça Visual com Proveniência Sintética
- **Prompt/Diretriz:** *"Produzir síntese de voz em português brasileiro para a minuta institucional sem ler 'não localizado' cruamente, e gerar cartaz informativo institucional incorporando o brasão oficial de Mato Grosso com rotulagem visível de conteúdo sintético."*
- **Ação Executada:** Implementação em `src/audio.py` com voz neural `pt-BR-FranciscaNeural` e aviso amigável ao ouvinte, e em `src/image_generation.py` gerando imagem em alta resolução com tarja mandatória de proveniência de IA.

---

## 3. Sugestões Aceitas, Modificadas e Rejeitadas

1. **Sugestão Aceita:** Utilização do `edge-tts` para o requisito de acessibilidade auditiva (RF07), por ser gratuito, de altíssima qualidade neural em português brasileiro e não exigir cartão de crédito ou cotas pagas.
2. **Sugestão Modificada:** Inicialmente, a regex de detecção de segredos em logs utilizava comprimento estrito de 35 caracteres (`AIza[0-9A-Za-z-_]{35}`). Durante os testes unitários, identificou-se que chaves podem ter comprimentos variáveis, sendo ajustada para `{20,}` para garantir segurança total.
3. **Sugestão Rejeitada:** Utilização de OCR em nuvem exclusivo para leitura da ficha manuscrita. Rejeitou-se a dependência estrita de nuvem para incluir a fundamentação formal de processamento local (Tesseract / on-premise) visando soberania de dados e LGPD em repartições públicas.

---

## 4. Erros e Inadequações Encontrados e Como Foram Corrigidos

1. **Inadequação na Tipografia da Imagem:** A fonte padrão bitmap do Pillow gerava caracteres ilegíveis e sem acentuação em português (`~`, `^`, `´`).
   - *Correção:* Atualização de `src/image_generation.py` para carregar fontes TrueType do sistema (`Segoe UI` / `Arial`), garantindo perfeita legibilidade e padrão estético de design público.
2. **Falha na Execução de Teste de Chave em Log:** O teste unitário falhou no primeiro disparo por conta da regex restritiva.
   - *Correção:* A regex foi generalizada para capturar qualquer padrão de token do Google ou OpenAI a partir de 20 caracteres.

---

### 4.1. Inadequações encontradas na revisão de 16 e 17/10/2026 e como foram corrigidas
A revisão mostrou que boa parte da primeira versão gerada pela IA **simulava** o funcionamento em vez de implementá-lo.

| # | Inadequação encontrada | Correção |
| :---: | :--- | :--- |
| 1 | Extração, transcrição, leitura da ficha e minuta eram textos fixos no código; o pipeline rodava igual sem chave de API | Chamadas reais ao Gemini em todas as etapas; sem chave, o sistema para com mensagem clara |
| 2 | Telemetria inventada no log (modelos inexistentes, tokens e custos constantes) | Log preenchido com os dados devolvidos pela API; `resumir_auditoria.py` gera o resumo a partir dele |
| 3 | Chave real do Gemini escrita em um teste e incluída no `.zip` | Chave fictícia no teste; o verificador procura o valor do `.env` em todos os arquivos e no zip. **A chave exposta precisa ser revogada.** |
| 4 | `mutagen` ausente do `requirements.txt` (instalação limpa falhava) | Todas as dependências com versão fixada |
| 5 | Matriz do experimento era texto pronto ("96/100") que contradizia as saídas reais | Matriz gerada das medições; notas subjetivas dadas pela equipe em arquivo próprio |
| 6 | Prompt A inventou 8 documentos; B v1 escreveu "3 dias alternados" (vinha da regra do próprio prompt); C expôs o CPF | Prompt B v2: sem dados do caso no prompt, citação literal da declaração, "não localizado" para a lista de documentos, dados minimizados |
| 7 | Prompt C não tinha metaprompt registrado | Metaprompt criado e registrado; C gerado por ele (`prompt_c_metaprompt_origem.json`) |
| 8 | Minuta e cartaz com documentos inventados, "prazo improrrogável", dados "conferidos" e uma "Portaria de Transparência" inexistente | Textos removidos; validação automática de invenções; cartaz só com dados confirmados e o texto impresso na ficha |
| 9 | Decisões humanas fabricadas ("Servidor Público - Matrícula 84920") e menu que aprovava com Enter | Menus sem opção padrão, revisor identificado, justificativa obrigatória; simulações em arquivo separado |
| 10 | Texto falado montado por regex sobre o documento (lia hash e status "pendente" após aprovação) | Locução montada dos campos aprovados; `.txt` salvo ao lado do MP3; verificação por transcrição |
| 11 | Cartaz feito só com Pillow, metadados atribuídos a um "Assistant Multimodal", status "REVISADO_E_CONFORME" sem revisão, símbolos "□" e texto vazando | Ilustração gerada por modelo (sem texto), edição medida com `textbbox`, detecção de glifos, metadados reais e status PENDENTE até a revisão |
| 12 | Gabaritos com erros: e-mail da ficha diferente do escrito; transcrição de referência diferente do áudio | Ficha corrigida (EXAMPLO) e campos incertos esperados; referência do áudio revisada pela equipe ouvindo a gravação em 17/10/2026 (frase das faltas corrigida para "Declaro estar ciente... se eu faltar sem justificativa comprovada"); comparação recalculada sem nova chamada à API |
| 13 | `lgpd_mapeamento.md` descrevia mascaramentos que o código não fazia | `src/privacidade.py` implementado e documento reescrito conforme o código |
| 14 | Testes dependiam de arquivos de execuções antigas e um teste chamava a API real a cada `pytest` (consumindo cota) | Mocks e pastas temporárias; teste de integração só com `RODAR_TESTES_INTEGRACAO=1` |
| 15 | Relatório técnico com custos e resultados de testes inventados ("11 testes, 100% de acerto") | Números tirados do log real |

### 4.2. Inadequações apontadas pela auditoria externa de 17/10/2026 e correções
Uma segunda revisão (execução real em cópias isoladas e 8 testes de aceite, incorporados em
`testes/test_aceite_auditoria.py`) e uma reauditoria (4 testes em `testes/test_reauditoria.py`) encontraram:

| # | Inadequação | Correção |
| :---: | :--- | :--- |
| 16 | O pipeline informava "concluído" mesmo quando a minuta (ou voz, cartaz, extração) falhava | Pendências acumuladas; `EXECUÇÃO INCOMPLETA` e código de erro |
| 17 | Aprovação simulada gerava áudio dizendo "aprovada por servidor" | Demonstração não libera a minuta nem sintetiza voz; validação marca `simulada` |
| 18 | Nova geração com o mesmo protocolo sobrescrevia minuta, áudio e verificação (hashes do log deixavam de conferir) | Nomes versionados com data e hora; nada é sobrescrito |
| 19 | CPF e e-mail digitados em campos livres (pedido, trechos suspeitos) iam sem máscara ao modelo | `minimizar()` aplica as máscaras também aos campos livres |
| 20 | Campos vazios (`""`) não viravam "não localizado"; protocolo ausente era soletrado na voz | Validação no esquema; locução diz "número de protocolo não localizado" |
| 21 | Modelo trocado no `.env` recebia o preço do modelo padrão | Custo só é estimado para o modelo da tabela; os demais ficam sem custo |
| 22 | Correção seguida de aprovação contava como aprovação sem correção | O relatório considera correções e novas gerações desde a última rejeição |
| 23 | Hash da ilustração não correspondia ao arquivo salvo (imagem regravada) | Ilustração salva com os bytes recebidos; hash calculado do arquivo |
| 24 | Dúvidas de leitura da ficha (código, CPF) podiam ser confirmadas sem olhar | Conferência obrigatória campo a campo, com opção de deixar pendente (registrada) |
| 25 | Execução de teste misturou dois casos (dados do Marcos digitados no caso da Joana) e aprovou a injeção | Resultados limpos e casos refeitos; `verificar_entrega.py` confere o protocolo de cada registro e a decisão final de cada caso |
| 26 | Ficha com campo deixado pendente podia ser registrada como APROVADO | Decisão `PENDENTE` (não final); o campo pendente vira "não localizado" até nova conferência |
| 27 | `registro_confirmado` e demais intermediários eram sobrescritos, quebrando o hash de entrada da minuta anterior | Cópia imutável em `dados/processados/versoes/` referenciada pelo log |
| 28 | Corrigir curso/turno deixava assunto e pedido com os valores antigos, enviados ao modelo | Menções ao valor antigo marcadas como corrigidas; correções enviadas explicitamente |
| 29 | Custo desconhecido aparecia como US$ 0 no resumo | "não estimado" ou total parcial com o número de chamadas sem preço |

**Lição para a equipe:** código gerado por IA pode "parecer pronto" produzindo saídas plausíveis sem executar a
tarefa. A verificação que revelou isso foi rodar o sistema sem chave de API e comparar as saídas com as entradas.

## 5. Forma de Validação do Código e do Conteúdo Gerado

- **Validação de Código:** 61 testes com `pytest` (60 offline com provedor simulado, incluindo os 12 testes da auditoria e reauditoria externas, e 1 de integração sob demanda), cobrindo falhas do provedor, injeção de prompt, sanitização, esquemas, leitura da ficha, texto falado, cartaz, revisão humana e minimização;
- **Avaliação subjetiva do experimento RF02:** as notas (0 a 2) em `experimento_prompts_notas_equipe.json` são da
  equipe. Antes de fechá-las, o integrante comparou as próprias notas com uma análise de referência feita pela IA
  (Claude Code) a partir das três saídas e revisou algumas por decisão própria;
- **Validação por execução real:** fluxos executados com a API em 16 e 17/10/2026; as chamadas estão em `resultados/logs/auditoria.jsonl`;
- **Validação Factual:** Confronto algorítmico e manual contra gabaritos formais em JSON (`gabarito_texto.json`, `gabarito_visao.json`, `gabarito_audio.json`);
- **Validação de Segurança:** Inspeção ativa de ausência de chaves de API e arquivos `.env` no versionamento.

---

## 6. Declaração Formal de Responsabilidade

A equipe do projeto declara que compreende integralmente a arquitetura, o código-fonte, os modelos e as decisões técnicas adotadas nesta solução. A Inteligência Artificial Generativa atuou como ferramenta aceleradora de programação assistida e geração de ativos sintéticos sob constante supervisão, auditoria e revisão técnica humana, assumindo os estudantes a inteira responsabilidade pelo produto entregue.
