#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
==============================================================================
GERADOR DO ACERVO INSTITUCIONAL FICTÍCIO E DAS SOLICITAÇÕES REAPROVEITADAS
Desafio 02, Seção 6 (dados de entrada) e RF17 (acervo identificado)
==============================================================================
Gera, de forma determinística (mesmo conteúdo -> mesmos bytes e mesmo SHA-256):
- dados/acervo/: 6 documentos do acervo principal (2 temas; TXT e PDF textual)
  e o DOC-99, usado só na demonstração de exclusão (RF24 / T14), com o
  manifesto_acervo.json (identificador, título, versão, vigência e hash);
- dados/solicitacoes/: SOL-02 (transcrição revisada do áudio do Desafio 01) e
  SOL-05 (leitura de referência da ficha digitalizada), derivadas dos
  gabaritos do Desafio 01, sem nova chamada a modelo.
Todo o conteúdo é fictício. Os editais reais de contexto/ serviram só de
inspiração de estrutura (ex.: "Onde se lê / Leia-se"); nenhum nome, contato,
endereço ou número deles foi copiado.
Os PDFs usam a fonte Helvetica embutida no PyMuPDF, que não representa o
travessão: os textos usam hífen. Depois de gravar, o texto de cada página é
extraído e comparado com a fonte; qualquer diferença interrompe a geração.
Uso: python scripts/gerar_acervo_ficticio.py
==============================================================================
"""

import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

import pymupdf

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from src.vision import CAMPOS_FICHA  # rótulos da ficha, iguais aos do Desafio 01

AVISO = ("DOCUMENTO FICTÍCIO - elaborado exclusivamente para o Desafio Prático 02 (FIC_DEV); "
         "sem validade administrativa.")
DATA_FIXA_PDF = "D:20260901000000-03'00'"  # metadados fixos: o PDF não muda de hash a cada geração
PAGINA = pymupdf.Rect(0, 0, 595, 842)      # A4 em pontos
AREA_TEXTO = pymupdf.Rect(56, 56, 539, 786)
TAMANHO_FONTE = 10.5

TEMAS = {
    "T1_matricula_e_frequencia": "Processo seletivo, matrícula, chamadas e frequência no início do curso",
    "T2_estagio_e_assistencia": "Estágio supervisionado e assistência estudantil",
}

# ------------------------------------------------------------------------------
# Acervo: o texto de cada documento (PDF: uma string por página; TXT: uma string)
# ------------------------------------------------------------------------------
DOCUMENTOS: List[Dict[str, Any]] = [
    {
        "doc_id": "DOC-01",
        "arquivo": "DOC-01_edital_ficticio_010_2026.pdf",
        "formato": "pdf",
        "titulo": "Edital Fictício nº 010/2026 - Processo Seletivo e Matrícula dos Cursos Técnicos - Turmas 2027/1",
        "versao": "1.0",
        "data_publicacao": "01/09/2026",
        "tema": "T1_matricula_e_frequencia",
        "emissor": "Direção da ETEC Cuiabá (fictícia)",
        "retifica": None,
        "retificado_por": ["DOC-02"],
        "vigencia": "Vigente; os itens 3.3, 3.4 e 5.1 têm redação alterada pelo DOC-02 a partir de 10/10/2026.",
        "regra_de_prevalencia": None,
        "uso": "acervo_principal",
        "paginas": [
            """EDITAL FICTÍCIO Nº 010/2026 - ETEC CUIABÁ
PROCESSO SELETIVO E MATRÍCULA PARA OS CURSOS TÉCNICOS SUBSEQUENTES - TURMAS 2027/1

A Direção da Escola Técnica Estadual de Cuiabá (ETEC Cuiabá) torna público este edital, que estabelece as regras de seleção, matrícula e preenchimento de vagas dos cursos técnicos subsequentes com início no primeiro semestre de 2027.

1. DISPOSIÇÕES PRELIMINARES
1.1. O processo seletivo é regido por este edital e por suas retificações, quando publicadas.
1.2. Podem participar candidatos que tenham concluído o ensino médio ou que estejam cursando a terceira série do ensino médio.
1.3. As informações sobre o processo seletivo são prestadas pela Secretaria Escolar da ETEC Cuiabá, de forma presencial ou pelos canais oficiais da unidade.

2. DOS CURSOS E DAS VAGAS
2.1. São ofertadas vagas nos seguintes cursos:
a) Técnico em Enfermagem - eixo tecnológico Saúde - 1200 horas - turno noturno - 40 vagas - sede da ETEC Cuiabá;
b) Técnico em Recursos Humanos - eixo tecnológico Gestão e Negócios - 800 horas - turno noturno - 40 vagas - sede da ETEC Cuiabá;
c) Técnico em Informática - eixo tecnológico Informação e Comunicação - 1000 horas - turno vespertino - 40 vagas - sede da ETEC Cuiabá;
d) Técnico em Agropecuária - eixo tecnológico Recursos Naturais - 1200 horas - turno noturno - 40 vagas - Polo Distrito de Vale Verde.
2.2. A seleção é feita por sorteio eletrônico público, e a classificação segue a ordem do sorteio.

3. DO CRONOGRAMA
3.1. As inscrições ocorrem de 08/09/2026 a 22/09/2026, exclusivamente pelo formulário eletrônico da unidade.
3.2. O sorteio público será realizado em 25/09/2026.
3.3. O período de matrícula da 1ª chamada será de 01/10/2026 a 20/10/2026, de segunda a sexta-feira, das 13h às 21h, na Secretaria Escolar.
3.4. As aulas terão início em 01/02/2027 para todos os cursos.""",
            """4. DA MATRÍCULA E DOS DOCUMENTOS EXIGIDOS
4.1. A matrícula é presencial e somente será efetivada com a entrega de cópia simples e a apresentação do original dos seguintes documentos:
a) documento oficial de identificação com foto;
b) CPF;
c) certidão de nascimento ou de casamento;
d) histórico escolar e certificado de conclusão do ensino médio, ou declaração de matrícula na terceira série do ensino médio;
e) comprovante de residência emitido nos últimos 3 (três) meses;
f) 1 (uma) foto 3x4 recente;
g) comprovante de quitação eleitoral, para maiores de 18 anos.
4.2. Para o Curso Técnico em Enfermagem, além dos documentos do item 4.1, é obrigatória a apresentação da carteira de vacinação atualizada, com registro das doses contra hepatite B e tétano.
4.3. O candidato menor de 18 anos deve estar acompanhado do responsável legal no ato da matrícula.
4.4. A falta de qualquer documento exigido impede a efetivação da matrícula, e o candidato perde a vaga se não regularizar a pendência dentro do período de matrícula.

5. DAS CHAMADAS E DAS VAGAS REMANESCENTES
5.1. As vagas não ocupadas na 1ª chamada serão oferecidas em 2ª chamada, publicada em 23/10/2026, com matrícula em 26/10/2026 e 27/10/2026.
5.2. Persistindo vagas, a Secretaria Escolar publicará a chamada de vagas remanescentes no mural da unidade, obedecendo à ordem do sorteio.
5.3. O candidato convocado que não comparecer no período indicado perde o direito à vaga.""",
            """6. DA FREQUÊNCIA NO INÍCIO DO CURSO
6.1. O estudante matriculado deve observar as regras de frequência dos primeiros dias letivos definidas no Manual da Secretaria Escolar.

7. DISPOSIÇÕES FINAIS
7.1. Os casos omissos serão resolvidos pela Direção da ETEC Cuiabá.
7.2. Informações prestadas por telefone ou aplicativo de mensagens não substituem o disposto neste edital e em suas retificações.
7.3. Este edital entra em vigor na data de sua publicação.

Cuiabá, 01 de setembro de 2026.
Direção da ETEC Cuiabá (assinatura fictícia)""",
        ],
    },
    {
        "doc_id": "DOC-02",
        "arquivo": "DOC-02_edital_retificador_ficticio_01.pdf",
        "formato": "pdf",
        "titulo": "Edital Retificador Fictício nº 01 ao Edital Fictício nº 010/2026",
        "versao": "1.0",
        "data_publicacao": "10/10/2026",
        "tema": "T1_matricula_e_frequencia",
        "emissor": "Direção da ETEC Cuiabá (fictícia)",
        "retifica": "DOC-01",
        "retificado_por": [],
        "vigencia": "Vigente desde 10/10/2026.",
        "regra_de_prevalencia": "Art. 5º: prevalece sobre a redação original dos itens 3.3, 3.4 e 5.1 do DOC-01; as demais disposições do DOC-01 permanecem inalteradas (art. 4º).",
        "uso": "acervo_principal",
        "paginas": [
            """EDITAL RETIFICADOR FICTÍCIO Nº 01 AO EDITAL FICTÍCIO Nº 010/2026 - ETEC CUIABÁ

A Direção da Escola Técnica Estadual de Cuiabá (ETEC Cuiabá) torna pública a retificação do Edital Fictício nº 010/2026, nos termos abaixo.

Art. 1º. O item 3.3 do Edital Fictício nº 010/2026 passa a vigorar com a seguinte redação:
Onde se lê: "3.3. O período de matrícula da 1ª chamada será de 01/10/2026 a 20/10/2026, de segunda a sexta-feira, das 13h às 21h, na Secretaria Escolar."
Leia-se: "3.3. O período de matrícula da 1ª chamada será de 01/10/2026 a 30/10/2026, de segunda a sexta-feira, das 13h às 21h, na Secretaria Escolar."

Art. 2º. O item 5.1 do Edital Fictício nº 010/2026 passa a vigorar com a seguinte redação:
Onde se lê: "5.1. As vagas não ocupadas na 1ª chamada serão oferecidas em 2ª chamada, publicada em 23/10/2026, com matrícula em 26/10/2026 e 27/10/2026."
Leia-se: "5.1. As vagas não ocupadas na 1ª chamada serão oferecidas em 2ª chamada, publicada em 05/11/2026, com matrícula em 09/11/2026 e 10/11/2026.\"""",
            """Art. 3º. O item 3.4 do Edital Fictício nº 010/2026 passa a vigorar com a seguinte redação:
Onde se lê: "3.4. As aulas terão início em 01/02/2027 para todos os cursos."
Leia-se: "3.4. As aulas terão início em 01/02/2027 para os cursos ofertados na sede da ETEC Cuiabá e em 22/02/2027 para o curso ofertado no Polo Distrito de Vale Verde."

Art. 4º. Todas as demais disposições do Edital Fictício nº 010/2026 permanecem inalteradas.

Art. 5º. Esta retificação entra em vigor na data de sua publicação e prevalece sobre a redação original dos itens 3.3, 3.4 e 5.1 do Edital Fictício nº 010/2026.

Cuiabá, 10 de outubro de 2026.
Direção da ETEC Cuiabá (assinatura fictícia)""",
        ],
    },
    {
        "doc_id": "DOC-03",
        "arquivo": "DOC-03_manual_secretaria_frequencia.txt",
        "formato": "txt",
        "titulo": "Manual da Secretaria Escolar - Frequência nos Primeiros Dias Letivos, Justificativa de Faltas e Vagas Remanescentes",
        "versao": "1.0",
        "data_publicacao": "15/08/2026",
        "tema": "T1_matricula_e_frequencia",
        "emissor": "Secretaria Escolar da ETEC Cuiabá (fictícia)",
        "retifica": None,
        "retificado_por": [],
        "vigencia": "Vigente.",
        "regra_de_prevalencia": None,
        "uso": "acervo_principal",
        "texto": """MANUAL DA SECRETARIA ESCOLAR - ETEC CUIABÁ
FREQUÊNCIA NOS PRIMEIROS DIAS LETIVOS, JUSTIFICATIVA DE FALTAS E VAGAS REMANESCENTES

1. FINALIDADE
1.1. Este manual orienta estudantes e servidores sobre a frequência exigida no início dos cursos técnicos e sobre o reaproveitamento das vagas liberadas.

2. FREQUÊNCIA NOS DEZ PRIMEIROS DIAS LETIVOS
2.1. A matrícula será cancelada automaticamente quando o estudante faltar, sem justificativa comprovada, nos 2 (dois) primeiros dias letivos consecutivos.
2.2. A matrícula também será cancelada quando o estudante acumular 3 (três) faltas sem justificativa, consecutivas ou não, nos 10 (dez) primeiros dias letivos.
2.3. As faltas são registradas diariamente pelo professor no diário de classe e conferidas pela Secretaria Escolar ao final do décimo dia letivo.

3. JUSTIFICATIVA DE FALTAS
3.1. São aceitos como justificativa: atestado médico, declaração de comparecimento a órgão público, certidão de óbito de familiar de primeiro grau e convocação para serviço militar ou eleitoral.
3.2. O documento de justificativa deve ser entregue na Secretaria Escolar em até 3 (três) dias úteis após o retorno do estudante.
3.3. A justificativa entregue fora do prazo não impede o cancelamento previsto no item 2.

4. VAGAS REMANESCENTES APÓS O INÍCIO DAS AULAS
4.1. A vaga liberada por cancelamento de matrícula é oferecida ao próximo candidato da lista de classificação do curso, na ordem do sorteio.
4.2. O candidato convocado tem 2 (dois) dias úteis para comparecer à Secretaria Escolar com os documentos exigidos no edital.
4.3. Não há convocação de vagas remanescentes depois do 15º (décimo quinto) dia letivo.

5. ATENDIMENTO
5.1. A Secretaria Escolar atende de segunda a sexta-feira, das 13h às 21h, no bloco administrativo da ETEC Cuiabá.""",
    },
    {
        "doc_id": "DOC-04",
        "arquivo": "DOC-04_comunicado_coordenacao_estagio_02_2026.txt",
        "formato": "txt",
        "titulo": "Comunicado Fictício nº 02/2026 da Coordenação de Estágio - Documentação para Início do Estágio Supervisionado",
        "versao": "1.0",
        "data_publicacao": "20/08/2026",
        "tema": "T2_estagio_e_assistencia",
        "emissor": "Coordenação de Estágio da ETEC Cuiabá (fictícia)",
        "retifica": None,
        "retificado_por": [],
        "vigencia": "Vigente.",
        "regra_de_prevalencia": None,
        "uso": "acervo_principal",
        "texto": """COMUNICADO FICTÍCIO Nº 02/2026 - COORDENAÇÃO DE ESTÁGIO DA ETEC CUIABÁ
DOCUMENTAÇÃO PARA INÍCIO DO ESTÁGIO SUPERVISIONADO

1. OBJETIVO
1.1. Este comunicado orienta os estudantes dos cursos técnicos sobre a documentação necessária para iniciar o estágio supervisionado nas instituições concedentes.

2. DOCUMENTOS DO ESTÁGIO
2.1. O estudante deve providenciar o termo de compromisso de estágio, assinado por ele, pela instituição concedente e pela coordenação de estágio, e o comprovante de seguro contra acidentes pessoais.
2.2. O termo de compromisso de estágio assinado deve ser entregue à coordenação de estágio com antecedência mínima de 5 (cinco) dias úteis do início das atividades no campo de estágio.
2.3. Sem a entrega do termo de compromisso, o estudante não poderá iniciar as atividades no campo de estágio.
2.4. Este comunicado se aplica a todos os cursos técnicos que possuem estágio supervisionado.

3. ORIENTAÇÕES GERAIS
3.1. A coordenação de estágio atende às terças e quintas-feiras, das 14h às 20h.
3.2. Os modelos de termo de compromisso estão disponíveis na coordenação de estágio.""",
    },
    {
        "doc_id": "DOC-05",
        "arquivo": "DOC-05_regulamento_estagio_saude.pdf",
        "formato": "pdf",
        "titulo": "Regulamento Fictício de Estágio Supervisionado dos Cursos Técnicos da Área de Saúde",
        "versao": "1.0",
        "data_publicacao": "20/08/2026",
        "tema": "T2_estagio_e_assistencia",
        "emissor": "Coordenação do Curso Técnico em Enfermagem da ETEC Cuiabá (fictícia)",
        "retifica": None,
        "retificado_por": [],
        "vigencia": "Vigente.",
        "regra_de_prevalencia": None,
        "uso": "acervo_principal",
        "paginas": [
            """REGULAMENTO FICTÍCIO DE ESTÁGIO SUPERVISIONADO DOS CURSOS TÉCNICOS DA ÁREA DE SAÚDE - ETEC CUIABÁ

1. DA NATUREZA DO ESTÁGIO
1.1. O estágio supervisionado é componente obrigatório do Curso Técnico em Enfermagem e integra a carga horária total do curso.
1.2. O estágio supervisionado do Curso Técnico em Enfermagem tem carga horária de 400 (quatrocentas) horas, cumpridas a partir do segundo módulo do curso.

2. DOS TURNOS E DOS CAMPOS DE ESTÁGIO
2.1. As atividades de estágio podem ocorrer nos turnos matutino, vespertino ou noturno, conforme a disponibilidade das instituições de saúde conveniadas.
2.2. A distribuição dos estudantes entre os campos de estágio é feita pela coordenação do curso, que publica a escala com antecedência mínima de 30 (trinta) dias.
2.3. O estudante não pode cumprir mais de 6 (seis) horas diárias de estágio.""",
            """3. DOS REQUISITOS PARA INÍCIO DO ESTÁGIO
3.1. Para iniciar o estágio, o estudante deve apresentar a carteira de vacinação com o esquema completo contra hepatite B, tétano e influenza.
3.2. O termo de compromisso de estágio, assinado pelo estudante, pela instituição concedente e pela coordenação, deve ser entregue com antecedência mínima de 15 (quinze) dias corridos do início das atividades no campo de estágio.
3.3. O estudante deve utilizar uniforme branco e crachá de identificação durante as atividades no campo de estágio.

4. DA AVALIAÇÃO
4.1. O estudante é avaliado pelo supervisor do campo de estágio e pelo professor orientador, com registro em ficha própria.
4.2. A aprovação no estágio exige frequência integral, admitida a reposição de faltas justificadas.

Cuiabá, 20 de agosto de 2026.
Coordenação do Curso Técnico em Enfermagem (assinatura fictícia)""",
        ],
    },
    {
        "doc_id": "DOC-06",
        "arquivo": "DOC-06_faq_assistencia_estudantil.txt",
        "formato": "txt",
        "titulo": "Perguntas Frequentes Fictícias - Assistência Estudantil e Declarações",
        "versao": "1.0",
        "data_publicacao": "05/09/2026",
        "tema": "T2_estagio_e_assistencia",
        "emissor": "Secretaria Escolar da ETEC Cuiabá (fictícia)",
        "retifica": None,
        "retificado_por": [],
        "vigencia": "Vigente.",
        "regra_de_prevalencia": None,
        "uso": "acervo_principal",
        "texto": """PERGUNTAS FREQUENTES FICTÍCIAS - ASSISTÊNCIA ESTUDANTIL E DECLARAÇÕES - ETEC CUIABÁ

1. AUXÍLIO-TRANSPORTE
1.1. Quem pode pedir o auxílio-transporte?
Pode pedir o auxílio-transporte o estudante regularmente matriculado que resida a mais de 3 (três) quilômetros da unidade escolar e tenha renda familiar per capita de até 1,5 (um e meio) salário mínimo.
1.2. Qual é o valor do auxílio-transporte?
O auxílio-transporte corresponde a R$ 150,00 (cento e cinquenta reais) mensais, pagos durante os meses letivos.
1.3. Como faço o pedido?
O pedido é feito na Secretaria Escolar, com o formulário de solicitação, o comprovante de residência e a declaração de renda familiar, nos primeiros 30 (trinta) dias de cada semestre letivo.
1.4. Estudantes de outros municípios podem pedir o auxílio?
Sim. O critério é a distância entre a residência e a unidade escolar, e não o município de residência.

2. ALIMENTAÇÃO ESCOLAR
2.1. A escola oferece refeição aos estudantes?
Sim. Os estudantes dos cursos noturnos recebem um lanche servido no intervalo das 19h15, sem custo.
2.2. Preciso me cadastrar para receber o lanche?
Não. Basta apresentar o crachá de estudante no refeitório.

3. DECLARAÇÕES E DOCUMENTOS ESCOLARES
3.1. Como peço uma declaração de matrícula?
A declaração de matrícula é solicitada na Secretaria Escolar e entregue em até 2 (dois) dias úteis.
3.2. A declaração pode ser enviada por e-mail?
Sim. Quando solicitada pelo estudante, a declaração assinada digitalmente é enviada ao e-mail cadastrado na matrícula.
3.3. Quanto tempo leva a emissão do histórico escolar?
O histórico escolar é emitido em até 10 (dez) dias úteis após o pedido.""",
    },
    {
        "doc_id": "DOC-99",
        "arquivo": "DOC-99_informativo_recesso_temporario.txt",
        "formato": "txt",
        "titulo": "Informativo Fictício Temporário - Recesso Escolar de Fim de Ano",
        "versao": "1.0",
        "data_publicacao": "15/10/2026",
        "tema": "T1_matricula_e_frequencia",
        "emissor": "Direção da ETEC Cuiabá (fictícia)",
        "retifica": None,
        "retificado_por": [],
        "vigencia": "Temporário: deixa de valer em 29/01/2027.",
        "regra_de_prevalencia": None,
        "uso": "teste_exclusao_T14",
        "texto": """INFORMATIVO FICTÍCIO - RECESSO ESCOLAR DE FIM DE ANO - ETEC CUIABÁ

1. RECESSO
1.1. As atividades letivas das turmas em andamento ficam suspensas de 21/12/2026 a 04/01/2027, em razão do recesso escolar de fim de ano.

2. PLANTÃO DA SECRETARIA ESCOLAR
2.1. Durante o recesso, a Secretaria Escolar funciona em regime de plantão, às segundas e quartas-feiras, das 8h às 12h.

3. VALIDADE
3.1. Este informativo é temporário e deixa de valer em 29/01/2027.""",
    },
]


def normalizar_espacos(texto: str) -> str:
    return " ".join(texto.split())


def sha256(caminho: Path) -> str:
    return hashlib.sha256(caminho.read_bytes()).hexdigest()


def cabecalho(doc: Dict[str, Any]) -> str:
    """Aviso de conteúdo fictício e identificação visível (identificador, versão e data), exigidos na Seção 6."""
    linha = f"Identificador: {doc['doc_id']} | Versão: {doc['versao']} | Publicação: {doc['data_publicacao']}"
    if doc.get("retifica"):
        linha += f" | Retifica: {doc['retifica']}"
    if doc["uso"] != "acervo_principal":
        linha += f" | {doc['vigencia']}"
    return f"{AVISO}\n{linha}"


def paginas_finais(doc: Dict[str, Any]) -> List[str]:
    """Texto efetivamente gravado em cada página (o cabeçalho abre a primeira)."""
    paginas = list(doc["paginas"])
    paginas[0] = f"{cabecalho(doc)}\n\n{paginas[0]}"
    return paginas


def gravar_pdf(doc: Dict[str, Any], caminho: Path) -> int:
    pdf = pymupdf.open()
    for numero, texto in enumerate(paginas_finais(doc), start=1):
        pagina = pdf.new_page(width=PAGINA.width, height=PAGINA.height)
        sobra = pagina.insert_textbox(AREA_TEXTO, texto, fontsize=TAMANHO_FONTE, fontname="helv")
        if sobra < 0:
            raise ValueError(f"{doc['doc_id']}, página {numero}: o texto não cabe na página.")
    pdf.set_metadata({
        "title": f"{doc['doc_id']} - {doc['titulo']}",
        "author": "Equipe FIC_DEV - documento fictício",
        "subject": AVISO,
        "keywords": f"{doc['doc_id']}; versão {doc['versao']}; fictício",
        "creator": "scripts/gerar_acervo_ficticio.py",
        "producer": "PyMuPDF",
        "creationDate": DATA_FIXA_PDF,
        "modDate": DATA_FIXA_PDF,
    })
    pdf.save(caminho, garbage=4, deflate=True, no_new_id=True)
    pdf.close()
    return len(doc["paginas"])


def conferir_pdf(doc: Dict[str, Any], caminho: Path):
    """O texto extraído de cada página precisa ser igual ao da fonte (garante PDF textual e sem perda de caracteres)."""
    with pymupdf.open(caminho) as pdf:
        extraidas = [normalizar_espacos(pagina.get_text()) for pagina in pdf]
    esperadas = [normalizar_espacos(texto) for texto in paginas_finais(doc)]
    for numero, (extraida, esperada) in enumerate(zip(extraidas, esperadas), start=1):
        if extraida != esperada:
            raise ValueError(f"{doc['doc_id']}, página {numero}: o texto extraído do PDF difere da fonte.")
    if len(extraidas) != len(esperadas):
        raise ValueError(f"{doc['doc_id']}: o PDF tem {len(extraidas)} páginas; esperadas {len(esperadas)}.")


def gerar_acervo(destino: Path) -> Dict[str, Any]:
    destino.mkdir(parents=True, exist_ok=True)
    registros = []
    for doc in DOCUMENTOS:
        caminho = destino / doc["arquivo"]
        if doc["formato"] == "pdf":
            paginas = gravar_pdf(doc, caminho)
            conferir_pdf(doc, caminho)
        else:
            caminho.write_text(f"{cabecalho(doc)}\n\n{doc['texto']}\n", encoding="utf-8", newline="\n")
            paginas = None
        registro = {chave: valor for chave, valor in doc.items() if chave not in ("paginas", "texto", "arquivo")}
        registro.update({"arquivo": f"dados/acervo/{doc['arquivo']}", "paginas": paginas, "hash_sha256": sha256(caminho)})
        registros.append(registro)

    manifesto = {
        "versao_acervo": "1.0.0",
        "gerado_por": "scripts/gerar_acervo_ficticio.py",
        "aviso": "Todos os documentos são fictícios e foram criados para o Desafio Prático 02 (FIC_DEV). "
                 "Nenhum nome, contato, endereço ou número de documento real foi utilizado.",
        "temas": TEMAS,
        "regra_de_conflito": "Só há prevalência entre documentos quando ela está escrita no acervo (ex.: retificação "
                             "explícita do DOC-02 sobre o DOC-01). DOC-04 e DOC-05 têm a mesma data e versão e nenhum "
                             "deles declara prevalência: a divergência sobre o prazo do termo de compromisso deve ser "
                             "apresentada como conflito e encaminhada à revisão humana.",
        "documentos": registros,
    }
    (destino / "manifesto_acervo.json").write_text(json.dumps(manifesto, indent=2, ensure_ascii=False) + "\n",
                                                   encoding="utf-8", newline="\n")
    return manifesto


# ------------------------------------------------------------------------------
# Solicitações reaproveitadas do Desafio 01 (Seção 6: saídas de áudio e OCR)
# ------------------------------------------------------------------------------
def _valor(dados: Dict[str, Any], caminho: str) -> str:
    atual: Any = dados
    for parte in caminho.split("."):
        atual = atual.get(parte, "não localizado") if isinstance(atual, dict) else "não localizado"
    return atual


def texto_ficha_ocr(gabarito_visao: Dict[str, Any]) -> str:
    """
    Leitura de referência da ficha no formato de texto bruto do Desafio 01 (VisionProcessor.montar_texto_bruto).
    O cabeçalho reproduz o impresso no formulário; campos em branco e incertos seguem o gabarito.
    """
    esperado = gabarito_visao["dados_extraidos_esperados"]
    incertos = gabarito_visao.get("campos_incertos_esperados", {})
    linhas = ["CABEÇALHO: GOVERNO DE MATO GROSSO | SECRETARIA DE ESTADO DE CIÊNCIA, TECNOLOGIA E INOVAÇÃO - "
              "SECITECI/MT | ESCOLA TÉCNICA ESTADUAL DE CUIABÁ | FICHA DE MATRÍCULA"]
    for identificador, (rotulo, caminho) in CAMPOS_FICHA.items():
        valor = _valor(esperado, caminho)
        if valor == "não localizado":
            linhas.append(f"{rotulo}: [EM BRANCO]  [EM_BRANCO]")
        elif identificador in incertos:
            # Só a descrição do traçado; a parte do gabarito que diz o que o leitor deve fazer não entra na entrada
            linhas.append(f"{rotulo}: {valor}  [INCERTO] - {incertos[identificador].split(';')[0]}")
        else:
            linhas.append(f"{rotulo}: {valor}  [LEGIVEL]")
    assinaturas = esperado["conformidade_e_assinaturas"]
    linhas.append(f"DECLARAÇÃO DE CIÊNCIA DE FALTAS: {'MARCADA' if assinaturas['termo_ciencia_faltas_assinado'] else 'NÃO MARCADA'}")
    linhas.append(f"ASSINATURA DO ALUNO OU RESPONSÁVEL: {'PRESENTE' if assinaturas['assinatura_aluno_presente'] is True else 'AUSENTE'}")
    linhas.append(f"ASSINATURA DA SECRETARIA ESCOLAR: {'PRESENTE' if assinaturas['assinatura_secretaria_escolar'] is True else 'AUSENTE'}")
    return "\n".join(linhas) + "\n"


def gerar_solicitacoes_reaproveitadas(destino: Path) -> Dict[str, str]:
    destino.mkdir(parents=True, exist_ok=True)
    gabaritos = RAIZ / "dados" / "gabaritos"
    audio = json.loads((gabaritos / "gabarito_audio.json").read_text(encoding="utf-8"))
    visao = json.loads((gabaritos / "gabarito_visao.json").read_text(encoding="utf-8"))
    arquivos = {
        "SOL-02_transcricao_audio_desafio01.txt": audio["transcricao_referencia"] + "\n",
        "SOL-05_leitura_ficha_ocr_desafio01.txt": texto_ficha_ocr(visao),
    }
    hashes = {}
    for nome, conteudo in arquivos.items():
        (destino / nome).write_text(conteudo, encoding="utf-8", newline="\n")
        hashes[nome] = sha256(destino / nome)
    return hashes


def main():
    manifesto = gerar_acervo(RAIZ / "dados" / "acervo")
    hashes = gerar_solicitacoes_reaproveitadas(RAIZ / "dados" / "solicitacoes")
    print("Acervo fictício gerado em dados/acervo/:")
    for doc in manifesto["documentos"]:
        paginas = f"{doc['paginas']} pág." if doc["paginas"] else "TXT"
        print(f"  - {doc['doc_id']} ({doc['formato']}, {paginas}, {doc['uso']}): {doc['hash_sha256'][:16]}")
    print("Solicitações reaproveitadas do Desafio 01 em dados/solicitacoes/:")
    for nome, valor in hashes.items():
        print(f"  - {nome}: {valor[:16]}")


if __name__ == "__main__":
    main()
