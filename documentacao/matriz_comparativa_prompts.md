# Matriz Comparativa do Experimento de Prompts (RF02)
*Gerada por `testes/executar_experimento_prompts.py` em 17/10/2026 14:42.*

## 1. Condições
- Modelo: `gemini-3.8-flash` (google) | Temperatura: 0.2 | Seed: 20261017
- Entrada: `dados/originais/entrada_texto.txt` | Execução: 2026-10-17T10:45:59
- Prompts: A = `PROMPT_A_ZERO_SHOT` (src/prompts.py); B v1 = `prompts/prompt_b_estruturado.txt`;
  C = `prompts/prompt_c_metaprompt.txt`, gerado pelo modelo a partir de `prompts/metaprompt_gerador_prompt_c.txt`
  (origem em `prompts/prompt_c_metaprompt_origem.json`).

## 2. Medições automáticas
| Critério | Prompt A (zero-shot) | Prompt B v1 (estruturado) | Prompt C (gerado por metaprompt) |
| :--- | :---: | :---: | :---: |
| Latência (s) | 15.4 | 16.6 | 30.7 |
| Tokens de entrada | 310 | 780 | 739 |
| Tokens de saída (+ raciocínio) | 672 (+1187) | 923 (+1563) | 356 (+1403) |
| Custo estimado (USD) | 0.007204 | 0.009908 | 0.007150 |
| CPF completo exposto | não | não | não |
| RG exposto | não | **sim** | não |
| E-mail exposto | não | **sim** | não |
| Nome da mãe exposto | não | **sim** | não |
| Ocorrências de "não localizado" | 0 | 6 | 1 |
| Menciona "alternados" | **sim** | não | não |
| Documentos citados que não estão na entrada | 8 | 0 | 0 |
| Palavras | 350 | 452 | 193 |

Documentos citados que não constam na entrada:
- **Prompt A (zero-shot):** certidão de nascimento ou casamento, histórico escolar, certificado de conclusão, comprovante de residência, foto 3x4, quitação eleitoral / título de eleitor, serviço militar / reservista, carteira de vacinação
- **Prompt B v1 (estruturado):** nenhum
- **Prompt C (gerado por metaprompt):** nenhum
Trechos com "alternados":
- **Prompt A (zero-shot):** "os dois primeiros dias de aula consecutivos ou em três dias alternados dentro dos dez primeiros dias letivos*"

## 3. Avaliação da equipe (média das notas 0 a 2)
| Critério | Prompt A (zero-shot) | Prompt B v1 (estruturado) | Prompt C (gerado por metaprompt) |
| :--- | :---: | :---: | :---: |
| fidelidade | 0.00 | 1.00 | 2.00 |
| dados_inventados | 0.00 | 2.00 | 2.00 |
| formato | 1.00 | 1.00 | 1.00 |
| tom | 2.00 | 1.00 | 2.00 |
| lacunas | 0.00 | 1.00 | 1.00 |
| tempo_ate_resultado_utilizavel | 0.00 | 0.00 | 2.00 |
| **Total (máx. 12)** | **3.00** | **6.00** | **10.00** |

## 4. Por que a produção usa o Prompt B v2
Na avaliação da equipe, a maior nota foi do **Prompt C (gerado por metaprompt)** (10.00 de 12). Nenhum dos três prompts foi usado sem mudanças: todos recebiam o texto bruto do cidadão, e as saídas
mostraram três problemas que um prompt sozinho não resolve. O B v2 (`prompts/prompt_b_estruturado_v2.txt`) parte da
estrutura do B (persona, contexto, regras e formato), adota as regras que fizeram o C ir bem e muda o desenho:
1. **Regra copiada do prompt, não da entrada:** o B v1 trazia "3 dias alternados" no próprio texto. O B v2 não traz
   dados do caso e manda citar a declaração de faltas exatamente como está na entrada (campo `texto_ciencia_faltas`).
2. **Documentos inventados:** sem a lista oficial na base, o modelo completa com documentos comuns. O B v2 manda
   responder que a informação não foi localizada e que a secretaria a informará.
3. **Dados pessoais:** A, B v1 e C recebem o texto bruto e reproduziram identificadores. O B v2 recebe só os
   dados confirmados e minimizados (`src/privacidade.py`: CPF, RG e e-mail mascarados; filiação, telefones e data de
   nascimento omitidos), e a validação automática alerta se a minuta reproduzir CPF, e-mail ou identificador mascarado.

O C gerado por metaprompt incorporou boa parte dessas regras (fidelidade, lacunas, privacidade) porque o metaprompt
as pedia. O B v2 mantém a estrutura do B e, além das regras, muda os dados de entrada (registro confirmado pelo
servidor e minimizado, em vez do texto bruto) e a saída (JSON validado, montado no modelo institucional pelo código).

## 5. Execução anterior (16/10/2026), com o Prompt C escrito sem metaprompt
Saídas preservadas em `documentacao/evidencias/experimento_2026-10-16/` e medidas pelo mesmo script.

| Critério | Prompt A (zero-shot) | Prompt B v1 (estruturado) | Prompt C v1 (sem metaprompt) |
| :--- | :---: | :---: | :---: |
| CPF completo exposto | não | não | **sim** |
| RG exposto | não | **sim** | **sim** |
| E-mail exposto | não | **sim** | **sim** |
| Nome da mãe exposto | não | **sim** | **sim** |
| Ocorrências de "não localizado" | 0 | 6 | 9 |
| Menciona "alternados" | **sim** | **sim** | não |
| Documentos citados que não estão na entrada | 8 | 0 | 0 |
| Palavras | 407 | 404 | 467 |

Achados registrados na revisão de 16/10/2026:
- O Prompt A listou 8 documentos que não constam na entrada
  (certidão de nascimento ou casamento, histórico escolar, certificado de conclusão, comprovante de residência, foto 3x4, quitação eleitoral / título de eleitor, serviço militar / reservista, carteira de vacinação).
- O Prompt B v1 escreveu "3 dias alternados": a expressão está na regra 3 do próprio prompt; a entrada diz "consecutivos ou não".
- O Prompt C (versão sem metaprompt) reproduziu o CPF completo.

Variação entre as execuções (mesma entrada e mesmo texto de A e B v1; o C mudou de versão; a execução de
16/10 não fixou seed e não registrou o modelo no arquivo de saída):
- **Prompt B v1 (estruturado):** menciona "alternados": True -> False
- **Prompt C (gerado por metaprompt):** CPF completo exposto: True -> False; RG exposto: True -> False; e-mail exposto: True -> False; nome da mãe exposto: True -> False
Saídas de modelos generativos variam entre execuções; por isso um prompt não é avaliado por uma única saída e a
produção combina prompt, dados minimizados, validação automática e revisão humana.

## 6. Arquivos
- Saídas: `resultados/minutas/experimento_prompt_a.txt`, `_b.txt`, `_c.txt`
- Medições e telemetria: `documentacao/experimento_prompts_resultado.json`
- Notas da equipe: `documentacao/experimento_prompts_notas_equipe.json`
- Chamadas registradas em `resultados/logs/auditoria.jsonl` (caso `RF02_EXPERIMENTO_PROMPTS`)
