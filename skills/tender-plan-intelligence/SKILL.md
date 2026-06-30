---
name: tender-plan-intelligence
description: 贵州省 AP1 招标计划采集器的独立诊断、资金来源解析、详情缓存、版本合并和关联算法维护。仅在用户明确要求只运行或修复招标计划、不运行施工粗筛时使用；日常施工粗筛加超长期的一次更新与发布改用 guizhou-construction-opportunity-intelligence。
---

# 贵州招标计划查询 Skill

## 统一入口

本 Skill 现在是统一施工机会工作流的内部能力。用户要求日常更新、施工粗筛与超长期一起运行、生成统一页面或发布时，使用 `guizhou-construction-opportunity-intelligence`；只有招标计划源站排错、资金解析测试或明确要求单独运行计划采集时才直接执行本 Skill。

## 目标

从贵州省公共资源交易云工程建设栏目采集 `AP1` 招标计划，抽取列表字段和详情表格字段，生成可筛选的本地静态页面。收录规则是栏目全量收录，不套施工资质关键词规则。

在计划采集完成后，读取 `construction-tender-intelligence` 已公开的施工标讯结果，把资金来源命中“超长期”的计划与后续采购或招标公告做可解释的候选关联。施工公告的来源采集和资质筛选仍由施工 Skill 负责，本 Skill 不复制其采集器或放宽其收录规则。

## 信息源

- 列表入口：`http://ztb.guizhou.gov.cn/trade/?prjtype=A&category=AP1`
- 列表接口：`http://ztb.guizhou.gov.cn/api/trade/search`
- 详情接口：`http://ztb.guizhou.gov.cn/api/trade/GetDetail/{id}`
- 固定查询参数：`region=5200` 表示全省不限；`prjType=A` 表示工程建设；`noticeType=AP1` 表示招标计划。

## 执行

默认保持最近三个月招标计划页面，并根据上次成功运行时间自动选择采集窗口：

```bash
python3 ~/.codex/skills/tender-plan-intelligence/scripts/collect_plan.py \
  --site-dir /Users/nonolee/Documents/标讯/site/tender-plan
```

常用参数：

- `--pub-date td|l3d|l10d|l1m|l3m|l1y|all`：手动覆盖智能窗口；不传时自动选择。
- `--max-pages N`：限制列表页数。源站每页 10 条。
- `--all-pages`：按接口返回总页数采集。全量约数千条，会访问每条详情页以抽取资金来源，谨慎使用。
- `--workers N`：详情并发数，默认 4。
- `--request-interval N`：全局请求最小间隔秒数，默认 `0.25`。
- `--detail-cache-ttl-days N`：详情缓存有效天数，默认 30 天。
- `--refresh-details`：忽略未过期缓存并强制刷新详情。
- `--rebuild`：不合并现有 `latest.json`，按指定窗口重建；日常运行不要使用。
- `--no-details`：只取列表，不抽取资金来源；页面资金来源筛选会显示为未载明。
- `--construction-data PATH_OR_URL`：指定施工标讯 `latest.json`；默认优先读取 `/Users/nonolee/Documents/标讯/site/construction/data/latest.json`，本机文件不存在时读取施工标讯公开页数据。
- `--no-construction-match`：仅在排错时跳过施工标讯关联；日常更新不要使用。

输出固定包含：

- `site/tender-plan/data/latest.json`
- `site/tender-plan/index.html`
- `site/tender-plan/assets/style.css`
- `site/tender-plan/assets/app.js`

私有运行文件固定放在项目根目录 `.runtime/tender-plan/`，不放入 `site/`：

- `detail-cache.json`：按 `source_notice_id` 缓存成功解析的详情字段；过期刷新失败时使用旧缓存，不把已有资金来源降级为“未载明”。
- `run-state.json`：记录最后尝试、最后成功、周回查和月回查时间。

智能窗口规则：无状态时 `bootstrap/l3m`；当天已成功运行时 `daily/td`；上次成功为昨天时 `daily/l3d`；间隔 2–9 天时 `catchup/l10d`；间隔 10–29 天时 `catchup/l1m`；更长时 `catchup/l3m`。每 7 天至少使用 `weekly/l1m`，每 30 天使用 `monthly/l3m`，多个条件同时满足时选择范围最大的窗口。

采集结果必须按 `source_notice_id` 与现有 `latest.json` 合并后再按三个月口径裁剪。列表分页不完整、`--max-pages`、`--keywords` 或 `--no-details` 运行不得推进最后成功时间。`stats` 必须包含 `mode`、`pub_date`、`detail_cache_hits`、`detail_cache_misses`、`detail_fetch_failed`、`stale_cache_used`、`window_items`、`merged_total` 和 `pruned_items`。

如果只需对现有招标计划数据重新关联最新施工标讯，不重新访问招标计划源站：

```bash
python3 ~/.codex/skills/tender-plan-intelligence/scripts/priority_match.py \
  --plan-data /Users/nonolee/Documents/标讯/site/tender-plan/data/latest.json
```

## 字段规则

列表字段：

- `title`
- `published_at`
- `region`
- `buyer`
- `agency`
- `source_name`
- `url`
- `source_notice_id`

详情表格字段：

- `project_name`
- `fixed_asset_code`
- `approval`
- `budget`
- `fund_source`
- `fund_source_tags`
- `project_content`
- `planned_bid_time`
- `planned_tender_content`
- `planned_trade_place`
- `project_location`
- `supervisor`

资金来源分类只用于页面筛选，不替代原文。分类按钮顺序为：超长期、政府投资、财政资金、上级补助、国有资金、专项债、地方自筹、企业自筹、银行贷款、社会资本、其他、未载明。“超长期”只表示资金来源原文命中“超长期国债”“超长期特别国债”或“特别国债”，不按预计招标时间判断。页面必须同时保留资金来源原文。

## 施工标讯融合规则

1. 施工标讯输入只使用 `construction-tender-intelligence` 生成的 `site/construction/data/latest.json`，不在本 Skill 内重新抓取施工公告。
2. 只对资金来源命中“超长期”的招标计划建立重点关联；“政府投资”“专项债”等其他资金标签不能代替“超长期”。
3. 公告发布日期不得早于招标计划发布日期，防止把历史公告错挂到新计划。
4. 以下任一项达到条件即可进入红色重点区：招标人/采购人名称标准化后一致；投资项目代码一致；批复文件名称或文号一致；标准化项目名称完全一致、形成明确包含关系或相似度不低于 78%；项目建设内容相似度不低于 42%。
5. 项目名称相似匹配要检查名称开头的县、市、区、州等地域词；双方地域明确且不一致时，不把名称相似算作命中，避免把不同县的同类项目误关联。其他独立强证据仍可触发。
6. 标准化只移除空白、标点、公告类型后缀和标段/包尾缀，不移除“一期/二期”、地名、项目类型等区分信息。
7. 每条重点关联保留 `methods`、`confidence`、`match_level`、`review_required`、`review_note`、`evidence` 和各字段 `similarities`。单凭招标人、近似名称或建设内容命中的记录标记为“候选需复核”；代码、批复或多项证据命中的记录标记为“高可信”。
8. 同一施工公告若与多个计划得到相同或接近的最高分，写入 `candidate_plans` 并全部展示，不静默指定唯一计划。
9. `latest.json.items` 继续保留公告级招标计划原始记录；关联结果单独写入顶层 `priority_notices`，避免污染计划原字段。
10. 施工标讯源异常时保留招标计划页面和旧数据，在 `warnings` 中说明关联失败，不得把施工源失败解释为“当前没有重点公告”。

## 页面要求

- 页面风格参考 `guizang-ppt-skill` 的电子杂志 / 瑞士信息设计取向，但这是工具页面，不做横向翻页 PPT。
- 保留类似施工标讯页的筛选：关键词、地州市、区县、发布时间、来源平台、预计招标时间。
- 额外提供资金来源筛选：按分类筛选，并把所有资金来源分类列为可点击按钮。
- 卡片必须展示原公告链接和详情抽取字段；抽取不到的字段显示“未载明”，不要猜测。
- 页面顶部设置“超长期项目已出施工公告”重点区，按施工公告时间倒序展示施工公告链接、原招标计划链接、采购人、项目编号、施工资质命中词、相似说明和人工复核提示。
- 已关联的招标计划在普通列表中置顶并加“已出施工公告”标识；该标识表示自动关联结果，与施工页人工“查阅文件”标记含义不同。

## 安全边界

- 只访问公开接口，不绕过验证码、登录、短信、人脸或协议确认。
- 采集异常时保留已生成页面，并在 `warnings` 中记录。
- 不自动创建 Codex 定时任务；需要每日运行时由用户另行配置自动化。
