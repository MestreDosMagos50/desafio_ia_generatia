# Relatório Técnico
**Central Inteligente de Atendimento e Comunicação Institucional**
*Desafio Prático 1 — FIC_DEV | Programador de Sistemas com IA (Aulas 01 a 07)*
*Cenário fictício: Escola Técnica Estadual de Cuiabá — SECITECI/MT*

---

## 1. Problema e solução
A secretaria recebe pedidos de matrícula por e-mail, mensagem de voz e ficha manuscrita. O protótipo transforma
essas entradas em dados estruturados, aponta divergências e lacunas, redige uma minuta de resposta e gera recursos de
acessibilidade e comunicação visual. **Toda saída passa por um revisor humano**; não há envio automático.

## 2. Arquitetura e fluxo
```
entrada_texto.txt ─┐                     ┌─ extração JSON (RF05) ─────────────┐
entrada_audio.mp3 ─┼─ validação ─ modelo ─┼─ transcrição bruta/revisada (RF06) ┼─ revisão humana ─ conferência cruzada
ficha (PDF)       ─┘                     └─ leitura campo a campo (RF08) ─────┘        (decisões registradas)
        │
        └─ registro confirmado ─ minimizar() (RF12) ─ Prompt B v2 ─ minuta JSON ─ validação automática
                └─ revisão: aprovar / rejeitar / corrigir (gera de novo) / nova geração ─ aprovada ─ voz (RF07)
cartaz (RF10): prompt estruturado ─ ilustração por IA (sem texto) ─ edição Pillow ─ revisão com checklist
auditoria (RF11): cada etapa ─ auditoria.jsonl; cada decisão ─ decisoes_humanas.json ─ relatório de qualidade
```

| Módulo | Responsabilidade |
| :--- | :--- |
| `src/llm_client.py` | Chamadas ao Gemini (texto, arquivo, imagem), timeout, novas tentativas, classificação de erros, tokens e custo |
| `src/parsers.py` | Esquemas Pydantic, extração, cálculo de lacunas, minuta (`.txt`/`.docx`) e validação automática |
| `src/audio.py`, `src/vision.py` | Transcrição e leitura da ficha; texto falado e síntese de voz |
| `src/conferencia.py` | Comparação com gabaritos, WER, conferência entre canais, ancoragem e detecção de injeção (determinístico) |
| `src/revisao_humana.py` | Menus de decisão sem opção padrão |
| `src/privacidade.py` | Minimização e máscaras de CPF, RG e e-mail |
| `src/image_generation.py` | Ilustração por IA, edição medida e metadados de proveniência |
| `src/audit.py` | Log JSONL, decisões, relatório de qualidade |

## 3. Ferramentas e modelos
| Componente | Escolha | Motivo |
| :--- | :--- | :--- |
| Modelo principal | `gemini-3.8-flash` (temperatura 0.2) | Multimodal (texto, áudio e PDF na mesma API), saída JSON com esquema e nível gratuito |
| Imagem | `gemini-3.1-flash-image`; alternativa `FLUX.1-schnell` (Apache-2.0) no Space oficial do Hugging Face | O nível gratuito do Gemini não inclui imagem (429 com cota zero em 17/10); a API paga do HF exigiu créditos (402) e descontinuou o modelo no provedor padrão (410); o edital admite modelo aberto |
| Voz | `edge-tts`, `pt-BR-FranciscaNeural`, −5% | Gratuito, voz neural em português |
| Validação | Pydantic 2.14 | JSON válido mesmo com campos ausentes (critério do RF05) |
| Edição de imagem | Pillow 12.3 | Textos medidos com `draw.textbbox`; detecção de glifos ausentes |
| Testes | pytest 9.1 | Mocks do provedor; integração só sob demanda |

## 4. Prompts (RF02 e RF03)
- **Experimento:** A (zero-shot), B v1 (persona, contexto, regras e formato) e C (gerado por metaprompt), mesmo modelo,
  temperatura e seed. Resultados e notas: `matriz_comparativa_prompts.md`.
- **Achados:** A inventou 8 documentos nas duas execuções; B v1 escreveu "3 dias alternados" (copiado da própria regra)
  em 16/10 e reproduziu RG, e-mail e nome da mãe; a versão original do C expôs o CPF.
- **Produção:** B v2 (`prompts/prompt_b_estruturado_v2.txt`, v2.1) + mensagem de sistema com separação de dados não
  confiáveis (`<DADOS_EXTERNOS_NAO_CONFIAVEIS>`). Recebe o registro confirmado e minimizado, cita a declaração de faltas
  literalmente, declara como "não localizado" o que não está na base e responde em JSON validado.
- **Injeção:** caso `entrada_texto_injection.txt` com gabarito próprio; detecção pelo modelo e por regras; minuta com
  alerta ao revisor; decisão esperada: REJEITADO.

## 5. Custos e desempenho (medidos)
Valores do log em 17/10/2026, estimados com o preço do nível pago (US$ 0,75 / 3,75 por 1M de tokens de entrada /
saída; raciocínio cobrado como saída). No nível gratuito o custo efetivo é zero.

| Etapa | Latência | Entrada / saída / raciocínio | Custo (USD) |
| :--- | :---: | :---: | :---: |
| Extração do texto | 12,5 s | 661 / 416 / 1.132 | 0,0063 |
| Minuta | 51,4 s | 1.276 / 321 / 1.028 | 0,0060 |
| Leitura da ficha | 37,8 s | 1.488 / 1.585 / 3.593 | 0,0205 |
| Verificação do áudio | 8,4 s | 2.964 / 413 / 589 | 0,0060 |
| Experimento: A / B v1 / C | 15,4 / 16,6 / 30,7 s | 310–780 de entrada | 0,0072 / 0,0099 / 0,0072 |

O raciocínio do modelo é a maior parcela de tokens. Um atendimento por texto (extração, minuta e verificação do áudio) custou cerca de US$ 0,018 e levou
cerca de 80 s de processamento, incluindo 6,9 s de síntese de voz, sem contar o tempo do revisor.
A execução final está em `resumo_execucoes.md`, gerado por `resumir_auditoria.py` a partir do log.

## 6. Riscos e mitigações
| Risco | Mitigação implementada | Risco residual |
| :--- | :--- | :--- |
| Invenção de documentos, prazos ou normas | B v2 proíbe; validação automática compara a minuta com as fontes; revisor decide | Termos fora da lista de padrões passam pela validação |
| Erro de leitura (manuscrito, áudio) | Versão bruta preservada; incertos marcados; confirmação da ficha; conferência entre canais | Erro não sinalizado pelo modelo e não percebido pelo revisor |
| Prompt injection | Dados delimitados como não confiáveis; detecção dupla; alerta; decisão humana | Instruções disfarçadas que escapem às duas detecções |
| Dados pessoais | Minimização na minuta; máscaras nos logs; `.env` fora do pacote | Extração envia o documento inteiro ao provedor |
| Falha do provedor | Timeout, até 4 tentativas em 429/5xx/rede (esperas de 5, 10 e 20 s); depois, modelos Gemini alternativos (cota própria); cota diária esgotada troca de modelo sem insistir; mensagem clara, nenhum texto pronto | Sem cota em nenhum modelo, o fluxo para |
| Aprovação por desatenção | Menus sem opção padrão; justificativa obrigatória na rejeição; conferência obrigatória das dúvidas da ficha | Revisor aprovar sem ler |
| Evidência inconsistente | Arquivos versionados; pendências tornam a execução incompleta; verificador confere protocolo e decisão final de cada caso | Revisor digitar dados de outro caso |

## 7. Avaliação de qualidade
- Gabaritos por caso (`dados/gabaritos/`), com decisão humana esperada; comparação automática campo a campo.
- Relatório `relatorio_avaliacao_qualidade.md`: taxa de aprovação pela última decisão de cada caso e esperado × obtido,
  com gravidade. Decisões simuladas ficam fora do cálculo.
- 61 testes automatizados (60 offline, incluindo os 12 testes da auditoria e reauditoria externas, + 1 de integração sob demanda).

## 8. Limitações e melhorias
Limitações detalhadas no README (seção 9). Melhorias propostas: OCR/transcrição local para soberania de dados;
lista oficial de documentos como base de conhecimento (eliminaria o "não localizado" na pergunta do cidadão);
versionamento do conteúdo das minutas; contrato com o provedor que exclua o uso dos dados para treinamento.
