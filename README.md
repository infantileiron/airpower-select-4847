# 铸星 · 空压站耗电模型择优

从连续小时计量中筛选耗电预测特征，以时间验证比较Ridge正则强度，并把解释转成待负责人签核的节能评议。

## 业务场景

铸星制造能源组负责ZX-A01空压站。当前仪表员导出 `ZX-A01_20261101-10_小时计量.xlsx`，工程师在工作簿中试删变量和拟合回归，再用周会文档提出节能动作。三个痛点：随机切分把未来信息带入训练、标准化使用全表、回归系数被误当成可直接兑现的节能收益。

上游是压力/气量/温度/开机台数和电表小时记录；本应用替代时间窗校验、特征配置、模型比选和评议留痕；下游是工艺负责人安排安全可控的试点。

五页分别为耗电样本、特征方案、模型比选、节能评议、降级模型族。核心实体为Sample（小时计量）、Run（特征/alpha配置与冻结模型结果）、Review（观察、业务动作和签核）、Family（降级模型族与全部子集结果）、Batch（冻结的缺测工况批次与逐行路由）；另有User和Audit。

|角色|权限|典型动作|
|---|---|---|
|admin|全部，独占签核和审计|确认安全边界后签核节能评议|
|analyst|样本修订、提交模型、起草评议、导出|比较含/不含无关噪声的特征方案|
|viewer|业务只读及导出|核对模型时间窗；后端拒绝写入与计算|

## 启动与账号

```sh
cp .env.example .env
docker compose config --quiet
docker compose up -d --build
docker compose exec -T backend python -m scripts.seed_demo
```

前端 [localhost:18209](http://localhost:18209)，后端 [localhost:19209/docs](http://localhost:19209/docs)，MySQL映射17709。演示账号 `admin@demo.local`、`analyst@demo.local`、`viewer@demo.local`，密码均 `Demo123!`。演示凭据仅供本地使用，部署时替换DB_PASSWORD/JWT_SECRET。

`SEED_DEMO=true` 启动自动执行一次seed，生成3账号、240小时计量：2026-11-01 00:00至11-10 23:00，固定随机种子3110。按本地小时自然键幂等，重复执行不新增同小时也不覆盖人工修订。

## 一天的业务剧本

1. 08:50 viewer查看ZX-A01过去240小时计量。
2. 09:00 analyst核对 `ZX-A01_20261101-10_小时计量.xlsx` 的小时连续性。
3. 09:10 录入11月11日00:00：压力6.7bar、气量9m³/min、温度22℃、开机4台、噪声0、耗电203kWh。
4. 09:20 对异常电表读数填写记录ID和完整字段修订，并保留计量说明。
5. 09:30 创建“ZX-A01能耗特征复核”，选择气量、压力、温度、开机台数及候选alpha。
6. 09:40 worker计算完成，模型比选页核对末段RMSE、基线、每折时间和系数单位，导出 `airpower-select-<id>.json`。
7. 10:00 analyst起草“空载复核”，写明模型观察、安全边界和保持产量一致的试点动作。
8. 10:10 admin签核后评议冻结；10:20 viewer下载 `airpower-review-<id>.json`。
9. 11:00 传感器检修期间部分工况缺测：analyst在“降级模型族”页选定压力/气量/温度/开机台数，训练全部非空子集；整族成功后导入缺测工况批次，逐行核对选用子集、训练内误差与预测，导出 `airpower-batch-<id>.json`。

## 降级模型族与缺测批次

选定特征后枚举其全部非空子集（4项特征=15个成员），所有成员共用同一按小时排序的时间窗：前floor(0.8N)训练、后20%末段。每折只用该折训练部分fit StandardScaler，再fit Ridge；候选alpha与子集排序只依据训练段内3折平均CV RMSE，末段指标仅展示、从不参与选择或排序，标准化不读取末段/未来数据。整族成员全部训练成功才置为done并可发布；任一子集在训练段常量、样本缺口或非有限值都会令整族failed且不发布任何成员，可在修复样本后重新排队（`POST /families/{id}/requeue`）。同一时间窗、同一过程重复执行结果一致；worker重启恢复queued/running任务时按`state=='queued'`过滤，已完成结果不会被重复发布或改写。

缺测工况按批导入（`POST /families/{id}/batches`，正文`text`每行一个JSON对象，缺失字段直接省略）。解析规则：hour必须为本地整点；只允许FEATURES键加hour/kwh/label/note，未知字段、非数值、非有限值、越界、批次内小时重复均记为该行错误；整批任一坏行即422整批拒绝、不入账。每行按已给特征可覆盖的子集，选择训练内CV RMSE最低者（同分取成员数更少、再按key）；缺测特征保持缺失，绝不补零；没有任何可用子集（例如只给对照噪声）同样整批拒绝。批次内容+父族快照校验生成`batch_key`，`(family_id,batch_key)`唯一；重复导入返回原批次并标记`duplicate=true`，不重复入账、不新增审计。

批次冻结所属模型族id/名称/checksum、族特征与排序、每行原始已给特征、选用子集、排名、训练CV RMSE、预测及实际/残差（未给kwh时为空）。之后修订原始样本、重训或删除族版本都不改变已入账批次。整族失败时不能创建批次或导出。

## 算法与口径

输入为同站点本地连续整点小时记录：压力bar、气量m³/min、温度℃、开机台数、无关对照噪声和目标kWh。小时唯一且不得缺口；至少60小时；训练段所选列不得为常量；所有数值须有限。目标不会进入特征。

按小时排序，前floor(0.8N)为训练段，最后20%为末段验证。训练段内采用3折扩展窗 `TimeSeriesSplit`；每折新建Pipeline，只用该折训练部分fit `StandardScaler`，然后fit `Ridge`。目标函数为 `||y−Xβ||²+alpha||β||²`，截距不惩罚。候选alpha逐折RMSE取平均，最小者入选，同分优先较小alpha。只对选中alpha在完整训练段重拟合，最后20%用于一次末段评估；并比较“训练目标均值”的基线RMSE。

输出包含每折时间范围/样本量/Scaler均值、训练和验证小时、候选CV RMSE、选中alpha、末段实际/预测/残差、训练均值/标准差、系数和checksum。标准化系数表示特征增加一个训练标准差时的条件预测变化（kWh）；原单位系数=标准化系数/训练标准差；原单位截距=模型截距−原单位系数点乘训练均值。系数是关联，不能直接认定因果节能收益。

所有选择使用提交时冻结输入；修订原始计量不会改写旧版本。反复查看末段指标选择特征后，该末段不再是独立最终测试集，实际落地需另设未见时间窗。没有自动控制空压机或在线模型部署。

## 工程说明

Python3.11/FastAPI/SQLAlchemy/scikit-learn/NumPy、原生ES modules/CSS、Nginx、MySQL8、Redis7。恰好五服务frontend/backend/worker/db/redis；全部有健康检查；后端等数据库/Redis，worker还等后端，前端等后端。worker真实消费Redis模型任务，心跳`/tmp/heartbeat`，结果写共享`/artifacts`卷；重启恢复queued/running任务。数据库、Redis和结果均命名卷。

Nginx `/api/`转后端根路由，前端SPA回落。仅前端、后端和数据库映射宿主端口。用 `docker compose down -v --remove-orphans`清理本项目测试数据。

目录：backend/src按models/schemas/services/controllers/routes/middlewares/config/constants/utils分工（降级族训练在services/analysis.py，批次解析与路由在services/degradation.py）；frontend/src按api/stores/types/components/common/hooks/pages/router/utils/constants分工。共用表格、表单、状态标签；表单hooks/HTML转义utils；请求ID和安全头中间件，全局异常处理，写操作审计。首次表结构由ORM创建，migrations提供实测数据库导出的初始DDL（002_degradation.sql为降级族/批次增量），未带在线迁移执行器。

本地开发可先启动db/redis，backend安装requirements并设DATABASE_URL/REDIS_URL/JWT_SECRET后运行 `uvicorn src.main:app --reload`；前端使用Nginx或同源代理。依赖固定在requirements.txt。

变量见.env.example：COMPOSE_PROJECT_NAME、FRONTEND_PORT、BACKEND_PORT、DB_PORT、DB_PASSWORD、JWT_SECRET、SEED_DEMO、NETWORK_SUBNET。独立子网10.253.110.0/24规避当前机器地址池耗尽，迁移可调整。角色ROLES、任务STATES、族FAMILY_STATES、批BATCH_STATES、特征FEATURES和评议REVIEW_STATES分别定义在后端src/constants/enums.py与前端src/constants/enums.js，schema校验在backend/src/schemas/business.py，持久化列见models/entities.py。

## 范围与交付

逐条表单/API录入及完整字段修订，无Excel文件批导（缺测工况通过粘贴JSON行批处理）、删除或分页。固定站点ZX-A01，无自动仪表采集；单worker；评议站内签核，没有外部通知或设备控制。Google Fonts离线时回退serif/sans-serif。后端接口与算法测试在 `backend/tests`（`pip install -r backend/requirements-dev.txt && cd backend && pytest -q tests`，用 fakeredis 代替 Redis）；截图、真实运行结果与已知差异在 `../../test-artifacts/gb-3110/TESTING.md`，源码不放截图或测试报告。MIT License，见LICENSE。
