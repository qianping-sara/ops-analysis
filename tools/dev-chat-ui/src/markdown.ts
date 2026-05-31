import DOMPurify from "dompurify";
import { marked } from "marked";

marked.setOptions({
  gfm: true,
  breaks: true,
});

const sanitizeOptions: DOMPurify.Config = {
  USE_PROFILES: { html: true },
};

/** Render markdown into element (assistant messages). */
export function setMarkdownContent(el: HTMLElement, markdown: string): void {
  const html = marked.parse(markdown, { async: false }) as string;
  el.innerHTML = DOMPurify.sanitize(html, sanitizeOptions);
}
