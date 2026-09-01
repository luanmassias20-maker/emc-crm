#!/usr/bin/env python3
import csv, io, json, os, tempfile, zipfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

COMP=os.getenv('RFB_VALIDATION_COMPETENCIA','2026-08')
ROOT=f'https://dadosabertos.rfb.gov.br/CNPJ/dados_abertos_cnpj/{COMP}/'
UF=os.getenv('RFB_UFS','PA').split(',')[0].strip().upper() or 'PA'
DAYS=int(os.getenv('RFB_RETENTION_DAYS','180'))
LIMIT=int(os.getenv('RFB_VALIDATION_LIMIT','3000'))
OUT=Path('data'); OUT.mkdir(exist_ok=True)

S=requests.Session()
retry=Retry(total=4,connect=4,read=4,status=4,backoff_factor=4,status_forcelist=(429,500,502,503,504),allowed_methods=frozenset(['GET','HEAD']))
S.mount('https://',HTTPAdapter(max_retries=retry))
S.headers.update({'User-Agent':'EMC-CRM-RFB-Validator/1.0'})

def log(x): print(f'[{datetime.now().isoformat(timespec="seconds")}] {x}',flush=True)
def download(name):
    url=ROOT+name
    with tempfile.NamedTemporaryFile(delete=False,suffix='.zip') as tmp:
        path=Path(tmp.name)
    try:
        log(f'Baixando {name}')
        with S.get(url,stream=True,timeout=(90,1200)) as r:
            r.raise_for_status()
            with open(path,'wb') as f:
                for ch in r.iter_content(1024*1024):
                    if ch: f.write(ch)
        return path
    except Exception:
        path.unlink(missing_ok=True); raise

def rows(path):
    with zipfile.ZipFile(path) as z:
        name=z.namelist()[0]
        with z.open(name) as raw:
            txt=io.TextIOWrapper(raw,encoding='latin-1',errors='replace',newline='')
            yield from csv.reader(txt,delimiter=';',quotechar='"')

def refs(name):
    p=download(name)
    try: return {r[0].strip():r[1].strip() for r in rows(p) if len(r)>=2}
    finally: p.unlink(missing_ok=True)

def fmt_date(v):
    v=(v or '').strip()
    return f'{v[:4]}-{v[4:6]}-{v[6:]}' if len(v)==8 and v.isdigit() else None

def main():
    cutoff=(date.today()-timedelta(days=DAYS)).strftime('%Y%m%d')
    log(f'VALIDAÇÃO RÁPIDA: competencia={COMP} UF={UF} dias={DAYS} limite={LIMIT}')
    municipios=refs('Municipios.zip')
    cnaes=refs('Cnaes.zip')
    p=download('Estabelecimentos0.zip')
    out=[]
    try:
        for r in rows(p):
            if len(r)<28: continue
            basic,ordem,dv=(r[0].strip(),r[1].strip(),r[2].strip())
            situ=r[5].strip(); opening=r[10].strip(); uf=r[19].strip().upper()
            if situ!='02' or uf!=UF or not opening or opening<cutoff: continue
            cnpj=(basic+ordem+dv).upper(); cnae=r[11].strip(); mun=r[20].strip()
            fantasia=r[4].strip() or f'Empresa {cnpj}'
            phone=''.join(c for c in (r[21].strip()+r[22].strip()) if c.isdigit())
            email=(r[27].strip().lower() if len(r)>27 else '')
            out.append({'cnpj':cnpj,'razao_social':fantasia,'nome_fantasia':fantasia,'data_abertura':fmt_date(opening),'situacao_cadastral':'ATIVA','cnae_principal':cnae,'cnae_descricao':cnaes.get(cnae,''),'porte':'','simples':None,'mei':None,'municipio':municipios.get(mun,mun),'uf':uf,'telefone':phone,'email':email})
            if len(out)>=LIMIT: break
    finally: p.unlink(missing_ok=True)
    (OUT/'receita_pa.json').write_text(json.dumps(out,ensure_ascii=False,separators=(',',':')),encoding='utf-8')
    status={'referencia':COMP,'status':'concluido','registros':len(out),'ufs':UF,'dias_retencao':DAYS,'concluido_em':datetime.now(timezone.utc).isoformat(),'modo':'validacao_local'}
    (OUT/'status.json').write_text(json.dumps(status,ensure_ascii=False,indent=2),encoding='utf-8')
    log(f'Base local pronta: {len(out)} empresas')

if __name__=='__main__': main()
