import { createCounterWidget } from "./counter.js";
import { createHistogramWidget } from "./histogram.js";
import { createTimeseriesWidget } from "./timeseries.js";

const WIDGET_FACTORIES = {
  counter: createCounterWidget,
  timeseries: createTimeseriesWidget,
  histogram: createHistogramWidget,
};

export function createWidgetElement(widget, context, onRemove) {
  const factory = WIDGET_FACTORIES[widget.type];
  if (!factory) {
    const fallback = document.createElement("article");
    fallback.className = "widget-card";
    fallback.textContent = `Unknown widget type: ${widget.type}`;
    return fallback;
  }
  return factory(widget, context, onRemove);
}

export function destroyWidgetElement(element) {
  if (typeof element.__destroy === "function") {
    element.__destroy();
  }
}
