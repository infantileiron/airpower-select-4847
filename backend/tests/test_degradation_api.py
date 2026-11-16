import json,math,random
import pytest
from datetime import datetime,timedelta
from src.services.analysis import FEATURES

def seed_rows(client,token,n=240):
 samples=[]
 for i in range(n):
  hour=(datetime(2026,11,1)+timedelta(hours=i)).strftime('%Y-%m-%dT%H:00')
  r=client.post('/samples',json={'hour':hour,'pressure':round(6+0.5*math.sin(i/5),3),'flow':round(8+3*math.sin(i/12),3),'temperature':round(22+5*math.sin(i/12),3),'machines':2+i%4,'sensor_noise':0.5,'kwh':round(200+20*math.sin(i/12)+5*(i%4),3),'note':''},headers={'Authorization':'Bearer '+token})
  assert r.status_code==200,r.text
  samples.append(r.json())
 return samples

@pytest.fixture()
def auth(client,redis_server):
 for role in ('admin','analyst','viewer'):
  from src.utils.security import hash_password
  from src.config.database import Session
  from src.models.entities import User
  with Session() as s:
   if not s.query(User).filter_by(email=role+'@t.local').first():
    s.add(User(email=role+'@t.local',role=role,password=hash_password('Demo123!')));s.commit()
 tokens={}
 for role in ('admin','analyst','viewer'):
  r=client.post('/auth/login',json={'email':role+'@t.local','password':'Demo123!'})
  assert r.status_code==200,r.text
  tokens[role]=r.json()['token']
 return tokens

def run_worker_once(redis_server=None):
 from src import worker
 r=worker.r
 item=r.blpop('airpower:runs',timeout=3)
 assert item, 'expected queued job'
 worker.handle(item)

def create_family(client,token,features=None,alphas=None):
 r=client.post('/families',json={'name':'降级族','features':features or ['pressure','flow','temperature','machines'],'alphas':alphas or [0.1,1,10]},headers={'Authorization':'Bearer '+token})
 assert r.status_code==200,r.text
 return r.json()

def test_family_trains_all_nonempty_subsets(client,auth):
 seed_rows(client,auth['analyst'])
 fam=create_family(client,auth['analyst'])
 assert fam['state']=='queued'
 run_worker_once()
 got=client.get('/families/'+str(fam['id']),headers={'Authorization':'Bearer '+auth['viewer']}).json()
 assert got['state']=='done' and got['result']['complete'] is True
 assert got['result']['member_count']==15==len(got['result']['members'])
 feats=['pressure','flow','temperature','machines']
 expected=sorted('+'.join([f for f,b in zip(feats,bits) if b]) for bits in [(a,b,c,d) for a in (0,1) for b in (0,1) for c in (0,1) for d in (0,1) if a or b or c or d])
 assert sorted(m['key'] for m in got['result']['members'])==expected
 by_rank=sorted(got['result']['members'],key=lambda m:m['rank'])
 assert [m['rank'] for m in by_rank]==list(range(1,16))
 assert [m['cv_rmse'] for m in by_rank]==sorted(m['cv_rmse'] for m in by_rank)
 assert got['result']['train_n']==192 and got['result']['validation_n']==48
 assert all(m['validation_rmse'] is not None for m in got['result']['members'])

def test_family_failure_blocks_publish(client,auth):
 rows=seed_rows(client,auth['analyst'],n=60)
 fam=create_family(client,auth['analyst'])
 # make a chosen feature constant in training segment so a member fails
 from src.config.database import Session
 from src.models.entities import Sample
 with Session() as s:
  for r in s.query(Sample).order_by(Sample.hour).limit(50).all():r.sensor_noise=0.0
  s.commit()
 fam2=create_family(client,auth['analyst'],features=['pressure','flow','sensor_noise'])
 run_worker_once();run_worker_once()
 got=client.get('/families/'+str(fam2['id']),headers={'Authorization':'Bearer '+auth['analyst']}).json()
 assert got['state']=='failed'
 assert '常量' in got['error']
 r=client.post('/families/'+str(fam2['id'])+'/batches',json={'text':json.dumps({'hour':'2026-11-11T00:00','pressure':6,'flow':8})},headers={'Authorization':'Bearer '+auth['analyst']})
 assert r.status_code==409
 r=client.get('/families/'+str(fam2['id'])+'/export',headers={'Authorization':'Bearer '+auth['analyst']})
 assert r.status_code==409

def test_batch_routing_variants_and_duplicate(client,auth):
 seed_rows(client,auth['analyst'])
 fam=create_family(client,auth['analyst'])
 run_worker_once()
 lines=[
  {'hour':'2026-11-11T00:00','pressure':6.1,'flow':8.5,'temperature':22,'machines':3,'kwh':210,'label':'all'},
  {'hour':'2026-11-11T01:00','flow':8.0,'machines':2,'label':'flow+machines'},
  {'hour':'2026-11-11T02:00','temperature':21.5,'label':'temperature'},
 ]
 text='\n'.join(json.dumps(x) for x in lines)
 r=client.post('/families/'+str(fam['id'])+'/batches',json={'text':text},headers={'Authorization':'Bearer '+auth['viewer']})
 assert r.status_code==403
 r=client.post('/families/'+str(fam['id'])+'/batches',json={'text':text},headers={'Authorization':'Bearer '+auth['analyst']})
 assert r.status_code==200,r.text
 body=r.json();assert body['duplicate'] is False and body['result']['row_count']==3
 rows=body['result']['rows']
 detailed=client.get('/families/'+str(fam['id']),headers={'Authorization':'Bearer '+auth['analyst']}).json()
 members={m['key']:m for m in detailed['result']['members']}
 assert rows[2]['chosen_features']==['temperature']
 assert rows[0]['family_missing_features']==[]
 assert set(rows[1]['chosen_features'])<= {'flow','machines'}
 # chosen member must be the lowest training error among available subsets
 for row in rows:
  available=[m for m in detailed['result']['members'] if set(m['features'])<=set(row['provided_features'])]
  best=min(available,key=lambda m:(m['cv_rmse'],len(m['features']),m['key']))
  assert row['chosen_features']==best['features']
  assert row['training_cv_rmse']==best['cv_rmse']
  assert row['prediction']==pytest.approx(best['intercept_original']+sum(c['original_unit']*row['features'][c['feature']] for c in best['coefficients']),rel=1e-9)
  assert row['actual']==row['kwh']
 r2=client.post('/families/'+str(fam['id'])+'/batches',json={'text':text},headers={'Authorization':'Bearer '+auth['analyst']})
 assert r2.status_code==200 and r2.json()['duplicate'] is True and r2.json()['id']==body['id']
 listed=client.get('/families/'+str(fam['id'])+'/batches',headers={'Authorization':'Bearer '+auth['analyst']}).json()
 assert len(listed)==1
 assert listed[0]['rows'] is None

def test_batch_rejects_bad_row_and_no_subset(client,auth):
 seed_rows(client,auth['analyst'])
 fam=create_family(client,auth['analyst'])
 run_worker_once()
 good={'hour':'2026-11-11T00:00','pressure':6.1,'flow':8.5}
 bad={'hour':'2026-11-11T01:00','flow':'high'}
 text=json.dumps(good)+'\n'+json.dumps(bad)
 r=client.post('/families/'+str(fam['id'])+'/batches',json={'text':text},headers={'Authorization':'Bearer '+auth['analyst']})
 assert r.status_code==422 and r.json()['detail']['errors'][0]['line']==2
 r=client.post('/families/'+str(fam['id'])+'/batches',json={'text':json.dumps({'hour':'2026-11-11T00:00','kwh':200})},headers={'Authorization':'Bearer '+auth['analyst']})
 assert r.status_code==422
 text=json.dumps(good)+'\n'+json.dumps({'hour':'2026-11-11T02:00','sensor_noise':1})
 r=client.post('/families/'+str(fam['id'])+'/batches',json={'text':text},headers={'Authorization':'Bearer '+auth['analyst']})
 assert r.status_code==422 and r.json()['detail']['errors'][0]['line']==2
 listed=client.get('/families/'+str(fam['id'])+'/batches',headers={'Authorization':'Bearer '+auth['analyst']}).json()
 assert listed==[]

def test_batch_frozen_after_family_and_samples_change(client,auth):
 seed_rows(client,auth['analyst'])
 fam=create_family(client,auth['analyst'])
 run_worker_once()
 text=json.dumps({'hour':'2026-11-11T00:00','pressure':6.1,'flow':8.5})
 r=client.post('/families/'+str(fam['id'])+'/batches',json={'text':text},headers={'Authorization':'Bearer '+auth['analyst']})
 batch=r.json();frozen=batch['result']['rows'][0]['prediction'];checksum=batch['result']['family_checksum']
 # mutate source sample and verify batch untouched
 samples=client.get('/samples',headers={'Authorization':'Bearer '+auth['analyst']}).json()
 first=samples[0]
 client.put('/samples/'+str(first['id']),json={**{k:first[k] for k in ('hour','pressure','flow','temperature','machines','sensor_noise','kwh','note')},'kwh':first['kwh']+50},headers={'Authorization':'Bearer '+auth['analyst']})
 got=client.get('/batches/'+str(batch['id']),headers={'Authorization':'Bearer '+auth['analyst']}).json()
 assert got['result']['rows'][0]['prediction']==frozen
 assert got['result']['family_checksum']==checksum
 assert got['result']['family_id']==fam['id']
# last row failure and recovery
def test_last_row_failure_and_family_recovery(client,auth):
 seed_rows(client,auth['analyst'])
 fam=create_family(client,auth['analyst'])
 run_worker_once()
 lines=[{'hour':'2026-11-11T00:00','pressure':6.1},{'hour':'2026-11-11T01:00','flow':8},{'hour':'2026-11-11T02:00','sensor_noise':1.5}]
 text='\n'.join(json.dumps(x) for x in lines)
 r=client.post('/families/'+str(fam['id'])+'/batches',json={'text':text},headers={'Authorization':'Bearer '+auth['analyst']})
 assert r.status_code==422
 assert r.json()['detail']['errors'][0]['line']==3
 first=client.get('/families/'+str(fam['id']),headers={'Authorization':'Bearer '+auth['analyst']}).json()
 assert first['state']=='done'
 from src.config.database import Session
 from src.models.entities import Family,Audit
 with Session() as s:
  row=s.get(Family,fam['id']);row.state='running';s.commit()
 from src import worker
 worker.recover()
 run_worker_once()  # recovery job
 from src.config.database import Session
 from src.models.entities import Family
 with Session() as s:
  assert s.get(Family,fam['id']).state=='done'
  assert s.query(Audit).filter(Audit.action.like('创建降级模型族%')).count()==1
 # second worker pass must not find the stale queue item again
 from src import worker
 assert worker.r.blpop('airpower:runs',timeout=1) is None

def test_requeue_failed_family(client,auth):
 seed_rows(client,auth['analyst'],n=60)
 from src.config.database import Session
 from src.models.entities import Sample,Family
 with Session() as s:
  for r in s.query(Sample).order_by(Sample.hour).limit(50).all():r.sensor_noise=0.0
  s.commit()
 fam=create_family(client,auth['analyst'],features=['pressure','sensor_noise'])
 run_worker_once()
 assert client.get('/families/'+str(fam['id']),headers={'Authorization':'Bearer '+auth['analyst']}).json()['state']=='failed'
 r=client.post('/families/'+str(fam['id'])+'/requeue',headers={'Authorization':'Bearer '+auth['analyst']})
 assert r.status_code==200 and r.json()['state']=='queued'
 run_worker_once()
 assert client.get('/families/'+str(fam['id']),headers={'Authorization':'Bearer '+auth['analyst']}).json()['state']=='failed'

def test_batch_rejects_duplicate_hours_and_unknown_field(client,auth):
 seed_rows(client,auth['analyst'])
 fam=create_family(client,auth['analyst'])
 run_worker_once()
 text=json.dumps({'hour':'2026-11-11T00:00','pressure':6.1})+'\n'+json.dumps({'hour':'2026-11-11T00:00','flow':8})
 r=client.post('/families/'+str(fam['id'])+'/batches',json={'text':text},headers={'Authorization':'Bearer '+auth['analyst']})
 assert r.status_code==422 and len(r.json()['detail']['errors'])==2
 r=client.post('/families/'+str(fam['id'])+'/batches',json={'text':json.dumps({'hour':'2026-11-11T00:00','pressure':6.1,'kwh_typo':9})},headers={'Authorization':'Bearer '+auth['analyst']})
 assert r.status_code==422 and '未知字段' in r.json()['detail']['errors'][0]['message']

def test_family_never_uses_holdout_for_selection(client,auth):
 from src.services.analysis import train_family
 import math
 rows=[]
 for i in range(120):
  from datetime import datetime,timedelta
  rows.append({'hour':(datetime(2026,11,1)+timedelta(hours=i)).strftime('%Y-%m-%dT%H:00'),'pressure':round(6+i%3,3),'flow':round(8+3*math.sin(i/9),3),'temperature':round(22+5*math.sin(i/9),3),'machines':2+i%4,'sensor_noise':0.4,'kwh':round(200+20*math.sin(i/9)+5*(i%4),3)})
 a=train_family(rows,['pressure','flow','temperature','machines'],[0.1,1,10])
 for r in rows[96:]:r['kwh']=r['kwh']*1000
 b=train_family(rows,['pressure','flow','temperature','machines'],[0.1,1,10])
 assert [(m['key'],m['cv_rmse'],m['selected_alpha']) for m in a['members']]==[(m['key'],m['cv_rmse'],m['selected_alpha']) for m in b['members']]
 assert [m['key'] for m in sorted(a['members'],key=lambda m:m['rank'])]==[m['key'] for m in sorted(b['members'],key=lambda m:m['rank'])]
 pa=sorted(a['members'],key=lambda m:m['key']);pb=sorted(b['members'],key=lambda m:m['key'])
 assert [m['scaler_mean'] for m in pa]==[m['scaler_mean'] for m in pb]
 assert [m['coefficients'] for m in pa]==[m['coefficients'] for m in pb]
 assert all(m['validation_rmse']!=n['validation_rmse'] for m,n in zip(pa,pb))

def test_requeue_freezes_current_samples(client,auth):
 seed_rows(client,auth['analyst'],n=60)
 from src.config.database import Session
 from src.models.entities import Sample,Family
 with Session() as s:
  for r in s.query(Sample).order_by(Sample.hour).limit(50).all():r.sensor_noise=0.0
  s.commit()
 fam=create_family(client,auth['analyst'],features=['pressure','flow','sensor_noise'])
 run_worker_once()
 assert client.get('/families/'+str(fam['id']),headers={'Authorization':'Bearer '+auth['analyst']}).json()['state']=='failed'
 with Session() as s:
  for i,r in enumerate(s.query(Sample).order_by(Sample.hour).limit(50).all()):r.sensor_noise=0.25+i%3
  s.commit()
 client.post('/families/'+str(fam['id'])+'/requeue',headers={'Authorization':'Bearer '+auth['analyst']})
 run_worker_once()
 got=client.get('/families/'+str(fam['id']),headers={'Authorization':'Bearer '+auth['analyst']}).json()
 assert got['state']=='done'
 with Session() as s:assert s.get(Family,fam['id']).result['members'][0]['scaler_mean'][-1]>0
# requeue after success is refused
 r=client.post('/families/'+str(fam['id'])+'/requeue',headers={'Authorization':'Bearer '+auth['analyst']})
 assert r.status_code==409
