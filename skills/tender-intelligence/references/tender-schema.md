# 标讯统一字段

## 必填字段

- `title`: 项目名称
- `url`: 公告原始网址
- `source_name`: 信息源名称
- `published_at`: 公告发布时间
- `collected_at`: 采集时间
- `region`: 项目所在地
- `buyer`: 招标人或采购人
- `agency`: 采购代理机构；公告未提供时使用“公告未载明”
- `bid_deadline`: 投标截止时间
- `summary`: 项目主要内容
- `first_seen_at`: 系统首次发现时间
- `is_new`: 是否为首次发现当日的新增标讯

## 建议字段

- `budget`
- `registration_fee`
- `registration_deadline`
- `contact`
- `phone`
- `agency`
- `submission_channel`
- `submission_method`
- `submission_place`
- `announcement_type`
- `attachments`
- `matched_keywords`
- `region_status`
- `raw_text_hash`

## 状态值

- `included`: 明确属于当前区域
- `excluded`: 明确属于排除区域
- `review`: 地区无法确认，需要人工复核
