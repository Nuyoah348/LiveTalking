'use client'

import { useCallback, useEffect, useState } from 'react'
import Link from 'next/link'
import { BookOpen, RefreshCw, Users } from 'lucide-react'
import { apiFetch, apiUrl } from '@/lib/api'
import { scopedUrl } from '@/lib/workspace-scope'
import { LearningShell } from '@/components/learning/LearningShell'
import { ClassPanel } from './ClassPanel'

type Course = {
  id: string
  name: string
  status: string
  units: number
  covered_units: number
  content_workspace_id: string
  content_workspace_name: string
}

type NextStep = {
  kind: 'weak_point' | 'due_review' | 'error_record'
  title: string
  reason: string
  target_label: string
  target_path: string | null
  content_workspace_id: string
}

type Report = {
  scope: 'current_account'
  account: { id: string; name: string }
  practice: {
    questions: number
    mistakes: number
    due: number
    reviewed_today: number
    reviews_last_30_days: number
    daily: { date: string; reviews: number }[]
  }
  courses: Course[]
  unavailable_workspaces: string[]
  unavailable_paths: number
  next_steps: NextStep[]
  recommendation_note: string
}

export default function TeacherPage() {
  const [report, setReport] = useState<Report | null>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const [version, setVersion] = useState(0)
  const refresh = useCallback(() => setVersion(value => value + 1), [])

  useEffect(() => {
    const controller = new AbortController()
    const load = async () => {
      setLoading(true)
      setError('')
      try {
        const timezone = Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC'
        const url = apiUrl(`/api/teacher/report?timezone=${encodeURIComponent(timezone)}`)
        const response = await apiFetch(url, { signal: controller.signal })
        if (!response.ok) throw new Error(`HTTP ${response.status}`)
        const payload = await response.json() as Report
        if (!controller.signal.aborted) setReport(payload)
      } catch {
        if (!controller.signal.aborted) setError('暂时无法读取学习报告，请重试。')
      } finally {
        if (!controller.signal.aborted) setLoading(false)
      }
    }
    void load()
    return () => controller.abort()
  }, [version])

  const recentDays = report?.practice.daily.slice(-14) ?? []
  const maxReviews = Math.max(1, ...recentDays.map(day => day.reviews))
  const activeCourses = report?.courses.filter(course => course.status === 'active') ?? []

  return (
    <LearningShell
      title="教学分析"
      subtitle="根据当前账号保存的学习记录，查看练习活动和下一步学习建议。"
      back={false}
      scopeChip={<span className="rounded-full border border-[var(--border)] px-2.5 py-1 text-xs text-[var(--muted-foreground)]">当前账号</span>}
      action={<button type="button" onClick={refresh} disabled={loading} className="inline-flex items-center gap-2 rounded-lg border border-[var(--border)] px-3 py-2 text-sm disabled:opacity-50"><RefreshCw size={15} />刷新</button>}
    >
      <div className="mb-6 flex gap-3 rounded-xl border border-[var(--border)] bg-[var(--card)] p-4 text-sm text-[var(--muted-foreground)]">
        <Users size={18} className="mt-0.5 shrink-0" />
        <p>本页上方仅包含{report ? `“${report.account.name}”` : '当前账号'}的数据。下方班级报告只汇总使用邀请码主动加入的学生。</p>
      </div>

      {loading && !report && <p className="py-12 text-center text-sm text-[var(--muted-foreground)]">正在读取学习记录…</p>}
      {error && <p role="alert" className="mb-5 rounded-xl border border-[var(--destructive)]/30 p-4 text-sm text-[var(--destructive)]">{error}</p>}
      {report && <>
        {(report.unavailable_workspaces.length > 0 || report.unavailable_paths > 0) && <p role="status" className="mb-5 rounded-xl border border-amber-400/40 p-3 text-sm">部分工作区或掌握路径暂时不可读取；以下数据和建议可能不完整。</p>}
        <section className="mb-6 rounded-xl border border-[var(--border)] bg-[var(--card)] p-5">
          <h2 className="font-serif text-lg font-semibold">下一步学习</h2>
          <p className="mt-1 text-xs text-[var(--muted-foreground)]">{report.recommendation_note}</p>
          {report.next_steps.length === 0 ? <p className="mt-4 text-sm text-[var(--muted-foreground)]">目前没有足够的已测评弱点、到期复习或未结案错误记录来生成具体建议。</p> : <ul className="mt-4 grid gap-3 md:grid-cols-2">{report.next_steps.map((step, index) => <li key={`${step.kind}:${step.content_workspace_id}:${index}`} className="rounded-lg border border-[var(--border)] p-4"><h3 className="font-medium">{step.title}</h3><p className="mt-1 text-sm text-[var(--muted-foreground)]">{step.reason}</p>{step.target_path && <Link href={scopedUrl(step.target_path, step.content_workspace_id)} className="mt-3 inline-block text-sm font-medium text-emerald-700 hover:underline dark:text-emerald-400">{step.target_label} →</Link>}</li>)}</ul>}
        </section>
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          {[
            ['练习题目', report.practice.questions],
            ['待复习', report.practice.due],
            ['今日已复习', report.practice.reviewed_today],
            ['近 30 天复习次数', report.practice.reviews_last_30_days],
          ].map(([label, value]) => <div key={label} className="rounded-xl border border-[var(--border)] bg-[var(--card)] p-5"><p className="text-xs text-[var(--muted-foreground)]">{label}</p><p className="mt-2 text-3xl font-semibold tabular-nums">{value}</p></div>)}
        </div>

        <div className="mt-6 grid gap-6 lg:grid-cols-[1.3fr_1fr]">
          <section className="rounded-xl border border-[var(--border)] bg-[var(--card)] p-5">
            <h2 className="font-serif text-lg font-semibold">复习活动</h2>
            <p className="mt-1 text-xs text-[var(--muted-foreground)]">最近 14 天，每根柱子表示当天记录的复习次数。</p>
            <div className="mt-6 flex h-40 items-end gap-1.5" role="img" aria-label={`最近 14 天共复习 ${recentDays.reduce((sum, day) => sum + day.reviews, 0)} 次`}>
              {recentDays.map(day => <div key={day.date} title={`${day.date}：${day.reviews} 次`} className="flex min-w-0 flex-1 flex-col items-center justify-end gap-2"><div className="w-full rounded-t bg-emerald-500/75" style={{ height: `${Math.max(day.reviews ? 6 : 2, (day.reviews / maxReviews) * 116)}px` }} /><span className="text-[10px] text-[var(--muted-foreground)]">{day.date.slice(5)}</span></div>)}
            </div>
            {recentDays.length === 0 && <p className="mt-4 text-sm text-[var(--muted-foreground)]">还没有复习记录。</p>}
          </section>

          <section className="rounded-xl border border-[var(--border)] bg-[var(--card)] p-5">
            <h2 className="font-serif text-lg font-semibold">课程单元</h2>
            <p className="mt-1 text-xs text-[var(--muted-foreground)]">覆盖数来自课程中手动标记的单元，不代表测评掌握度。</p>
            {activeCourses.length === 0 ? <div className="mt-8 text-sm text-[var(--muted-foreground)]"><BookOpen size={22} className="mb-2" />当前账号还没有进行中的课程。</div> : <ul className="mt-5 space-y-4">{activeCourses.map(course => <li key={`${course.content_workspace_id}:${course.id}`} className="border-b border-[var(--border)] pb-4 last:border-0 last:pb-0"><div className="flex items-center justify-between gap-3 text-sm"><Link href={scopedUrl(`/courses/${course.id}`, course.content_workspace_id)} className="font-medium hover:underline">{course.name}</Link><span className="shrink-0 tabular-nums text-[var(--muted-foreground)]">{course.covered_units}/{course.units}</span></div>{course.content_workspace_name && <p className="mt-1 text-xs text-[var(--muted-foreground)]">{course.content_workspace_name}</p>}<div className="mt-2 h-1.5 overflow-hidden rounded-full bg-[var(--muted)]"><div className="h-full rounded-full bg-emerald-500" style={{ width: `${course.units ? course.covered_units / course.units * 100 : 0}%` }} /></div></li>)}</ul>}
          </section>
        </div>
      </>}
      <ClassPanel />
    </LearningShell>
  )
}
