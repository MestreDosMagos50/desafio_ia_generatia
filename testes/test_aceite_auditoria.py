"""Testes de aceite escritos pelo auditor externo (17/10/2026) para lacunas que ele encontrou; todos devem passar."""
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
import src.main as main
from src import revisao_humana as revisao
from src.parsers import GeradorMinuta, SolicitacaoEstruturada, MinutaGerada
from src.llm_client import LLMClient, LLMResponse
from src.privacidade import minimizar
from src.audio import AudioProcessor

class Cliente:
    disponivel = True
    modelo = 'teste-offline'
    def gerar(self, *args, **kwargs):
        if kwargs.get('schema') is MinutaGerada:
            return LLMResponse('', self.modelo, 'teste', False, 1, codigo_erro='TIMEOUT', erro='Timeout simulado')
        return LLMResponse(json.dumps({'protocolo':'TESTE-001','solicitante':{'nome_completo':'Pessoa Ficticia'}}),self.modelo,'teste',True,1)

def test_pipeline_deve_retornar_falha_se_minuta_nao_for_gerada(tmp_path, monkeypatch):
    (tmp_path/'dados/processados').mkdir(parents=True)
    (tmp_path/'entrada.txt').write_text('Protocolo TESTE-001. Pessoa Ficticia.',encoding='utf-8')
    cliente=Cliente()
    gerador=GeradorMinuta(llm_client=cliente)
    gerador.raiz_projeto=tmp_path
    gerador.dir_processados=tmp_path/'dados/processados'
    gerador.dir_minutas=tmp_path/'minutas'
    monkeypatch.setattr(main,'RAIZ_PROJETO',tmp_path)
    monkeypatch.setattr('src.llm_client.LLMClient',lambda:cliente)
    monkeypatch.setattr('src.parsers.GeradorMinuta',lambda **kw:gerador)
    monkeypatch.setattr('src.audit.AuditManager',lambda:SimpleNamespace(registrar_execucao=lambda **kw:'EXEC-TESTE'))
    monkeypatch.setattr(revisao,'conferir_dados_criticos',lambda *a,**kw:{})
    retorno=main.executar_pipeline({'arquivos_originais':{'texto':'entrada.txt'}},modo='texto',auto_demo=True)
    assert retorno is False, 'Pipeline informa sucesso mesmo sem gerar a minuta obrigatoria'

def test_minimizacao_nao_reenvia_cpf_e_email_em_pedido_livre():
    dados=SolicitacaoEstruturada(pedido_detalhado='Contato ficticio pessoa@exemplo.com; CPF 123.456.789-00').model_dump()
    enviado=json.dumps(minimizar(dados))
    assert '123.456.789-00' not in enviado and 'pessoa@exemplo.com' not in enviado

def test_demo_nao_deve_liberar_sintese_com_aprovacao_humana(monkeypatch):
    sintetizar=Mock()
    monkeypatch.setattr(revisao,'sintetizar_e_registrar',sintetizar)
    audit=SimpleNamespace(registrar_decisao_humana=lambda **kw:None)
    revisao.revisar_minuta(audit,'EXEC-DEMO','CASO-DEMO',SolicitacaoEstruturada(),{'protocolo':'TESTE','caminho_arquivo':'teste.txt','alertas':[]},None,True)
    assert not sintetizar.called, 'Demo usa a mesma sintese que afirma aprovacao por servidor'

def test_campo_vazio_deve_virar_nao_localizado():
    r=SolicitacaoEstruturada(protocolo='',solicitante={'nome_completo':''})
    assert r.protocolo=='não localizado' and r.solicitante.nome_completo=='não localizado'

def test_protocolo_ausente_nao_deve_ser_soletrado():
    texto=AudioProcessor(llm_client=Cliente()).montar_texto_locucao(SolicitacaoEstruturada(),{'assunto':'Teste','saudacao':'Ola','paragrafos':['Teste.'],'fechamento':'Fim.'})
    assert 'n ã o' not in texto and 'l o c a l i z a d o' not in texto

def test_modelo_sobrescrito_nao_deve_usar_preco_do_padrao(monkeypatch):
    from testes.test_error_handling import ClienteFalso,resposta_falsa
    monkeypatch.setenv('GEMINI_MODEL','modelo-sem-tabela-propria')
    c=LLMClient()
    c.gemini_client=ClienteFalso(resposta_falsa())
    r=c.gerar('teste sem rede')
    assert r.custo_estimado_usd is None

def test_nova_geracao_preserva_conteudo_anterior(tmp_path,monkeypatch):
    class ClienteMinuta:
        def __init__(self): self.n=0
        def gerar(self,*args,**kwargs):
            self.n+=1
            corpo={'assunto':f'Versao {self.n}','saudacao':'Ola','paragrafos':[f'Texto {self.n}.'],'fechamento':'Fim'}
            return LLMResponse(json.dumps(corpo),'teste','teste',True,1)
    gerador=GeradorMinuta(llm_client=ClienteMinuta())
    gerador.dir_minutas=tmp_path
    monkeypatch.setattr(gerador,'_salvar_docx',lambda *a:None)
    registro=SolicitacaoEstruturada(protocolo='TESTE-001')
    primeira=gerador.gerar_minuta_institucional(registro,[])
    texto_anterior=Path(primeira['caminho_arquivo']).read_text(encoding='utf-8')
    gerador.gerar_minuta_institucional(registro,[])
    assert Path(primeira['caminho_arquivo']).read_text(encoding='utf-8')==texto_anterior

def test_correcao_seguida_de_aprovacao_conta_como_corrigida():
    from src.audit import AuditManager
    decisoes=[{'caso_id':'TESTE','objeto_revisado':'minuta','timestamp_decisao':'2026-10-17T10:00:00','decisao':'CORRIGIDO_MANUALMENTE'},
              {'caso_id':'TESTE','objeto_revisado':'minuta','timestamp_decisao':'2026-10-17T10:01:00','decisao':'APROVADO'}]
    ultimas=AuditManager.ultimas_decisoes(decisoes)
    resultado=AuditManager.resultado_do_caso({objeto:d for (caso,objeto),d in ultimas.items()},'minuta')
    assert resultado=='CORRIGIDO_MANUALMENTE'
