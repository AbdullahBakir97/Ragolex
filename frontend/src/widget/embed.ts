// The script websites embed:
//   <script src="https://<web app>/widget.js" data-widget="wgt_…" async></script>
// Optional attributes: data-api (where the API is, if not where the script
// is), data-position="left", data-open="true". The page can then call
// window.RagolexWidget.open() and .close().

import { WidgetError } from "./client";
import { ChatWidget, type WidgetOptions } from "./widget";

let instance: ChatWidget | null = null;

/** Show a widget on the page; resolves to null when it cannot be used (the console says why). */
export async function mount(options: WidgetOptions): Promise<ChatWidget | null> {
  instance?.destroy();
  try {
    instance = await ChatWidget.mount(options);
  } catch (error) {
    instance = null;
    const signal = error instanceof WidgetError ? error.signal : String(error);
    const hint =
      signal === "origin_not_allowed"
        ? ` Add ${location.origin} to the widget's allowed origins.`
        : signal === "widget_not_found"
          ? " Check the data-widget attribute."
          : "";
    console.warn(`Chat widget ${options.widgetId} is not shown: ${signal}.${hint}`);
  }
  return instance;
}

export function open(): void {
  instance?.open();
}

export function close(): void {
  instance?.close();
}

function sessionStore(): Storage | null {
  try {
    return window.sessionStorage;
  } catch {
    return null;
  }
}

const script = document.currentScript as HTMLScriptElement | null;
const widgetId = script?.dataset.widget;
if (script && widgetId) {
  const options: WidgetOptions = {
    widgetId,
    apiBase: script.dataset.api ?? new URL(script.src, location.href).origin,
    position: script.dataset.position === "left" ? "left" : "right",
    open: script.dataset.open === "true",
    storage: sessionStore(),
  };
  if (document.body) void mount(options);
  else document.addEventListener("DOMContentLoaded", () => void mount(options), { once: true });
}
