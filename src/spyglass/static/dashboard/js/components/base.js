export function createWidgetShell(widget, onRemove) {
  const card = document.createElement("article");
  card.className = "widget-card";
  card.dataset.widgetId = widget.id;

  const header = document.createElement("div");
  header.className = "widget-card__header";

  const titleWrap = document.createElement("div");
  const title = document.createElement("h3");
  title.className = "widget-card__title";
  title.textContent = widget.title;

  const meta = document.createElement("p");
  meta.className = "widget-card__meta";
  meta.textContent = widget.metric_name;

  titleWrap.append(title, meta);

  const removeButton = document.createElement("button");
  removeButton.type = "button";
  removeButton.className = "widget-card__remove";
  removeButton.setAttribute("aria-label", "Remove widget");
  removeButton.textContent = "×";
  removeButton.addEventListener("click", onRemove);

  header.append(titleWrap, removeButton);

  const body = document.createElement("div");
  body.className = "widget-card__body";

  card.append(header, body);
  return { card, body };
}

export function setWidgetStatus(body, message, isError = false) {
  body.className = "widget-card__body";
  body.replaceChildren();
  const status = document.createElement("p");
  status.className = isError ? "widget-card__status widget-card__status--error" : "widget-card__status";
  status.textContent = message;
  body.append(status);
}

export function setWidgetChartBody(body) {
  body.className = "widget-card__body widget-card__body--chart";
  body.replaceChildren();
}
