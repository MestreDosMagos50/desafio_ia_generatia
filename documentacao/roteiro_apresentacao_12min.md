# Roteiro da Apresentação (12 minutos)
**Central Inteligente de Atendimento e Comunicação Institucional — FIC_DEV**

> Antes: deixe abertos o terminal (venv ativo), a pasta `resultados/` e os documentos citados. Evite chamar a API ao
> vivo (cota e latência de 10–50 s por chamada): mostre os resultados da execução final e, se sobrar tempo, rode
> `--modo visao` (1 chamada).

### 1. [00:00–02:00] Problema e arquitetura
- Pedidos de matrícula chegam por e-mail, voz e ficha manuscrita; o protótipo extrai, confere, redige a minuta e gera
  voz e cartaz, **sempre com decisão humana** e sem envio automático.
- Modelo `gemini-3.8-flash` para texto, áudio e PDF; ilustração com modelo de imagem (FLUX.1-schnell, porque o nível
  gratuito do Gemini não inclui imagem); voz com `edge-tts`; Pydantic para JSON; Pillow para editar o cartaz.
- Mostrar: `python -m src.main --info` e o diagrama da seção 2 do `relatorio_tecnico.md`.

### 2. [02:00–04:00] Experimento dos prompts (RF02)
- A, B v1 e C (gerado por metaprompt) com o mesmo modelo, temperatura e seed; métricas medidas pelo script e notas da
  equipe em arquivo separado.
- Achados: A inventou 8 documentos; B v1 escreveu "3 dias alternados" — expressão que estava no próprio prompt;
  a primeira versão do C expôs o CPF. Na reexecução o B v1 não repetiu o erro: saídas variam.
- Na avaliação da equipe (seção 3 da matriz), o C — gerado por metaprompt — teve a maior nota: o metaprompt pediu
  fidelidade, "não localizado" e privacidade, e o modelo seguiu.
- Por isso a produção usa o **B v2**, que junta a estrutura do B às regras que fizeram o C ir bem: dados confirmados e minimizados, citação literal, "não localizado" quando a base
  não tem a resposta.
- Mostrar: `matriz_comparativa_prompts.md` (seções 2, 4 e 5).

### 3. [04:00–07:00] Fluxo multimodal e revisão humana
- Texto → JSON com lacunas "não localizado"; áudio → transcrição bruta e revisada com WER contra a referência;
  ficha → leitura campo a campo com incertos.
- Exemplo real: o modelo leu "2024" no código e "MARCUS" no nome; a confirmação humana corrigiu antes da minuta.
- Conferência cruzada: o e-mail falado ("exemplo") diverge do escrito ("examplo"); o revisor decide.
- Mostrar: `dados/processados/visao_bruta.txt` × imagem da ficha; trecho de `decisoes_humanas.json`.

### 4. [07:00–09:00] Minuta, voz e cartaz (RF07, RF09, RF10)
- Minuta com cabeçalho, lista de não localizados, fontes com SHA-256 e trava de envio; validação automática.
- Voz montada dos campos aprovados (sem hash nem auditoria); o MP3 foi transcrito de volta para provar que não há
  acréscimos.
- Cartaz: ilustração sem texto gerada por IA + brasão, textos conferidos e tarja de proveniência; metadados com modelo,
  prompt, seed e data; checklist de revisão.
- Mostrar: a minuta `.docx`, 10 s do MP3 e o cartaz com o JSON de metadados.

### 5. [09:00–11:00] Segurança, falhas, LGPD e qualidade (RF03, RF04, RF11–RF13)
- Injeção: a solicitação com instruções à IA foi sinalizada e a minuta, rejeitada pelo revisor.
- Falhas do provedor: chave ausente, 401, 429 com nova tentativa, 503, timeout, resposta vazia e JSON inválido
  testados com provedor simulado; nenhuma resposta pronta substitui o modelo.
- LGPD: minimização na minuta, máscaras no log; limite assumido: a extração envia o documento inteiro.
- Qualidade: taxa de aprovação pela última decisão de cada caso, esperado × obtido.
- Mostrar: `pytest` (offline, ~5 s) e `relatorio_avaliacao_qualidade.md`.

### 6. [11:00–12:00] Custos, limitações e uso de IA
- Custo medido: ~US$ 0,018 por atendimento por texto no nível pago (zero no gratuito); o raciocínio do modelo é a
  maior parte dos tokens (`resumo_execucoes.md`).
- Limitações: leitura de manuscrito, variação entre execuções, dependência de serviços on-line.
- Uso de IA: o código inicial gerado por IA simulava etapas; a revisão encontrou 15 inadequações e as corrigiu
  (`uso_ia.md`, seção 4.1). A equipe responde pelo código entregue.
