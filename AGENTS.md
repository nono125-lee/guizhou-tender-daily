# 标讯项目协作规则

## 项目目标

本项目分别采集贵州省图文广告和施工行业标讯，统一筛选、去重并发布到
GitHub Pages。两个行业使用独立规则、数据状态和网页入口。

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
- 施工Skill源文件：`skills/construction-tender-intelligence/`
- 私密数据库：`data/private/tenders.sqlite3`
- 公开网页：`site/`
- 施工公开网页：`site/construction/`
- 本机自动采集：`/Users/nonolee/Library/LaunchAgents/com.nono.tender-daily.plist`
- GitHub部署任务：`.github/workflows/daily-pages.yml`

## 修改要求

- 新网站通常新增独立采集器，并补对应测试。
- 区域和行业规则放在 `config/`，不要硬编码到采集器。
- 关键词只能匹配项目名称、招标或采购内容、招标或采购范围、项目概况。
- 施工板块例外：只允许在资格要求、资质要求、特殊资格要求栏目匹配
  `config/industries/construction.json` 中的施工资质词；项目名称含监理、
  审计、招标代理时直接排除。
- 网页“项目主要内容”只提取公告中明确标注为“招标内容”“采购内容”
  “招标范围”“采购范围”或“项目概况”的栏目；其他栏目不得自动代替。
- 采购人、招标人、代理机构、资格条件及公告其他正文中的关键词不得计入。
- 用户确认的误报标题维护在 `config/excluded_notices.json`。
- 新增标讯以首次发现日标记，次日恢复普通颜色，不按公告发布日期反复标新。
- 采购人和采购代理机构必须分字段展示；无法核实则写“公告未载明”。
- 公告网址优先去重；信息源异常不能清空上次成功数据。
- GitHub Actions成功不代表所有来源成功；必须检查公开数据中的 `warnings`。
- 黔云招采可能对GitHub托管运行器超时，本机可访问，详见 `docs/OPERATIONS.md`。
- 标讯采集只在**本机**执行（黔云招采从 GitHub runner 无法访问）。
  发布流程：本机采集 → commit site/ → push → GitHub Actions 自动部署 gh-pages。
  也可以本机采集后直接用 `git subtree push --prefix=site origin gh-pages` 直推部署。
- 当前每日采集由 macOS `launchd` 发起，不由 Codex 或 GitHub Actions 发起；
  不得把“Actions部署成功”写成“来源采集成功”。
- 修改后至少运行：

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -q
```

- 发布后检查线上 `data/latest.json` 确认数据完整。
