import hashlib,json,math
from datetime import datetime
from src.constants.enums import FEATURES

_ALLOWED=set(FEATURES)|{'hour','kwh','note','label'}
_RANGES={'pressure':(0,20,False),'flow':(0,1000,False),'temperature':(-30,100,False),'machines':(0,20,True),'sensor_noise':(-100,100,False),'kwh':(0,10000,False)}
_MAX_ROWS=2000

class BatchRejected(Exception):
 def __init__(self,errors,row_count=None):
  self.errors=errors;self.row_count=row_count
  super().__init__('；'.join(f"第{e['line']}行：{e['message']}" for e in errors))

def _reject_constant(value):raise ValueError('不允许非有限数值')

def _number(value,field):
 if isinstance(value,bool) or not isinstance(value,(int,float)):raise ValueError(field+'必须为数值')
 if not math.isfinite(value):raise ValueError(field+'必须为有限数值')
 low,high,integral=_RANGES[field]
 if value<low or value>high:raise ValueError(f"{field}超出允许范围 {low}~{high}")
 if integral:
  if float(value)!=int(value):raise ValueError(field+'必须为整数')
  return int(value)
 return float(value)

def _hour(value):
 if not isinstance(value,str):raise ValueError('hour必须为字符串')
 try:d=datetime.fromisoformat(value.strip())
 except ValueError:raise ValueError('hour无法解析，请使用工厂本地整点如2026-11-11T00:00')
 if d.tzinfo is not None:raise ValueError('hour不得带时区偏移')
 if d.minute or d.second or d.microsecond:raise ValueError('hour必须为本地整点')
 return d.strftime('%Y-%m-%dT%H:00')

def parse_text(text):
 rows=[];errors=[]
 for lineno,raw in enumerate(text.splitlines(),1):
  if not raw.strip():continue
  if len(rows)>=_MAX_ROWS:raise BatchRejected([{'line':lineno,'message':f'单批最多 {_MAX_ROWS} 条工况记录'}])
  try:obj=json.loads(raw,parse_constant=_reject_constant)
  except Exception as e:errors.append({'line':lineno,'message':'JSON解析失败：'+str(e)});continue
  if not isinstance(obj,dict):errors.append({'line':lineno,'message':'每行必须是一个JSON对象'});continue
  unknown=sorted(set(obj)-_ALLOWED)
  if unknown:errors.append({'line':lineno,'message':'存在未知字段：'+'、'.join(unknown)});continue
  try:
   hour=_hour(obj.get('hour'))
   values={}
   for f in FEATURES:
    if f in obj and obj[f] is not None:values[f]=_number(obj[f],f)
   kwh=None
   if obj.get('kwh') is not None:kwh=_number(obj['kwh'],'kwh')
   label=obj.get('label')
   if label is not None and (not isinstance(label,str) or len(label)>100):raise ValueError('label必须是不超过100字符的字符串')
   note=obj.get('note')
   if note is not None and (not isinstance(note,str) or len(note)>1000):raise ValueError('note必须是不超过1000字符的字符串')
  except ValueError as e:errors.append({'line':lineno,'message':str(e)});continue
  if not values:errors.append({'line':lineno,'message':'该行没有任何可用特征，无法选择非空子集'});continue
  rows.append({'line':lineno,'hour':hour,'features':values,'kwh':kwh,'label':label or '',"note":note or ''})
 if not rows and not errors:raise BatchRejected([{'line':1,'message':'未解析到任何工况记录'}])
 if errors:raise BatchRejected(errors,len(rows))
 seen={}
 for row in rows:
  if row['hour'] in seen:raise BatchRejected([{'line':seen[row['hour']],'message':'批次内小时重复（与第'+str(row['line'])+'行相同），无法逐行路由'},{'line':row['line'],'message':'批次内小时重复（与第'+str(seen[row['hour']])+'行相同），无法逐行路由'}],len(rows))
  seen[row['hour']]=row['line']
 return rows

def batch_key(family_id,family_checksum,rows):
 payload={'family_id':family_id,'family_checksum':family_checksum,'rows':[{'hour':r['hour'],'features':r['features'],'kwh':r['kwh'],'label':r['label'],'note':r['note']} for r in sorted(rows,key=lambda r:r['hour'])]}
 return hashlib.sha256(json.dumps(payload,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()

def route_rows(rows,family_result):
 ranking=sorted(family_result['members'],key=lambda m:m['rank'])
 family_features=list(family_result['family_features'])
 routed=[];errors=[]
 for r in rows:
  present=set(r['features'])
  candidates=[m for m in ranking if set(m['features'])<=present]
  if not candidates:
   errors.append({'line':r['line'],'message':'该行所给特征组合在模型族中无可用子集（缺测特征不得补零）'});continue
  member=candidates[0]
  values=dict(r['features'])
  prediction=float(member['intercept_original'])+sum(float(c['original_unit'])*values[c['feature']] for c in member['coefficients'])
  routed.append({**r,'provided_features':[f for f in FEATURES if f in present],'family_missing_features':[f for f in family_features if f not in present],'unused_features':[f for f in present if f not in family_features],'chosen_features':list(member['features']),'member_key':member['key'],'member_rank':member['rank'],'training_cv_rmse':member['cv_rmse'],'prediction':prediction,'actual':r['kwh'],'residual':None if r['kwh'] is None else float(r['kwh']-prediction)})
 if errors:raise BatchRejected(errors,len(rows))
 return routed
