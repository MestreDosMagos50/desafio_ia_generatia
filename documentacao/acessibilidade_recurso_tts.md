# Síntese de Voz e Acessibilidade (RF07)
**Central Inteligente de Atendimento e Comunicação Institucional — FIC_DEV**

---

## 1. O que o sistema faz
- O áudio só é gerado depois que o servidor **aprova** a minuta na revisão humana (RF13).
- O texto falado é montado a partir dos **mesmos campos aprovados** que compõem a minuta
  (assunto, saudação, parágrafos, lista de informações não localizadas e fechamento),
  e não por expressões regulares aplicadas ao documento pronto (`src/audio.py`,
  `montar_texto_locucao`).
- Não são lidos: hash SHA-256, lista de arquivos de origem e a seção de auditoria.
- O aviso de status falado é coerente com a decisão: "Esta resposta foi redigida com apoio
  de inteligência artificial e aprovada por servidor da secretaria escolar."
- O texto exato enviado ao sintetizador é salvo ao lado do áudio:
  `resultados/audios/minuta_acessivel_<protocolo>.txt` e `.mp3`.

## 2. Voz e entonação
- Motor: `edge-tts` (vozes neurais da Microsoft), voz `pt-BR-FranciscaNeural`.
- Velocidade 5% abaixo do padrão (`tts_taxa = -5%` no `config.json`) para uma leitura
  institucional mais pausada; volume e tom no padrão.
- Ajustes de pronúncia que não mudam o conteúdo: datas DD/MM/AAAA lidas por extenso
  ("primeiro de fevereiro de 2027"), protocolo lido dígito a dígito, "SECITECI/MT" lido como
  "Seciteci, Mato Grosso".

## 3. Informações não localizadas
Campos marcados como `não localizado` não são sintetizados sem aviso: a locução anuncia
"Atenção: as seguintes informações não foram localizadas nos dados recebidos:" seguido dos
nomes dos campos.

## 4. Verificação do critério de aceite ("sem acréscimos relevantes")
Com `audio.verificar_tts = true`, o MP3 gerado é transcrito pelo mesmo modelo usado no RF06 e
comparado com o texto da locução (taxa de erro de palavras e trechos acrescentados). O resultado
fica em `resultados/audios/minuta_acessivel_<protocolo>_verificacao.json` e na auditoria
(etapa `verificacao_tts`). A verificação custa uma chamada ao modelo e pode ser desligada.

## 5. Como amplia a acessibilidade
1. Pessoas com deficiência visual ou baixa visão recebem a resposta sem depender de leitor de tela.
2. Pessoas com baixo letramento podem ouvir a resposta em linguagem clara.
3. O MP3 pode ser enviado por canais de mensagem ou usado em atendimento telefônico.

## 6. Limitações
1. `edge-tts` usa um serviço on-line não oficial da Microsoft: sem internet, ou se o serviço mudar,
   o áudio não é gerado (o erro é registrado e a minuta continua válida).
2. Nomes próprios, siglas e e-mails podem ser pronunciados de forma pouco natural.
3. A verificação por transcrição usa um modelo de IA e também pode errar; ela aponta diferenças
   para o revisor, não prova sozinha a ausência de acréscimos.
4. O áudio é um recurso de acessibilidade; o documento de referência continua sendo a minuta textual aprovada.
