const REPOSITORY = "nono125-lee/guizhou-tender-daily";
const STORAGE_KEY = "construction-tender-feedback-v1";
const FIELD_LABELS = {
  title: "项目名称",
  budget: "预算",
  buyer: "采购人",
  agency: "采购代理机构",
  bid_deadline: "投标截止时间",
  registration_period: "报名日期",
  source_name: "信息源名称",
  project_content: "项目主要内容"
};
const state = { items: [], feedback: [], processedIds: new Set(), dialog: null };

const $ = (selector) => document.querySelector(selector);
const daysAgo = (days) => {
  const date = new Date();
  date.setHours(0, 0, 0, 0);
  date.setDate(date.getDate() - days);
  return date;
};

function regionOf(item) {
  const text = `${item.location || ""} ${item.title || ""}`;
  const regions = [
    "贵阳", "遵义", "六盘水", "安顺", "毕节", "铜仁",
    "黔南", "黔东南", "黔西南", "贵安"
  ];
  return regions.find((name) => text.includes(name)) || "贵州省";
}

function updateRegions(items) {
  const select = $("#region");
  [...new Set(items.map(regionOf))].sort().forEach((region) => {
    const option = document.createElement("option");
    option.value = region;
    option.textContent = region;
    select.append(option);
  });
}

function loadLocalFeedback() {
  try {
    state.feedback = JSON.parse(localStorage.getItem(STORAGE_KEY) || "[]");
  } catch {
    state.feedback = [];
  }
}

function saveLocalFeedback() {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(state.feedback));
  updateFeedbackPanel();
}

function pendingFeedback() {
  return state.feedback.filter((event) => !state.processedIds.has(event.id));
}

function updateFeedbackPanel() {
  const pending = pendingFeedback();
  $("#feedback-count").textContent = pending.length;
  $("#feedback-status").textContent = pending.length
    ? `已记录 ${pending.length} 项，点击“当日反馈”提交`
    : "尚未填写反馈";
}

function snapshot(item) {
  return {
    published_at: item.published_at || "",
    date_basis: item.date_basis || "",
    title: item.title || "",
    url: item.url || "",
    budget: item.budget || "",
    buyer: item.buyer || "",
    agency: item.agency || "",
    bid_deadline: item.bid_deadline || "",
    registration_period: item.registration_period || "",
    source_name: item.source_name || "",
    project_content: item.project_content || "",
    location: item.location || "",
    matched_keywords: item.matched_keywords || []
  };
}

function addFeedback(item, action, details = {}) {
  const event = {
    id: crypto.randomUUID(),
    action,
    url: item.url,
    item: snapshot(item),
    created_at: new Date().toISOString(),
    ...details
  };
  state.feedback.push(event);
  saveLocalFeedback();
  return event;
}

function latestLocalStatus(url) {
  return pendingFeedback()
    .filter((event) => event.url === url && ["confirm", "exclude"].includes(event.action))
    .at(-1);
}

function localCorrections(url) {
  const corrections = {};
  pendingFeedback()
    .filter((event) => event.url === url && event.action === "correct")
    .forEach((event) => { corrections[event.field] = event.new_value; });
  return corrections;
}

function itemWithLocalFeedback(item) {
  return { ...item, ...localCorrections(item.url) };
}

function openDialog(item, mode, field = "") {
  const dialog = $("#feedback-dialog");
  const corrected = itemWithLocalFeedback(item);
  state.dialog = { item, mode, field };
  $("#dialog-project").textContent = corrected.title;
  if (mode === "exclude") {
    $("#dialog-title").textContent = "排除标讯";
    $("#dialog-label").textContent = "请填写不是有效标讯的原因";
    $("#dialog-value").value = "";
    $("#dialog-value").placeholder = "例如：资质词不在资格要求栏目中，或项目名称属于监理项目";
  } else {
    $("#dialog-title").textContent = `纠正${FIELD_LABELS[field]}`;
    $("#dialog-label").textContent = `当前内容：${corrected[field] || "未填写"}`;
    $("#dialog-value").value = corrected[field] || "";
    $("#dialog-value").placeholder =
      field === "bid_deadline" ? "2026-06-10 18:00"
        : field === "registration_period" ? "2026-06-08至2026-06-10"
          : `填写正确的${FIELD_LABELS[field]}`;
  }
  dialog.showModal();
  $("#dialog-value").focus();
}

function saveDialog() {
  const value = $("#dialog-value").value.trim();
  if (!value || !state.dialog) {
    $("#dialog-value").reportValidity();
    return;
  }
  const { item, mode, field } = state.dialog;
  if (mode === "exclude") {
    addFeedback(item, "exclude", { reason: value });
  } else {
    const corrected = itemWithLocalFeedback(item);
    addFeedback(item, "correct", {
      field,
      old_value: corrected[field] || "",
      new_value: value
    });
  }
  $("#feedback-dialog").close();
  state.dialog = null;
  render();
}

function issueBody(events) {
  const counts = {
    confirm: events.filter((event) => event.action === "confirm").length,
    exclude: events.filter((event) => event.action === "exclude").length,
    correct: events.filter((event) => event.action === "correct").length
  };
  const humanLines = events.map((event) => {
    const title = event.item?.title || event.url;
    if (event.action === "confirm") return `- 确认：${title}`;
    if (event.action === "exclude") return `- 排除：${title}；原因：${event.reason}`;
    return `- 纠正：${title}；${FIELD_LABELS[event.field]}：${event.old_value || "空"} → ${event.new_value}`;
  });
  const compactEvents = events.map((event) => ({
    ...event,
    item: {
      url: event.item?.url || event.url,
      title: event.item?.title || ""
    }
  }));
  const machine = JSON.stringify({
    schema_version: 1,
    submitted_at: new Date().toISOString(),
    events: compactEvents
  });
  return [
    `本次反馈：确认 ${counts.confirm} 条，排除 ${counts.exclude} 条，纠正 ${counts.correct} 项。`,
    "",
    ...humanLines,
    "",
    "以下数据供系统自动处理，请勿修改：",
    `<!-- TENDER_FEEDBACK_JSON\n${machine}\n-->`
  ].join("\n");
}

function submitFeedback() {
  const events = pendingFeedback();
  if (!events.length) {
    alert("当前没有待提交的反馈。");
    return;
  }
  const date = new Intl.DateTimeFormat("zh-CN", {
    timeZone: "Asia/Shanghai",
    year: "numeric",
    month: "2-digit",
    day: "2-digit"
  }).format(new Date()).replaceAll("/", "-");
  const params = new URLSearchParams({
    title: `施工标讯当日反馈 ${date}`,
    body: issueBody(events),
    labels: "construction-tender-feedback"
  });
  window.location.href = `https://github.com/${REPOSITORY}/issues/new?${params}`;
}

function render() {
  const query = $("#search").value.trim().toLowerCase();
  const region = $("#region").value;
  const cutoff = daysAgo(Number($("#date-range").value));
  const items = state.items.filter((item) => {
    const text = [
      item.title, item.project_content, item.summary, item.buyer, item.location,
      item.agency,
      ...(item.matched_keywords || [])
    ].join(" ").toLowerCase();
    const published = new Date(`${item.published_at.slice(0, 10)}T00:00:00`);
    return (!query || text.includes(query))
      && (!region || regionOf(item) === region)
      && published >= cutoff;
  });

  const list = $("#list");
  list.replaceChildren();
  $("#empty").hidden = items.length > 0;
  const template = $("#card-template");
  items.forEach((item, index) => {
    const displayItem = itemWithLocalFeedback(item);
    const card = template.content.cloneNode(true);
    card.querySelector(".card-index").textContent = String(index + 1).padStart(2, "0");
    card.querySelector(".date-label").textContent =
      item.date_basis === "official" ? "官方发布时间" : "采集日期";
    card.querySelector("time").textContent = item.published_at.slice(0, 10);
    card.querySelector(".location").textContent = regionOf(item);
    const article = card.querySelector(".tender-card");
    article.classList.toggle("is-new", Boolean(item.is_new));
    card.querySelector(".new-badge").hidden = !item.is_new;
    const titleLink = card.querySelector("h3 a");
    titleLink.textContent = displayItem.title;
    titleLink.href = item.url;
    const fields = [
      [".budget-row", ".budget", displayItem.budget],
      [".deadline-row", ".deadline", displayItem.bid_deadline],
      [".registration-row", ".registration", displayItem.registration_period],
      [".source-row", ".source", displayItem.source_name]
    ];
    fields.forEach(([, value, content]) => {
      card.querySelector(value).textContent = content || "公告未载明";
    });
    card.querySelector(".buyer").textContent = displayItem.buyer || "公告未载明";
    card.querySelector(".agency").textContent = displayItem.agency || "公告未载明";
    card.querySelector(".project-content").textContent =
      displayItem.project_content || "公告未载明";
    card.querySelector(".qualification-requirement").textContent =
      displayItem.qualification_requirement || "公告未载明";
    const keywords = card.querySelector(".keywords");
    (item.matched_keywords || []).slice(0, 8).forEach((keyword) => {
      const tag = document.createElement("span");
      tag.textContent = keyword;
      keywords.append(tag);
    });
    card.querySelector(".read-more").href = item.url;
    card.querySelectorAll(".correct-button").forEach((button) => {
      button.addEventListener("click", () => openDialog(item, "correct", button.dataset.field));
    });
    card.querySelector(".confirm-button").addEventListener("click", () => {
      addFeedback(item, "confirm");
      render();
    });
    card.querySelector(".exclude-button").addEventListener("click", () => {
      openDialog(item, "exclude");
    });
    const localStatus = latestLocalStatus(item.url);
    const reviewState = card.querySelector(".review-state");
    const status = localStatus?.action || item.review_status;
    if (status === "confirm" || status === "confirmed") {
      article.classList.add("is-confirmed");
      reviewState.textContent = localStatus ? "待提交：已确认有效" : "已确认有效";
    } else if (status === "exclude" || status === "excluded") {
      article.classList.add("is-excluded");
      reviewState.textContent = localStatus ? "待提交：将排除" : "已排除";
    } else if ((item.corrected_fields || []).length || Object.keys(localCorrections(item.url)).length) {
      reviewState.textContent = "已有字段纠正";
    }
    article.style.animationDelay = `${Math.min(index * 35, 350)}ms`;
    list.append(card);
  });
}

async function load() {
  try {
    loadLocalFeedback();
    const [response, feedbackResponse] = await Promise.all([
      fetch(`./data/latest.json?v=${Date.now()}`),
      fetch(`./data/feedback-state.json?v=${Date.now()}`)
    ]);
    if (!response.ok) throw new Error("日报数据读取失败");
    const payload = await response.json();
    if (feedbackResponse.ok) {
      const feedbackState = await feedbackResponse.json();
      state.processedIds = new Set(feedbackState.processed_event_ids || []);
      state.feedback = state.feedback.filter((event) => !state.processedIds.has(event.id));
      saveLocalFeedback();
    }
    state.items = payload.items || [];
    const updated = new Date(payload.updated_at);
    $("#update-date").textContent = `更新：${updated.toLocaleString("zh-CN", {
      timeZone: "Asia/Shanghai",
      hour12: false
    })}`;
    if (payload.warnings?.length) {
      $("#warning").textContent = payload.warnings.join("；");
      $("#warning").hidden = false;
    }
    updateRegions(state.items);
    render();
  } catch (error) {
    $("#warning").textContent = `${error.message}，请稍后刷新。`;
    $("#warning").hidden = false;
  }
}

["search", "region", "date-range"].forEach((id) => {
  $(`#${id}`).addEventListener(id === "search" ? "input" : "change", render);
});

$("#dialog-save").addEventListener("click", saveDialog);
$("#submit-feedback").addEventListener("click", submitFeedback);

load();
