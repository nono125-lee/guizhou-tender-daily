# 标讯系统位置与运维交接

## 系统组成

这套系统由六部分组成：

1. 本地Skill：让Codex知道何时、按什么规则执行标讯任务。
2. 本地Agent代码：负责导入、筛选、去重、采集和生成网页数据。
3. macOS `launchd`：每天在本机更新图文广告，并运行统一施工机会工作流后提交发布。
4. GitHub Actions：只部署仓库中已有的 `site/`，不发起采集。
5. GitHub Pages：提供手机和电脑可打开的最新标讯页面。
6. 统一标讯雷达编排层：一次运行施工粗筛、招标计划、超长期识别与关联、测试和发布，并生成单页工作台。

## 本地位置

项目根目录：

`/Users/nonolee/Documents/标讯`

| 内容 | 位置 | 说明 |
|---|---|---|
| Agent主代码 | `src/tender_agent/` | 导入、筛选、去重、网页数据生成 |
| 独立网站采集器 | `src/tender_agent/collectors/` | 每个网站按结构单独适配 |
| Skill源文件 | `skills/tender-intelligence/` | 项目内可版本管理 |
| Codex已安装Skill | `/Users/nonolee/.codex/skills/tender-intelligence` | 指向项目Skill目录的软链接 |
| 区域配置 | `config/regions.json` | 当前为贵州省 |
| 图文广告关键词配置 | `config/industries/graphic-advertising.json` | 自动采集实际使用的关键词 |
| 施工资质关键词配置 | `config/industries/construction.json` | 只在资格类栏目匹配 |
| 图文广告信息源配置 | `config/graphic_sources.json` | 十一个图文广告配置来源 |
| 施工信息源配置 | `config/construction_sources.json` | 十三个施工配置来源 |
| 信息源正式名称映射 | `config/source_names.json` | 网页展示名称 |
| 人工核实公告 | `config/verified_notices.json` | 暂无采集器时的临时补录 |
| 已确认误报排除清单 | `config/excluded_notices.json` | 每次更新时强制排除 |
| 人工反馈规则 | `config/feedback_rules.json` | 保存确认、排除原因和字段纠正 |
| 私密信息源数据库 | `data/private/tenders.sqlite3` | 含账号资料，不上传GitHub |
| 公开网页文件 | `site/` | 发布到GitHub Pages |
| 施工独立网页 | `site/construction/` | 与图文广告数据和反馈状态隔离 |
| 统一标讯雷达网页 | `site/opportunities/` | 重点关联、施工粗筛、全部招标计划和运行状态 |
| 招标计划详细网页 | `site/tender-plan/` | AP1 招标计划、资金来源和历史版本 |
| 统一编排模块 | `src/tender_agent/unified_site.py` | 一次运行、测试门禁和发布 |
| 统一入口 Skill | `skills/guizhou-construction-opportunity-intelligence/` | 日常默认入口 |
| 招标计划内部 Skill | `skills/tender-plan-intelligence/` | 计划采集器、缓存和关联算法 |
| 施工增量采集状态 | `site/construction/data/collector-state.json` | 各来源游标、公告ID、失败重试和项目编码 |
| 最新公开数据 | `site/data/latest.json` | 网页读取的数据 |
| 施工最新公开数据 | `site/construction/data/latest.json` | 施工网页读取的数据 |
| 施工粗筛共享副本 | `/Users/nonolee/Desktop/共享win/标讯/施工粗筛/` | 每次施工粗筛后覆盖更新，仅包含公开页面与 `latest.json` |
| 本机自动采集任务 | `/Users/nonolee/Library/LaunchAgents/com.nono.tender-daily.plist` | 本地时间每天15:03运行 |
| 本机采集日志 | `/Users/nonolee/.local/logs/tender-collect-YYYYMMDD.log` | 记录采集、提交和发布结果 |
| GitHub部署任务 | `.github/workflows/daily-pages.yml` | 北京时间每天7:15兜底部署 |
| 测试 | `tests/` | 采集器和数据处理测试 |

## 原始资料位置

以下文件是用户维护的原始资料，已归档到项目私密目录：

| 内容 | 绝对路径 |
|---|---|
| 信息源库 | `/Users/nonolee/Documents/标讯/data/private/original_inputs/01信息源库.xlsx` |
| 图文广告原始关键词库 | `/Users/nonolee/Documents/标讯/data/private/original_inputs/02图文广告行业关键词库.txt` |
| 历史标讯信息表 | `/Users/nonolee/Documents/标讯/data/private/original_inputs/03标讯信息表.xlsx` |

原始附件不会提交到GitHub。信息源库导入私密数据库；关键词库导入后形成
`config/industries/graphic-advertising.json`；历史标讯表导入私密数据库用于历史数据和去重。

原始资料在2026-06-09的盘点结果：

- 信息源账号记录：171条
- 不同信息源网址：108个
- 历史标讯记录：431条

当前代码共有12个独立采集器模块，覆盖图文广告和施工两个板块。

## 已开发采集器

| 网站或板块 | 采集器 |
|---|---|
| 贵州省招标投标公共服务平台 | `src/tender_agent/collectors/guizhou_ztb.py` |
| 贵州省招标投标公共服务平台（施工） | `src/tender_agent/collectors/ztb_construction.py` |
| 黔云招采主板块、子板块及云农商（图文广告） | `src/tender_agent/collectors/eqyzc.py` |
| 黔云招采主板块、子板块及云农商（施工） | `src/tender_agent/collectors/eqyzc_construction.py` |
| 遵义市公共交通（集团）有限责任公司 | `src/tender_agent/collectors/zunyi_bus.py` |
| 贵阳市公共资源交易国有企业招标采购平台 | `src/tender_agent/collectors/ygzc.py` |
| 中烟电子采购平台 | `src/tender_agent/collectors/tobacco.py` |
| 中国南方电网供应链统一服务平台 | `src/tender_agent/collectors/csg.py` |
| 贵州省公共资源交易云（图文广告） | `src/tender_agent/collectors/ggzy_graphic.py` |
| 贵州省公共资源交易云（施工） | `src/tender_agent/collectors/ggzy_construction.py` |
| “黔顺云采”集采平台 | `src/tender_agent/collectors/asgq.py` |
| 军队采购网 | `src/tender_agent/collectors/plap.py` |

信息源库中的其他网站只是“待开发来源”，不会因为存在于Excel或数据库中就自动完成查询。

## 新增来源开发SOP

新增网站采集器时，按“先确认结构，再固化规则，再测试上线”的顺序执行。
Scrapling 的方法可作为调研参考，但不直接替代本项目的业务筛选规则。

### 1. 来源初查

1. 打开网站首页、公告列表页和一条详情页，确认是否公开访问。
2. 记录网站正式名称，并同步 `config/source_names.json`。
3. 判断是否需要登录、验证码、短信、人脸、协议确认或组织账号授权。
4. 如果出现验证或协议确认，停止自动化，记录为需要人工处理。

### 2. 抓取路径选择

按以下顺序选择抓取方式：

1. 公开 JSON/API：优先使用，稳定后写入独立采集器。
2. 静态 HTML：页面直接包含列表和详情正文时使用。
3. 动态浏览器调研：静态层没有数据时，用浏览器观察页面行为和 XHR/fetch。
4. 反爬或强保护页面：只在公开来源、合规且用户授权的前提下实验；不得绕过
   验证码、短信、人脸或协议确认。

对 SPA 网站，要先通过正常页面访问确认真实接口，包括分页参数、详情 ID、
请求 headers、返回字段、发布时间和公告类型，再把接口调用固化到采集器。

### 3. 样本与缓存

- 调试阶段保存少量列表页、详情页或接口响应样本，作为单元测试 fixture。
- 修改解析规则时优先用样本回归测试，避免反复高频请求源站。
- 样本不得包含账号、密码、联系人电话、cookie、token 或其他私密信息。
- Scrapling 的 development cache 思路只用于开发调试，不进入每日更新主流程。

### 4. 选择器与字段容错

采集器不能只依赖单一 CSS 选择器或单一正则。页面字段应尽量结合以下特征：

- 标题文本。
- 详情链接或公告 ID。
- 发布时间。
- 父级容器和栏目区域。
- 明确字段标签，如“项目名称”“采购人”“采购代理机构”“投标截止时间”。
- “招标内容”“采购内容”“招标范围”“采购范围”“项目概况”等允许栏目。

即使使用类似 Scrapling adaptive scraping 的思路，也只能用于定位页面元素，
不能放宽项目收录规则。采购人、代理机构、资格要求和公告其他正文中的关键词
仍然不得计入图文广告匹配。

### 5. AI输入清洗

如果把网页片段交给 AI 辅助分析，先清理：

- `script`、`style`、模板、注释。
- `display:none`、`aria-hidden`、隐藏表单和不可见文本。
- 导航、页脚、推荐阅读、分享按钮、统计脚本。

清洗后的内容只用于辅助判断，最终字段仍以采集器规则和单元测试为准。

### 6. 采集器上线标准

每个新来源上线前至少完成：

1. 新增独立采集器文件，不和其他网站混写。
2. 接入图文广告或施工对应入口，不跨行业复用规则。
3. 独立状态文件或来源状态，支持已处理跳过和失败重试。
4. 单元测试覆盖列表解析、详情字段、关键词边界、区域过滤、去重、失败处理。
5. 文档同步：`README.md`、本文件、对应 Skill 和来源正式名称。
6. 运行：

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -q
```

7. 真实来源小范围连通验证，确认不会清空旧数据，异常会写入 warnings。

## 关键词收录规则

只允许以下字段参与行业关键词匹配：

1. 项目名称。
2. 招标或采购内容。
3. 招标或采购范围。
4. 项目概况。

上述任一字段命中一个关键词即可收录。采购人、招标人、代理机构、资格条件、
报名要求、公告发布媒介及公告其他正文中的关键词均不参与匹配。

用户明确指出的误报标题保存于 `config/excluded_notices.json`，即使旧公开数据
或来源网站再次返回这些公告，也会在发布前删除。

## 页面新增标记与采购主体

- 标讯首次进入系统时记录 `first_seen_at`，首次发现当日显示浅绿色“新增”标记。
- 次日自动恢复为普通颜色，历史标讯不会因重新采集而再次标为新增。
- 每条标讯固定显示采购人和采购代理机构。
- 官网未公开相应单位时显示“公告未载明”，不根据联系人或其他正文自行猜测。

## 人工确认、排除与纠正

- 每条标讯可确认有效、填写原因后排除，或纠正项目名称、预算、采购人、
  采购代理机构、投标截止时间、报名日期、信息源名称和项目主要内容。
- 项目主要内容只读取公告中明确标注为“招标内容”“采购内容”“招标范围”
  “采购范围”或“项目概况”的栏目；其他相似栏目不自动代入。
- 页面操作先保存在当前浏览器中；点击“当日反馈”后打开GitHub反馈单，
  需要登录GitHub并点击一次“Submit new issue”正式提交。
- 反馈单提交后，需要由人工或另行配置的 Agent 读取并处理；当前本机每日采集任务
  不读取 GitHub 反馈单，也不依赖 Codex 自动任务。
- GitHub Pages本身不能直接写入数据，因此提交时会打开GitHub反馈单，
  需要再点击一次“Submit new issue”。反馈只有在处理程序写入规则并重新发布后
  才会生效，不能把“已提交反馈单”当成“已处理”。
- 已确认网址以后固定保留；已排除网址以后固定剔除；字段纠正以后覆盖采集值。
- 同一网址先确认后排除或先排除后确认时，系统停止自动修改并在反馈单中提出
  冲突，等待再次判断。

## 施工标讯查阅文件

- 施工页面原“重点项目”已改为“查阅文件”，含义是进入招标文件下载与解析待办，
  不表示项目重要程度。
- 标记继续保存在当前浏览器本地，旧的“重点项目”标记会原样保留，不需要重新选择。
- 在“查阅文件”面板点击“提交查阅文件”后，会打开带
  `construction-tender-document-review` 标签的 GitHub Issue；仍需登录 GitHub 并点击
  `Submit new issue` 才算正式提交。
- Agent 读取 Issue 中的 `TENDER_DOCUMENT_REVIEW_JSON` 清单，逐项目下载公告明确提供的
  招标文件和附件，再调用 `tender-document-analyzer` Skill。该 Skill 每个项目固定输出
  三份 DOCX。
- 登录、验证码、付费、协议确认或组织账号授权不得绕过，应记录为需要人工处理。
- GitHub Pages 不能直接调用本机 Codex Skill，因此“提交查阅文件”是任务交接，
  不是网页端已经完成下载或解析。

## 标讯更新与发布流程

### 统一施工机会默认流程

日常手动更新优先执行：

```bash
PYTHONPATH=src python3 -m tender_agent.unified_site update --publish
```

流程固定为：施工粗筛 → 招标计划 → 超长期关联 → 统一页面 → 三组测试 → 提交 `site/` → 推送 `main` → 更新 `gh-pages`。存在未提交的非 `site/` 代码改动时自动发布会停止，防止只发布数据而遗漏代码。

只用现有数据重建页面：

```bash
PYTHONPATH=src python3 -m tender_agent.unified_site build
```

GitHub Actions **不再重新采集**。采集只在本机执行，Actions 只负责将
`site/` 目录部署到 GitHub Pages。

### 完整发布流程

```bash
# 1. 本机采集图文广告标讯
PYTHONPATH=src python3 -m tender_agent.site update

# 2. 本机采集施工标讯
PYTHONPATH=src python3 -m tender_agent.construction_site
# 完成后同步覆盖到 /Users/nonolee/Desktop/共享win/标讯/施工粗筛/

# 3. 提交并推送 site/ 到 main 分支
git add site/
git commit -m "更新标讯数据"
git push

# 4. 部署到 GitHub Pages（二选一）
# 方式A：等待 GitHub Actions 自动部署（推送后 1-3 分钟）
# 方式B：手动直推 gh-pages（更快，建议本机采集后用这个）
git subtree push --prefix=site origin gh-pages
```

### 为什么不在 Actions 里采集

黔云招采等平台从 GitHub 托管运行器（美国 IP）访问会超时，导致 Actions
自动采集的数据永远比本机少。改为本机采集 → 推送 site/ → Actions 只部署，
数据完整性由本机保证。

### 本机自动采集任务

- 任务标识：`com.nono.tender-daily`
- 安装文件：`/Users/nonolee/Library/LaunchAgents/com.nono.tender-daily.plist`
- macOS本地时间每天15:03运行；夏令时约为北京时间6:03，冬令时约为7:03
- 顺序执行图文广告采集，以及施工粗筛 → 超长期计划 → 关联 → 测试 → 统一页面 → 提交发布
- 日志：`/Users/nonolee/.local/logs/tender-collect-YYYYMMDD.log`
- 本机必须处于开机可运行、网络可用状态；该任务是系统定时任务，不消耗Codex会话Token

检查任务和最近日志：

```bash
launchctl print gui/$(id -u)/com.nono.tender-daily
tail -n 100 /Users/nonolee/.local/logs/tender-collect-$(date +%Y%m%d).log
```

### GitHub部署任务

- 任务名称：`发布标讯页面`
- 北京时间每天 7:15 将 `main` 分支上已有的 `site/` 部署到 GitHub Pages
- 推送到 `main` 且 `site/**` 变更时也会触发部署
- 定时任务只部署不采集——如果 `main` 上没新数据，就重新部署旧数据

## GitHub位置

- 代码仓库：<https://github.com/nono125-lee/guizhou-tender-daily>
- 公开页面：<https://nono125-lee.github.io/guizhou-tender-daily/>
- 施工页面：<https://nono125-lee.github.io/guizhou-tender-daily/construction/>
- 主分支：`main`
- 网页发布分支：`gh-pages`
- 自动任务名称：`发布标讯页面`

施工板块只在”资格要求””资质要求””特殊资格要求”栏目匹配施工资质词，当前包含“电力工程施工总承包”、“承装（修、试）”和“地质灾害防治单位”。
项目名称含”监理””审计””招标代理”时直接排除。施工反馈规则保存在
`config/construction_feedback_rules.json`，不写入图文广告反馈规则。

施工采集采用按来源独立增量机制：

- 首次运行查询最近7日并建立公告ID状态。
- 日常从上次成功时间向前重叠6小时，已处理公告不再读取详情。
- 每周回查最近14日列表，每月回查最近45日列表，仅补抓遗漏公告ID。
- 详情访问失败进入重试队列；来源整体失败时不推进该来源游标。
- 已确认或排除项目冻结；已有且超过7日的项目不重新覆盖。
- 变更、澄清和答疑公告通过项目编码关联未冻结的已有项目。
- `collector-state.json` 是运行状态，不应手工删除或回退。

## 日常维护

更新原始资料后重新导入：

```bash
PYTHONPATH=src python3 -m tender_agent.cli bootstrap \
  --sources "/Users/nonolee/Documents/标讯/data/private/original_inputs/01信息源库.xlsx" \
  --keywords "/Users/nonolee/Documents/标讯/data/private/original_inputs/02图文广告行业关键词库.txt" \
  --history "/Users/nonolee/Documents/标讯/data/private/original_inputs/03标讯信息表.xlsx"
```

查看本地数据状态：

```bash
PYTHONPATH=src python3 -m tender_agent.cli status
```

手动执行一次公开采集：

```bash
PYTHONPATH=src python3 -m tender_agent.site update
```

运行全部测试：

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -q
```

## 隐私与备份

- `data/private/` 已被 `.gitignore` 排除，只存在本机。
- GitHub只保存代码、非敏感配置和公开标讯数据。
- 原始Excel、关键词文本和私密数据库都应纳入本机备份。
- 更换电脑时，除克隆GitHub仓库外，还必须迁移 `data/private/original_inputs/` 和
  `data/private/tenders.sqlite3`，否则账号资料和本地历史库不会自动恢复。
