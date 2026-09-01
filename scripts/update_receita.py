#!/usr/bin/env python3
import csv, io, os, sqlite3, tempfile, time, zipfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

ROOT="https://dadosabertos.rfb.gov.br/CNPJ/dados_abertos_cnpj/"
SUPABASE_URL=os.environ["SUPABASE_URL"].rstrip("/")
SERVICE_KEY=os.environ["SUPABASE_SERVICE_ROLE_KEY"]
UFS={x.strip().upper() for x in os.getenv("RFB_UFS","PA").split(",") if x.strip()}
RETENTION_DAYS=int(os.getenv("RFB_RETENTION_DAYS","180"))
BATCH=int(os.getenv("SUPABASE_BATCH_SIZE","500"))
VALIDATION_MODE=os.getenv("RFB_VALIDATION_MODE","1")=="1"
MAX_EST_FILES=int(os.getenv("RFB_MAX_EST_FILES","1" if VALIDATION_MODE else "10"))
COMPETENCIA=os.getenv("RFB_COMPETENCIA","2026-08").strip()
HEADERS={"apikey":SERVICE_KEY,"Authorization":f"Bearer {SERVICE_KEY}"}

SESSION=requests.Session()
retry=Retry(total=4,connect=4,read=4,status=4,backoff_factor=3,status_forcelist=(429,500,502,503,504),allowed_methods=frozenset(["GET","HEAD"]),raise_on_status=False)
adapter=HTTPAdapter(max_retries=retry,pool_connections=4,pool_maxsize=4)
SESSION.mount("https://",adapter)
SESSION.mount("http://",adapter)
SESSION.headers.update({"User-Agent":"EMC-CRM-RFB-Updater/validation"})

def log(msg): print(f"[{datetime.now().isoformat(timespec='seconds')}] {msg}",flush=True)

def get(url,stream=False,attempts=3,connect=45,read=900):
    last=None
    for n in range(1,attempts+1):
        try:
            log(f"GET {url} tentativa {n}/{attempts}")
            r=SESSION.get(url,stream=stream,timeout=(connect,read)); r.raise_for_status(); return r
        except Exception as e:
            last=e
            if n<attempts:
                wait=10*n; log(f"Falha temporária: {type(e).__name__}; aguardando {wait}s"); time.sleep(wait)
    raise RuntimeError(f"Falha ao acessar {url}: {last}")

def download(url,path):
    with get(url,stream=True,attempts=3,connect=45,read=1800) as r:
        with open(path,"wb") as f:
            for chunk in r.iter_content(1024*1024):
                if chunk: f.write(chunk)
    if not path.exists() or path.stat().st_size==0: raise RuntimeError(f"Download vazio: {url}")

def zip_rows(path):
    with zipfile.ZipFile(path) as z:
        with z.open(z.namelist()[0]) as raw:
            txt=io.TextIOWrapper(raw,encoding="latin-1",errors="replace",newline="")
            yield from csv.reader(txt,delimiter=";",quotechar='"')

def clean(v): return (v or "").strip()
def parse_date(v):
    v=clean(v); return f"{v[:4]}-{v[4:6]}-{v[6:]}" if len(v)==8 and v.isdigit() else None

def ref_table(filename):
    with tempfile.TemporaryDirectory() as td:
        p=Path(td)/filename; download(f"{ROOT}{COMPETENCIA}/{filename}",p)
        return {clean(r[0]):clean(r[1]) for r in zip_rows(p) if len(r)>=2}

def status_start():
    payload={"referencia":COMPETENCIA,"status":"processando","fonte_url":f"{ROOT}{COMPETENCIA}/","ufs":",".join(sorted(UFS)),"dias_retencao":RETENTION_DAYS,"verificado_em":datetime.now(timezone.utc).isoformat(),"proxima_verificacao":(datetime.now(timezone.utc)+timedelta(days=7)).isoformat(),"observacao":"modo_validacao" if VALIDATION_MODE else "carga_completa"}
    h={**HEADERS,"Content-Type":"application/json","Prefer":"return=representation"}
    r=requests.post(f"{SUPABASE_URL}/rest/v1/receita_import_status",headers=h,json=payload,timeout=30); r.raise_for_status(); return r.json()[0]["id"]

def status_finish(i,count,error=None):
    payload={"concluido_em":datetime.now(timezone.utc).isoformat(),"registros":count,"status":"falhou" if error else "concluido","erro":error}
    r=requests.patch(f"{SUPABASE_URL}/rest/v1/receita_import_status?id=eq.{i}",headers={**HEADERS,"Content-Type":"application/json"},json=payload,timeout=30);r.raise_for_status()

def setup(path):
    c=sqlite3.connect(path);c.executescript('''create table selected(cnpj text primary key,razao_social text,nome_fantasia text,data_abertura text,situacao text,cnae text,cnae_desc text,porte text,simples integer,mei integer,municipio text,uf text,telefone text,email text);''');return c

def process_est(conn,municipios,cnaes):
    cutoff=(date.today()-timedelta(days=RETENTION_DAYS)).strftime("%Y%m%d"); total=0
    for i in range(MAX_EST_FILES):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/f"Estabelecimentos{i}.zip"; download(f"{ROOT}{COMPETENCIA}/Estabelecimentos{i}.zip",p)
            batch=[]
            for r in zip_rows(p):
                if len(r)<30: continue
                situ,opening,uf=clean(r[5]),clean(r[10]),clean(r[19]).upper()
                if situ!="02" or uf not in UFS or not opening or opening<cutoff: continue
                cnpj=(clean(r[0])+clean(r[1])+clean(r[2])).upper(); fantasy=clean(r[4])
                cnae=clean(r[11]); phone=''.join(ch for ch in clean(r[21])+clean(r[22]) if ch.isdigit()); email=clean(r[27]).lower(); mun=municipios.get(clean(r[20]),clean(r[20]))
                display=fantasy or f"CNPJ {cnpj}"
                batch.append((cnpj,display,fantasy,parse_date(opening),"ATIVA",cnae,cnaes.get(cnae,""),None,None,None,mun,uf,phone,email))
                if len(batch)>=3000:
                    conn.executemany("insert or replace into selected values(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",batch);conn.commit();total+=len(batch);batch=[]
            if batch: conn.executemany("insert or replace into selected values(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",batch);conn.commit();total+=len(batch)
            log(f"Arquivo {i}: {total} empresas PA recentes selecionadas")
    return total

def upsert(conn):
    rows=conn.execute("select * from selected");url=f"{SUPABASE_URL}/rest/v1/receita_empresas?on_conflict=cnpj";h={**HEADERS,"Content-Type":"application/json","Prefer":"resolution=merge-duplicates,return=minimal"};batch=[];total=0
    keys=['cnpj','razao_social','nome_fantasia','data_abertura','situacao_cadastral','cnae_principal','cnae_descricao','porte','simples','mei','municipio','uf','telefone','email']
    for row in rows:
        item=dict(zip(keys,row));item['updated_at']=datetime.now(timezone.utc).isoformat();batch.append(item)
        if len(batch)>=BATCH:
            r=requests.post(url,headers=h,json=batch,timeout=120);r.raise_for_status();total+=len(batch);batch=[];log(f"Supabase: {total}")
    if batch:
        r=requests.post(url,headers=h,json=batch,timeout=120);r.raise_for_status();total+=len(batch)
    return total

def main():
    log(f"MODO={'VALIDAÇÃO' if VALIDATION_MODE else 'COMPLETO'} competencia={COMPETENCIA} UFs={','.join(sorted(UFS))} arquivos_est={MAX_EST_FILES}")
    sid=status_start()
    try:
        municipios=ref_table("Municipios.zip"); cnaes=ref_table("Cnaes.zip")
        with tempfile.TemporaryDirectory() as td:
            conn=setup(Path(td)/"etl.sqlite"); found=process_est(conn,municipios,cnaes); log(f"Candidatos encontrados: {found}"); total=upsert(conn)
        status_finish(sid,total); log(f"VALIDAÇÃO CONCLUÍDA: {total} registros enviados ao Supabase")
    except Exception as e:
        status_finish(sid,0,str(e)[:2000]); raise

if __name__=="__main__": main()
