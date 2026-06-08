# 标讯项目协作规则

## 项目目标

本项目采集贵州省图文广告行业标讯，统一筛选、去重并发布到
GitHub Pages。后续通过配置扩展省份、行业和信息源。

## 开始工作前

1. 先读 `README.md` 和 `docs/OPERATIONS.md`。
2. 涉及标讯查询、信息源或关键词时，使用 `tender-intelligence` Skill。
3. 涉及联网访问时，使用 `web-access`。
4. 涉及原始 Excel 时，使用 Spreadsheets 工具，不能破坏工作簿现有内容。

## 安全边界

- 不得把账号、密码、联系人电话或 `data/private/` 提交到 Git。
- 不得在回复、日志、README、Skill或网页数据中输出明文密码。
- 遇到验证码、短信、人脸或协议确认时标记为需要人工，不绕过验证。
- 信息源正式名称以网站名称及 `config/source_names.json` 为准。

## 真实运行位置

- Agent代码：`src/tender_agent/`
- 网站采集器：`src/tender_agent/collectors/`
- Skill源文件：`skills/tender-intelligence/`
- 私密数据库：`data/private/tenders.sqlite3`
- 公开网页：`site/`
- 自动任务：`.github/workflows/daily-pages.yml`

## 修改要求

- 新网站通常新增独立采集器，并补对应测试。
- 区域和行业规则放在 `config/`，不要硬编码到采集器。
- 公告网址优先去重；信息源异常不能清空上次成功数据。
- 修改后至少运行：

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -q
PYTHONPATH=src python3 -m tender_agent.site update
```

- 发布后检查GitHub Actions成功，并核对线上 `data/latest.json`。
