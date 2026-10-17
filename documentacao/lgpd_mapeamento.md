# Privacidade, LGPD e Minimização de Dados (RF12)
**Desafio Prático 1 — FIC_DEV | Inteligência Artificial Generativa**

Este documento descreve o que o código **faz de fato** com os dados pessoais, etapa por etapa.
Todos os dados do projeto são fictícios (CPF `123.456.789-00`, e-mails em `exemplo.com`/`examplo.com`).

---

## 1. Finalidade, necessidade e base legal (cenário real)
- **Finalidade:** identificar o solicitante, instruir o pedido de matrícula e redigir a resposta da secretaria escolar.
- **Necessidade:** só os dados exigidos para essa resposta; o que não é necessário em uma etapa não é enviado a ela.
- **Bases legais prováveis:** Art. 7º, II e III, e Art. 23 da Lei nº 13.709/2018 (execução de políticas públicas e
  obrigação legal da instituição de ensino). Por envolver adolescentes, aplica-se também o Art. 14 (melhor interesse).

## 2. Inventário dos campos
| Campo | Dado pessoal? | Usado para | Envio ao modelo na minuta | Logs de auditoria |
| :--- | :--- | :--- | :--- | :--- |
| Nome completo | Sim | Saudação e identificação | Enviado | Não registrado (só hash do prompt) |
| CPF | Sim (identificador) | Conferência cadastral | **Mascarado** (`***.456.789-**`) | **Mascarado** |
| RG / órgão expedidor | Sim (identificador) | Conferência cadastral | **Mascarado** (`****567-8`) | Não registrado |
| E-mail | Sim (contato) | Canal de resposta | **Mascarado** (`m***@examplo.com`) | **Mascarado** |
| Telefones | Sim (contato) | Contato | **Omitido** | Não registrado |
| Data de nascimento / naturalidade | Sim | Verificação de idade | **Omitido** | Não registrado |
| Nome da mãe / do pai | Sim | Registro escolar | **Omitido** | Não registrado |
| Assinatura (imagem da ficha) | Sim (pode identificar) | Comprovar ciência das regras | Não se aplica | Não registrado |
| Voz (mensagem de áudio) | Sim (pode identificar) | Transcrição | Não se aplica | Não registrado |
| Curso, turno, datas do curso | Não (dado acadêmico) | Resposta e cartaz | Enviado | Pode aparecer em resumos |

## 3. O que vai a cada serviço externo
| Etapa | Serviço | O que é enviado | Por quê |
| :--- | :--- | :--- | :--- |
| Extração (RF05) | Google Gemini | Texto **completo** da solicitação | A tarefa é justamente ler os dados |
| Transcrição (RF06) | Google Gemini | Arquivo de áudio **completo** (voz) | Idem |
| Leitura da ficha (RF08) | Google Gemini | PDF **completo**, com a assinatura | Idem |
| Minuta (RF09) | Google Gemini | Saída de `src/privacidade.py::minimizar()` | Só o necessário para redigir |
| Ilustração do cartaz (RF10) | Gemini ou Hugging Face (FLUX.1-schnell) | Prompt descritivo, **sem dado pessoal** | O modelo gera só a ilustração |
| Voz da minuta (RF07) | Microsoft (edge-tts) | Texto falado da minuta aprovada (inclui o nome) | Síntese de voz |
| Verificação do áudio (RF07) | Google Gemini | MP3 sintetizado | Conferir se o áudio corresponde ao texto |

**Trade-off assumido:** a minimização vale da minuta em diante. Extração, transcrição e leitura da ficha precisam
ver os dados para extraí-los; mascarar antes impediria a tarefa. Em produção, essas etapas deveriam rodar em
modelo local ou sob contrato com o provedor (ver `soberania_e_privacidade_ocr.txt`). No nível gratuito da API Gemini,
os termos do Google permitem usar o conteúdo enviado para melhorar produtos: aceitável aqui apenas porque os dados
são fictícios.

## 4. Medidas implementadas no código
1. **`src/privacidade.py::minimizar()`** monta o payload da minuta: CPF, RG e e-mail mascarados (inclusive quando
   aparecem nos campos de texto livre: assunto, pedido, declaração, trechos suspeitos); filiação, telefones,
   data de nascimento, naturalidade e texto original omitidos. O Prompt B v2 proíbe reproduzir esses identificadores,
   mesmo mascarados.
2. **Validação da minuta** (`src/parsers.py::validar_minuta`): alerta o revisor se a minuta contiver número no formato
   de CPF, endereço de e-mail ou identificador mascarado.
3. **Auditoria** (`src/audit.py`): CPF e e-mail são mascarados (`mascarar_texto`) em resumos, observações,
   justificativas e alterações das decisões; chaves de API (`AIza…`, `AQ.…`, `sk-…`, `hf_…`) são removidas; o texto
   dos prompts não é gravado, apenas o hash SHA-256 e o tamanho.
4. **Cartaz:** a ilustração é gerada sem pessoas; os textos inseridos são dados do curso e a regra impressa na ficha.
5. **Credenciais** só no `.env` (fora do repositório e do pacote de entrega); `verificar_entrega.py` procura chaves nos arquivos.

## 5. Onde os dados completos ainda ficam (e por quê)
- `dados/processados/*.json` (extrações, `registro_confirmado_*.json`, `visao_*.json`): necessários para a conferência
  humana e para gerar a minuta. Em produção: acesso restrito, criptografia em repouso e prazo de retenção.
- Terminal da revisão humana: mostra CPF e e-mail completos, porque o revisor precisa conferi-los com o documento.
- `resultados/minutas/*` e `resultados/audios/*`: contêm o nome do solicitante (destinatário da resposta).

## 6. Limitações
- O mascaramento em texto livre usa padrões (CPF com 11 dígitos, e-mail com `@`); um CPF escrito por extenso ou com
  separadores incomuns não seria detectado.
- RG, nomes e telefones não são mascarados em texto livre nos logs; hoje eles não são gravados ali, mas uma mudança
  futura nos resumos poderia expô-los.
- Não há rotina automática de exclusão dos arquivos processados.
