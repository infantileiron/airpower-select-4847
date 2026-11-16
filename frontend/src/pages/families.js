import {state} from '../stores/session.js';import {esc} from '../utils/html.js';import {badge} from '../components/common/status.js';import {table} from '../components/common/table.js';import {field} from '../components/common/fields.js';import {FEATURES} from '../constants/enums.js';
const fmt=x=>typeof x==='number'?x.toFixed(3):'—';
const SHORT={pressure:'压力',flow:'气量',temperature:'温度',machines:'台数',sensor_noise:'噪声'};
const shortLabel=keys=>keys.map(k=>SHORT[k]||k).join('+')||'—';
const when=x=>x?String(x).replace('T',' ').slice(0,16):'—';
function familyPanel(f){
 if(!f)return '<p class="notice">先在右侧创建降级模型族。整族全部子集训练成功后才可用于缺测工况估算。</p>';
 const r=f.result||{};
 let body='';
 if(f.state==='done'&&r.members){
  const ranked=[...r.members].sort((a,b)=>a.rank-b.rank);
  body=`<p class="eyebrow">族特征 ${r.family_features.map(k=>FEATURES[k]).join(' / ')} · 成员 ${r.member_count} 个 · 窗口 ${esc(r.train_start)} → ${esc(r.validation_end)}</p><div class="metrics"><div><strong>${r.member_count}</strong>全部非空子集</div><div><strong>${r.train_n}</strong>共用训练小时</div><div><strong>${r.validation_n}</strong>末段小时</div></div><h3>训练内误差排序 / CV RMSE</h3>${table(['排名','特征子集','α','训练内CV RMSE','末段RMSE'],ranked.map(m=>[m.rank,shortLabel(m.features),m.selected_alpha,fmt(m.cv_rmse),fmt(m.validation_rmse)]))}<p class="notice">排序只依据训练段内3折扩展窗平均RMSE；末段指标仅展示，不参与选择。同一时间窗、每折独立拟合标准化。</p><p class="notice">${esc(r.warning||'')}</p><button id="family-download">下载模型族 JSON</button>`;
 }else if(f.state==='failed'){
  body=`<p class="notice">整族训练失败，未发布任何成员：${esc(f.error||'未知错误')}</p>${state.user.role!=='viewer'?'<button id="family-requeue">重新排队（修复样本后）</button>':''}`;
 }else{
  body='<p class="notice">后台正在训练全部子集，稍后刷新状态。</p>';
 }
 return `<div class="result-head"><h2>#${f.id} ${esc(f.name)} ${badge(f.state)}</h2><button id="family-refresh">刷新状态</button></div>${body}`;
}
function batchPanel(f){
 if(!f||f.state!=='done')return '';
 const list=state.batches;
 return `<h3>已冻结批次</h3>${list.map(b=>`<button class="study ${state.selectedBatch?.id===b.id?'chosen':''}" data-batch="${b.id}">#${b.id} ${esc(b.created||'')} · ${b.result?.row_count??'—'}行 · ${esc(when(b.created))}</button>`).join('')||'<p>尚无批次。导入的整批成功记录会冻结所属模型族、选用特征和预测。</p>'}${batchDetail()}`;
}
function batchDetail(){
 const b=state.selectedBatch;
 if(!b)return '';
 const r=b.result||{};
 return `<h3>批次 #${b.id} 逐行路由 <button id="batch-download">导出批次</button></h3><p class="eyebrow">冻结模型族 #${r.family_id} ${esc(r.family_name||'')} · 族快照校验 ${esc((r.family_checksum||'').slice(0,12))} · ${r.row_count} 行</p>${table(['行','本地小时','已给特征','缺测特征','选用子集','排名','训练CV','预测kWh','实际kWh','残差'],(r.rows||[]).map(x=>[x.line,x.hour,shortLabel(x.provided_features),shortLabel(x.family_missing_features),shortLabel(x.chosen_features),x.member_rank,fmt(x.training_cv_rmse),fmt(x.prediction),x.actual==null?'—':fmt(x.actual),x.residual==null?'—':fmt(x.residual)]),'routing')}<p class="notice">每行在已给特征能覆盖的子集中选择训练内误差最低者；缺测特征保持缺失，绝不补零。批次一旦入账即冻结，重复导入同一内容不会重复入账。</p>`;
}
export function render(){
 const f=state.selectedFamily;
 return `<div class="split"><section class="panel">${familyPanel(f)}<h3>模型族版本</h3>${state.families.map(x=>`<button class="study ${f?.id===x.id?'chosen':''}" data-family="${x.id}">#${x.id} ${esc(x.name)} · ${x.features.length}特征 · ${esc(x.state)}</button>`).join('')||'<p>暂无降级模型族。</p>'}${batchPanel(f)}</section><aside class="side"><h2>创建降级模型族</h2><form id="family">${field('版本名称','name','text','required value="ZX-A01缺测降级族"')}<fieldset><legend>选定特征（枚举全部非空子集）</legend>${Object.entries(FEATURES).map(([k,v])=>`<label class="check"><input type="checkbox" name="features" value="${k}" ${k==='sensor_noise'?'':'checked'}>${v}</label>`).join('')}</fieldset>${field('alpha候选（英文逗号）','alphas','text','required value="0.1,1,10"')}<button class="primary">训练整族</button></form><h2>导入缺测工况</h2><form id="batch">${field('批次父族ID','family_id','number',`required min=1 value="${f?.id??''}"`)}<label>工况记录（每行一个JSON，缺失字段直接省略，不填0）<textarea name="text" rows="9" required placeholder='{"hour":"2026-11-11T00:00","pressure":6.7,"flow":9,"machines":4}
{"hour":"2026-11-11T01:00","flow":9.2,"label":"仅气量"}'></textarea></label><p class="notice">坏行、未知字段或无可用子集会整批拒绝，不入账。同一内容重复导入返回原批次，不重复入账。</p><button class="primary">解析并路由整批</button></form></aside></div>`;
}
