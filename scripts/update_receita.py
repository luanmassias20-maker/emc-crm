#!/usr/bin/env python3
import csv, io, os, re, sqlite3, sys, tempfile, time, zipfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urljoin
import requests

ROOT="https://dadosabertos.rfb.gov.br/CNPJ/dados_abertos_cnpj/"
SUPABASE_URL=os.environ["SUPABASE_URL"].rstrip("/")
SERVICE_KEY=os.environ["SUPABASE_SERVICE_ROLE_KEY"]
UFS={x.strip().upper() for x in os.getenv("RFB_UFS","PA").split(",") if x.strip()}
RETENTION_DAYS=int(os.getenv("RFB_RETENTION_DAYS","180"))
BATCH=int(os.getenv("SUPABASE_BATCH_SIZE","500"))
FORCE=os.getenv("FORCE_UPDATE","0")=="1"
HEADERS={"apikey":SERVICE_KEY,"Authorization":f"Bearer {SERVICE_KEY}"}
SESSION=requests.Session()
SESSION.headers.update({"User-Agent":"EMC-CRM-RFB-Updater/1.0"})

def log(msg): print(f"[{datetime.now().isoformat(timespec='seconds')}] {msg}",flush=True)

def get_latest_competencia():
    r=SESSION.get(ROOT,timeout=60); r.raise_for_status()
    comps=sorted(set(re.findall(r'href=["\'](\d{4}-\d{2})/?["\']',r.text)))
    if not comps:
        comps=sorted(set(re.findall(r'(\d{4}-\d{2})/',r.text)))
    if not comps: raise RuntimeError("Nenhuma competência encontrada no diretório oficial da RFB.")
    return comps[-1]

def latest_completed():
    url=f"{SUPABASE_URL}/rest/v1/receita_import_status"
    params={"select":"referencia,status","status":"eq.concluido","order":"id.desc","limit":"1"}
    r=requests.get(url,headers=HEADERS,params=params,timeout=30); r.raise_for_status()
    arr=r.json(); return arr[0]["referencia"] if arr else None

def status_start(comp):
    payload={"referencia":comp,"status":"processando","fonte_url":f"{ROOT}{comp}/",
             "ufs":",".join(sorted(UFS)),"dias_retencao":RETENTION_DAYS,
             "verificado_em":datetime.now(timezone.utc).isoformat(),
             "proxima_verificacao":(datetime.now(timezone.utc)+timedelta(days=7)).isoformat()}
    h={**HEADERS,"Content-Type":"application/json","Prefer":"return=representation"}
    r=requests.post(f"{SUPABASE_URL}/rest/v1/receita_import_status",headers=h,json=payload,timeout=30); r.raise_for_status()
    return r.json()[0]["id"]

def status_finish(row_id,count,error=None):
    payload={"concluido_em":datetime.now(timezone.utc).isoformat(),"registros":count,
             "status":"falhou" if error else "concluido","erro":error}
    h={**HEADERS,"Content-Type":"application/json"}
    r=requests.patch(f"{SUPABASE_URL}/rest/v1/receita_import_status?id=eq.{row_id}",headers=h,json=payload,timeout=30); r.raise_for_status()

def download(url,path):
    log(f"Baixando {url}")
    with SESSION.get(url,stream=True,timeout=(30,900)) as r:
        r.raise_for_status()
        with open(path,"wb") as f:
            for chunk in r.iter_content(1024*1024):
                if chunk: f.write(chunk)

def zip_rows(path):
    with zipfile.ZipFile(path) as z:
        name=z.namelist()[0]
        with z.open(name) as raw:
            txt=io.TextIOWrapper(raw,encoding="latin-1",errors="replace",newline="")
            yield from csv.reader(txt,delimiter=";",quotechar='"')

def clean_text(v): return (v or "").strip()
def parse_date(v):
    v=clean_text(v)
    if len(v)==8 and v.isdigit(): return f"{v[:4]}-{v[4:6]}-{v[6:]}"
    return None

def ref_table(comp,filename):
    with tempfile.TemporaryDirectory() as td:
        p=Path(td)/filename
        download(f"{ROOT}{comp}/{filename}",p)
        return {clean_text(r[0]):clean_text(r[1]) for r in zip_rows(p) if len(r)>=2}

def setup_db(path):
    c=sqlite3.connect(path)
    c.executescript("""
    pragma journal_mode=WAL;
    create table selected(
      cnpj text primary key, basic text, razao_social text, nome_fantasia text,
      data_abertura text, situacao text, cnae text, cnae_desc text, porte text,
      simples integer, mei integer, municipio text, uf text, telefone text, email text
    );
    create index idx_selected_basic on selected(basic);
    """)
    return c

def process_estabelecimentos(comp,conn,municipios,cnaes):
    cutoff=(date.today()-timedelta(days=RETENTION_DAYS)).strftime("%Y%m%d")
    inserted=0
    for i in range(10):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/f"Estabelecimentos{i}.zip"
            url=f"{ROOT}{comp}/Estabelecimentos{i}.zip"
            try: download(url,p)
            except requests.HTTPError as e:
                if e.response is not None and e.response.status_code==404: continue
                raise
            batch=[]
            for r in zip_rows(p):
                if len(r)<30: continue
                basic,ordem,dv=map(clean_text,r[0:3])
                situ=clean_text(r[5]); opening=clean_text(r[10]); uf=clean_text(r[19]).upper()
                if situ!="02" or (UFS and uf not in UFS) or not opening or opening<cutoff: continue
                cnpj=(basic+ordem+dv).upper()
                cnae=clean_text(r[11]); mun_code=clean_text(r[20])
                phone=("".join(ch for ch in (clean_text(r[21])+clean_text(r[22])) if ch.isdigit()))
                email=clean_text(r[27]).lower()
                batch.append((cnpj,basic.upper(),None,clean_text(r[4]),parse_date(opening),"ATIVA",cnae,cnaes.get(cnae,""),None,None,None,municipios.get(mun_code,mun_code),uf,phone,email))
                if len(batch)>=5000:
                    conn.executemany("insert or replace into selected values(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",batch);conn.commit();inserted+=len(batch);batch=[]
            if batch: conn.executemany("insert or replace into selected values(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",batch);conn.commit();inserted+=len(batch)
            log(f"Estabelecimentos{i}: candidatos acumulados {inserted}")
    return inserted

def process_empresas(comp,conn):
    porte={"00":"NAO INFORMADO","01":"ME","03":"EPP","05":"DEMAIS"}
    for i in range(10):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/f"Empresas{i}.zip"
            try: download(f"{ROOT}{comp}/Empresas{i}.zip",p)
            except requests.HTTPError as e:
                if e.response is not None and e.response.status_code==404: continue
                raise
            cur=conn.cursor()
            for r in zip_rows(p):
                if len(r)<6: continue
                basic=clean_text(r[0]).upper()
                if cur.execute("select 1 from selected where basic=? limit 1",(basic,)).fetchone():
                    cur.execute("update selected set razao_social=?,porte=? where basic=?",(clean_text(r[1]),porte.get(clean_text(r[5]),clean_text(r[5])),basic))
            conn.commit()
            log(f"Empresas{i}: enriquecimento concluído")

def process_simples(comp,conn):
    with tempfile.TemporaryDirectory() as td:
        p=Path(td)/"Simples.zip"; download(f"{ROOT}{comp}/Simples.zip",p)
        cur=conn.cursor()
        for r in zip_rows(p):
            if len(r)<5: continue
            basic=clean_text(r[0]).upper()
            if cur.execute("select 1 from selected where basic=? limit 1",(basic,)).fetchone():
                cur.execute("update selected set simples=?,mei=? where basic=?",(1 if clean_text(r[1])=="S" else 0,1 if clean_text(r[4])=="S" else 0,basic))
        conn.commit()

def upsert_supabase(conn):
    cur=conn.execute("""select cnpj,coalesce(razao_social,nome_fantasia,''),nome_fantasia,data_abertura,situacao,cnae,cnae_desc,
                       porte,simples,mei,municipio,uf,telefone,email from selected where coalesce(razao_social,nome_fantasia,'')<>''""")
    url=f"{SUPABASE_URL}/rest/v1/receita_empresas?on_conflict=cnpj"
    h={**HEADERS,"Content-Type":"application/json","Prefer":"resolution=merge-duplicates,return=minimal"}
    total=0;batch=[]
    for r in cur:
        batch.append({"cnpj":r[0],"razao_social":r[1],"nome_fantasia":r[2],"data_abertura":r[3],"situacao_cadastral":r[4],
                      "cnae_principal":r[5],"cnae_descricao":r[6],"porte":r[7],"simples":None if r[8] is None else bool(r[8]),
                      "mei":None if r[9] is None else bool(r[9]),"municipio":r[10],"uf":r[11],"telefone":r[12],"email":r[13],
                      "updated_at":datetime.now(timezone.utc).isoformat()})
        if len(batch)>=BATCH:
            rr=requests.post(url,headers=h,json=batch,timeout=120);rr.raise_for_status();total+=len(batch);batch=[]
            log(f"Upsert Supabase: {total}")
    if batch:
        rr=requests.post(url,headers=h,json=batch,timeout=120);rr.raise_for_status();total+=len(batch)
    return total

def prune():
    cutoff=(date.today()-timedelta(days=RETENTION_DAYS)).isoformat()
    url=f"{SUPABASE_URL}/rest/v1/receita_empresas"
    params={"data_abertura":f"lt.{cutoff}"}
    if len(UFS)==1: params["uf"]=f"eq.{next(iter(UFS))}"
    elif UFS: params["uf"]="in.("+",".join(UFS)+")"
    r=requests.delete(url,headers=HEADERS,params=params,timeout=120);r.raise_for_status()

def main():
    comp=get_latest_competencia(); old=latest_completed()
    log(f"Competência mais recente: {comp}; última concluída: {old}")
    if old==comp and not FORCE:
        log("Sem nova competência. Nada a baixar."); return
    sid=status_start(comp)
    try:
        municipios=ref_table(comp,"Municipios.zip")
        cnaes=ref_table(comp,"Cnaes.zip")
        with tempfile.TemporaryDirectory() as td:
            conn=setup_db(Path(td)/"etl.sqlite")
            process_estabelecimentos(comp,conn,municipios,cnaes)
            process_empresas(comp,conn)
            process_simples(comp,conn)
            total=upsert_supabase(conn)
            prune()
        status_finish(sid,total)
        log(f"Atualização concluída: {total} empresas sincronizadas.")
    except Exception as e:
        status_finish(sid,0,str(e)[:2000])
        raise

if __name__=="__main__":
    main()
