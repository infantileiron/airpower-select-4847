import math,json,hashlib
from datetime import datetime,timedelta
from itertools import combinations
import numpy as np
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import Ridge
from sklearn.model_selection import TimeSeriesSplit
FEATURES=['pressure','flow','temperature','machines','sensor_noise']
def rmse(y,p):return float(np.sqrt(np.mean((np.asarray(y)-np.asarray(p))**2)))
def pipeline(alpha):return Pipeline([('scale',StandardScaler()),('ridge',Ridge(alpha=alpha))])
def choose(rows,features,alphas):
 if not features or len(set(features))!=len(features) or not set(features)<=set(FEATURES):raise ValueError('选择不重复的有效特征')
 if not alphas or any(not math.isfinite(a) or a<=0 for a in alphas):raise ValueError('alpha必须为有限正数')
 rows=sorted(rows,key=lambda r:r['hour']);n=len(rows)
 if n<60:raise ValueError('至少需要60个连续小时样本，保障时间验证窗口')
 hours=[datetime.fromisoformat(r['hour']) for r in rows]
 if len(set(hours))!=n:raise ValueError('小时重复，无法按时间验证')
 if any(b-a!=timedelta(hours=1) for a,b in zip(hours,hours[1:])):raise ValueError('小时不连续，请补齐缺口；不得把缺失耗电当作零')
 x=np.array([[r[f] for f in features] for r in rows],dtype=float);y=np.array([r['kwh'] for r in rows],dtype=float)
 if not np.isfinite(x).all() or not np.isfinite(y).all():raise ValueError('输入含缺失或非有限值')
 cut=int(n*.8);xt,yt=x[:cut],y[:cut];xv,yv=x[cut:],y[cut:]
 if np.any(np.ptp(xt,axis=0)<=1e-12):raise ValueError('训练段存在常量特征，请调整特征方案')
 candidates=[];folds=list(TimeSeriesSplit(n_splits=3).split(xt))
 for alpha in sorted(set(alphas)):
  results=[]
  for tr,va in folds:
   model=pipeline(alpha);model.fit(xt[tr],yt[tr]);pred=model.predict(xt[va])
   results.append(dict(train_start=rows[int(tr[0])]['hour'],train_end=rows[int(tr[-1])]['hour'],validation_start=rows[int(va[0])]['hour'],validation_end=rows[int(va[-1])]['hour'],train_n=len(tr),validation_n=len(va),rmse=rmse(yt[va],pred),scaler_mean=model.named_steps['scale'].mean_.tolist()))
  candidates.append(dict(alpha=alpha,cv_rmse=float(np.mean([r['rmse'] for r in results])),folds=results))
 selected=min(candidates,key=lambda r:(r['cv_rmse'],r['alpha']))
 model=pipeline(selected['alpha']);model.fit(xt,yt);prediction=model.predict(xv);sc=model.named_steps['scale'];ridge=model.named_steps['ridge'];original=ridge.coef_/sc.scale_
 return dict(n=n,train_n=cut,validation_n=n-cut,train_end=rows[cut-1]['hour'],validation_start=rows[cut]['hour'],train_hours=[r['hour'] for r in rows[:cut]],validation_hours=[r['hour'] for r in rows[cut:]],features=features,selected_alpha=selected['alpha'],cv_rmse=selected['cv_rmse'],validation_rmse=rmse(yv,prediction),baseline_rmse=rmse(yv,np.repeat(yt.mean(),len(yv))),candidates=candidates,predictions=[dict(hour=r['hour'],actual=float(a),prediction=float(p),residual=float(a-p)) for r,a,p in zip(rows[cut:],yv,prediction)],coefficients=[dict(feature=f,standardized=float(a),original_unit=float(b)) for f,a,b in zip(features,ridge.coef_,original)],intercept_original=float(ridge.intercept_-np.dot(original,sc.mean_)),scaler_mean=sc.mean_.tolist(),scaler_scale=sc.scale_.tolist(),checksum=hashlib.sha256(json.dumps(rows,sort_keys=True,ensure_ascii=False).encode()).hexdigest(),method='按小时排序，前80%为训练段；训练段内3折扩展窗TimeSeriesSplit，逐折独立fit StandardScaler+Ridge，平均RMSE选alpha；最后20%仅验证选中模型。Ridge目标||y−Xβ||²+α||β||²，截距不惩罚。',warning='标准化系数表示特征增加一个训练标准差时的条件预测变化（kWh）；原单位系数已除以训练标准差。关联不代表节能因果；多次查看末段验证结果后，需另设最终未见时间窗。')

def _family_validate(rows,features,alphas):
 if not features or len(set(features))!=len(features) or not set(features)<=set(FEATURES):raise ValueError('选择不重复的有效特征')
 if not alphas or any(not math.isfinite(a) or a<=0 for a in alphas):raise ValueError('alpha必须为有限正数')
 rows=sorted(rows,key=lambda r:r['hour']);n=len(rows)
 if n<60:raise ValueError('至少需要60个连续小时样本，保障时间验证窗口')
 hours=[datetime.fromisoformat(r['hour']) for r in rows]
 if len(set(hours))!=n:raise ValueError('小时重复，无法按时间验证')
 if any(b-a!=timedelta(hours=1) for a,b in zip(hours,hours[1:])):raise ValueError('小时不连续，请补齐缺口；不得把缺失耗电当作零')
 for r in rows:
  for f in list(features)+['kwh']:
   if r.get(f) is None:raise ValueError('训练样本 '+r['hour']+' 缺少 '+f+'，降级模型族只使用所选特征完整的历史样本')
 y=np.array([r['kwh'] for r in rows],dtype=float)
 if not np.isfinite(y).all():raise ValueError('输入含缺失或非有限值')
 for f in features:
  values=np.array([r[f] for r in rows],dtype=float)
  if not np.isfinite(values).all():raise ValueError('输入含缺失或非有限值')
 return rows,n

def _family_member(rows,subset,alphas,cut,folds):
 x=np.array([[r[f] for f in subset] for r in rows],dtype=float);y=np.array([r['kwh'] for r in rows],dtype=float)
 xt,yt=x[:cut],y[:cut];xv,yv=x[cut:],y[cut:]
 if np.any(np.ptp(xt,axis=0)<=1e-12):raise ValueError('特征组合 '+'+'.join(subset)+' 在训练段为常量，整族不予发布')
 candidates=[]
 for alpha in sorted(set(alphas)):
  results=[]
  for tr,va in folds:
   model=pipeline(alpha);model.fit(xt[tr],yt[tr]);pred=model.predict(xt[va])
   results.append(dict(train_start=rows[int(tr[0])]['hour'],train_end=rows[int(tr[-1])]['hour'],validation_start=rows[int(va[0])]['hour'],validation_end=rows[int(va[-1])]['hour'],train_n=len(tr),validation_n=len(va),rmse=rmse(yt[va],pred),scaler_mean=model.named_steps['scale'].mean_.tolist()))
  candidates.append(dict(alpha=alpha,cv_rmse=float(np.mean([r['rmse'] for r in results])),folds=results))
 selected=min(candidates,key=lambda r:(r['cv_rmse'],r['alpha']))
 model=pipeline(selected['alpha']);model.fit(xt,yt);prediction=model.predict(xv);sc=model.named_steps['scale'];ridge=model.named_steps['ridge'];original=ridge.coef_/sc.scale_
 return dict(key='+'.join(subset),features=list(subset),selected_alpha=selected['alpha'],cv_rmse=selected['cv_rmse'],validation_rmse=rmse(yv,prediction),baseline_rmse=rmse(yv,np.repeat(yt.mean(),len(yv))),candidates=candidates,coefficients=[dict(feature=f,standardized=float(a),original_unit=float(b)) for f,a,b in zip(subset,ridge.coef_,original)],intercept_original=float(ridge.intercept_-np.dot(original,sc.mean_)),scaler_mean=sc.mean_.tolist(),scaler_scale=sc.scale_.tolist())

def train_family(rows,features,alphas):
 rows,n=_family_validate(rows,features,alphas)
 cut=int(n*.8);folds=list(TimeSeriesSplit(n_splits=3).split(np.arange(cut).reshape(-1,1)))
 members=[]
 for size in range(1,len(features)+1):
  for idx in combinations(range(len(features)),size):
   members.append(_family_member(rows,[features[i] for i in idx],alphas,cut,folds))
 ranking=sorted(members,key=lambda m:(m['cv_rmse'],len(m['features']),m['key']))
 for position,member in enumerate(ranking,1):member['rank']=position
 return dict(family_features=list(features),alphas=sorted(set(alphas)),complete=True,member_count=len(members),n=n,train_n=cut,validation_n=n-cut,train_start=rows[0]['hour'],train_end=rows[cut-1]['hour'],validation_start=rows[cut]['hour'],validation_end=rows[-1]['hour'],train_hours=[r['hour'] for r in rows[:cut]],validation_hours=[r['hour'] for r in rows[cut:]],ranking_basis='training_cv_rmse',ranking=[m['key'] for m in ranking],members=members,method='按选定特征枚举全部非空子集；所有子集共用同一条按小时排序的时间窗（前80%训练、后20%末段验证）。训练段内3折扩展窗TimeSeriesSplit，每折只用该折训练部分fit StandardScaler，再fit Ridge；仅以训练内平均CV RMSE排序，末段指标不参与排序和选择。整族成员全部成功才发布。',warning='降级路由按训练内CV RMSE从低到高选择当前可用子集；缺测特征保持缺失，绝不补零。标准化参数只在训练段拟合，未读取末段或未来数据。预测为关联估计，不代表因果或可直接兑现的节能收益。',checksum=hashlib.sha256(json.dumps(rows,sort_keys=True,ensure_ascii=False).encode()).hexdigest())
