# Roteiro da Execução Final e dos Testes Manuais
**Para a equipe.** Execute na ordem; cada passo indica as decisões esperadas. Gasto total: cerca de 12 chamadas ao
Gemini (cota do nível gratuito por modelo e por dia; veja a nota no fim) e 1 ao Hugging Face. Abra o PowerShell na pasta `desafio_ia_generativa` com o venv ativado.

Antes de começar:
- [ ] Venv ativado e dependências atualizadas: `.\venv\Scripts\activate` e `pip install -r requirements.txt`
      (a lista mudou: inclui `gradio_client` para o cartaz).
- [ ] No `.env`: `GEMINI_API_KEY` (de preferência uma chave nova, já que a antiga apareceu no zip antigo),
      `GEMINI_MODEL=gemini-3.8-flash` (modelo principal, com preço na tabela; os alternativos entram sozinhos) e `HF_TOKEN`.
- [ ] `python -m src.main --check-env` termina com "AMBIENTE E ARQUIVOS BASE ÍNTEGROS".
- [ ] Alguém ouviu `dados/originais/entrada_audio.mp3`, corrigiu `transcricao_referencia` em
      `dados/gabaritos/gabarito_audio.json` (atenção ao trecho das faltas e ao e-mail) e atualizou a linha 12
      da tabela 4.1 de `documentacao/uso_ia.md` (hoje marcada como PENDENTE).
- [ ] Defina o revisor: `$env:REVISOR = "Estudante 1 - revisor"` (sem dados pessoais reais).

Cada passo termina com `PIPELINE CONCLUÍDO` ou `EXECUÇÃO INCOMPLETA`. No segundo caso o terminal lista o que falhou
(ex.: cota); resolva a causa e rode **só aquele passo** de novo.

## Passo 1 — Limpar resultados antigos
```powershell
python limpar_resultados.py
```
Preserva o experimento RF02 (saídas e log).

## Passo 2 — Caso do áudio (esperado: APROVADO)
```powershell
python -m src.main --modo audio
```
1. **Transcrição:** compare a transcrição revisada com o que você ouviu. A pessoa diz "exemplo.com": isso está correto
   para o áudio. Se estiver fiel, `1` (aprovar).
2. **Conferência:** compare cada campo com o áudio, não com os outros canais (no modo áudio só o áudio aparece).
   Corrija só o que o modelo extraiu errado: por exemplo, se o turno vier como `noturno, noturno`, digite `e`, escolha
   `turno`, informe `Noturno` e depois `s`. Se corrigir algo, informe a gravidade (`1` = BAIXA para ruído de formatação).
3. **Minuta:** leia o texto. Confira: nenhum documento, prazo ou norma inventados; declaração de faltas citada como
   está; "não localizado" na pergunta sobre documentos. Se estiver correta, `1` (aprovar).
4. Ouça o MP3 mais recente em `resultados/audios/` (`minuta_acessivel_2026-000142_<data-hora>.mp3`) e compare com o
   `.txt` de mesmo nome (RF07). Cada execução grava arquivos novos; os anteriores são preservados.

Se o resultado obtido no relatório diferir do esperado (APROVADO) por causa de uma correção, isso não é um problema:
a tabela esperado × obtido serve justamente para registrar os erros do modelo que o revisor precisou corrigir.

## Passo 3 — Caso de prompt injection (esperado: REJEITADO)
```powershell
python -m src.main --modo texto --entrada-texto dados/originais/entrada_texto_injection.txt
```
Confirme o alerta de suspeita de injeção. **Na conferência, responda `s` sem editar nada**: este caso é de outra
pessoa fictícia (Joana, protocolo 2026-000187) e os campos ausentes devem continuar "não localizado" — não copie dados
do Marcos. Na minuta, `2` (rejeitar), justificativa
(ex.: "A solicitação contém instruções dirigidas à IA; encaminhar para análise da secretaria") e gravidade `4` (CRITICA).

## Passo 4 — Ficha manuscrita (esperado no gabarito: APROVADO)
```powershell
python -m src.main --modo visao
```
Abra `dados/originais/entrada_pdf-imagem.pdf`. Primeiro o sistema pede a conferência, um a um, dos campos com dúvida
(os marcados como incertos pelo modelo e os que o gabarito espera como incertos, ex.: código e CPF): responda `s` (confere),
`c` (corrigir) ou `p` (deixar pendente). **Atenção:** com algum campo pendente a decisão da ficha fica `PENDENTE`
(não é aprovada) e o campo vira "não localizado"; para fechar o caso, rode `--modo visao` de novo e resolva o campo. Depois compare os demais campos críticos (data da matrícula,
nome, e-mail); corrija com `2` o que o modelo leu errado e confirme com `1`. Se houver correção,
a decisão fica CORRIGIDO_MANUALMENTE: registre no relatório que o esperado era APROVADO e por que diferiu.

## Passo 5 — Caso do texto (esperado: APROVADO)
```powershell
python -m src.main --modo texto
```
Confirme a conferência com `s` e, se a minuta estiver correta, aprove com `1`. Se encontrar erro, use `3` (corrigir
campo) ou `4` (nova geração): cada uma cria uma nova execução ligada à anterior no log.

## Passo 6 — Cartaz (RF10)
```powershell
python -m src.main --modo cartaz
```
Abra o cartaz mais recente em `resultados/imagens/` (`cartaz_orientacao_matricula_<data-hora>.png` e a ilustração
`..._ilustracao_ia.*`) e responda ao checklist:
sem texto/logotipo na ilustração, objetos coerentes, sem pessoas reais, brasão e cores corretos, textos conferidos.

## Passo 7 — Notas do experimento RF02
Cada integrante lê `resultados/minutas/experimento_prompt_a.txt`, `_b.txt` e `_c.txt` e preenche suas notas (0 a 2)
em `documentacao/experimento_prompts_notas_equipe.json` (copie o bloco de avaliação para cada integrante). Depois:
```powershell
python testes/executar_experimento_prompts.py --somente-matriz
```

## Passo 8 — Conferir e empacotar
```powershell
python resumir_auditoria.py
pytest
python verificar_entrega.py
python empacotar_entrega.py
```
O `verificar_entrega.py` precisa terminar **sem nenhuma `[FALHA]`**: ele confere os arquivos versionados, a decisão
final de cada caso, a coerência dos protocolos, a revisão do cartaz, as notas do experimento e a ausência de chaves.
Confira também em `documentacao/relatorio_avaliacao_qualidade.md` a tabela esperado × obtido.

## Passo 9 — Teste do pacote em ambiente limpo (critério de aceite do RF01)
```powershell
$t = "$env:TEMP\teste_entrega"; Remove-Item -Recurse -Force $t -ErrorAction SilentlyContinue
Expand-Archive ..\Desafio01-FICDEV-IAGenerativa.zip $t
Push-Location $t\desafio_ia_generativa
python -m venv venv; .\venv\Scripts\activate
pip install -r requirements.txt
python -m src.main --check-env
pytest
deactivate; Pop-Location
```

## Passo 10 — Envio
E-mail para **ficdev00@gmail.com**, assunto `Desafio01-FICDEV-IAGenerativa`, anexo
`Desafio01-FICDEV-IAGenerativa.zip`, até **18/10/2026 às 23:59**.

## Nota sobre cota (HTTP 429)
O nível gratuito do Gemini limita chamadas por minuto e por dia, **por modelo**. Se aparecer `LIMITE_REQUISICOES`:
- esperar alguns minutos resolve o limite por minuto;
- o limite diário renova à meia-noite do horário do Pacífico (cerca de 04:00 em Brasília);
- o sistema já troca sozinho para `gemini-3.5-flash` e depois `gemini-3.1-flash-lite` (cota própria por modelo) e
  avisa no terminal com `[MODELO ALTERNATIVO]`; o modelo que respondeu fica no log.
Quando uma etapa falha, nada é inventado: a minuta não é gerada e a falha fica no log. Rode de novo só aquele passo.
