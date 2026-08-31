let setup = {};
let selectedShip = null;
let leafletMap = null;
let routeLayer = null;
let planRequestId = 0;
let sourceState = {
  query: "",
  factType: null,
  sortKey: "fact_type",
  sortDir: 1
};
const $ = id => document.getElementById(id);
const SHIP_ICON = `
<svg viewBox="0 0 48 48" fill="none" aria-hidden="true">
  <path d="M6 30 L10 22 H38 L42 30M4 30H44L40 38H8Z"
        stroke="currentColor" stroke-width="2"/>
  <rect x="15" y="14" width="6" height="8"
        stroke="currentColor" stroke-width="2"/>
  <rect x="24" y="10" width="6" height="12"
        stroke="currentColor" stroke-width="2"/>
</svg>`;
async function getJSON(url) {
  const response = await fetch(url);
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.error || `Request failed: ${response.status}`);
  }
  return data;
}
function programsFor(shipId) {
  return setup.programs
    .filter(program => program.ship_id === shipId)
    .sort((a, b) => a.nights - b.nights);
}
const CRUISE_TYPE_DISPLAY = {
  "WEEKEND": "Short getaway"
};
function updateNightChoices() {
  const programs = programsFor(selectedShip);
  $("nights").innerHTML = programs.map(program => `
    <option value="${program.nights}">
      ${program.nights} nights · ${CRUISE_TYPE_DISPLAY[program.cruise_type] || program.cruise_type}
    </option>
  `).join("");
}
async function init() {
  try {
    initDatePicker();
    setup = await getJSON("/api/setup");
    selectedShip = setup.ships[0].ship_id;
    renderShips();
    updateNightChoices();
    setupSourceControls();
    $("evaluateBtn").addEventListener("click", generatePlan);
    await generatePlan();
  } catch (error) {
    showError(error);
  }
}
function initDatePicker() {
  const start = $("start");
  const trigger = $("dateTrigger");
  const popup = $("datePopup");
  const label = $("dateLabel");
  const monthLabel = $("monthLabel");
  const days = $("calendarDays");
  const previousMonth = $("previousMonth");
  const nextMonth = $("nextMonth");
  const todayButton = $("todayButton");
  if (
    !start ||
    !trigger ||
    !popup ||
    !label ||
    !monthLabel ||
    !days ||
    !previousMonth ||
    !nextMonth ||
    !todayButton
  ) {
    console.error("Date-picker HTML elements are missing.");
    return;
  }
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  let selected = new Date(today);
  let visible = new Date(
    today.getFullYear(),
    today.getMonth(),
    1
  );
  const iso = date => [
    date.getFullYear(),
    String(date.getMonth() + 1).padStart(2, "0"),
    String(date.getDate()).padStart(2, "0")
  ].join("-");
  function closeCalendar() {
    popup.hidden = true;
    trigger.setAttribute("aria-expanded", "false");
  }
  function chooseDate(date) {
    selected = new Date(date);
    visible = new Date(
      date.getFullYear(),
      date.getMonth(),
      1
    );
    start.value = iso(selected);
    label.textContent = selected.toLocaleDateString(undefined, {
      month: "short",
      day: "numeric",
      year: "numeric"
    });
    start.dispatchEvent(
      new Event("change", { bubbles: true })
    );
    closeCalendar();
    renderCalendar();
  }
  function renderCalendar() {
    days.innerHTML = "";
    monthLabel.textContent = visible.toLocaleDateString(undefined, {
      month: "long",
      year: "numeric"
    });
    const year = visible.getFullYear();
    const month = visible.getMonth();
    const firstDay = new Date(year, month, 1).getDay();
    const lastDay = new Date(year, month + 1, 0).getDate();
    for (let index = 0; index < firstDay; index += 1) {
      days.append(document.createElement("span"));
    }
    for (let day = 1; day <= lastDay; day += 1) {
      const date = new Date(year, month, day);
      const button = document.createElement("button");
      button.type = "button";
      button.textContent = day;
      button.disabled = date < today;
      button.setAttribute(
        "aria-label",
        date.toLocaleDateString()
      );
      if (iso(date) === iso(selected)) {
        button.classList.add("selected");
        button.setAttribute("aria-current", "date");
      }
      button.addEventListener("click", () => {
        chooseDate(date);
      });
      days.append(button);
    }
    const previousMonthEnd = new Date(
      year,
      month,
      0
    );
    previousMonth.disabled = previousMonthEnd < today;
  }
  trigger.addEventListener("click", event => {
    event.stopPropagation();
    popup.hidden = !popup.hidden;
    trigger.setAttribute(
      "aria-expanded",
      String(!popup.hidden)
    );
    if (!popup.hidden) {
      renderCalendar();
    }
  });
  previousMonth.addEventListener("click", event => {
    event.stopPropagation();
    visible = new Date(
      visible.getFullYear(),
      visible.getMonth() - 1,
      1
    );
    renderCalendar();
  });
  nextMonth.addEventListener("click", event => {
    event.stopPropagation();
    visible = new Date(
      visible.getFullYear(),
      visible.getMonth() + 1,
      1
    );
    renderCalendar();
  });
  todayButton.addEventListener("click", event => {
    event.stopPropagation();
    chooseDate(today);
  });
  popup.addEventListener("click", event => {
    event.stopPropagation();
  });
  document.addEventListener("click", event => {
    if (!event.target.closest(".custom-date")) {
      closeCalendar();
    }
  });
  document.addEventListener("keydown", event => {
    if (event.key === "Escape") {
      closeCalendar();
      trigger.focus();
    }
  });
  chooseDate(today);
}
function renderShips() {
  $("shipGrid").innerHTML = setup.ships.map(ship => {
    const isSelected = ship.ship_id === selectedShip;
    return `
      <button
        class="ship-card ${isSelected ? "selected" : ""}"
        data-ship="${ship.ship_id}"
      >
        <div class="ship-ribbon">
          <span>${ship.ship_class} class</span>
          <span>
            ${
              ship.service_year > new Date().getFullYear()
                ? "Future debut"
                : `Since ${ship.service_year}`
            }
          </span>
        </div>
        <div class="ship-body">
          <div class="ship-top">
            <h3>${ship.ship_name}</h3>
            <div class="ship-icon">${SHIP_ICON}</div>
          </div>
          <div class="ship-stats">
            <div>
              Guests
              <b>${ship.double_occupancy_guests.toLocaleString()}</b>
            </div>
            <div>
              Draft
              <b>${Number(ship.draft_m).toFixed(2)} m*</b>
            </div>
            <div>
              GT
              <b>${ship.gross_tonnage.toLocaleString()}</b>
            </div>
            <div>
              Crew
              <b>${ship.crew.toLocaleString()}</b>
            </div>
          </div>
          <div class="ship-score">
            Ship-size experience score
            <b>
              ${Number(ship.model_size_experience_score).toFixed(2)}/5*
            </b>
          </div>
        </div>
      </button>
    `;
  }).join("");
  document.querySelectorAll("[data-ship]").forEach(card => {
    card.addEventListener("click", async () => {
      selectedShip = card.dataset.ship;
      renderShips();
      updateNightChoices();
      await generatePlan();
    });
  });
}
async function generatePlan() {
  const requestId = ++planRequestId;
  const button = $("evaluateBtn");
  button.disabled = true;
  button.textContent = "Screening…";
  try {
    const parameters = new URLSearchParams({
      ship_id: selectedShip,
      start: $("start").value,
      nights: $("nights").value,
      objective: $("objective").value
    });
    const data = await getJSON(
      `/api/generate-plan?${parameters}`
    );
    if (requestId !== planRequestId) {
      return;
    }
    renderPlan(data);
  } catch (error) {
    if (requestId === planRequestId) {
      showError(error);
    }
  } finally {
    if (requestId === planRequestId) {
      button.disabled = false;
      button.textContent = "Compare Plans";
    }
  }
}

function summarizeSeason(days) {
  const portDays = days.filter(day => day.port_id && !day.homeport_flag);
  if (!portDays.length) return null;
  const distinctMonths = [
    ...new Set(portDays.map(day => day.season_month_label))
  ];
  if (distinctMonths.length === 1) {
    const day = portDays[0];
    return {
      chip: `${day.season_month_label} · ${day.season_label} · ${day.seasonality_multiplier}x`,
      isMulti: false
    };
  }
  const perMonth = distinctMonths
    .map(month => {
      const day = portDays.find(d => d.season_month_label === month);
      return `${month} ${day.seasonality_multiplier}x`;
    })
    .join(" → ");
  return {
    chip: `Spans ${distinctMonths.join("–")} · ${perMonth} combined average`,
    isMulti: true
  };
}
function renderPlan(data) {
  const best = data.candidates[0];
  const metrics = best.metrics;
  const evidenceClass =
    best.evidence_status.toLowerCase();
  const seasonSummary = summarizeSeason(best.days);
  $("summary").innerHTML = `
    <div class="signal-light ${
      metrics.conflicts.length ? "stop" : "go"
    }"></div>
    <div>
      <span class="eyebrow">
        ${CRUISE_TYPE_DISPLAY[data.cruise_type] || data.cruise_type} ·
        ${
          best.sailing_type === "ROUNDTRIP"
            ? "Miami roundtrip"
            : `One-way: Miami to ${best.destination}`
        }
      </span>
      <h2>
        ${data.ship.ship_name} · ${data.nights} nights
      </h2>
      <p class="sub">
        Score ${metrics.score}/100 ·
        ${metrics.distance_nm.toLocaleString()} nautical miles ·
        ${metrics.sea_days} sea days ·
        ~${metrics.modeled_sailing_hours} modeled sailing hours
      </p>
      <span class="tag ${evidenceClass}">
        ${
          best.evidence_status === "VERIFIED"
            ? "Observed itinerary pattern"
            : "Sample planning case"
        }
      </span>
      ${
        seasonSummary
          ? `<span class="season-chip">${seasonSummary.chip}</span>`
          : ""
      }
    </div>
    <div class="conflict-count">
      <b>${metrics.conflicts.length}</b>
      <span>screening conflicts</span>
    </div>
    <div class="economics-row">
      <div class="econ-item">
        <b>
          $${metrics.average_guest_spend_per_day.toLocaleString()}
        </b>
        <span>Guest spend / day ${
          seasonSummary && seasonSummary.isMulti
            ? "(seasonal avg, spans months)"
            : "(seasonal)"
        }</span>
      </div>
      <div class="econ-item">
        <b>
          $${metrics.total_modeled_guest_spend.toLocaleString()}
        </b>
        <span>Total modeled guest spend</span>
      </div>
      <div class="econ-item">
        <b>
          $${metrics.total_modeled_port_fees.toLocaleString()}
        </b>
        <span>Total modeled port fees</span>
      </div>
      <div class="econ-item">
        <b>${metrics.blended_experience_score}/100</b>
        <span>
          Blended experience
          (ship ${metrics.ship_size_experience_score}/5)
        </span>
      </div>
    </div>
  `;
  $("aiPanel").innerHTML = `
    <div>
      <span class="eyebrow">
        ${
          data.ai_used
            ? "Gemini-assisted explanation"
            : "Rule-based explanation"
        }
      </span>
      <h3>Recommendation</h3>
      <p>${data.recommendation}</p>
      <small>${data.assumption_note}</small>
    </div>
  `;
  const remaining = data.candidates.length - 1;
  const compareHint = document.querySelector(".compare-hint");
  if (compareHint) {
    if (remaining <= 0) {
      compareHint.textContent = "";
      compareHint.style.display = "none";
    } else {
      compareHint.style.display = "";
      compareHint.textContent =
        remaining === 1
          ? "One more option, ranked below the recommendation:"
          : `${remaining} more options, ranked below the recommendation:`;
    }
  }
  $("candidateGrid").innerHTML = data.candidates
    .slice(1)
    .map((candidate, i) => {
      const index = i + 1;
      return `
        <button
          class="candidate"
          data-candidate="${index}"
        >
          <div class="candidate-ribbon">
            ${
              candidate.sailing_type === "ROUNDTRIP"
                ? "Roundtrip from Miami"
                : `One-way to ${candidate.destination}`
            }
          </div>
          <div class="candidate-body">
            <b>Option ${index + 1}</b>
            <span>${candidate.route_name}</span>
            <small>
              ${candidate.metrics.score}/100 ·
              ${candidate.metrics.distance_nm.toLocaleString()} nm ·
              max leg
              ${candidate.metrics.max_leg_nm.toLocaleString()} nm ·
              ${candidate.metrics.sea_days} sea days
            </small>
            <small>
              $${candidate.metrics.average_guest_spend_per_day.toLocaleString()}
              /guest/day ·
              $${candidate.metrics.total_modeled_port_fees.toLocaleString()}
              total fees ·
              exp ${candidate.metrics.blended_experience_score}/100
            </small>
            <small class="evidence-label ${
              candidate.evidence_status.toLowerCase()
            }">
              ${
                candidate.evidence_status === "VERIFIED"
                  ? "Published pattern"
                  : "Sample case"
              }
            </small>
          </div>
        </button>
      `;
    })
    .join("");
  document
    .querySelectorAll("[data-candidate]")
    .forEach(button => {
      button.addEventListener("click", () => {
        document
          .querySelectorAll(".candidate")
          .forEach(item => item.classList.remove("active"));
        button.classList.add("active");
        renderCandidate(
          data.candidates[
            Number(button.dataset.candidate)
          ],
          data.nights,
          false
        );
      });
    });
  renderCandidate(best, data.nights, true);
}
function renderCandidate(candidate, nights, isTopRanked) {
  const metrics = candidate.metrics;
  $("scheduleTitle").textContent = isTopRanked
    ? "Your itinerary — recommended option"
    : `Your itinerary — ${candidate.route_name}`;
  $("calendar").innerHTML = candidate.days.map(day => `
    <article class="day ${day.status}">
      <div class="day-top">
        <b>Day ${day.day_number}</b>
        <span>
          ${new Date(`${day.date}T12:00`).toLocaleDateString(
            "en-US",
            {
              weekday: "short",
              month: "short",
              day: "numeric"
            }
          )}
        </span>
      </div>
      <h3>${day.port_name}</h3>
      ${
        day.port_id
          ? `
            <div class="metrics">
              ${
                day.homeport_flag
                  ? "Miami homeport"
                  : `
                    Modeled rating
                    ${Number(day.model_guest_rating).toFixed(1)}/5 ·
                    cost index
                    ${Number(day.model_port_cost_index).toFixed(0)}/100
                  `
              }
            </div>
            <div class="metrics">
              Draft screen
              ${Number(day.max_draft_m).toFixed(1)} m ·
              ${day.projected_calls || 1}/${day.model_daily_ship_limit} modeled slots
            </div>
            ${
              !day.homeport_flag
                ? `
                  <div class="day-economics">
                    <div class="econ-chip">
                      <b>
                        $${Number(
                          day.adjusted_guest_spend_per_guest || 0
                        ).toFixed(0)}
                      </b>
                      <span>Spend / guest</span>
                    </div>
                    <div class="econ-chip">
                      <b>
                        $${Number(
                          day.model_port_fee_usd || 0
                        ).toFixed(0)}
                      </b>
                      <span>Port fee / guest</span>
                    </div>
                  </div>
                  ${
                    day.season_month_label
                      ? `
                        <span class="season-chip">
                          ${day.season_month_label} ·
                          ${day.season_label} ·
                          ${day.seasonality_multiplier}x
                        </span>
                      `
                      : ""
                  }
                `
                : ""
            }
            <span class="tag ${
              (
                day.port_evidence_status || "sample"
              ).toLowerCase()
            }">
              ${
                day.port_evidence_status === "VERIFIED"
                  ? "Observed ship-port pairing"
                  : "Sample / modeled"
              }
            </span>
          `
          : `
            <div class="metrics">
              Onboard programming and sailing time
            </div>
          `
      }
      <small class="reason">${day.reason}</small>
    </article>
  `).join("");
  drawMap(candidate.days);
}
function drawMap(days) {
  const points = days.filter(
    day => day.latitude !== null
  );
  if (!points.length) return;
  if (!leafletMap) {
    leafletMap = L.map("mapView", {
      scrollWheelZoom: false
    });
    L.tileLayer(
      "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
      {
        maxZoom: 12,
        attribution:
          '&copy; <a href="https://www.openstreetmap.org/copyright">' +
          "OpenStreetMap</a> contributors"
      }
    ).addTo(leafletMap);
  }
  if (routeLayer) {
    routeLayer.remove();
  }
  const latLngs = points.map(point => [
    Number(point.latitude),
    Number(point.longitude)
  ]);
  const markers = points.map(point => {
    const isHome = Boolean(point.homeport_flag);
    return L.circleMarker(
      [
        Number(point.latitude),
        Number(point.longitude)
      ],
      {
        radius: isHome ? 9 : 7,
        fillColor: isHome ? "#128A56" : "#0B2D63",
        fillOpacity: 1,
        color: "white",
        weight: 2
      }
    ).bindTooltip(
      `
        <b>${point.port_name}</b><br>
        Day ${point.day_number}
        ${isHome ? " · Homeport" : ""}
      `,
      {
        direction: "top",
        offset: [0, -6]
      }
    );
  });
  const line = L.polyline(latLngs, {
    color: "#1657C4",
    weight: 3,
    dashArray: "7 6"
  });
  routeLayer = L
    .layerGroup([line, ...markers])
    .addTo(leafletMap);
  setTimeout(() => {
    leafletMap.invalidateSize();
    leafletMap.fitBounds(
      line.getBounds(),
      { padding: [36, 36] }
    );
  }, 30);
}
function setupSourceControls() {
  const factTypes = [
    ...new Set(
      setup.sources.map(source => source.fact_type)
    )
  ];
  $("sourceFilterChips").innerHTML = `
    <button
      class="chip ${!sourceState.factType ? "active" : ""}"
      data-filter=""
    >
      All
    </button>
    ${factTypes.map(type => `
      <button
        class="chip ${
          sourceState.factType === type ? "active" : ""
        }"
        data-filter="${type}"
      >
        ${type}
      </button>
    `).join("")}
  `;
  $("sourceFilterChips")
    .querySelectorAll("[data-filter]")
    .forEach(chip => {
      chip.addEventListener("click", () => {
        sourceState.factType =
          chip.dataset.filter || null;
        renderSources();
      });
    });
  $("sourceSearch").addEventListener("input", event => {
    sourceState.query =
      event.target.value.trim().toLowerCase();
    renderSources();
  });
  document
    .querySelectorAll("th[data-key]")
    .forEach(header => {
      header.addEventListener("click", () => {
        const key = header.dataset.key;
        if (sourceState.sortKey === key) {
          sourceState.sortDir *= -1;
        } else {
          sourceState.sortKey = key;
          sourceState.sortDir = 1;
        }
        renderSources();
      });
    });
  renderSources();
}
function renderSources() {
  const query = sourceState.query;
  let list = setup.sources.filter(source =>
    (
      !sourceState.factType ||
      source.fact_type === sourceState.factType
    ) &&
    (
      !query ||
      `${source.source_title} ${source.publisher}`
        .toLowerCase()
        .includes(query)
    )
  );
  const key = sourceState.sortKey;
  const direction = sourceState.sortDir;
  list = list.slice().sort((a, b) => {
    if (a[key] < b[key]) return -1 * direction;
    if (a[key] > b[key]) return direction;
    return 0;
  });
  document
    .querySelectorAll("th[data-key]")
    .forEach(header => {
      header.classList.toggle(
        "sorted",
        header.dataset.key === key
      );
      header.dataset.dir =
        header.dataset.key === key
          ? direction
          : "";
    });
  $("sources").innerHTML = list.length
    ? list.map(source => `
        <tr>
          <td>
            <span class="tag ${
              source.fact_type.toLowerCase()
            }">
              ${source.fact_type}
            </span>
          </td>
          <td>${source.source_url
            ? `<a href="${source.source_url}" target="_blank" rel="noopener">${source.source_title}</a>`
            : `<span>${source.source_title}</span>`}
          </td>
          <td>${source.publisher}</td>
          <td>
            ${String(source.accessed_date).slice(0, 10)}
          </td>
        </tr>
      `).join("")
    : `
        <tr>
          <td colspan="4" class="no-results">
            No sources match that search.
          </td>
        </tr>
      `;
}
function showError(error) {
  $("summary").innerHTML = `
    <div>
      <h2>Planner error</h2>
      <p>${error.message}</p>
      <small>
        Check the Flask terminal for details.
      </small>
    </div>
  `;
  console.error(error);
}
init();