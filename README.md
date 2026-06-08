# 贵州标讯晨报

这是一个面向多省份、多行业、多信息源的标讯采集项目。当前首期范围：

- 区域：贵州省
- 行业：图文广告
- 输入：信息源账号表、行业关键词库、历史标讯表
- 输出：去重后的每日标讯、复核队列和 GitHub Pages 网页

运行要求：Python 3.9 或更高版本。

## 当前完成

- 已建立项目本地 Skill：`skills/tender-intelligence/`
- 已建立 Excel/文本导入器，不修改原始附件
- 已建立 SQLite 数据结构和账号私密存储目录
- 已建立贵州区域筛选、关键词命中和重复公告指纹
- 已建立适合手机打开的 GitHub Pages 标讯晨报
- 已建立贵州省招标投标公共服务平台公开接口增量采集器
- 已建立黔云招采电子招标采购交易平台公开接口增量采集器
- 已建立遵义市公共交通（集团）有限责任公司通知公告采集器
- 已建立北京时间每天 7:15 自动采集和发布工作流

## 初始化现有资料

```bash
PYTHONPATH=src python3 -m tender_agent.cli bootstrap \
  --sources "/Users/nonolee/Desktop/共享win/01信息源库.xlsx" \
  --keywords "/Users/nonolee/Desktop/共享win/02图文广告行业关键词库.txt" \
  --history "/Users/nonolee/Desktop/共享win/03标讯信息表.xlsx"
```

导入后的账号密码位于 `data/private/tenders.sqlite3`，文件权限设为仅当前用户可读写，并被 `.gitignore` 排除。

生成最近采集日的日报：

```bash
PYTHONPATH=src python3 -m tender_agent.cli digest
```

生成 GitHub Pages 初始公开数据：

```bash
PYTHONPATH=src python3 -m tender_agent.site seed
```

## 尚未上线的部分

- 信息源库中尚未接入的其他网站适配器
- 需要登录、短信验证码或人工确认的平台
- 更多省份和行业关键词库

这些信息源需要结合网站实际结构和验证方式逐项接入。

## 自动更新时间

GitHub Actions 按 `Asia/Shanghai` 时区每天 7:15 启动。GitHub 官方说明定时任务在高负载时可能延迟，因此网页显示实际更新时间；如果采集失败，会保留上次成功数据并显示提示。

## 隐私

GitHub Pages 是公开网页。仓库只发布项目名称、预算、采购人、截止时间、关键词和原公告链接，不发布账号、密码、联系人电话或私密数据库。
