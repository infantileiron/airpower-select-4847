import os,json
import redis
from datetime import datetime,timezone
from fastapi import APIRouter,Depends,HTTPException,Response
from sqlalchemy.exc import IntegrityError
from src.config.database import db
from src.models.entities import User,Sample,Run,Review,Audit,Family,Batch
from src.schemas.business import Login,SampleInput,RunInput,ReviewInput,FamilyInput,BatchInput
from src.middlewares.auth import current,editor,admin
from src.utils.security import verify,token
from src.services.business import audit,dump
from src.services.degradation import BatchRejected,parse_text,batch_key,route_rows
from src.controllers.business import ensure_run,ensure_family,publishable
router=APIRouter()
@router.post('/auth/login')
def login(data:Login,s=Depends(db)):
 u=s.query(User).filter_by(email=data.email).first()
 if not u or not verify(data.password,u.password):raise HTTPException(401,'账号或密码错误')
 return {'token':token(u),'user':dump(u)}
@router.get('/me')
def me(u=Depends(current)):return dump(u)
@router.get('/samples')
def samples(u=Depends(current),s=Depends(db)):return [dump(r) for r in s.query(Sample).order_by(Sample.hour).all()]
@router.post('/samples')
def create(data:SampleInput,u=Depends(editor),s=Depends(db)):
 r=Sample(**data.model_dump());s.add(r)
 try:s.commit()
 except IntegrityError:s.rollback();raise HTTPException(409,'该小时已存在，请使用修订功能')
 audit(s,u,'录入小时 '+r.hour);return dump(r)
@router.put('/samples/{i}')
def edit(i:int,data:SampleInput,u=Depends(editor),s=Depends(db)):
 r=s.get(Sample,i)
 if not r:raise HTTPException(404,'小时样本不存在')
 for k,v in data.model_dump().items():setattr(r,k,v)
 try:s.commit()
 except IntegrityError:s.rollback();raise HTTPException(409,'小时重复')
 audit(s,u,'修订样本 '+str(i));return dump(r)
@router.get('/runs')
def runs(u=Depends(current),s=Depends(db)):return [dump(r) for r in s.query(Run).order_by(Run.id.desc()).all()]
@router.post('/runs')
def train(data:RunInput,u=Depends(editor),s=Depends(db)):
 rows=[dump(r) for r in s.query(Sample).order_by(Sample.hour).all()];r=Run(**data.model_dump(),result={'snapshot':rows});s.add(r);s.commit()
 try:redis.Redis.from_url(os.environ['REDIS_URL']).rpush('airpower:runs',r.id)
 except redis.RedisError:r.state='failed';r.error='队列暂不可用，请稍后重试';s.commit();raise HTTPException(503,r.error)
 audit(s,u,'提交模型 '+str(r.id));return dump(r)
@router.get('/runs/{i}')
def detail(i:int,u=Depends(current),s=Depends(db)):return dump(ensure_run(s,i))
@router.get('/runs/{i}/export')
def export(i:int,u=Depends(current),s=Depends(db)):
 r=ensure_run(s,i)
 if r.state!='done':raise HTTPException(409,'仅成功版本可导出')
 return Response(json.dumps(dump(r),ensure_ascii=False,indent=2),media_type='application/json',headers={'Content-Disposition':f'attachment; filename="airpower-select-{i}.json"'})
@router.get('/reviews')
def reviews(u=Depends(current),s=Depends(db)):return [dump(r) for r in s.query(Review).order_by(Review.id.desc()).all()]
@router.post('/reviews')
def review(data:ReviewInput,u=Depends(editor),s=Depends(db)):
 if ensure_run(s,data.run_id).state!='done':raise HTTPException(409,'模型计算完成后才能起草评议')
 r=Review(**data.model_dump());s.add(r);s.commit();audit(s,u,'起草节能评议 '+str(r.id));return dump(r)
@router.put('/reviews/{i}')
def edit_review(i:int,data:ReviewInput,u=Depends(editor),s=Depends(db)):
 r=s.get(Review,i)
 if not r:raise HTTPException(404,'评议不存在')
 if r.status!='draft':raise HTTPException(409,'已签核评议冻结，请新建')
 if ensure_run(s,data.run_id).state!='done':raise HTTPException(409,'需要已成功模型')
 for k,v in data.model_dump().items():setattr(r,k,v)
 s.commit();audit(s,u,'修订评议 '+str(i));return dump(r)
@router.post('/reviews/{i}/approve')
def approve(i:int,u=Depends(admin),s=Depends(db)):
 r=s.get(Review,i)
 if not r:raise HTTPException(404,'评议不存在')
 if r.status!='draft':raise HTTPException(409,'已签核评议不能重复签核')
 r.status='approved';s.commit();audit(s,u,'签核节能评议 '+str(i));return dump(r)
@router.get('/reviews/{i}/export')
def export_review(i:int,u=Depends(current),s=Depends(db)):
 r=s.get(Review,i)
 if not r:raise HTTPException(404,'评议不存在')
 return Response(json.dumps(dump(r),ensure_ascii=False,indent=2),media_type='application/json',headers={'Content-Disposition':f'attachment; filename="airpower-review-{i}.json"'})
@router.get('/audits')
def audits(u=Depends(admin),s=Depends(db)):return [dump(r) for r in s.query(Audit).order_by(Audit.id.desc()).limit(100)]
def _family_view(row,mode='list'):
 data=dump(row);result=data.get('result') or {}
 if row.state!='done' or not result.get('members'):
  data['result']={'complete':bool(result.get('complete')),'family_features':result.get('family_features'),'alphas':result.get('alphas')} if result else None
  return data
 base={k:v for k,v in result.items() if k not in ('snapshot','members','train_hours','validation_hours')}
 members=[]
 for m in result['members']:
  if mode=='list':members.append({k:m.get(k) for k in ('key','features','rank','cv_rmse','validation_rmse','selected_alpha')})
  elif mode=='detail':members.append({k:v for k,v in m.items() if k!='candidates'})
  else:members.append(dict(m))
 base['members']=members
 data['result']=base
 return data

def _batch_view(row,full=True):
 data=dump(row)
 if not full and data.get('rows'):
  data['rows']=None
  if data.get('result'):data['result']={**data['result'],'rows':None}
 return data

@router.get('/families')
def families(u=Depends(current),s=Depends(db)):return [_family_view(r,'list') for r in s.query(Family).order_by(Family.id.desc()).all()]

@router.post('/families')
def create_family(data:FamilyInput,u=Depends(editor),s=Depends(db)):
 rows=[dump(r) for r in s.query(Sample).order_by(Sample.hour).all()]
 r=Family(name=data.name,features=data.features,alphas=sorted(set(data.alphas)),result={'snapshot':rows},created=datetime.now(timezone.utc).isoformat());s.add(r);s.commit()
 try:redis.Redis.from_url(os.environ['REDIS_URL']).rpush('airpower:runs',json.dumps({'type':'family','id':r.id}))
 except redis.RedisError:r.state='failed';r.error='队列暂不可用，请稍后重试';s.commit();raise HTTPException(503,r.error)
 audit(s,u,'创建降级模型族 '+str(r.id));return _family_view(r,'detail')

@router.get('/families/{i}')
def family_detail(i:int,u=Depends(current),s=Depends(db)):return _family_view(ensure_family(s,i),'detail')

@router.post('/families/{i}/requeue')
def requeue_family(i:int,u=Depends(editor),s=Depends(db)):
 row=ensure_family(s,i)
 if row.state not in ('failed',):raise HTTPException(409,'仅失败的模型族可重新排队')
 rows=[dump(r) for r in s.query(Sample).order_by(Sample.hour).all()]
 row.result={'snapshot':rows};row.state='queued';row.error='';s.commit()
 try:redis.Redis.from_url(os.environ['REDIS_URL']).rpush('airpower:runs',json.dumps({'type':'family','id':row.id}))
 except redis.RedisError:row.state='failed';row.error='队列暂不可用，请稍后重试';s.commit();raise HTTPException(503,row.error)
 audit(s,u,'重排降级模型族 '+str(row.id)+'（按当前样本重新冻结输入）');return _family_view(row,'detail')

@router.get('/families/{i}/export')
def export_family(i:int,u=Depends(current),s=Depends(db)):
 row=ensure_family(s,i)
 if not publishable(row):raise HTTPException(409,'整族未全部成功，不能发布或导出')
 data=_family_view(row,'full')
 return Response(json.dumps(data,ensure_ascii=False,indent=2),media_type='application/json',headers={'Content-Disposition':f'attachment; filename="airpower-family-{i}.json"'})

@router.post('/families/{i}/batches')
def create_batch(i:int,data:BatchInput,u=Depends(editor),s=Depends(db)):
 family=ensure_family(s,i)
 if not publishable(family):raise HTTPException(409,'降级模型族未全部成功，暂不可用于缺测工况估算')
 try:rows=parse_text(data.text)
 except BatchRejected as e:raise HTTPException(422,{'message':'整批拒绝：存在无法解析的工况记录','errors':e.errors})
 try:routed=route_rows(rows,family.result)
 except BatchRejected as e:raise HTTPException(422,{'message':'整批拒绝：存在无可用子集或非法工况行','errors':e.errors})
 key=batch_key(family.id,family.result.get('checksum',''),rows)
 existing=s.query(Batch).filter_by(family_id=family.id,batch_key=key).first()
 if existing:return {**_batch_view(existing),'duplicate':True}
 result={'family_id':family.id,'family_name':family.name,'family_checksum':family.result.get('checksum',''),'family_features':family.result.get('family_features',[]),'ranking':family.result.get('ranking',[]),'row_count':len(routed),'rows':routed}
 row=Batch(family_id=family.id,batch_key=key,state='done',rows=rows,result=result,created=datetime.now(timezone.utc).isoformat());s.add(row)
 try:s.commit()
 except IntegrityError:
  s.rollback();existing=s.query(Batch).filter_by(family_id=family.id,batch_key=key).first()
  if existing:return {**_batch_view(existing),'duplicate':True}
  raise HTTPException(409,'批次写入冲突，请重试')
 audit(s,u,'导入缺测工况批次 '+str(row.id)+'（模型族 '+str(family.id)+'，'+str(len(routed))+'行）')
 return {**_batch_view(row),'duplicate':False}

@router.get('/families/{i}/batches')
def family_batches(i:int,u=Depends(current),s=Depends(db)):
 ensure_family(s,i);return [_batch_view(r,False) for r in s.query(Batch).filter_by(family_id=i).order_by(Batch.id.desc()).all()]

@router.get('/batches/{i}')
def batch_detail(i:int,u=Depends(current),s=Depends(db)):
 row=s.get(Batch,i)
 if not row:raise HTTPException(404,'缺测工况批次不存在')
 return _batch_view(row)

@router.get('/batches/{i}/export')
def export_batch(i:int,u=Depends(current),s=Depends(db)):
 row=s.get(Batch,i)
 if not row:raise HTTPException(404,'缺测工况批次不存在')
 data=_batch_view(row)
 return Response(json.dumps(data,ensure_ascii=False,indent=2),media_type='application/json',headers={'Content-Disposition':f'attachment; filename="airpower-batch-{i}.json"'})
