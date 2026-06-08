const state = { items: [] };

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

function render() {
  const query = $("#search").value.trim().toLowerCase();
  const region = $("#region").value;
  const cutoff = daysAgo(Number($("#date-range").value));
  const items = state.items.filter((item) => {
    const text = [
      item.title, item.project_content, item.summary, item.buyer, item.location,
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
    const card = template.content.cloneNode(true);
    card.querySelector(".card-index").textContent = String(index + 1).padStart(2, "0");
    card.querySelector("time").textContent = item.published_at.slice(0, 10);
    card.querySelector(".location").textContent = regionOf(item);
    const titleLink = card.querySelector("h3 a");
    titleLink.textContent = item.title;
    titleLink.href = item.url;
    const fields = [
      [".budget-row", ".budget", item.budget],
      [".buyer-row", ".buyer", item.buyer],
      [".deadline-row", ".deadline", item.bid_deadline],
      [".registration-row", ".registration", item.registration_period],
      [".source-row", ".source", item.source_name]
    ];
    fields.forEach(([row, value, content]) => {
      card.querySelector(row).hidden = !content;
      card.querySelector(value).textContent = content || "";
    });
    card.querySelector(".project-content").textContent =
      item.project_content || item.summary || "请查看原公告了解具体内容。";
    const keywords = card.querySelector(".keywords");
    (item.matched_keywords || []).slice(0, 8).forEach((keyword) => {
      const tag = document.createElement("span");
      tag.textContent = keyword;
      keywords.append(tag);
    });
    card.querySelector(".read-more").href = item.url;
    const article = card.querySelector(".tender-card");
    article.style.animationDelay = `${Math.min(index * 35, 350)}ms`;
    list.append(card);
  });
}

async function load() {
  try {
    const response = await fetch(`./data/latest.json?v=${Date.now()}`);
    if (!response.ok) throw new Error("日报数据读取失败");
    const payload = await response.json();
    state.items = payload.items || [];
    const updated = new Date(payload.updated_at);
    $("#update-date").textContent = `更新：${updated.toLocaleString("zh-CN", {
      timeZone: "Asia/Shanghai",
      hour12: false
    })}`;
    $("#coverage").textContent = payload.coverage || "";
    $("#total-count").textContent = payload.stats?.total ?? state.items.length;
    $("#today-count").textContent = payload.stats?.new_today ?? 0;
    $("#source-count").textContent = payload.stats?.sources ?? 0;
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

load();
