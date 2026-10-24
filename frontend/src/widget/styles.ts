// The widget's styles. They live in its shadow root, so the host page's
// styles cannot reach in, and these cannot leak out.

export const STYLES = `
:host {
  all: initial;
  --accent: #2563eb;
  --on-accent: #ffffff;
  --bg: #ffffff;
  --surface: #f3f4f6;
  --text: #111827;
  --muted: #4b5563;
  --border: #e5e7eb;
  --danger: #b91c1c;
  --shadow: 0 12px 40px rgba(15, 23, 42, 0.18), 0 2px 8px rgba(15, 23, 42, 0.08);
}
@media (prefers-color-scheme: dark) {
  :host {
    --bg: #111827;
    --surface: #1f2937;
    --text: #f3f4f6;
    --muted: #9ca3af;
    --border: #374151;
    --danger: #f87171;
    --shadow: 0 12px 40px rgba(0, 0, 0, 0.5);
  }
}
* { box-sizing: border-box; }
button { font: inherit; color: inherit; cursor: pointer; }
button:focus-visible, textarea:focus-visible, summary:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 2px;
}
[hidden] { display: none !important; }

/* Set here, not on :host, which the page's own styles can still reach. */
.root {
  position: fixed; bottom: 20px; right: 20px; z-index: 2147483000;
  font-family: system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
  font-size: 15px; font-weight: 400; font-style: normal; line-height: 1.5;
  letter-spacing: normal; text-align: left; text-transform: none; color: var(--text);
}
.root.left { right: auto; left: 20px; }
.root.inline { position: relative; bottom: auto; right: auto; left: auto; z-index: auto; height: 100%; }

.launcher {
  width: 56px; height: 56px; border-radius: 50%; border: none;
  background: var(--accent); color: var(--on-accent);
  display: grid; place-items: center; box-shadow: var(--shadow);
  transition: transform 0.15s ease;
}
.launcher:hover { transform: scale(1.05); }
.launcher svg { width: 26px; height: 26px; }

.panel {
  position: absolute; bottom: 72px; right: 0;
  width: min(390px, calc(100vw - 40px)); height: min(600px, calc(100vh - 120px));
  display: flex; flex-direction: column; overflow: hidden;
  background: var(--bg); border: 1px solid var(--border); border-radius: 16px;
  box-shadow: var(--shadow);
}
.root.left .panel { right: auto; left: 0; }
.root.inline .panel { position: static; width: 100%; height: 100%; min-height: 420px; }

header {
  display: flex; align-items: center; gap: 8px; padding: 12px 12px 12px 16px;
  background: var(--accent); color: var(--on-accent);
}
header .logo { width: 28px; height: 28px; flex: none; border-radius: 6px; object-fit: cover; background: rgba(255, 255, 255, 0.85); }
header h2 { flex: 1; margin: 0; font-size: 16px; font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.icon-button {
  width: 32px; height: 32px; border: none; border-radius: 8px; background: transparent;
  display: grid; place-items: center; color: inherit;
}
.icon-button:hover { background: rgba(127, 127, 127, 0.2); }
.icon-button svg { width: 18px; height: 18px; }
.icon-button:focus-visible { outline-color: var(--on-accent); }

.log { flex: 1; overflow-y: auto; padding: 16px; display: flex; flex-direction: column; gap: 12px; }
.message { max-width: 88%; padding: 10px 14px; border-radius: 14px; overflow-wrap: anywhere; }
.message.user { align-self: flex-end; background: var(--accent); color: var(--on-accent); border-bottom-right-radius: 4px; white-space: pre-wrap; }
.message.assistant { align-self: flex-start; background: var(--surface); border-bottom-left-radius: 4px; }
.message.error { color: var(--danger); }
.message p, .message ul, .message ol { margin: 0 0 8px; }
.message > :last-child, .body > :last-child { margin-bottom: 0; }
.message ul, .message ol { padding-left: 20px; }
.message .heading { display: block; margin-bottom: 4px; }
.message code { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 13px; background: var(--border); padding: 1px 4px; border-radius: 4px; }

.cite {
  display: inline-block; min-width: 20px; padding: 0 5px; margin: 0 1px;
  border: 1px solid var(--accent); border-radius: 6px; background: transparent;
  color: var(--text); font-size: 12px; line-height: 18px; vertical-align: 1px;
}
.cite:hover { background: var(--accent); color: var(--on-accent); }

.sources { margin-top: 10px; padding-top: 8px; border-top: 1px solid var(--border); display: grid; gap: 4px; }
.sources-title { font-size: 12px; font-weight: 600; color: var(--muted); text-transform: uppercase; letter-spacing: 0.04em; }
details { border-radius: 8px; }
details.flash { animation: flash 1.2s ease; }
@keyframes flash { from { background: color-mix(in srgb, var(--accent) 25%, transparent); } to { background: transparent; } }
summary { cursor: pointer; font-size: 13px; color: var(--muted); padding: 2px 4px; border-radius: 6px; }
summary:hover { color: var(--text); }
summary b { color: var(--text); }
blockquote {
  margin: 4px 0 6px; padding: 8px 10px; border-left: 3px solid var(--accent); background: var(--bg);
  border-radius: 0 8px 8px 0; font-size: 13px; color: var(--muted); white-space: pre-wrap;
  max-height: 180px; overflow-y: auto;
}

.feedback { display: flex; gap: 4px; margin-top: 8px; }
.feedback button {
  border: 1px solid var(--border); background: var(--bg); border-radius: 8px;
  width: 30px; height: 26px; display: grid; place-items: center; color: var(--muted);
}
.feedback button svg { width: 15px; height: 15px; }
.feedback button[aria-pressed="true"] { border-color: var(--accent); color: var(--accent); }

.typing { display: inline-flex; gap: 4px; padding: 4px 0; }
.typing span { width: 7px; height: 7px; border-radius: 50%; background: var(--muted); animation: blink 1.2s infinite ease-in-out; }
.typing span:nth-child(2) { animation-delay: 0.15s; }
.typing span:nth-child(3) { animation-delay: 0.3s; }
@keyframes blink { 0%, 80%, 100% { opacity: 0.25; } 40% { opacity: 1; } }

form { display: flex; align-items: flex-end; gap: 8px; padding: 10px 12px; border-top: 1px solid var(--border); }
textarea {
  flex: 1; resize: none; max-height: 120px; padding: 9px 12px;
  border: 1px solid var(--border); border-radius: 12px; background: var(--bg); color: var(--text);
  font: inherit;
}
textarea::placeholder { color: var(--muted); }
.send {
  width: 40px; height: 40px; border: none; border-radius: 12px;
  background: var(--accent); color: var(--on-accent); display: grid; place-items: center;
}
.send:disabled { opacity: 0.5; cursor: default; }
.send svg { width: 18px; height: 18px; }
.note { margin: 0; padding: 0 12px 10px; font-size: 11px; color: var(--muted); text-align: center; }

@media (max-width: 480px) {
  .root:not(.inline) .panel { position: fixed; inset: 0; width: 100%; height: 100%; border-radius: 0; border: none; }
  /* The panel covers the screen; its header's button closes it. */
  .root.open .launcher { display: none; }
}
@media (prefers-reduced-motion: reduce) {
  .launcher, details.flash, .typing span { transition: none; animation: none; }
}
`;
