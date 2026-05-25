import { fetchSeries } from "../api.js";
import { createWidgetShell, setWidgetChartBody, setWidgetStatus } from "./base.js";
import { createResponsiveChartManager } from "./chart-helper.js";

function toChartData(points) {
  const timestamps = [];
  const values = [];
  points.forEach((point) => {
    timestamps.push(Math.floor(new Date(point.timestamp).getTime() / 1000));
    values.push(point.value);
  });
  return [timestamps, values];
}

export function createTimeseriesWidget(widget, context, onRemove) {
  const { card, body } = createWidgetShell(widget, onRemove);
  const chartMgr = createResponsiveChartManager(body);

  async function render() {
    setWidgetStatus(body, "Loading…");
    try {
      const series = await fetchSeries(context.project, widget.metric_name, context.from, context.to);
      if (!series.points.length) {
        setWidgetStatus(body, "No data in selected range");
        return;
      }

      setWidgetChartBody(body);
      if (chartMgr.getChart()) {
        chartMgr.getChart().destroy();
      }

      const style = getComputedStyle(document.documentElement);
      const accent = style.getPropertyValue("--accent").trim() || "#0a84ff";
      const axisStroke = "rgba(235,235,245,0.3)";
      const gridStroke = "rgba(84,84,88,0.4)";

      const chart = new uPlot(
        {
          width: body.clientWidth,
          height: 220,
          series: [{}, { label: "value", stroke: accent, width: 2 }],
          axes: [
            { stroke: axisStroke, grid: { stroke: gridStroke } },
            { stroke: axisStroke, grid: { stroke: gridStroke } },
          ],
        },
        toChartData(series.points),
        body,
      );
      chartMgr.setChart(chart);
    } catch (error) {
      setWidgetStatus(body, error.message, true);
    }
  }

  render();
  card.__destroy = () => chartMgr.destroy();
  return card;
}
