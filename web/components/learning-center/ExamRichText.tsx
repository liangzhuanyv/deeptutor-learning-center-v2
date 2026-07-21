"use client";

import { useMemo } from "react";
import { normalizeExamRichText } from "@/lib/exam-rich-text";

export interface ExamRichTextProps {
  text?: string | null;
  className?: string;
  /** Inline span instead of block div (for option labels). */
  as?: "div" | "span" | "p" | "h1" | "h2" | "h3";
}

/**
 * Render exam-bank stem / option / explanation text with HTML entities and
 * ``<br/>`` normalized for display. Uses pre-wrap so multi-line stems keep
 * their structure without needing full markdown.
 */
export default function ExamRichText({
  text,
  className = "",
  as = "div",
}: ExamRichTextProps) {
  const content = useMemo(() => normalizeExamRichText(text), [text]);
  if (!content) return null;

  const Tag = as;
  return (
    <Tag className={`whitespace-pre-wrap break-words [overflow-wrap:anywhere] ${className}`.trim()}>
      {content}
    </Tag>
  );
}
