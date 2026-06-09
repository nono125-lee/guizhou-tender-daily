# 标讯系统位置与运维交接

## 系统组成

这套系统由四部分组成：

1. 本地Skill：让Codex知道何时、按什么规则执行标讯任务。
2. 本地Agent代码：负责导入、筛选、去重、采集和生成网页数据。
3. GitHub Actions：每天自动运行Agent并发布网站。
4. GitHub Pages：提供手机和电脑可打开的最新标讯页面。

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
| 施工信息源配置 | `config/construction_sources.json` | 九个施工公告来源 |
| 信息源正式名称映射 | `config/source_names.json` | 网页展示名称 |
| 人工核实公告 | `config/verified_notices.json` | 暂无采集器时的临时补录 |
| 已确认误报排除清单 | `config/excluded_notices.json` | 每次更新时强制排除 |
| 人工反馈规则 | `config/feedback_rules.json` | 保存确认、排除原因和字段纠正 |
| 私密信息源数据库 | `data/private/tenders.sqlite3` | 含账号资料，不上传GitHub |
| 公开网页文件 | `site/` | 发布到GitHub Pages |
| 施工独立网页 | `site/construction/` | 与图文广告数据和反馈状态隔离 |
| 最新公开数据 | `site/data/latest.json` | 网页读取的数据 |
| 自动任务 | `.github/workflows/daily-pages.yml` | 北京时间每天7:15运行 |
| 测试 | `tests/` | 采集器和数据处理测试 |

## 原始资料位置

以下文件是用户维护的原始资料，仍在桌面共享目录：

| 内容 | 绝对路径 |
|---|---|
| 信息源库 | `/Users/nonolee/Desktop/共享win/01信息源库.xlsx` |
| 图文广告原始关键词库 | `/Users/nonolee/Desktop/共享win/02图文广告行业关键词库.txt` |
| 历史标讯信息表 | `/Users/nonolee/Desktop/共享win/03标讯信息表.xlsx` |

原始附件不会提交到GitHub。信息源库导入私密数据库；关键词库导入后形成
`config/industries/graphic-advertising.json`；历史标讯表导入私密数据库用于历史数据和去重。

2026-06-09盘点结果：

- 信息源账号记录：171条
- 不同信息源网址：108个
- 历史标讯记录：431条
- 已开发独立采集器：3个

## 已开发采集器

| 网站 | 采集器 |
|---|---|
| 贵州省招标投标公共服务平台 | `src/tender_agent/collectors/guizhou_ztb.py` |
| 黔云招采电子招标采购交易平台 | `src/tender_agent/collectors/eqyzc.py` |
| 遵义市公共交通（集团）有限责任公司 | `src/tender_agent/collectors/zunyi_bus.py` |

信息源库中的其他网站只是“待开发来源”，不会因为存在于Excel或数据库中就自动完成查询。

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
- 反馈单提交后，本机Codex的“处理标讯人工反馈”自动任务定期读取反馈，
  写入 `config/feedback_rules.json`、更新网页并关闭已处理反馈单。
- GitHub Pages本身不能直接写入数据，因此提交时会打开GitHub反馈单，
  需要再点击一次“Submit new issue”；通常在下一次自动任务运行后完成处理。
- 已确认网址以后固定保留；已排除网址以后固定剔除；字段纠正以后覆盖采集值。
- 同一网址先确认后排除或先排除后确认时，系统停止自动修改并在反馈单中提出
  冲突，等待再次判断。

## GitHub位置

- 代码仓库：<https://github.com/nono125-lee/guizhou-tender-daily>
- 公开页面：<https://nono125-lee.github.io/guizhou-tender-daily/>
- 施工页面：<https://nono125-lee.github.io/guizhou-tender-daily/construction/>
- 主分支：`main`
- 网页发布分支：`gh-pages`
- 自动任务名称：`每日标讯更新`

自动任务每天北京时间7:15启动，也会在采集代码、配置或网页文件推送到
`main`后启动。GitHub任务可能因平台排队稍有延迟。

施工板块只在“资格要求”“资质要求”“特殊资格要求”栏目匹配施工资质词。
项目名称含“监理”“审计”“招标代理”时直接排除。施工反馈规则保存在
`config/construction_feedback_rules.json`，不写入图文广告反馈规则。

## 已知运行限制

截至2026-06-09，黔云招采公开接口在本机可正常访问，但从GitHub托管运行器
访问时可能持续超时。采集器已经加入请求重试；超时后会保留上次成功数据，
并在 `site/data/latest.json` 的 `warnings` 中记录异常。

因此检查每日任务时必须同时确认：

1. GitHub Actions任务是否成功完成。
2. `site/data/latest.json` 的 `warnings` 是否包含来源采集异常。
3. 黔云招采当天是否需要从本机补跑并推送。

在GitHub云端访问限制解决前，不能仅凭任务显示绿色就认定黔云招采当天已完成查询。

## 日常维护

更新原始资料后重新导入：

```bash
PYTHONPATH=src python3 -m tender_agent.cli bootstrap \
  --sources "/Users/nonolee/Desktop/共享win/01信息源库.xlsx" \
  --keywords "/Users/nonolee/Desktop/共享win/02图文广告行业关键词库.txt" \
  --history "/Users/nonolee/Desktop/共享win/03标讯信息表.xlsx"
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
- 更换电脑时，除克隆GitHub仓库外，还必须迁移三份原始资料和
  `data/private/tenders.sqlite3`，否则账号资料和本地历史库不会自动恢复。
