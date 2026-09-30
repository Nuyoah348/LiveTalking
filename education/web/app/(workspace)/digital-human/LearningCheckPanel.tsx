"use client";

import { useState } from "react";
import Link from "next/link";
import { PRACTICE_HOME } from "@/lib/learning-routes";
import { scopedUrl } from "@/lib/workspace-scope";

type Check = {
  check_id: string;
  question: string;
  options: Record<string, string>;
  question_type: "choice";
};
type Verdict = {
  correct: boolean;
  next_action: { kind: string; entry_id?: number };
};

async function request<T>(path: string, body: object): Promise<T> {
  const response = await fetch(scopedUrl(path), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const payload: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    const detail = payload && typeof payload === "object" ? (payload as { detail?: unknown }).detail : null;
    throw new Error(typeof detail === "string" ? detail : `请求失败（HTTP ${response.status}）`);
  }
  return payload as T;
}

export default function LearningCheckPanel({ sessionId, lessonQuestion, lessonAnswer, kbName }: {
  sessionId: string;
  lessonQuestion: string;
  lessonAnswer: string;
  kbName: string;
}) {
  const [knowledgePoint, setKnowledgePoint] = useState(lessonQuestion.slice(0, 120));
  const [check, setCheck] = useState<Check | null>(null);
  const [choice, setChoice] = useState("");
  const [verdict, setVerdict] = useState<Verdict | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function generate() {
    if (!knowledgePoint.trim() || busy || check) return;
    setBusy(true);
    setError("");
    try {
      const generated = await request<Check>("/api/learning-checks", {
        session_id: sessionId,
        knowledge_point: knowledgePoint.trim(),
        lesson_question: lessonQuestion,
        lesson_answer: lessonAnswer,
        kb_name: kbName,
      });
      setCheck(generated);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "生成检验题失败");
    } finally {
      setBusy(false);
    }
  }

  async function submit() {
    if (!check || !choice || busy || verdict) return;
    setBusy(true);
    setError("");
    try {
      setVerdict(await request<Verdict>(`/api/learning-checks/${encodeURIComponent(check.check_id)}/submit`, { answer: choice }));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "提交答案失败");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section aria-labelledby="learning-check-title" className="mt-5 rounded-xl border border-teal-200 bg-teal-50/50 p-4 dark:border-teal-900 dark:bg-teal-950/20">
      <h2 id="learning-check-title" className="text-sm font-semibold text-teal-800 dark:text-teal-200">讲完练一题</h2>
      <p className="mt-1 text-xs text-[var(--muted-foreground)]">用一道同主题小题检查是否理解；答错会记录到练习复习中。</p>
      {!check && <div className="mt-3 flex flex-wrap items-end gap-2">
        <label className="min-w-48 flex-1 text-xs">本次知识点
          <input value={knowledgePoint} maxLength={500} onChange={(event) => setKnowledgePoint(event.target.value)} className="mt-1 w-full rounded-lg border border-[var(--border)] bg-[var(--card)] px-3 py-2 text-sm" />
        </label>
        <button type="button" onClick={() => void generate()} disabled={busy || !knowledgePoint.trim()} className="rounded-lg bg-teal-700 px-4 py-2 text-sm text-white disabled:opacity-50">{busy ? "正在生成…" : "生成一题检验"}</button>
      </div>}
      {check && <div className="mt-3">
        <p className="text-sm font-medium">{check.question}</p>
        <div className="mt-3 grid gap-2 sm:grid-cols-2">
          {Object.entries(check.options).map(([key, label]) => <label key={key} className="flex cursor-pointer gap-2 rounded-lg border border-[var(--border)] bg-[var(--card)] p-3 text-sm">
            <input type="radio" name={`learning-check-${check.check_id}`} value={key} checked={choice === key} disabled={Boolean(verdict)} onChange={() => setChoice(key)} />
            <span><strong>{key}.</strong> {label}</span>
          </label>)}
        </div>
        {!verdict && <button type="button" onClick={() => void submit()} disabled={busy || !choice} className="mt-3 rounded-lg bg-teal-700 px-4 py-2 text-sm text-white disabled:opacity-50">{busy ? "正在提交…" : "提交答案"}</button>}
        {verdict && <div role="status" className="mt-3 text-sm">
          {verdict.correct ? "答对了，这道题已记录到练习中。" : "这次没有答对，题目已进入练习复习。"}
          {verdict.next_action.kind === "practice" && <Link href={scopedUrl(`${PRACTICE_HOME}?question=${verdict.next_action.entry_id ?? ""}`)} className="ml-2 font-medium text-teal-700 underline dark:text-teal-300">前往复习</Link>}
        </div>}
      </div>}
      {error && <p role="alert" className="mt-2 text-xs text-red-600">{error}</p>}
    </section>
  );
}
