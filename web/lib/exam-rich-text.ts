/**
 * Normalize exam-bank stem / option / explanation text for display.
 *
 * Imported questions often carry HTML-ish fragments and entities
 * (e.g. ``&emsp;``, ``&nbsp;``, ``<br />``) that must not be rendered
 * as raw source in React text nodes.
 */

function decodeNumericEntity(raw: string, hex: boolean): string {
  try {
    const code = hex ? parseInt(raw, 16) : Number(raw);
    if (!Number.isFinite(code) || code < 0 || code > 0x10ffff) return "";
    return String.fromCodePoint(code);
  } catch {
    return "";
  }
}

/** Decode common named + numeric HTML entities without a DOM. */
export function decodeHtmlEntities(input: string): string {
  if (!input) return "";
  return input
    .replace(/&nbsp;/gi, "\u00a0")
    .replace(/&ensp;/gi, "\u2002")
    .replace(/&emsp;/gi, "\u3000")
    .replace(/&thinsp;/gi, "\u2009")
    .replace(/&quot;/gi, '"')
    .replace(/&apos;|&#0*39;/gi, "'")
    .replace(/&lt;/gi, "<")
    .replace(/&gt;/gi, ">")
    .replace(/&#x([0-9a-f]+);/gi, (_, hex: string) => decodeNumericEntity(hex, true))
    .replace(/&#(\d+);/g, (_, dec: string) => decodeNumericEntity(dec, false))
    // Do ``&amp;`` last so intermediate rewrites stay stable.
    .replace(/&amp;/gi, "&");
}

/**
 * Convert exam-bank HTML fragments into plain text suitable for
 * markdown / pre-wrap display. Safe for untrusted bank content:
 * tags are stripped after known break tags are turned into newlines.
 */
export function normalizeExamRichText(input: string | null | undefined): string {
  if (input == null) return "";
  let s = String(input);
  if (!s) return "";

  // 1) Structural breaks → newlines (before stripping tags).
  s = s.replace(/<br\s*\/?>/gi, "\n");
  s = s.replace(/<\/p>\s*<p(?:\s[^>]*)?>/gi, "\n\n");
  s = s.replace(/<\/?p(?:\s[^>]*)?>/gi, "\n");
  s = s.replace(/<\/div>\s*<div(?:\s[^>]*)?>/gi, "\n");
  s = s.replace(/<\/?div(?:\s[^>]*)?>/gi, "\n");
  s = s.replace(/<\/li>/gi, "\n");
  s = s.replace(/<li(?:\s[^>]*)?>/gi, "• ");
  s = s.replace(/<\/h[1-6]>/gi, "\n");
  s = s.replace(/<h[1-6](?:\s[^>]*)?>/gi, "");

  // 2) Drop remaining tags; keep inner text.
  s = s.replace(/<\/?[a-zA-Z][^>]*>/g, "");

  // 3) Decode entities (including those that looked like ``&emsp;``).
  s = decodeHtmlEntities(s);

  // 4) NBSP → regular space for consistent wrapping; tidy blank lines.
  s = s.replace(/\u00a0/g, " ");
  s = s.replace(/[ \t]+\n/g, "\n");
  s = s.replace(/\n{3,}/g, "\n\n");
  s = s.replace(/[ \t]{2,}/g, " ");
  return s.trim();
}
