import { fetchSummary } from "../api.js";
import { createWidgetShell, setWidgetStatus } from "./base.js";

function formatValue(value) {
  if (value === null || value === undefined) {
    return "—";
  }
  if (Number.isInteger(value)) {
    return String(value);
  }
  return value.toFixed(2);
}

export function createCounterWidget(widget, context, onRemove) {
  const { card, body } = createWidgetShell(widget, onRemove);

  async function render() {
    setWidgetStatus(body, "Loading…");
    try {
      const summary = await fetchSummary(
        context.project,
        widget.metric_name,
        context.from,
        context.to,
      );
      body.className = "widget-card__body";
      body.replaceChildren();

      const value = document.createElement("div");
      value.className = "counter-value";
      value.textContent = formatValue(summary.latest_value);

      const label = document.createElement("div");
      label.className = "counter-label";
      if (summary.metric_type === "counter") {
        label.textContent = `Window sum: ${formatValue(summary.window_sum)}`;
      } else {
        label.textContent = "Latest value";
      }

      body.append(value, label);
    } catch (error) {
      setWidgetStatus(body, error.message, true);
    }
  }

  render();
  card.__destroy = () => {};
  return card;
}
