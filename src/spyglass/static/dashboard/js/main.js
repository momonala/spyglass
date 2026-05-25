import {
  fetchLayout,
  fetchMetricNames,
  fetchProjects,
  rangeToWindow,
  saveLayout,
} from "./api.js";
import {
  addWidget,
  createLayoutState,
  createWidgetId,
  defaultTitle,
  destroyWidgets,
  removeWidget,
  renderWidgets,
  widgetTypesForMetric,
} from "./layout.js";

const projectSelect = document.getElementById("project-select");
const rangeSelect = document.getElementById("range-select");
const addWidgetBtn = document.getElementById("add-widget-btn");
const saveLayoutBtn = document.getElementById("save-layout-btn");
const widgetGrid = document.getElementById("widget-grid");
const statusBanner = document.getElementById("status-banner");
const addWidgetDialog = document.getElementById("add-widget-dialog");
const addWidgetForm = document.getElementById("add-widget-form");
const closeDialogBtn = document.getElementById("close-dialog-btn");
const metricSelect = document.getElementById("metric-select");
const metricSearch = document.getElementById("metric-search");
const widgetTypeSelect = document.getElementById("widget-type-select");
const widgetTitleInput = document.getElementById("widget-title-input");

let layout = createLayoutState();
let metricCatalog = [];

function showStatus(message, isError = false) {
  statusBanner.hidden = false;
  statusBanner.textContent = message;
  statusBanner.className = isError ? "status-banner status-banner--error" : "status-banner";
}

function clearStatus() {
  statusBanner.hidden = true;
  statusBanner.textContent = "";
  statusBanner.className = "status-banner";
}

function currentContext() {
  const window = rangeToWindow(rangeSelect.value);
  return {
    project: projectSelect.value,
    from: window.from,
    to: window.to,
  };
}

function refreshWidgets() {
  destroyWidgets(widgetGrid);
  renderWidgets(widgetGrid, layout, currentContext(), handleRemoveWidget);
}

async function loadProjects() {
  const projects = await fetchProjects();
  projectSelect.replaceChildren();
  projects.forEach((project) => {
    const option = document.createElement("option");
    option.value = project.slug;
    option.textContent = project.name;
    projectSelect.append(option);
  });
  if (!projects.length) {
    showStatus("No projects found in data/. Register or copy project data first.");
  }
}

async function loadMetricCatalog() {
  if (!projectSelect.value) {
    metricCatalog = [];
    return;
  }
  metricCatalog = await fetchMetricNames(projectSelect.value);
}

async function loadLayoutForProject() {
  if (!projectSelect.value) {
    layout = createLayoutState();
    refreshWidgets();
    return;
  }
  layout = await fetchLayout(projectSelect.value);
  refreshWidgets();
}

function populateMetricSelect() {
  metricSelect.replaceChildren();
  metricCatalog.forEach((metric) => {
    const option = document.createElement("option");
    option.value = metric.name;
    option.textContent = `${metric.name} (${metric.metric_type})`;
    option.dataset.metricType = metric.metric_type;
    option.dataset.searchText = `${metric.name} ${metric.metric_type}`.toLowerCase();
    metricSelect.append(option);
  });
  metricSearch.value = "";
}

function filterMetricSelect() {
  const query = metricSearch.value.toLowerCase();
  const options = metricSelect.querySelectorAll("option");
  let visibleCount = 0;
  options.forEach((option) => {
    const matches = option.dataset.searchText.includes(query);
    option.hidden = !matches;
    if (matches) visibleCount++;
  });
  if (visibleCount > 0 && !metricSelect.value) {
    metricSelect.value = [...options].find((o) => !o.hidden)?.value || "";
  }
}

function populateWidgetTypeSelect() {
  const selectedOption = metricSelect.selectedOptions[0];
  const metricType = selectedOption?.dataset.metricType;
  const allowedTypes = metricType ? widgetTypesForMetric(metricType) : ["timeseries"];

  widgetTypeSelect.replaceChildren();
  allowedTypes.forEach((type) => {
    const option = document.createElement("option");
    option.value = type;
    option.textContent = type;
    widgetTypeSelect.append(option);
  });
}

function openAddWidgetDialog() {
  if (!projectSelect.value) {
    showStatus("Select a project before adding widgets.", true);
    return;
  }
  if (!metricCatalog.length) {
    showStatus("No metrics available for this project.", true);
    return;
  }
  populateMetricSelect();
  populateWidgetTypeSelect();
  widgetTitleInput.value = defaultTitle(metricSelect.value);
  addWidgetDialog.showModal();
}

function handleRemoveWidget(widgetId) {
  removeWidget(layout, widgetId);
  refreshWidgets();
}

async function handleSaveLayout() {
  if (!projectSelect.value) {
    showStatus("Select a project before saving.", true);
    return;
  }
  try {
    layout = await saveLayout(projectSelect.value, layout);
    showStatus("Dashboard saved.");
  } catch (error) {
    showStatus(error.message, true);
  }
}

async function handleAddWidget(event) {
  event.preventDefault();
  const metricName = metricSelect.value;
  const widgetType = widgetTypeSelect.value;
  const title = widgetTitleInput.value.trim() || defaultTitle(metricName);

  addWidget(layout, {
    id: createWidgetId(),
    type: widgetType,
    metric_name: metricName,
    title,
  });
  addWidgetDialog.close();
  clearStatus();
  refreshWidgets();
}

async function bootstrap() {
  try {
    await loadProjects();
    await loadMetricCatalog();
    await loadLayoutForProject();
  } catch (error) {
    showStatus(error.message, true);
  }
}

projectSelect.addEventListener("change", async () => {
  clearStatus();
  try {
    await loadMetricCatalog();
    await loadLayoutForProject();
  } catch (error) {
    showStatus(error.message, true);
  }
});

rangeSelect.addEventListener("change", () => {
  refreshWidgets();
});

addWidgetBtn.addEventListener("click", openAddWidgetDialog);
saveLayoutBtn.addEventListener("click", handleSaveLayout);
closeDialogBtn.addEventListener("click", () => addWidgetDialog.close());
addWidgetForm.addEventListener("submit", handleAddWidget);
metricSelect.addEventListener("change", () => {
  populateWidgetTypeSelect();
  widgetTitleInput.value = defaultTitle(metricSelect.value);
});

metricSearch.addEventListener("input", filterMetricSelect);

bootstrap();
