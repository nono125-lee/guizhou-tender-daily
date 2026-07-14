const FUND_KEYWORD_FILTERS = ["国债", "专项", "中央", "省级"];
const FUND_TAG_ORDER = [
  ...FUND_KEYWORD_FILTERS,
  "超长期",
  "政府投资",
  "财政资金",
  "上级补助",
  "国有资金",
  "专项债",
  "地方自筹",
  "企业自筹",
  "银行贷款",
  "社会资本",
  "其他",
  "未载明"
];
const PREFECTURE_LABELS = {
  "贵阳市": "贵阳",
  "六盘水市": "六盘水",
  "遵义市": "遵义",
  "安顺市": "安顺",
  "毕节市": "毕节",
  "铜仁市": "铜仁",
  "黔西南布依族苗族自治州": "黔西南",
  "黔东南苗族侗族自治州": "黔东南",
  "黔南布依族苗族自治州": "黔南",
  "贵安新区": "贵安"
};
const state = { items: [], projects: [], priorityNotices: [], payload: null, activeButton: "" };
const $ = (selector) => document.querySelector(selector);

function valueOrBlank(value) {
  return value && String(value).trim() ? String(value).trim() : "未载明";
}

function parseDate(value) {
  const text = (value || "").slice(0, 10);
  const date = new Date(`${text}T00:00:00+08:00`);
  return Number.isNaN(date.getTime()) ? null : date;
}

function projectName(item) {
  return String(item.project_name || item.title || "")
    .normalize("NFKC")
    .replace(/\s+/g, " ")
    .trim();
}

function groupProjects(items) {
  const groups = new Map();
  items.forEach((item) => {
    const name = projectName(item);
    const key = name || `notice:${item.source_notice_id || item.url}`;
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(item);
  });

  return [...groups.entries()]
    .map(([key, versions]) => {
      versions.sort((a, b) => {
        const dateOrder = (b.published_at || "").localeCompare(a.published_at || "");
        if (dateOrder) return dateOrder;
        return (b.source_notice_id || "").localeCompare(a.source_notice_id || "");
      });
      return { key, latest: versions[0], history: versions.slice(1), versions };
    })
    .sort((a, b) => {
      const dateOrder = (b.latest.published_at || "").localeCompare(a.latest.published_at || "");
      if (dateOrder) return dateOrder;
      return a.key.localeCompare(b.key, "zh-CN");
    });
}

function attachPriorityNotices(projects, priorityNotices) {
  const byPlanNoticeId = new Map();
  priorityNotices.forEach((entry) => {
    const candidates = entry.candidate_plans?.length
      ? entry.candidate_plans
      : [{ plan: entry.plan }];
    candidates.forEach((candidate) => {
      const id = String(candidate.plan?.source_notice_id || "");
      if (!id) return;
      if (!byPlanNoticeId.has(id)) byPlanNoticeId.set(id, []);
      if (!byPlanNoticeId.get(id).includes(entry)) byPlanNoticeId.get(id).push(entry);
    });
  });
  projects.forEach((project) => {
    const linked = [];
    project.versions.forEach((version) => {
      linked.push(...(byPlanNoticeId.get(String(version.source_notice_id || "")) || []));
    });
    project.priorityNotices = linked;
  });
  return projects;
}

function daysAgo(days) {
  const date = new Date();
  date.setHours(0, 0, 0, 0);
  date.setDate(date.getDate() - Number(days));
  return date;
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

function isUltraLongBond(item) {
  return /超长期(?:特别)?国债|特别国债/.test(item.fund_source || "");
}

function matchesFundFilter(item, filter) {
  if (FUND_KEYWORD_FILTERS.includes(filter)) return (item.fund_source || "").includes(filter);
  if (filter === "超长期") return isUltraLongBond(item);
  return (item.fund_source_tags || []).includes(filter);
}

function populateFilters(items) {
  optionList($("#prefecture"), [...new Set(items.map(prefectureOf))]);
  updateDistrictOptions();
  optionList($("#source"), [...new Set(items.map((item) => item.source_name))]);
}

function updateDistrictOptions() {
  const prefecture = $("#prefecture").value;
  const values = state.items
    .filter((item) => !prefecture || prefectureOf(item) === prefecture)
    .map(districtOf);
  optionList($("#district"), [...new Set(values)]);
}

function updateStats(payload, projects) {
  const stats = payload.stats || {};
  $("#stat-total").textContent = stats.total || 0;
  $("#stat-source").textContent = stats.source_total || 0;
  const rawNewToday = state.items.filter((item) => item.is_new).length;
  const uniqueNewToday = projects.filter((project) => project.versions.some((item) => item.is_new)).length;
  $("#stat-new").textContent = uniqueNewToday;
  $("#stat-new").parentElement.title = rawNewToday === uniqueNewToday
    ? `今日原始公告 ${rawNewToday} 条`
    : `今日原始公告 ${rawNewToday} 条，按同名项目去重后 ${uniqueNewToday} 个`;
  $("#stat-regions").textContent = stats.regions || 0;
  $("#stat-priority").textContent = stats.priority_projects || 0;
  $("#source-link").href = payload.source_url || $("#source-link").href;
  const updated = payload.updated_at ? new Date(payload.updated_at) : null;
  $("#updated-at").textContent = updated
    ? `更新 ${updated.toLocaleString("zh-CN", { hour12: false })}`
    : "更新未知";
  if (payload.warnings?.length) {
    $("#warning").hidden = false;
    $("#warning").textContent = payload.warnings.slice(0, 6).join("；");
  }
}

function renderPrioritySection() {
  const section = $("#priority-section");
  const list = $("#priority-list");
  list.replaceChildren();
  section.hidden = state.priorityNotices.length === 0;
  $("#priority-count").textContent = state.priorityNotices.length;
  if (!state.priorityNotices.length) return;

  state.priorityNotices.forEach((entry, index) => {
    const plan = entry.plan || {};
    const notice = entry.notice || {};
    const match = entry.match || {};
    const candidates = entry.candidate_plans?.length
      ? entry.candidate_plans
      : [{ plan, match }];
    const template = $("#priority-card").content.cloneNode(true);
    const article = template.querySelector(".priority-card");
    if (notice.is_new) article.classList.add("is-new");
    if (match.review_required) article.classList.add("needs-review");
    template.querySelector("time").textContent = valueOrBlank((notice.published_at || "").slice(0, 10));
    template.querySelector(".priority-source").textContent = valueOrBlank(notice.source_name);
    template.querySelector(".priority-confidence").textContent = match.review_required
      ? `候选需复核 · ${Math.round((match.confidence || 0) * 100)}%`
      : `高可信 · ${Math.round((match.confidence || 0) * 100)}%`;
    const title = template.querySelector(".priority-notice-link");
    title.href = notice.url;
    title.textContent = notice.project_name || notice.title;
    template.querySelector(".priority-plan-name").textContent = candidates.length > 1
      ? `可能关联 ${candidates.length} 个重点资金计划；首要候选：${plan.project_name || plan.title || "未载明"}`
      : `关联重点资金计划：${plan.project_name || plan.title || "未载明"}`;
    template.querySelector(".priority-review-note").textContent = valueOrBlank(match.review_note);
    template.querySelector(".priority-buyer").textContent = valueOrBlank(notice.buyer);
    template.querySelector(".priority-code").textContent = valueOrBlank(notice.project_code);
    template.querySelector(".priority-keywords").textContent = valueOrBlank((notice.matched_keywords || []).join("、"));
    template.querySelector(".priority-evidence").textContent = valueOrBlank((match.evidence || []).join("；"));
    if (candidates.length > 1) {
      const details = template.querySelector(".priority-candidates");
      const candidateList = template.querySelector(".priority-candidate-list");
      details.hidden = false;
      template.querySelector(".priority-candidate-count").textContent = `${candidates.length} 个`;
      candidates.forEach((candidate) => {
        const item = document.createElement("li");
        const link = document.createElement("a");
        const description = document.createElement("span");
        link.href = candidate.plan?.url || "#";
        link.target = "_blank";
        link.rel = "noopener noreferrer";
        link.textContent = candidate.plan?.project_name || candidate.plan?.title || "未载明";
        description.textContent = (candidate.match?.evidence || []).join("；");
        item.append(link, description);
        candidateList.append(item);
      });
    }
    const noticeButton = template.querySelector(".priority-notice-button");
    noticeButton.href = notice.url;
    const planLink = template.querySelector(".priority-plan-link");
    planLink.href = plan.url;
    article.style.animationDelay = `${Math.min(index * 40, 240)}ms`;
    list.append(template);
  });
}

function passFilters(item) {
  const query = $("#search").value.trim().toLowerCase();
  const prefecture = $("#prefecture").value;
  const district = $("#district").value;
  const source = $("#source").value;
  const dateRange = $("#date-range").value;
  const plannedMonth = $("#planned-month").value;
  const button = state.activeButton;
  const haystack = [
    item.title,
    item.project_name,
    item.buyer,
    item.agency,
    item.project_content,
    item.project_location,
    item.fund_source,
    ...(item.fund_source_tags || [])
  ].join(" ").toLowerCase();
  const published = parseDate(item.published_at);
  const passDate = dateRange === "all" || (published && published >= daysAgo(dateRange));
  const passPlanned = !plannedMonth || (item.planned_bid_time || "").startsWith(plannedMonth);
  const passButton = !button
    || matchesFundFilter(item, button);
  return (!query || haystack.includes(query))
    && (!prefecture || prefectureOf(item) === prefecture)
    && (!district || districtOf(item) === district)
    && (!source || item.source_name === source)
    && passDate
    && passPlanned
    && passButton;
}

function renderFundStrip() {
  const counts = new Map();
  const latestItems = state.projects.map((project) => project.latest);
  latestItems.forEach((item) => {
    (item.fund_source_tags || ["未载明"]).forEach((tag) => counts.set(tag, (counts.get(tag) || 0) + 1));
  });
  FUND_KEYWORD_FILTERS.forEach((keyword) => {
    counts.set(keyword, latestItems.filter((item) => matchesFundFilter(item, keyword)).length);
  });
  counts.set("超长期", latestItems.filter(isUltraLongBond).length);
  const strip = $("#fund-strip");
  strip.replaceChildren();
  const allTags = [...new Set([...FUND_TAG_ORDER, ...counts.keys()])];
  allTags
    .sort((a, b) => {
      const ai = FUND_TAG_ORDER.indexOf(a);
      const bi = FUND_TAG_ORDER.indexOf(b);
      if (ai >= 0 || bi >= 0) return (ai < 0 ? 999 : ai) - (bi < 0 ? 999 : bi);
      return a.localeCompare(b, "zh-CN");
    })
    .forEach((tag) => {
      const button = document.createElement("button");
      button.type = "button";
      button.innerHTML = `<span>${tag}</span><strong>${counts.get(tag) || 0}</strong>`;
      button.className = state.activeButton === tag ? "active" : "";
      button.addEventListener("click", () => {
        state.activeButton = state.activeButton === tag ? "" : tag;
        render();
      });
      strip.append(button);
    });
}

function renderHistory(template, history) {
  if (!history.length) return;
  const details = template.querySelector(".version-history");
  const count = template.querySelector(".history-count");
  const list = template.querySelector(".history-list");
  details.hidden = false;
  count.textContent = `${history.length} 条`;

  history.forEach((item) => {
    const row = document.createElement("li");
    const link = document.createElement("a");
    const meta = document.createElement("span");
    link.href = item.url;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    link.textContent = `${valueOrBlank((item.published_at || "").slice(0, 10))} · 查看原公告`;
    meta.textContent = [
      `预计招标：${valueOrBlank(item.planned_bid_time)}`,
      `投资估算：${valueOrBlank(item.budget)}`
    ].join(" / ");
    row.append(link, meta);
    list.append(row);
  });
}

function renderCard(project, index) {
  const item = project.latest;
  const template = $("#plan-card").content.cloneNode(true);
  const article = template.querySelector(".plan-card");
  if (item.is_new) article.classList.add("is-new");
  if (project.priorityNotices?.length) article.classList.add("has-priority-notice");
  template.querySelector(".card-no").textContent = String(index + 1).padStart(2, "0");
  template.querySelector("time").textContent = valueOrBlank((item.published_at || "").slice(0, 10));
  template.querySelector(".region").textContent = valueOrBlank(item.region);
  template.querySelector(".notice-type").textContent = valueOrBlank(item.notice_type);
  const title = template.querySelector("h2 a");
  title.href = item.url;
  title.textContent = item.project_name || item.title;
  template.querySelector(".buyer").textContent = valueOrBlank(item.buyer);
  template.querySelector(".agency").textContent = valueOrBlank(item.agency);
  template.querySelector(".planned-time").textContent = valueOrBlank(item.planned_bid_time);
  template.querySelector(".budget").textContent = valueOrBlank(item.budget);
  template.querySelector(".planned-content").textContent = `拟招标内容：${valueOrBlank(item.planned_tender_content)}`;
  template.querySelector(".fund-source").textContent = valueOrBlank(item.fund_source);
  template.querySelector(".location").textContent = valueOrBlank(item.project_location || item.region);
  template.querySelector(".content").textContent = valueOrBlank(item.project_content);
  const tags = template.querySelector(".tag-row");
  (item.fund_source_tags || ["未载明"]).forEach((tag) => {
    const chip = document.createElement("span");
    chip.textContent = tag;
    tags.append(chip);
  });
  if (project.priorityNotices?.length) {
    const chip = document.createElement("a");
    chip.className = "priority-chip";
    chip.href = project.priorityNotices[0].notice?.url || item.url;
    chip.target = "_blank";
    chip.rel = "noopener noreferrer";
    const allNeedReview = project.priorityNotices.every((entry) => entry.match?.review_required);
    chip.textContent = allNeedReview
      ? `施工公告候选 ${project.priorityNotices.length} 条`
      : `已出施工公告 ${project.priorityNotices.length} 条`;
    tags.prepend(chip);
  }
  const open = template.querySelector(".open-link");
  open.href = item.url;
  renderHistory(template, project.history);
  article.style.animationDelay = `${Math.min(index * 24, 260)}ms`;
  return template;
}

function render() {
  const projects = state.projects
    .filter((project) => passFilters(project.latest))
    .sort((a, b) => {
      const priorityOrder = Number(Boolean(b.priorityNotices?.length)) - Number(Boolean(a.priorityNotices?.length));
      if (priorityOrder) return priorityOrder;
      return (b.latest.published_at || "").localeCompare(a.latest.published_at || "");
    });
  const list = $("#list");
  list.replaceChildren();
  $("#result-count").textContent = projects.length;
  $("#empty").hidden = projects.length > 0;
  renderFundStrip();
  projects.forEach((project, index) => list.append(renderCard(project, index)));
}

async function load() {
  try {
    const response = await fetch(`./data/latest.json?v=${Date.now()}`);
    if (!response.ok) throw new Error("数据读取失败");
    const payload = await response.json();
    state.payload = payload;
    state.items = payload.items || [];
    state.priorityNotices = payload.priority_notices || [];
    state.projects = attachPriorityNotices(groupProjects(state.items), state.priorityNotices);
    updateStats(payload, state.projects);
    populateFilters(state.projects.map((project) => project.latest));
    renderPrioritySection();
    render();
  } catch (error) {
    $("#warning").hidden = false;
    $("#warning").textContent = `${error.message}。`;
  }
}

["search", "district", "date-range", "source", "planned-month"].forEach((id) => {
  const element = $(`#${id}`);
  element.addEventListener(element.tagName === "INPUT" ? "input" : "change", render);
});

$("#prefecture").addEventListener("change", () => {
  updateDistrictOptions();
  render();
});

$("#reset").addEventListener("click", () => {
  ["search", "prefecture", "district", "source", "planned-month"].forEach((id) => { $(`#${id}`).value = ""; });
  $("#date-range").value = "all";
  state.activeButton = "";
  updateDistrictOptions();
  render();
});

load();
