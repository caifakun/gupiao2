# 竞观 · 私人行情工作台

Vue 3 + Vite + Element Plus / FastAPI / MySQL。只读A股行情、自选竞价/分时与资金分析、美股行业样本看板，不提供买卖下单。

## 当前架构

- frontend/src/components：列表、2/4/6宫格卡片、分组、添加、导入、板块与资金组件；保持原有暗色风格及涨跌颜色。
- frontend/src/composables：行情订阅、可见页报价、全自选快照、筛选、取消与失败退避。
- frontend/src/renderers：沿用经过核对的SVG走势、指标格式化和资金展示；HTML片段由受控渲染函数生成，源文本转义。
- backend/app/api：登录、自选工作台和行情API。原行情路径与业务响应尽量保留，新增登录保护。
- backend/app/providers：上游HTTP、报价、分时、板块、明暗盘适配。
- backend/app/services：资金、龙虎榜与自选业务；core管理安全、配置、缓存和并发。
- backend/migrations：显式MySQL表结构迁移，启动不建表。
- deploy：Ubuntu单机Nginx、systemd和备份模板。

## 先在本机运行（无需数据库或登录）

在项目根目录执行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\start-local.ps1
```

脚本自动选择nvm中已安装的Node 22.12以上22.x版本（不切换全局nvm），构建Vue前端，再通过Python同时提供页面和真实行情API。浏览器打开 http://127.0.0.1:8001；终端保持运行，Ctrl+C停止。8001被占用可在命令末尾加`-Port 8002`，不会停止任何已有进程。首次换端口即换浏览器存储来源，请先导出自选。

- 本机模式不需要.env、数据库建表、账户或登录，不连接MySQL；页面明确标注浏览器存储。
- 自选、分组与布局保存在当前地址的浏览器中，刷新后恢复；不要清理浏览器数据，建议定期导出备份。
- 原地址的旧自选可导出JSON后通过“导入旧自选”导入；不同端口不能自动读取彼此存储。本机新存储使用独立键，不覆盖旧配置。
- 报价、普通分时、资金和板块仍调用真实上游，源失败时明确提示，不填模拟行情；不代表授权实时行情或竞价真实量已接通。
- 本机免登录模式仅允许development环境与回环地址，不可用于公网部署。服务器模式的安全要求保持不变。

首次安装依赖时需Python3.11以上：`python -m venv .venv`，随后执行`.\.venv\Scripts\python.exe -m pip install -r backend/requirements.lock.txt`。前端依赖缺失时脚本自动执行npm ci。

也可手动执行`cd frontend; npm run build`，返回项目根目录运行`.\.venv\Scripts\python.exe server.py --local --port 8001`。如需Vite热更新，将`PUBLIC_ORIGIN`设为`http://127.0.0.1:5173`，并让后端使用Vite代理默认的8000端口（先确认端口空闲）；不要复用仍在运行的旧服务。

## 数据库模式启动（后续服务器接入）

本项目锁定依赖要求Python3.11或以上；本次使用Python3.11.9验证。Node使用22系列（至少22.12）。Windows nvm-windows切换版本会影响共享符号链接，注意其他旧项目。

```powershell
nvm use 22.20.0
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend/requirements.lock.txt
```

将.env.example复制为.env，在本机编辑APP_SECRET、DB_PASSWORD等必要项。生成密钥可执行`python -c "import secrets; print(secrets.token_urlsafe(48))"`。不要提交或公开.env。开发地址统一使用http://127.0.0.1:5173，与PUBLIC_ORIGIN保持一致；COOKIE_SECURE=false仅限本地HTTP开发。

先按docs/deployment.md创建独立数据库和账号，使用迁移账号执行迁移，再使用运行账号创建登录账户。没有MySQL连接时不能保存，系统不会退回localStorage或伪造成功。

```powershell
.\.venv\Scripts\python.exe -m alembic -c backend/alembic.ini upgrade head
.\.venv\Scripts\python.exe -m backend.app.cli database-check
.\.venv\Scripts\python.exe -m backend.app.cli create-user --username yourname
.\.venv\Scripts\python.exe server.py
```

另开终端：

```powershell
cd frontend
npm ci
npm run dev
```

打开http://127.0.0.1:5173。后端8000只提供API，不再提供旧仪表盘。不要直接双击新前端HTML。原8000服务如仍在运行，请先自行正常停止再启动新后端；本次整改不强制终止已有进程。

## 配置保存、导入与安全

- 数据库模式工作台以MySQL为准；本机模式以浏览器存储为准。新增、改名、移组、排序和布局仅在对应存储确认成功后更新；失败不显示成功。
- 保存携带expected_revision；冲突409或网络结果不确定时暂停修改，显式重新加载后再继续，避免自动重试覆盖。
- 自选最多300只，分组最多100个；一只股票属于一个分组，全部自选是汇总入口。focus/watch默认组ID保留，可改名。
- 添加股票按60/68、00/30识别沪深A股，并通过源报价核验名称；不支持北交所、ETF或指数自动识别。
- “导入旧自选”支持原jingguan.workspace.v1和新版JSON备份。先预览后合并，不自动删除本地旧数据。不同来源需先在旧地址导出文件。
- 账户由管理命令创建；密码哈希、HttpOnly会话Cookie、CSRF、来源校验、Host白名单与登录尝试限制。生产必须HTTPS。
- 数据库凭证、APP_SECRET和代理凭证仅在后端私有配置；前端构建不生成Source Map，但压缩不等于源码加密。

## 构建与部署

```powershell
cd frontend
npm run build
```

只公开frontend/dist，不公开仓库根目录、backend、.env、迁移、备份或原始采样。生产部署详见docs/deployment.md。Nginx托管前端并转发/api，Python单进程监听127.0.0.1，MySQL本机连接。无需运行Vite开发服务器或Node常驻服务。

## 数据边界

本次为架构整改，不新增交易功能，不声明授权实时行情或交易所直连。完整竞价虚拟匹配量、未匹配量及方向依然未验证；不会用普通成交量填充。源时间与采集时间分离，缺失不当零，失败保留旧值并标记。美股仍为Nasdaq行业样本等权统计。资金分类不代表实际交易者身份；游资标签仅保留有公开证据的关联。

旧版详细字段、量比、竞价、资金与刷新口径保存在docs/legacy-data-notes.md。该文档的旧启动方式和本机存储描述属于历史记录，以本README和部署文档为准。auction_probe.py继续作为独立未核验采样工具，不会改变网页行情。

## 验证边界

本机模式已验证：前端生产构建、浏览器直接进入、真实代码核验与报价、自选刷新恢复、2/4/6宫格、普通分时指标、资金详情、A股与美股板块，以及390px窄屏无横向页面溢出。该流程未请求登录或服务端工作台接口；本机模式数据库入口明确拒绝访问。修复了模块拆分时遗漏的资金字段常量、暗盘采集依赖与暗盘展示时钟依赖。不代表所有股票、网络环境或交易时段都已验收。

生产数据库密码、域名与证书由你在服务器配置。本地构建或隔离数据库验证，不代表已经连接你的MySQL 5.7服务器；上线仍需按部署清单验收。应用启动不自动修改数据库结构，也不自动升级Node、MySQL、Nginx。
