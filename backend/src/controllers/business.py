from fastapi import HTTPException
from src.models.entities import Run,Family

def ensure_run(s,i):
 row=s.get(Run,i)
 if not row:raise HTTPException(404,'模型版本不存在')
 return row

def ensure_family(s,i):
 row=s.get(Family,i)
 if not row:raise HTTPException(404,'降级模型族不存在')
 return row

def publishable(row):
 if not row:return False
 result=row.result or {}
 return row.state=='done' and bool(result.get('complete')) and isinstance(result.get('members'),list) and bool(result['members'])
