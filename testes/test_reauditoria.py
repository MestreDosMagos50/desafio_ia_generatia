"""Testes escritos pelo auditor externo na reauditoria de 17/10/2026; todos devem passar."""
import json
import hashlib
from pathlib import Path
from types import SimpleNamespace
import src.main as main
from src import revisao_humana as revisao
from src.parsers import GeradorMinuta, MinutaGerada, SolicitacaoEstruturada
from src.llm_client import LLMResponse
from src.audit import AuditManager

def test_ficha_com_campo_pendente_nao_recebe_aprovacao(tmp_path,monkeypatch):
    respostas=iter(['p','1',''])
    monkeypatch.setattr('builtins.input',lambda msg='':next(respostas))
    monkeypatch.setattr(revisao,'_operador_identificado','TESTE AUTOMATIZADO')
    decisoes=[]
    audit=SimpleNamespace(registrar_decisao_humana=lambda **kw:decisoes.append(kw))
    res={'dados_revisados':{'codigo_matricula':'2024-000142','trechos_incertos':[]},'comparacao_gabarito':{'incertos_esperados':{'nao_sinalizados':['codigo']}}}
    confirmada=revisao.revisar_ficha(audit,res,'EXEC-TESTE','CASO-TESTE',False,tmp_path)
    assert confirmada['confirmacao_humana']['pendentes']==['codigo']
    assert decisoes[-1]['decisao']!='APROVADO', 'Campo explicitamente pendente foi registrado como aprovado'

def test_duas_execucoes_preservam_hash_do_registro_usado_na_primeira(tmp_path,monkeypatch):
    class Cliente:
        disponivel=True
        modelo='teste'
        def gerar(self,*args,**kw):
            conteudo=({'assunto':'Teste','saudacao':'Ola','paragrafos':['Teste.'],'fechamento':'Fim'} if kw.get('schema') is MinutaGerada else {'protocolo':'TESTE-001','solicitante':{'nome_completo':'Pessoa A'}})
            return LLMResponse(json.dumps(conteudo),'teste','teste',True,1)
    cliente=Cliente()
    (tmp_path/'dados/processados').mkdir(parents=True)
    (tmp_path/'entrada.txt').write_text('Protocolo TESTE-001. Pessoa A.',encoding='utf-8')
    gerador=GeradorMinuta(llm_client=cliente)
    gerador.raiz_projeto=tmp_path
    gerador.dir_processados=tmp_path/'dados/processados'
    gerador.dir_minutas=tmp_path/'minutas'
    monkeypatch.setattr(gerador,'_salvar_docx',lambda *a:None)
    auditor=AuditManager()
    auditor.raiz_projeto=tmp_path
    auditor.arquivo_log_jsonl=tmp_path/'audit.jsonl'
    monkeypatch.setattr(main,'RAIZ_PROJETO',tmp_path)
    monkeypatch.setattr('src.llm_client.LLMClient',lambda:cliente)
    monkeypatch.setattr('src.parsers.GeradorMinuta',lambda **kw:gerador)
    monkeypatch.setattr('src.audit.AuditManager',lambda:auditor)
    confirmacoes=iter([{'nome_completo':'Pessoa A'},{'nome_completo':'Pessoa B'}])
    monkeypatch.setattr(revisao,'conferir_dados_criticos',lambda *a,**kw:next(confirmacoes))
    monkeypatch.setattr(revisao,'revisar_minuta',lambda *a,**kw:'SEM_DECISAO_TESTE')
    for _ in range(2):
        assert main.executar_pipeline({'arquivos_originais':{'texto':'entrada.txt'}},modo='texto',auto_demo=True)
    logs=[json.loads(l) for l in auditor.arquivo_log_jsonl.read_text(encoding='utf-8').splitlines()]
    primeira=next(r for r in logs if r['etapa']=='geracao_minuta')
    origem=tmp_path/primeira['arquivo_origem']
    assert hashlib.sha256(origem.read_bytes()).hexdigest()==primeira['sha256_origem'], 'Snapshot de entrada da minuta anterior foi sobrescrito'

def test_correcao_curso_nao_deixa_payload_contraditorio():
    from src.conferencia import aplicar_valores_confirmados
    from src.privacidade import minimizar
    registro=SolicitacaoEstruturada(curso={'nome':'Informatica','turno':'vespertino'},assunto='Matricula em Informatica',pedido_detalhado='Quero Informatica no vespertino').model_dump()
    atualizado=aplicar_valores_confirmados(registro,{'curso':'Enfermagem','turno':'noturno'})
    payload=minimizar(atualizado)
    assert 'Informatica' not in payload['assunto']+payload['pedido_detalhado'], 'Texto antigo conflitante continua no payload sem indicacao de substituicao'

def test_resumo_nao_apresenta_custo_desconhecido_como_zero(tmp_path,monkeypatch):
    import resumir_auditoria as resumo
    log=tmp_path/'audit.jsonl'
    log.write_text(json.dumps({'timestamp':'2026-10-17T13:00:00','etapa':'geracao_minuta','sucesso':True,'usou_modelo_ia':True,'provedor':'teste','modelo':'sem-tabela','tokens_total':100,'custo_estimado_usd':None}),encoding='utf-8')
    (tmp_path/'config.json').write_text('{}',encoding='utf-8')
    monkeypatch.setattr(resumo,'RAIZ',tmp_path)
    monkeypatch.setattr(resumo,'ARQUIVO_LOG',log)
    texto=resumo.gerar_resumo()
    assert '**Total estimado:** US$ 0.000000' not in texto, 'Custo ausente aparece como total conhecido zero'
