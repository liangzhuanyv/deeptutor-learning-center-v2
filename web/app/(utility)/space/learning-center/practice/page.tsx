import { Suspense } from "react";

import LearningPracticeCenter from "@/components/learning-center/practice/LearningPracticeCenter";

export default function LearningCenterPracticePage() {
  return (
    <Suspense fallback={<div className="flex min-h-64 items-center justify-center text-sm text-[var(--muted-foreground)]">加载训练会话…</div>}>
      <LearningPracticeCenter />
    </Suspense>
  );
}
