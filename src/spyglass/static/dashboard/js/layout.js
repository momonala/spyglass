import { createWidgetElement, destroyWidgetElement } from "./components/registry.js";

const LAYOUT_VERSION = 1;

export function createLayoutState() {
  return {
    version: LAYOUT_VERSION,
    widgets: [],
  };
}

export function addWidget(layout, widget) {
  layout.widgets.push(widget);
  return layout;
}

export function removeWidget(layout, widgetId) {
  layout.widgets = layout.widgets.filter((widget) => widget.id !== widgetId);
  return layout;
}

export function createWidgetId() {
  if (globalThis.crypto?.randomUUID) {
    return globalThis.crypto.randomUUID();
  }
  return `widget-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

export function renderWidgets(container, layout, context, onRemove) {
  container.replaceChildren();
  layout.widgets.forEach((widget) => {
    const element = createWidgetElement(widget, context, () => onRemove(widget.id));
    container.appendChild(element);
  });
}

export function destroyWidgets(container) {
  container.querySelectorAll("[data-widget-id]").forEach((element) => {
    destroyWidgetElement(element);
  });
}

export function widgetTypesForMetric(metricType) {
  const types = ["timeseries"];
  if (metricType === "counter" || metricType === "gauge") {
    types.push("counter");
  }
  if (metricType === "timing") {
    types.push("histogram");
  }
  return types;
}

export function defaultTitle(metricName) {
  const parts = metricName.split(".");
  return parts[parts.length - 1] || metricName;
}
