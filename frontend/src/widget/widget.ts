// The chat widget: a launcher button and a chat panel in a shadow root, so
// it looks the same on every website and leaves the website's page alone.

import { WidgetClient, WidgetError, failureMessage, type WidgetCitation, type WidgetConfig } from "./client";
import { ICONS } from "./icons";
import { renderAnswer, sourceLabel, textOn } from "./render";
import { STYLES } from "./styles";

export interface WidgetOptions {
  widgetId: string;
  /** Where the API is, e.g. https://rag.example.com. */
  apiBase: string;
  /** An element to show the panel in, always open (a preview); the page's corner by default. */
  container?: HTMLElement;
  position?: "right" | "left";
  /** Open the panel at once. */
  open?: boolean;
  /** Keeps the conversation as the visitor moves between pages; null keeps nothing. */
  storage?: Storage | null;
}

interface Message {
  role: "user" | "assistant";
  text: string;
  citations?: WidgetCitation[];
  messageId?: number | null;
  rating?: "up" | "down" | null;
  noAnswer?: boolean;
  error?: boolean;
}

interface Saved {
  conversationId: string | null;
  messages: Message[];
  open: boolean;
}

const NO_ANSWER = "I couldn't find the answer to that in the documents I have.";

function element<K extends keyof HTMLElementTagNameMap>(
  tag: K,
  attributes: Record<string, string> = {},
  text?: string,
): HTMLElementTagNameMap[K] {
  const node = document.createElement(tag);
  for (const [name, value] of Object.entries(attributes)) node.setAttribute(name, value);
  if (text !== undefined) node.textContent = text;
  return node;
}

function iconButton(className: string, icon: string, label: string): HTMLButtonElement {
  const button = element("button", { type: "button", class: className, "aria-label": label, title: label });
  button.innerHTML = icon;
  return button;
}

export class ChatWidget {
  readonly host: HTMLElement;
  private readonly shadow: ShadowRoot;
  private readonly root: HTMLDivElement;
  private readonly panel: HTMLElement;
  private readonly launcher: HTMLButtonElement | null;
  private readonly log: HTMLDivElement;
  private readonly input: HTMLTextAreaElement;
  private readonly sendButton: HTMLButtonElement;
  private readonly inline: boolean;
  private conversationId: string | null = null;
  private messages: Message[] = [];
  private busy = false;
  private abort: AbortController | null = null;

  /** Loads the widget's settings and shows it; throws WidgetError when the widget cannot be used. */
  static async mount(options: WidgetOptions): Promise<ChatWidget> {
    const client = new WidgetClient(options.apiBase, options.widgetId);
    return new ChatWidget(client, options, await client.config());
  }

  constructor(
    private readonly client: WidgetClient,
    private readonly options: WidgetOptions,
    readonly config: WidgetConfig,
  ) {
    this.inline = Boolean(options.container);
    this.host = element("div", { "data-mini-rag-widget": config.id });
    this.shadow = this.host.attachShadow({ mode: "open" });
    const style = element("style", {}, STYLES);
    this.root = element("div", { class: `root${this.inline ? " inline" : ""}${options.position === "left" ? " left" : ""}` });
    this.root.style.setProperty("--accent", config.accent);
    this.root.style.setProperty("--on-accent", textOn(config.accent));

    this.panel = element("section", { class: "panel", role: this.inline ? "region" : "dialog", "aria-label": config.name });
    const header = element("header");
    const restart = iconButton("icon-button", ICONS.restart, "New conversation");
    restart.addEventListener("click", () => this.reset());
    if (config.logo_url?.startsWith("https://")) {
      // Decorative: the name beside it says the same. A broken image is left out.
      const logo = element("img", { class: "logo", src: config.logo_url, alt: "", referrerpolicy: "no-referrer" });
      logo.addEventListener("error", () => logo.remove());
      header.append(logo);
    }
    header.append(element("h2", {}, config.name), restart);
    if (!this.inline) {
      const close = iconButton("icon-button", ICONS.close, "Close");
      close.addEventListener("click", () => this.close());
      header.append(close);
    }

    this.log = element("div", { class: "log", role: "log", "aria-live": "polite" });
    const form = element("form");
    this.input = element("textarea", { rows: "1", maxlength: "2000", placeholder: "Ask a question…", "aria-label": "Your question" });
    this.sendButton = iconButton("send", ICONS.send, "Send");
    this.sendButton.type = "submit";
    form.append(this.input, this.sendButton);
    form.addEventListener("submit", (event) => {
      event.preventDefault();
      void this.ask(this.input.value);
    });
    this.input.addEventListener("keydown", (event) => {
      if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
        event.preventDefault();
        void this.ask(this.input.value);
      }
    });
    this.input.addEventListener("input", () => this.fitInput());
    const note = element("p", { class: "note" }, "Answers come from documents and can be wrong.");
    this.panel.append(header, this.log, form, note);
    this.panel.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && !this.inline) this.close();
    });

    if (this.inline) {
      this.launcher = null;
      this.root.append(this.panel);
    } else {
      this.launcher = iconButton("launcher", ICONS.chat, `Chat: ${config.name}`);
      this.launcher.setAttribute("aria-expanded", "false");
      this.launcher.addEventListener("click", () => this.toggle());
      this.root.append(this.panel, this.launcher);
    }
    this.shadow.append(style, this.root);

    const saved = this.load();
    this.conversationId = saved?.conversationId ?? null;
    this.messages = saved?.messages ?? [];
    this.renderLog();
    (options.container ?? document.body).append(this.host);
    this.setOpen(this.inline || Boolean(options.open || saved?.open), false);
  }

  get isOpen(): boolean {
    return !this.panel.hidden;
  }

  open(): void {
    this.setOpen(true, true);
  }

  close(): void {
    this.setOpen(false, true);
  }

  toggle(): void {
    this.setOpen(!this.isOpen, true);
  }

  /** Forget the conversation and start again. */
  reset(): void {
    this.abort?.abort();
    this.conversationId = null;
    this.messages = [];
    this.save();
    this.renderLog();
    this.input.focus();
  }

  destroy(): void {
    this.abort?.abort();
    this.host.remove();
  }

  private setOpen(open: boolean, focus: boolean): void {
    if (this.inline) open = true;
    this.panel.hidden = !open;
    this.root.classList.toggle("open", open);
    this.launcher?.setAttribute("aria-expanded", String(open));
    if (this.launcher) this.launcher.innerHTML = open ? ICONS.close : ICONS.chat;
    if (focus) (open ? this.input : this.launcher)?.focus();
    if (open) this.scrollToEnd();
    this.save();
  }

  /** Ask a question, showing the answer as it is written. */
  async ask(question: string): Promise<void> {
    question = question.trim();
    if (!question || this.busy) return;
    this.busy = true;
    this.sendButton.disabled = true;
    this.input.value = "";
    this.fitInput();
    this.messages.push({ role: "user", text: question });
    this.log.append(this.renderMessage(this.messages.at(-1)!));
    const bubble = element("div", { class: "message assistant", "aria-busy": "true" });
    const typing = element("span", { class: "typing", "aria-label": "Answering" });
    typing.append(element("span"), element("span"), element("span"));
    bubble.append(typing);
    this.log.append(bubble);
    this.scrollToEnd();

    this.abort = new AbortController();
    let text = "";
    let message: Message;
    try {
      let answered: Message | null = null;
      for await (const event of this.client.ask(question, this.conversationId, this.abort.signal)) {
        if (event.kind === "delta") {
          text += event.text;
          bubble.replaceChildren(this.renderBody(text, []));
          this.scrollToEnd();
        } else {
          const { answer } = event;
          this.conversationId = answer.conversation_id;
          answered = answer.answer === null
            ? { role: "assistant", text: NO_ANSWER, noAnswer: true, messageId: answer.message_id }
            : { role: "assistant", text: answer.answer, citations: answer.citations, messageId: answer.message_id };
        }
      }
      if (!answered) throw new WidgetError("request_failed", 200);
      message = answered;
    } catch (error) {
      if ((error as Error).name === "AbortError") {
        bubble.remove();
        return;
      }
      if (error instanceof WidgetError && error.signal === "conversation_not_found") this.conversationId = null;
      message = { role: "assistant", text: failureMessage(error), error: true };
    } finally {
      this.busy = false;
      this.sendButton.disabled = false;
      this.abort = null;
    }
    this.messages.push(message);
    bubble.replaceWith(this.renderMessage(message));
    this.scrollToEnd();
    this.save();
  }

  private renderLog(): void {
    const welcome = this.config.welcome ?? "Hi! Ask me a question and I'll answer from our documents.";
    this.log.replaceChildren(
      this.renderMessage({ role: "assistant", text: welcome }),
      ...this.messages.map((message) => this.renderMessage(message)),
    );
  }

  private renderMessage(message: Message): HTMLElement {
    const bubble = element("div", { class: `message ${message.role}${message.error ? " error" : ""}` });
    if (message.role === "user" || message.error || message.noAnswer) {
      bubble.textContent = message.text;
    } else {
      bubble.append(this.renderBody(message.text, message.citations ?? [], bubble));
    }
    if (message.citations?.length) bubble.append(this.renderSources(message.citations));
    if (message.role === "assistant" && message.messageId != null && this.conversationId) {
      bubble.append(this.renderFeedback(message));
    }
    return bubble;
  }

  /** The answer's text; [n] markers become buttons that open their source. */
  private renderBody(text: string, citations: WidgetCitation[], bubble?: HTMLElement): HTMLElement {
    const body = element("div", { class: "body" });
    const numbers = new Set(citations.map((citation) => citation.number));
    body.append(renderAnswer(text, (number) => {
      if (!bubble || !numbers.has(number)) return null;
      const button = element("button", { type: "button", class: "cite", "aria-label": `Source ${number}` }, String(number));
      button.addEventListener("click", () => this.showSource(bubble, number));
      return button;
    }));
    return body;
  }

  private renderSources(citations: WidgetCitation[]): HTMLElement {
    const sources = element("div", { class: "sources" });
    sources.append(element("div", { class: "sources-title" }, "Sources"));
    for (const citation of citations) {
      const details = element("details", { "data-number": String(citation.number) });
      const summary = element("summary");
      summary.append(element("b", {}, `[${citation.number}]`), ` ${sourceLabel(citation)}`);
      details.append(summary, element("blockquote", {}, citation.text));
      sources.append(details);
    }
    return sources;
  }

  private showSource(bubble: HTMLElement, number: number): void {
    const details = bubble.querySelector<HTMLDetailsElement>(`details[data-number="${number}"]`);
    if (!details) return;
    details.open = true;
    details.classList.remove("flash");
    void details.offsetWidth; // Restart the animation.
    details.classList.add("flash");
    details.scrollIntoView({ block: "nearest", behavior: "smooth" });
    details.querySelector("summary")?.focus({ preventScroll: true });
  }

  private renderFeedback(message: Message): HTMLElement {
    const feedback = element("div", { class: "feedback", role: "group", "aria-label": "Was this helpful?" });
    const conversationId = this.conversationId!;
    for (const rating of ["up", "down"] as const) {
      const button = iconButton("", ICONS[rating], rating === "up" ? "Helpful" : "Not helpful");
      button.setAttribute("aria-pressed", String(message.rating === rating));
      button.addEventListener("click", async () => {
        const previous = message.rating ?? null;
        message.rating = rating;
        this.updateFeedback(feedback, rating);
        try {
          await this.client.rate(conversationId, message.messageId!, rating);
          this.save();
        } catch {
          message.rating = previous;
          this.updateFeedback(feedback, previous);
        }
      });
      feedback.append(button);
    }
    return feedback;
  }

  private updateFeedback(feedback: HTMLElement, rating: "up" | "down" | null): void {
    feedback.querySelectorAll("button").forEach((button, index) => {
      button.setAttribute("aria-pressed", String((index === 0 ? "up" : "down") === rating));
    });
  }

  private fitInput(): void {
    this.input.style.height = "auto";
    this.input.style.height = `${Math.min(this.input.scrollHeight + 2, 120)}px`;
  }

  private scrollToEnd(): void {
    this.log.scrollTop = this.log.scrollHeight;
  }

  private get storageKey(): string {
    return `mini-rag-widget:${this.config.id}`;
  }

  private load(): Saved | null {
    try {
      const raw = this.options.storage?.getItem(this.storageKey);
      return raw ? (JSON.parse(raw) as Saved) : null;
    } catch {
      return null;
    }
  }

  private save(): void {
    try {
      const saved: Saved = { conversationId: this.conversationId, messages: this.messages.slice(-50), open: this.isOpen };
      this.options.storage?.setItem(this.storageKey, JSON.stringify(saved));
    } catch {
      // Storage may be full or blocked; the conversation still works on this page.
    }
  }
}
