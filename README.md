# 贵州标讯系统

## 统一标讯雷达

图文广告、园林绿化、施工标讯粗筛、招标计划和重点公告关联已合并为一个用户入口：

```bash
PYTHONPATH=src python3 -m tender_agent.unified_site update --publish
```

该命令依次完成图文广告与园林绿化采集、施工增量采集、招标计划智能窗口采集、国债/专项/中央/省级/超长期及用户重点项目关联、统一页面生成、测试、提交和 GitHub Pages 发布。统一页面位于：

<https://nono125-lee.github.io/guizhou-tender-daily/opportunities/>

页面标题为“标讯雷达”，按“重点关联、图文广告、园林绿化、施工粗筛、招标计划、运行状态”排列。重点关联对用户指定的项目强提示，同时自动关联资金来源原文命中“国债”“专项”“中央”“省级”或超长期的项目，并复用施工粗筛的检索、地区、时间、信息源、报名日期、截止日期、资质要求和信息源快捷按钮；时间可直接筛选最近 1 天、3 天和 7 天。图文广告和园林绿化的信息源下拉框包含施工粗筛全部来源与各自已有来源，并提供同款带数量快捷按钮。招标计划页最前提供五类资金快捷筛选；图文广告和园林绿化共用采集但独立分类；施工粗筛和招标计划保留原有筛选与详细页。

这是一个面向多省份、多行业、多信息源的标讯采集项目。当前首期范围：

- 区域：贵州省
- 行业：图文广告、施工
- 输入：信息源账号表、行业关键词库、历史标讯表
- 输出：去重后的每日标讯、复核队列和 GitHub Pages 网页

运行要求：Python 3.9 或更高版本。

## 当前完成

- 已建立项目本地 Skill：`skills/tender-intelligence/`
- 已建立独立施工 Skill：`skills/construction-tender-intelligence/`
- 已建立 Excel/文本导入器，不修改原始附件
- 已建立 SQLite 数据结构和账号私密存储目录
- 已建立贵州区域筛选、关键词命中和重复公告指纹
- 已建立适合手机打开的 GitHub Pages 标讯晨报
- 已建立贵州省招标投标公共服务平台公开接口增量采集器
- 已建立黔云招采电子招标采购交易平台公开接口增量采集器
- 已建立遵义市公共交通（集团）有限责任公司通知公告采集器
- 已建立贵阳市公共资源交易国有企业招标采购平台公开接口增量采集器
- 已建立中烟电子采购平台公开公告采集器
- 已建立中国南方电网供应链统一服务平台公开公告采集器
- 已建立贵州省公共资源交易云工程建设、政府采购、其他交易三类栏目采集器，图文广告与园林绿化共享采集并保留栏目级来源名称
- 已建立黔云招采四个子板块及云农商图文广告/施工采集接入
- 已建立“黔顺云采”集采平台图文广告/施工采集器
- 已建立军队采购网贵州公告图文广告/施工采集器
- 已建立 macOS 本机每日采集任务，通常在北京时间 6:03（冬令时 7:03）完成采集和推送
- 已建立北京时间每天 7:15 GitHub Actions 兜底部署工作流（只部署，不采集）
- 已建立网页人工确认、排除、字段纠正和GitHub反馈处理工作流
- 已建立施工来源独立游标、公告ID去重、失败重试和周/月补漏机制
- 已建立统一标讯雷达 Skill、全行业单次运行编排和单页工作台

完整的本地文件位置、GitHub部署位置和日常维护方法见
[`docs/OPERATIONS.md`](docs/OPERATIONS.md)。

## 初始化现有资料

```bash
PYTHONPATH=src python3 -m tender_agent.cli bootstrap \
  --sources "/Users/nonolee/Documents/标讯/data/private/original_inputs/01信息源库.xlsx" \
  --keywords "/Users/nonolee/Documents/标讯/data/private/original_inputs/02图文广告行业关键词库.txt" \
  --history "/Users/nonolee/Documents/标讯/data/private/original_inputs/03标讯信息表.xlsx"
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

本机 macOS 任务每天本地时间 15:03 采集并推送：夏令时对应北京时间
6:03，冬令时对应北京时间 7:03。GitHub Actions 按 `Asia/Shanghai`
时区每天 7:15 兜底部署仓库中已有的 `site/`，不会发起采集。电脑关机、休眠、
断网或来源异常都可能影响更新，因此以网页显示的实际更新时间和 `warnings`
为准；来源失败时保留上次成功数据。

公开页面：<https://nono125-lee.github.io/guizhou-tender-daily/>

施工行业独立页面：
<https://nono125-lee.github.io/guizhou-tender-daily/construction/>

每次施工粗筛运行后，公开结果同时覆盖更新到
`/Users/nonolee/Desktop/共享win/标讯/施工粗筛/`，便于 Windows 共享查看。

重点资金招标计划详细页面：
<https://nono125-lee.github.io/guizhou-tender-daily/tender-plan/>

GitHub 仓库：<https://github.com/nono125-lee/guizhou-tender-daily>

## 隐私

GitHub Pages 是公开网页。仓库发布统一整理后的公告公开字段、筛选结果和原公告
链接，不发布信息源账号、密码、联系人电话、Cookie、Token 或私密数据库。
