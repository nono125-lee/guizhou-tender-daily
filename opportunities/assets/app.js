const FUND_KEYWORD_FILTERS = ["国债", "专项", "中央", "省级"];
const FUND_TAG_ORDER = [
  ...FUND_KEYWORD_FILTERS, "超长期", "政府投资", "财政资金", "上级补助", "国有资金", "专项债",
  "地方自筹", "企业自筹", "银行贷款", "社会资本", "其他", "未载明"
];
const PREFECTURE_LABELS = {
  "贵阳市": "贵阳", "六盘水市": "六盘水", "遵义市": "遵义", "安顺市": "安顺",
  "毕节市": "毕节", "铜仁市": "铜仁", "黔西南布依族苗族自治州": "黔西南",
  "黔东南苗族侗族自治州": "黔东南", "黔南布依族苗族自治州": "黔南",
  "贵安新区": "贵安"
};
const CORE_QUALIFICATIONS = ["电力工程施工总承包", "承装（修、试）", "地质灾害防治单位"];
const MATCH_METHOD_LABELS = {
  project_name: "项目名称",
  buyer: "招标人/采购人",
  fixed_asset_code: "投资项目代码",
  approval: "批复文件",
  project_content: "建设内容",
  user_watchlist: "用户重点关注"
};
const VIEW_META = {
  matches: { kicker: "MATCH ARCHIVE", title: "重点关联档案", label: "条关联" },
  graphic: { kicker: "GRAPHIC ADVERTISING", title: "图文广告", label: "条公告" },
  landscaping: { kicker: "LANDSCAPING", title: "园林绿化", label: "条公告" },
  construction: { kicker: "SCREENED NOTICES", title: "施工标讯粗筛", label: "条施工公告" },
  plans: { kicker: "TENDER PLANS", title: "招标计划", label: "个项目" },
  status: { kicker: "RUN HEALTH", title: "采集与发布状态", label: "项状态" }
};

const state = {
  manifest: null,
  matches: null,
  status: null,
  industries: null,
  construction: null,
  plans: null,
  view: "matches",
  shown: 50,
  activeFund: "",
  matchFiltersReady: false,
  constructionFiltersReady: false,
  planFiltersReady: false
};

const $ = (selector) => document.querySelector(selector);

function text(value, fallback = "未载明") {
  const result = String(value ?? "").trim();
  return result || fallback;
}

function dateText(value) {
  return String(value || "").slice(0, 10);
}

function parseDate(value) {
  const normalized = dateText(value);
  const parsed = new Date(`${normalized}T00:00:00+08:00`);
  return Number.isNaN(parsed.getTime()) ? null : parsed;
}

function withinDays(value, days) {
  if (days === "all") return true;
  const parsed = parseDate(value);
  if (!parsed) return false;
  const cutoff = new Date();
  cutoff.setHours(0, 0, 0, 0);
  cutoff.setDate(cutoff.getDate() - Number(days));
  return parsed >= cutoff;
}

async function fetchJson(url) {
  const response = await fetch(`${url}${url.includes("?") ? "&" : "?"}v=${Date.now()}`);
  if (!response.ok) throw new Error(`数据读取失败：${url}`);
  return response.json();
}

async function ensureDataset(name) {
  if (state[name]) return state[name];
  const url = state.manifest.datasets[name === "plans" ? "tender_plans" : name];
  state[name] = await fetchJson(url);
  return state[name];
}

function normalizeProjectName(item) {
  return String(item.project_name || item.title || "")
    .normalize("NFKC")
    .replace(/\s+/g, " ")
    .trim();
}

function groupedPlans(items) {
  const groups = new Map();
  (items || []).forEach((item) => {
    const key = normalizeProjectName(item) || `notice:${item.source_notice_id || item.url}`;
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(item);
  });
  return [...groups.values()]
    .map((versions) => versions.sort((a, b) => (b.published_at || "").localeCompare(a.published_at || ""))[0])
    .sort((a, b) => (b.published_at || "").localeCompare(a.published_at || ""));
}

function optionList(select, values) {
  const current = select.value;
  select.querySelectorAll("option:not([value=''])").forEach((option) => option.remove());
  values.filter(Boolean).sort((a, b) => a.localeCompare(b, "zh-CN")).forEach((value) => {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = value;
    select.append(option);
  });
  if ([...select.options].some((option) => option.value === current)) select.value = current;
}

function constructionRegionOf(item) {
  const value = `${item.location || ""} ${item.title || ""}`;
  const regions = ["贵阳", "遵义", "六盘水", "安顺", "毕节", "铜仁", "黔南", "黔东南", "黔西南", "贵安"];
  return regions.find((region) => value.includes(region)) || "贵州省";
}

function locationParts(item) {
  const parts = (item.project_location || "").split("-").map((part) => part.trim()).filter(Boolean);
  if (parts.length >= 3 && parts[0] === "贵州省") return { prefectureRaw: parts[1], district: parts[2] };
  if (parts.length >= 2) return { prefectureRaw: parts.at(-2), district: parts.at(-1) };
  return { prefectureRaw: "", district: item.region || "" };
}

function prefectureOf(item) {
  const raw = locationParts(item).prefectureRaw;
  return PREFECTURE_LABELS[raw] || raw || "未载明";
}

function districtOf(item) {
  return locationParts(item).district || item.region || "未载明";
}

function isUltraLong(item) {
  return /超长期(?:特别)?国债|特别国债/.test(item.fund_source || "");
}

function matchesFundFilter(item, filter) {
  if (FUND_KEYWORD_FILTERS.includes(filter)) return (item.fund_source || "").includes(filter);
  if (filter === "超长期") return isUltraLong(item);
  return (item.fund_source_tags || []).includes(filter);
}

function populateNoticeFilters(items, prefix, availableSources = []) {
  optionList($(`#${prefix}-region`), [...new Set(items.map(constructionRegionOf))]);
  optionList($(`#${prefix}-source`), [...new Set([
    ...availableSources,
    ...items.map((item) => item.source_name)
  ])]);
  optionList($(`#${prefix}-qualification`), [...new Set([
    ...CORE_QUALIFICATIONS,
    ...items.flatMap((item) => item.matched_keywords || [])
  ])]);
}

function populateConstructionFilters(items) {
  populateNoticeFilters(items, "construction");
  state.constructionFiltersReady = true;
}

function populateMatchFilters(entries) {
  populateNoticeFilters(
    entries.map((entry) => entry.notice || {}),
    "match",
    state.matches.available_sources || []
  );
  state.matchFiltersReady = true;
}

function industryCategory(view) {
  return view === "graphic" ? "graphic-advertising" : "landscaping";
}

function industryItems(items, view = state.view) {
  const category = industryCategory(view);
  return (items || []).filter((item) => (item.industry_categories || []).includes(category));
}

function populateIndustryFilters(items) {
  optionList($("#industry-source"), [...new Set(items.map((item) => item.source_name))]);
}

function updatePlanDistricts() {
  if (!state.plans) return;
  const prefecture = $("#plan-prefecture").value;
  const items = groupedPlans(state.plans.items || []);
  optionList($("#plan-district"), [...new Set(items
    .filter((item) => !prefecture || prefectureOf(item) === prefecture)
    .map(districtOf))]);
}

function populatePlanFilters(items) {
  optionList($("#plan-prefecture"), [...new Set(items.map(prefectureOf))]);
  updatePlanDistricts();
  state.planFiltersReady = true;
}

function queryText() {
  return $("#search").value.trim().toLowerCase();
}

function includesQuery(values) {
  const query = queryText();
  if (!query) return true;
  return values.filter(Boolean).join(" ").toLowerCase().includes(query);
}

function passesNoticeFilters(item, prefix) {
  const days = $(`#${prefix}-date-range`).value;
  const region = $(`#${prefix}-region`).value;
  const source = $(`#${prefix}-source`).value;
  const registrationDate = $(`#${prefix}-reg-date`).value.trim();
  const cutoffDate = $(`#${prefix}-cutoff-date`).value;
  const qualification = $(`#${prefix}-qualification`).value.trim().toLowerCase();
  const passQualification = !qualification || [
    item.qualification_requirement || "",
    ...(item.matched_keywords || [])
  ].join(" ").toLowerCase().includes(qualification);
  return withinDays(item.published_at, days)
    && (!region || constructionRegionOf(item) === region)
    && (!source || item.source_name === source)
    && (!registrationDate || (item.registration_period || "").includes(registrationDate))
    && (!cutoffDate || (item.bid_deadline || "").startsWith(cutoffDate))
    && passQualification;
}

function filterMatches(items) {
  return (items || []).filter((entry) => {
    const notice = entry.notice || {};
    const plan = entry.plan || {};
    return passesNoticeFilters(notice, "match")
      && includesQuery([
        notice.title,
        notice.project_name,
        notice.buyer,
        notice.agency,
        notice.project_code,
        notice.project_content,
        ...(notice.matched_keywords || []),
        plan.project_name,
        plan.buyer,
        plan.fixed_asset_code,
        ...(entry.match?.evidence || [])
      ]);
  });
}

function filterConstruction(items) {
  return (items || []).filter((item) => {
    return passesNoticeFilters(item, "construction")
      && includesQuery([
        item.title,
        item.project_name,
        item.buyer,
        item.agency,
        item.project_code,
        item.project_content,
        ...(item.matched_keywords || [])
      ]);
  });
}

function filterIndustry(items) {
  const days = $("#industry-date-range").value;
  const source = $("#industry-source").value;
  return industryItems(items).filter((item) => withinDays(item.published_at, days)
    && (!source || item.source_name === source)
    && includesQuery([
      item.title,
      item.project_name,
      item.buyer,
      item.agency,
      item.project_code,
      item.project_content,
      ...(item.matched_keywords || [])
    ]));
}

function filterPlans(items) {
  const prefecture = $("#plan-prefecture").value;
  const district = $("#plan-district").value;
  const days = $("#plan-date-range").value;
  const plannedMonth = $("#plan-planned-month").value;
  return groupedPlans(items).filter((item) => {
    const passFund = !state.activeFund
      || matchesFundFilter(item, state.activeFund);
    return withinDays(item.published_at, days)
      && (!prefecture || prefectureOf(item) === prefecture)
      && (!district || districtOf(item) === district)
      && (!plannedMonth || (item.planned_bid_time || "").startsWith(plannedMonth))
      && passFund
      && includesQuery([
        item.title,
        item.project_name,
        item.buyer,
        item.fixed_asset_code,
        item.approval,
        item.project_content,
        item.fund_source
      ]);
  });
}

function renderFundStrip(items) {
  const strip = $("#fund-strip");
  strip.replaceChildren();
  const counts = new Map();
  items.forEach((item) => {
    (item.fund_source_tags || ["未载明"]).forEach((tag) => counts.set(tag, (counts.get(tag) || 0) + 1));
  });
  FUND_KEYWORD_FILTERS.forEach((keyword) => {
    counts.set(keyword, items.filter((item) => matchesFundFilter(item, keyword)).length);
  });
  counts.set("超长期", items.filter(isUltraLong).length);
  [...new Set([...FUND_TAG_ORDER, ...counts.keys()])]
    .sort((a, b) => {
      const ai = FUND_TAG_ORDER.indexOf(a);
      const bi = FUND_TAG_ORDER.indexOf(b);
      if (ai >= 0 || bi >= 0) return (ai < 0 ? 999 : ai) - (bi < 0 ? 999 : bi);
      return a.localeCompare(b, "zh-CN");
    })
    .forEach((tag) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = state.activeFund === tag ? "active" : "";
      button.innerHTML = `<span>${tag}</span><strong>${counts.get(tag) || 0}</strong>`;
      button.addEventListener("click", () => {
        state.activeFund = state.activeFund === tag ? "" : tag;
        state.shown = 50;
        render();
      });
      strip.append(button);
    });
}

function renderSourceStrip(items, stripSelector, selectSelector, availableSources = []) {
  const strip = $(stripSelector);
  const select = $(selectSelector);
  strip.replaceChildren();
  const counts = new Map();
  items.forEach((item) => {
    const source = text(item.source_name);
    counts.set(source, (counts.get(source) || 0) + 1);
  });
  [...new Set([...availableSources, ...counts.keys()])]
    .map((source) => [source, counts.get(source) || 0])
    .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0], "zh-CN"))
    .forEach(([source, count]) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = select.value === source ? "active" : "";
      button.innerHTML = `<span>${source}</span><strong>${count}</strong>`;
      button.addEventListener("click", () => {
        select.value = select.value === source ? "" : source;
        state.shown = 50;
        render();
      });
      strip.append(button);
    });
}

function addFact(list, label, value) {
  const wrapper = document.createElement("div");
  const term = document.createElement("dt");
  const description = document.createElement("dd");
  term.textContent = label;
  description.textContent = text(value);
  wrapper.append(term, description);
  list.append(wrapper);
}

function addTags(container, values) {
  [...new Set((values || []).filter(Boolean))].forEach((value) => {
    const tag = document.createElement("span");
    tag.textContent = value;
    container.append(tag);
  });
}

function truncate(value, limit = 480) {
  const result = text(value, "");
  return result.length > limit ? `${result.slice(0, limit)}…` : result;
}

function addRecordLink(container, label, url) {
  if (!url) return;
  const link = document.createElement("a");
  link.href = url;
  link.target = "_blank";
  link.rel = "noopener noreferrer";
  link.textContent = label;
  container.append(link);
}

function renderMatch(entry, index) {
  const notice = entry.notice || {};
  const plan = entry.plan || {};
  const match = entry.match || {};
  const candidatePlans = entry.candidate_plans?.length
    ? entry.candidate_plans
    : [{ plan, match }];
  const fragment = $("#record-template").content.cloneNode(true);
  const card = fragment.querySelector(".record-card");
  card.classList.add("priority");
  fragment.querySelector(".record-index").textContent = String(index + 1).padStart(2, "0");
  fragment.querySelector("time").textContent = text(dateText(notice.published_at));
  fragment.querySelector(".record-source").textContent = text(notice.source_name);
  fragment.querySelector(".record-badge").textContent = entry.priority_source === "user_watchlist"
    ? "用户重点提示"
    : match.review_required ? "候选需复核" : "高可信关联";
  const link = fragment.querySelector(".record-link");
  link.href = notice.url || plan.url || "#";
  link.textContent = notice.project_name || notice.title || "未载明";
  const relation = fragment.querySelector(".record-relation");
  relation.hidden = false;
  relation.textContent = candidatePlans.length > 1
    ? `可能关联 ${candidatePlans.length} 个计划；首选：${plan.project_name || plan.title || "未载明"}`
    : `关联计划：${plan.project_name || plan.title || "未载明"}`;
  const links = fragment.querySelector(".record-links");
  links.hidden = false;
  addRecordLink(links, "打开招标公告", notice.url);
  candidatePlans.forEach((candidate, candidateIndex) => {
    const candidatePlan = candidate.plan || {};
    addRecordLink(
      links,
      candidatePlans.length > 1 ? `打开关联招标计划 ${candidateIndex + 1}` : "打开关联招标计划",
      candidatePlan.url
    );
  });
  const facts = fragment.querySelector(".record-facts");
  addFact(facts, "招标人/采购人", notice.buyer);
  addFact(facts, "施工项目编号", notice.project_code);
  addFact(facts, "投资项目代码", plan.fixed_asset_code);
  addFact(facts, "资金来源", plan.fund_source);
  addFact(facts, "匹配置信度", `${Math.round((match.confidence || 0) * 100)}%`);
  fragment.querySelector(".record-content").textContent = truncate(notice.project_content || plan.project_content);
  addTags(fragment.querySelector(".record-tags"), [
    ...(notice.matched_keywords || []),
    ...(match.methods || []).map((method) => MATCH_METHOD_LABELS[method] || method)
  ]);
  const evidence = fragment.querySelector(".record-evidence");
  evidence.hidden = false;
  const candidateText = candidatePlans.length > 1
    ? `候选计划：${candidatePlans.map((candidate) => candidate.plan?.project_name || candidate.plan?.title || "未载明").join("、")}。`
    : "";
  evidence.textContent = `${(match.evidence || []).join("；")}。${match.review_note || ""}${candidateText}`;
  card.style.animationDelay = `${Math.min(index * 18, 220)}ms`;
  return fragment;
}

function renderConstruction(item, index) {
  const fragment = $("#record-template").content.cloneNode(true);
  fragment.querySelector(".record-index").textContent = String(index + 1).padStart(2, "0");
  fragment.querySelector("time").textContent = text(dateText(item.published_at));
  fragment.querySelector(".record-source").textContent = text(item.source_name);
  fragment.querySelector(".record-badge").textContent = item.is_new ? "新增" : "施工粗筛";
  const link = fragment.querySelector(".record-link");
  link.href = item.url || "#";
  link.textContent = item.project_name || item.title || "未载明";
  const facts = fragment.querySelector(".record-facts");
  addFact(facts, "招标人/采购人", item.buyer);
  addFact(facts, "代理机构", item.agency);
  addFact(facts, "预算", item.budget);
  addFact(facts, "项目编号", item.project_code);
  addFact(facts, "投标截止", item.bid_deadline);
  addFact(facts, "地区", item.location);
  fragment.querySelector(".record-content").textContent = truncate(item.project_content);
  addTags(fragment.querySelector(".record-tags"), item.matched_keywords);
  return fragment;
}

function renderIndustry(item, index) {
  const fragment = $("#record-template").content.cloneNode(true);
  fragment.querySelector(".record-index").textContent = String(index + 1).padStart(2, "0");
  fragment.querySelector("time").textContent = text(dateText(item.published_at));
  fragment.querySelector(".record-source").textContent = text(item.source_name);
  fragment.querySelector(".record-badge").textContent = item.is_new
    ? "新增"
    : state.view === "graphic" ? "图文广告" : "园林绿化";
  const link = fragment.querySelector(".record-link");
  link.href = item.url || "#";
  link.textContent = item.project_name || item.title || "未载明";
  const facts = fragment.querySelector(".record-facts");
  addFact(facts, "采购人/招标人", item.buyer);
  addFact(facts, "代理机构", item.agency);
  addFact(facts, "预算", item.budget);
  addFact(facts, "项目编号", item.project_code);
  addFact(facts, "投标截止", item.bid_deadline);
  addFact(facts, "地区", item.location);
  fragment.querySelector(".record-content").textContent = truncate(item.project_content);
  const category = industryCategory(state.view);
  addTags(fragment.querySelector(".record-tags"), item.category_keyword_matches?.[category] || item.matched_keywords);
  return fragment;
}

function renderPlan(item, index) {
  const fragment = $("#record-template").content.cloneNode(true);
  fragment.querySelector(".record-index").textContent = String(index + 1).padStart(2, "0");
  fragment.querySelector("time").textContent = text(dateText(item.published_at));
  fragment.querySelector(".record-source").textContent = text(item.source_name);
  fragment.querySelector(".record-badge").textContent = isUltraLong(item) ? "超长期" : "招标计划";
  const link = fragment.querySelector(".record-link");
  link.href = item.url || "#";
  link.textContent = item.project_name || item.title || "未载明";
  const facts = fragment.querySelector(".record-facts");
  addFact(facts, "招标人", item.buyer);
  addFact(facts, "投资估算", item.budget);
  addFact(facts, "资金来源", item.fund_source);
  addFact(facts, "投资项目代码", item.fixed_asset_code);
  addFact(facts, "预计招标", item.planned_bid_time);
  addFact(facts, "建设地点", item.project_location || item.region);
  fragment.querySelector(".record-content").textContent = text(item.project_content);
  addTags(fragment.querySelector(".record-tags"), item.fund_source_tags);
  return fragment;
}

function renderStatus() {
  const list = $("#list");
  list.className = "status-grid";
  const datasets = state.status?.datasets || {};
  Object.entries(datasets).forEach(([key, dataset]) => {
    const card = document.createElement("article");
    card.className = `status-card ${dataset.warning_count ? "bad" : ""}`;
    const title = document.createElement("h3");
    title.textContent = key === "industries" ? "图文广告与园林绿化"
      : key === "construction" ? "施工标讯粗筛" : "招标计划";
    const facts = document.createElement("dl");
    addFact(facts, "更新时间", dataset.updated_at);
    addFact(facts, "记录数量", dataset.stats?.total ?? dataset.stats?.merged_total);
    addFact(facts, "告警数量", dataset.warning_count);
    const warnings = document.createElement("ul");
    (dataset.warnings || []).forEach((warning) => {
      const item = document.createElement("li");
      item.textContent = warning;
      warnings.append(item);
    });
    card.append(title, facts);
    if (warnings.children.length) card.append(warnings);
    list.append(card);
  });
  const tests = state.status?.tests;
  const testCard = document.createElement("article");
  testCard.className = `status-card ${tests?.ok === false ? "bad" : ""}`;
  const testTitle = document.createElement("h3");
  testTitle.textContent = "测试门禁";
  const testText = document.createElement("p");
  testText.textContent = tests?.ok === true ? "全部测试通过" : tests?.ok === false ? "测试失败，未允许发布" : "本次仅重建页面，未运行测试";
  testCard.append(testTitle, testText);
  list.append(testCard);
  $("#result-count").textContent = list.children.length;
  $("#empty").hidden = list.children.length > 0;
}

function showWarning(messages) {
  const warning = $("#warning");
  const values = (messages || []).filter(Boolean);
  warning.hidden = values.length === 0;
  warning.textContent = values.slice(0, 8).join("；");
}

function updateFilterVisibility() {
  const isStatus = state.view === "status";
  $("#filters").hidden = isStatus;
  $("#match-source-strip").hidden = state.view !== "matches";
  $("#source-strip").hidden = state.view !== "construction";
  $("#fund-strip").hidden = state.view !== "plans";
  document.querySelectorAll("[data-views]").forEach((element) => {
    element.hidden = !element.dataset.views.split(",").includes(state.view);
  });
}

async function render() {
  const meta = VIEW_META[state.view];
  $("#view-kicker").textContent = meta.kicker;
  $("#view-title").textContent = meta.title;
  $("#result-label").textContent = meta.label;
  updateFilterVisibility();
  $("#load-more").hidden = true;
  const list = $("#list");
  list.className = "record-list";
  list.replaceChildren();

  if (state.view === "status") {
    showWarning([]);
    renderStatus();
    return;
  }

  let records = [];
  let renderer;
  if (state.view === "matches") {
    if (!state.matchFiltersReady) populateMatchFilters(state.matches.items || []);
    renderSourceStrip(
      (state.matches.items || []).map((entry) => entry.notice || {}),
      "#match-source-strip",
      "#match-source",
      state.matches.available_sources || []
    );
    records = filterMatches(state.matches.items);
    renderer = renderMatch;
  } else if (state.view === "graphic" || state.view === "landscaping") {
    const payload = await ensureDataset("industries");
    populateIndustryFilters(industryItems(payload.items || []));
    records = filterIndustry(payload.items);
    renderer = renderIndustry;
    showWarning(payload.warnings);
  } else if (state.view === "construction") {
    const payload = await ensureDataset("construction");
    if (!state.constructionFiltersReady) populateConstructionFilters(payload.items || []);
    renderSourceStrip(payload.items || [], "#source-strip", "#construction-source");
    records = filterConstruction(payload.items);
    renderer = renderConstruction;
    showWarning(payload.warnings);
  } else {
    const payload = await ensureDataset("plans");
    const projects = groupedPlans(payload.items || []);
    if (!state.planFiltersReady) populatePlanFilters(projects);
    renderFundStrip(projects);
    records = filterPlans(payload.items);
    renderer = renderPlan;
    showWarning(payload.warnings);
  }

  if (state.view === "matches") {
    showWarning(Object.values(state.status?.datasets || {}).flatMap((dataset) => dataset.warnings || []));
  }
  const limit = state.shown;
  records.slice(0, limit).forEach((record, index) => list.append(renderer(record, index)));
  $("#result-count").textContent = records.length;
  $("#empty").hidden = records.length > 0;
  $("#load-more").hidden = records.length <= limit;
}

function updateScoreboard() {
  const summary = state.manifest.summary || {};
  $("#score-matches").textContent = summary.priority_notices || 0;
  $("#score-graphic").textContent = summary.graphic_items || 0;
  $("#score-landscaping").textContent = summary.landscaping_items || 0;
  $("#score-construction").textContent = summary.construction_items || 0;
  $("#score-plans").textContent = summary.plan_notices || 0;
  const datasets = state.status?.datasets || {};
  const warningCount = Object.values(datasets).reduce((total, dataset) => total + Number(dataset.warning_count || 0), 0);
  const collectionFailed = Object.values(state.status?.collection || {}).some((result) => result && !result.ok);
  const testsFailed = state.status?.tests?.ok === false;
  const healthy = warningCount === 0 && !collectionFailed && !testsFailed;
  $("#score-health").textContent = healthy ? "正常" : "告警";
  $("#health-card").className = healthy ? "healthy" : "warning-health";
  const updated = state.manifest.updated_at ? new Date(state.manifest.updated_at) : null;
  $("#updated-at").textContent = updated
    ? `页面生成 ${updated.toLocaleString("zh-CN", { hour12: false })}`
    : "更新时间未知";
}

async function switchView(view) {
  state.view = view;
  state.shown = 50;
  document.querySelectorAll(".desk-tabs button").forEach((button) => {
    button.classList.toggle("active", button.dataset.view === view);
  });
  await render();
}

async function load() {
  try {
    state.manifest = await fetchJson("./data/manifest.json");
    [state.matches, state.status] = await Promise.all([
      fetchJson(state.manifest.datasets.matches),
      fetchJson(state.manifest.datasets.status)
    ]);
    updateScoreboard();
    await render();
  } catch (error) {
    showWarning([error.message]);
  }
}

document.querySelectorAll(".desk-tabs button").forEach((button) => {
  button.addEventListener("click", () => switchView(button.dataset.view));
});

[
  "search", "match-region", "match-date-range", "match-source", "match-reg-date",
  "match-cutoff-date", "match-qualification", "construction-region", "construction-date-range",
  "construction-source", "construction-reg-date", "construction-cutoff-date",
  "construction-qualification", "plan-district", "plan-date-range", "plan-planned-month",
  "industry-date-range", "industry-source"
].forEach((id) => {
  const element = $(`#${id}`);
  element.addEventListener(element.tagName === "INPUT" ? "input" : "change", () => {
    state.shown = 50;
    render();
  });
});

$("#plan-prefecture").addEventListener("change", () => {
  updatePlanDistricts();
  state.shown = 50;
  render();
});

$("#reset").addEventListener("click", () => {
  $("#search").value = "";
  if (state.view === "matches") {
    ["match-region", "match-source", "match-reg-date", "match-cutoff-date", "match-qualification"]
      .forEach((id) => { $(`#${id}`).value = ""; });
    $("#match-date-range").value = "7";
  } else if (state.view === "graphic" || state.view === "landscaping") {
    $("#industry-date-range").value = "7";
    $("#industry-source").value = "";
  } else if (state.view === "construction") {
    ["construction-region", "construction-source", "construction-reg-date", "construction-cutoff-date", "construction-qualification"]
      .forEach((id) => { $(`#${id}`).value = ""; });
    $("#construction-date-range").value = "1";
  } else if (state.view === "plans") {
    ["plan-prefecture", "plan-district", "plan-planned-month"].forEach((id) => { $(`#${id}`).value = ""; });
    $("#plan-date-range").value = "all";
    state.activeFund = "";
    updatePlanDistricts();
  }
  state.shown = 50;
  render();
});

$("#load-more").addEventListener("click", () => {
  state.shown += 50;
  render();
});

load();
