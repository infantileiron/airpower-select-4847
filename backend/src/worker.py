import os,time,json,logging
from pathlib import Path
import redis
from src.config.database import Session
from src.models.entities import Run,Family
from src.services.analysis import choose,train_family
r=redis.Redis.from_url(os.environ['REDIS_URL'])
ARTIFACTS=Path(os.environ.get('ARTIFACT_DIR','/artifacts'))
def parse_job(raw):
 text=raw.decode() if isinstance(raw,bytes) else str(raw)
 try:
  payload=json.loads(text)
  if isinstance(payload,dict) and payload.get('type') in ('run','family') and isinstance(payload.get('id'),int):return payload['type'],payload['id']
 except (ValueError,TypeError):pass
 return 'run',int(text)
def publish(name,payload):
 ARTIFACTS.mkdir(parents=True,exist_ok=True)
 (ARTIFACTS/name).write_text(json.dumps(payload,ensure_ascii=False))
def recover():
 with Session() as recovery:
  for pending in recovery.query(Run).filter(Run.state.in_(['queued','running'])).all():
   pending.state='queued';r.rpush('airpower:runs',pending.id)
  for pending in recovery.query(Family).filter(Family.state.in_(['queued','running'])).all():
   pending.state='queued';r.rpush('airpower:runs',json.dumps({'type':'family','id':pending.id}))
  recovery.commit()
def handle(item):
 kind,oid=parse_job(item[1])
 if kind=='family':
  with Session() as s:
   row=s.get(Family,oid)
   if not row or row.state!='queued':return
   snapshot=(row.result or {}).get('snapshot') or []
   row.state='running';s.commit()
   try:
    computed=train_family(snapshot,row.features,row.alphas)
    row.result={**computed,'snapshot':snapshot};row.state='done';row.error=''
    s.commit()
    try:publish('family-'+str(row.id)+'.json',row.result)
    except Exception:logging.exception('artifact family '+str(row.id))
   except Exception as e:
    row.state='failed';row.error=str(e);row.result={**(row.result or {}),'complete':False};s.commit()
  return
 with Session() as s:
  row=s.get(Run,oid)
  if not row or row.state!='queued':return
  snapshot=row.result['snapshot'];row.state='running';s.commit()
  try:
   computed={**choose(snapshot,row.features,row.alphas),'snapshot':snapshot}
   row.result=computed;row.state='done';s.commit()
   try:publish(str(row.id)+'.json',computed)
   except Exception:logging.exception('artifact run '+str(row.id))
  except Exception as e:row.state='failed';row.error=str(e);s.commit()
def main():
 recover()
 while True:
  Path('/tmp/heartbeat').touch()
  try:
   item=r.blpop('airpower:runs',timeout=3)
   if item:handle(item)
  except Exception:logging.exception('worker');time.sleep(2)
if __name__=='__main__':main()
