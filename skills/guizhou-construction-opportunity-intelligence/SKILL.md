---
name: guizhou-construction-opportunity-intelligence
description: 贵州施工机会统一采集、粗筛、超长期招标计划识别、采购公告关联、单页工作台生成和 GitHub Pages 发布。用户提到跑一次施工标讯、统一标讯、施工粗筛加超长期、查看超长期项目何时出公告、更新施工机会雷达、生成并发布统一页面时必须使用本 Skill；日常任务不要分别运行 construction-tender-intelligence 和 tender-plan-intelligence。
---

# 贵州施工机会统一 Skill

## 目标

一次运行完成施工标讯粗筛、超长期招标计划采集、跨数据关联、统一页面生成、测试和发布。用户只需要访问一个页面，不需要在两个 Skill、两个仓库和两个网页之间切换。

## 执行入口

用户说“跑一下统一施工标讯”“更新施工机会雷达”“粗筛和超长期一起更新”时，在项目目录执行：

```bash
cd /Users/nonolee/Documents/标讯
PYTHONPATH=src python3 -m tender_agent.unified_site update --publish
```

排错或只重建页面时使用：

```bash
PYTHONPATH=src python3 -m tender_agent.unified_site build
```

## 固定顺序

1. 运行施工标讯增量采集和资格资质粗筛。
2. 运行招标计划智能窗口采集和详情缓存更新。
3. 只从最新版本中识别“超长期”资金项目。
4. 按项目名、招标人、投资项目代码、批复和建设内容生成可解释关联。
5. 生成 `/site/opportunities/` 单页工作台和运行状态。
6. 运行施工、招标计划和统一工作台测试。
7. 测试通过且工作树没有非 `site/` 改动时，提交 `site/`、推送 `main`、更新 `gh-pages`。

任一采集来源失败时保留原有公开数据并在运行状态中标红。部署成功不能代替采集成功；最后分别核对数据更新时间、`warnings` 和线上页面。

## 页面结构

- `今日待看`：默认显示近 7 天、未处理的重点关联，最多 10 条。
- `施工粗筛`：经过施工资质规则筛选的公告。
- `超长期计划`：最新版本资金来源命中超长期的项目。
- `重点关联`：全部施工公告与超长期计划候选，显示相似说明和复核级别。
- `运行状态`：两个采集器的更新时间、数量、告警和本次运行结果。

同一项目的多个计划版本在详细计划页保留历史入口。红色区域只承担近期行动清单，不铺开全部历史。

## 内部能力边界

- `construction-tender-intelligence` 继续负责施工来源、资格栏目匹配、增量状态、失败重试和人工反馈。
- `tender-plan-intelligence` 继续负责 AP1 招标计划、资金来源、详情缓存、版本合并和关联算法。
- 本 Skill 只负责统一编排、统一页面、测试门禁和发布，不复制上述规则。
- 图文广告板块保持独立，不纳入本统一页面，也不改变其关键词规则。

## 数据与隐私

- 公开页面读取 `site/construction/data/latest.json`、`site/tender-plan/data/latest.json` 和 `site/opportunities/data/*.json`。
- 私有数据库、账号、Cookie、详情缓存和运行锁不得进入 Git。
- 登录、验证码、短信、人脸、付费或协议确认不得绕过。
- 页面本地“已确认/已排除”状态只保存在当前浏览器；跨设备持久化要通过既有反馈流程处理。
