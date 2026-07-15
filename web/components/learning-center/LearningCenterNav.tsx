"use client";
/* eslint-disable i18n/no-literal-ui-text -- Learning Center shell is Chinese-first until locale extraction. */

import Link from "next/link";
import { usePathname } from "next/navigation";
import { BarChart3, FileJson2, BookOpenCheck, Target, ListChecks, Sparkles, ChartNoAxesCombined } from "lucide-react";

const items = [
  { href: "/space/learning-center", label: "总览", icon: BarChart3 },
  { href: "/space/learning-center/imports", label: "导入中心", icon: FileJson2 },
  { href: "/space/learning-center/practice", label: "训练会话", icon: Target },
  { href: "/space/learning-center/review", label: "复习队列", icon: ListChecks },
  { href: "/space/learning-center/recommendations", label: "学习建议", icon: Sparkles },
  { href: "/space/learning-center/analytics", label: "学习分析", icon: ChartNoAxesCombined },
  { href: "/space/exam-practice", label: "兼容刷题", icon: BookOpenCheck },
];

export default function LearningCenterNav() {
  const pathname = usePathname();
  return (
    <nav aria-label="学习训练中心导航" className="mb-5 flex flex-wrap gap-1 rounded-xl border border-[var(--border)]/70 bg-[var(--card)] p-1.5">
      {items.map(({ href, label, icon: Icon }) => {
        const active = href === "/space/learning-center" ? pathname === href : pathname?.startsWith(href);
        return (
          <Link key={href} href={href} className={`inline-flex items-center gap-1.5 rounded-lg px-3 py-2 text-[12px] transition-colors ${active ? "bg-[var(--foreground)] font-medium text-[var(--background)]" : "text-[var(--muted-foreground)] hover:bg-[var(--muted)] hover:text-[var(--foreground)]"}`}>
            <Icon size={14} /> {label}
          </Link>
        );
      })}
    </nav>
  );
}
