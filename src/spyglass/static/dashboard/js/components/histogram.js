import { fetchHistogram } from "../api.js";
import { createWidgetShell, setWidgetChartBody, setWidgetStatus } from "./base.js";
import { createResponsiveChartManager } from "./chart-helper.js";

function toHistogramData(bins) {
  const xIndices = bins.map((_, i) => i + 1);
  const counts = bins.map((bin) => bin.count);
  return [xIndices, counts];
}

function binRangeLabel(bin) {
  return `${bin.start.toFixed(2)}–${bin.end.toFixed(2)}`;
}

export function createHistogramWidget(widget, context, onRemove) {
  const { card, body } = createWidgetShell(widget, onRemove);
  const chartMgr = createResponsiveChartManager(body);

  async function render() {
    setWidgetStatus(body, "Loading…");
    try {
      const histogram = await fetchHistogram(context.project, widget.metric_name, context.from, context.to);
      if (!histogram.bins.length) {
        setWidgetStatus(body, "No data in selected range");
        return;
      }

      setWidgetChartBody(body);
      if (chartMgr.getChart()) {
        chartMgr.getChart().destroy();
      }

      const style = getComputedStyle(document.documentElement);
      const seriesColor = style.getPropertyValue("--success").trim() || "#30d158";
      const axisStroke = "rgba(235,235,245,0.3)";
      const gridStroke = "rgba(84,84,88,0.4)";

      const chart = new uPlot(
        {
          width: body.clientWidth,
          height: 220,
          series: [
            {},
            {
              label: "count",
              stroke: seriesColor,
              width: 1,
              fill: `${seriesColor}55`,
            },
          ],
          axes: [
            {
              stroke: axisStroke,
              grid: { stroke: gridStroke },
              values: (_, ticks) =>
                ticks.map((tick) => {
                  const bin = histogram.bins[Math.round(tick) - 1];
                  return bin ? bin.start.toFixed(2) : "";
                }),
            },
            { stroke: axisStroke, grid: { stroke: gridStroke } },
          ],
          cursor: { points: { show: false } },
          plugins: [
            {
              hooks: {
                setCursor: (u) => {
                  const idx = u.cursor.idx;
                  if (idx != null && histogram.bins[idx]) {
                    u.root.title = binRangeLabel(histogram.bins[idx]);
                  }
                },
              },
            },
          ],
        },
        toHistogramData(histogram.bins),
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
