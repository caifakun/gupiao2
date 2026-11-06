# Ubuntu 22.04 单机部署

本文只提供操作步骤，不会自动连接服务器、创建数据库或修改现有Nginx/MySQL。示例域名stocks.example.com、数据库名和密码必须自行核对替换。上线前备份现有数据库与Nginx配置，确认8000端口未被其他业务占用。

## 结构与运行环境

- Nginx仅提供`/opt/gupiao/frontend/dist`，通过`/api/`转发到本机Python。不要将项目根目录设为网站目录。
- Python使用独立虚拟环境，当前锁定依赖要求3.11或以上。Ubuntu 22.04默认Python3.10不能直接使用此锁文件；先配置独立的3.11或以上解释器，不替换系统Python。
- 前端使用Node 22（至少22.12），仓库记录的初始验证版本为22.20.0；通过nvm管理，正式构建前核查该系列安全补丁。生产服务器只托管静态文件时无需常驻Node进程。
- MySQL迁移面向5.7语法，采用InnoDB、utf8mb4_unicode_ci；不使用MySQL 8专属排序规则、生成UUID默认表达式或CHECK约束。实际5.7实例仍需部署时验收。
- MySQL 5.7已停止常规维护，升级需另行评估和备份。本次不自动升级现有MySQL或Nginx。

## 1. 独立目录与依赖

创建专用非登录系统用户gupiao，将项目发布到`/opt/gupiao`。代码由发布账号/root管理，运行账号只需读取；不得给运行账号写入代码的权限。确认目录上级允许Nginx读取dist，但不向Nginx授予私有配置读取权限。

```bash
cd /opt/gupiao
python3.11 -m venv .venv
.venv/bin/python -m pip install -r backend/requirements.lock.txt
cd frontend
npm ci
npm run build
```

也可在开发机器构建后仅上传frontend/dist，避免在服务器安装Node。不要执行`npm run dev -- --host 0.0.0.0`作为生产部署。

## 2. 手动创建数据库与最小权限账号

由数据库管理员在MySQL交互客户端执行，所有密码通过安全流程设置，不要使用示例文字作为真实密码。

```sql
CREATE DATABASE gupiao CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'gupiao_app'@'127.0.0.1' IDENTIFIED BY 'REPLACE_APP_PASSWORD';
GRANT SELECT, INSERT, UPDATE, DELETE ON gupiao.* TO 'gupiao_app'@'127.0.0.1';
CREATE USER 'gupiao_migrator'@'127.0.0.1' IDENTIFIED BY 'REPLACE_MIGRATION_PASSWORD';
GRANT SELECT, INSERT, UPDATE, DELETE, CREATE, ALTER, DROP, INDEX, REFERENCES ON gupiao.* TO 'gupiao_migrator'@'127.0.0.1';
```

运行账号不授予DDL、FILE、SUPER、GRANT OPTION或全库权限。迁移账号只在维护时使用。不要修改其他项目的账号权限；是否收紧MySQL监听地址需先排查其他业务，不能直接覆盖全局配置。

## 3. 私有环境配置

将deploy/gupiao.env.example复制到`/etc/gupiao/gupiao.env`，编辑所有空白密钥和域名。目录建议root:gupiao、0750，文件root:gupiao、0640。APP_SECRET至少32字符，可用下列命令生成；不要提交真实配置、上传到网站或发到聊天中。

```bash
python3.11 -c 'import secrets; print(secrets.token_urlsafe(48))'
```

PUBLIC_ORIGIN必须与浏览器实际访问来源完全一致，例如https://stocks.example.com，不含结尾斜杠、路径。ALLOWED_HOSTS只填主机名。生产环境COOKIE_SECURE=true，登录仅通过HTTPS。

MARKET_PROXY是服务器访问数据源的可选HTTP/HTTPS代理；不能填开发电脑的127.0.0.1地址，除非代理确实运行在服务器本机。前端VITE_*变量中不得放密钥。

## 4. 显式迁移和创建账户

使用独立迁移环境文件，例如`/etc/gupiao/migrate.env`，其中仅DB_USER/DB_PASSWORD替换为迁移账号，其他安全配置保持有效。保护权限并在维护结束后限制访问。

```bash
cd /opt/gupiao
GUPIAO_ENV_FILE=/etc/gupiao/migrate.env .venv/bin/python -m alembic -c backend/alembic.ini upgrade head
GUPIAO_ENV_FILE=/etc/gupiao/gupiao.env .venv/bin/python -m backend.app.cli database-check
GUPIAO_ENV_FILE=/etc/gupiao/gupiao.env .venv/bin/python -m backend.app.cli create-user --username yourname
```

创建账户会交互询问密码，不通过命令参数传递。密码须12至128字符。没有默认账户、默认密码或公共注册。重置密码命令为`reset-password --username yourname`，会撤销该账户旧会话。

应用启动不自动建表/迁移。MySQL DDL可能隐式提交，不能依赖事务撤销失败的结构变更；迁移前备份并核对目标库。downgrade会删除本应用数据表，不可当作日常回滚命令。

## 5. systemd与Nginx

核对deploy/gupiao.service中的目录、用户和端口后安装为`/etc/systemd/system/gupiao.service`，随后执行：

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now gupiao
sudo systemctl status gupiao
sudo journalctl -u gupiao -n 80 --no-pager
```

单进程启动，缓存/采集状态在进程内共享；不要直接增加workers以免重复采集。进程健康接口不证明数据库或行情正常。

使用你自己的域名和已签发证书替换deploy/nginx.conf.example中的示例。先确认已有Nginx站点的组织方式，新增独立站点，不覆盖主配置或其他站点。检查成功后再reload：

```bash
sudo nginx -t
sudo systemctl reload nginx
```

Nginx中的Host必须保留公网域名，不能改成127.0.0.1。后端只信任127.0.0.1代理提供的转发头。防火墙不因本项目额外开放8000或3306；SSH规则需保留，勿执行未经核对的全局防火墙重置。

## 6. 备份与恢复验收

使用只读备份账号，按实际表和mysqldump需求授予最小权限，将deploy/mysql-backup.cnf.example复制为`/etc/gupiao/mysql-backup.cnf`并填入真实凭证，权限0600。调用`bash /opt/gupiao/deploy/backup.sh`生成一致性转储。备份脚本不会自动删除旧文件，需自行监控空间和制定保留策略。

备份目录不得位于dist，至少同步一份到另一台设备或受保护存储。定期恢复到独立验收数据库检查数据；不要首次演练就覆盖正式库。数据库备份包含账户哈希和会话哈希，同样属于敏感数据。

## 7. 旧自选迁移与上线验收

- 在旧浏览器来源（同协议、主机、端口）导出旧自选。根index.html已改为迁移说明与导出入口；它只读取原localStorage，不自动删除。
- 新地址登录后点“导入旧自选”，查看新增、重复、无效项，再明确确认合并。原有服务端记录优先，不自动替换默认分组名称。
- 验证两设备加载同一份自选；同时编辑时其中一份应收到409并重新加载，不能悄悄覆盖。
- 验证登出后行情和自选API不可匿名访问；.env、server.py、数据库备份、Source Map不可访问。
- 验证普通分时、列表、2/4/6宫格、行业筛选、板块、资金和龙虎榜；实际竞价时段另行验收。旧值、缺失、历史和源时间提示应保留。
- 数据源网络与开发电脑不同，应在服务器验证东方财富/Nasdaq可达性、限流与日期。不能把部署成功当作实时行情已授权或完整竞价量已接通。

## 更新与回退

更新前导出自选并备份数据库，单独保存上一版发布文件和环境配置。安装锁定依赖、检查迁移内容、构建dist后再重启API和检查Nginx。凭证始终在发布目录之外。应用代码回退不等于数据库可降级，结构变更需要独立评估。
