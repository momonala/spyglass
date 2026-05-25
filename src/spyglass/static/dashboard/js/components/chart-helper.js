/**
 * Shared chart lifecycle management.
 * Handles ResizeObserver and cleanup for responsive charts.
 */

export function createResponsiveChartManager(body) {
  let chart = null;

  const resizeObserver = new ResizeObserver(() => {
    if (chart) {
      chart.setSize({ width: body.clientWidth, height: 220 });
    }
  });
  resizeObserver.observe(body);

  return {
    setChart: (c) => { chart = c; },
    getChart: () => chart,
    destroy: () => {
      resizeObserver.disconnect();
      if (chart) chart.destroy();
    },
  };
}
