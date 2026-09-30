'use client'

import { useEffect, useState } from 'react'
import { apiFetch, apiUrl } from '@/lib/api'

type OwnedClass = { id: string; name: string; members: number }
type JoinedClass = { id: string; name: string }
type NextStep = { kind: string; title: string; reason: string; target_label: string; target_path: null; content_workspace_id: string }
type Member = {
  id: string
  name: string
  questions: number
  mistakes: number
  due: number
  reviewed_today: number
  reviews_last_30_days: number
  unavailable_workspaces: string[]
  unavailable_paths: number
  mastery_unavailable: boolean
  next_steps: NextStep[]
}
type ClassReport = {
  class: { id: string; name: string }
  members: Member[]
  unavailable_members: { id: string; name: string }[]
  incomplete_member_count: number
  totals: Pick<Member, 'questions' | 'mistakes' | 'due' | 'reviewed_today' | 'reviews_last_30_days'>
  mastery: {
    assessed_points: number
    weak_points_count: number
    weak_threshold_percent: number
    weak_points: { student_id: string; student_name: string; path_name: string; knowledge_point: string; mastery_percent: number; quiz_attempts: number }[]
    error_types: Record<string, number>
    unresolved_error_records: number
  }
}

const ERROR_NAMES: Record<string, string> = {
  structural: '知识结构', deviation: '理解偏差', application: '应用错误', metacognitive: '元认知',
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await apiFetch(apiUrl(path), init)
  const body = await response.json() as T & { detail?: string }
  if (!response.ok) throw new Error(body.detail || `HTTP ${response.status}`)
  return body
}

export function ClassPanel() {
  const [owned, setOwned] = useState<OwnedClass[]>([])
  const [joined, setJoined] = useState<JoinedClass[]>([])
  const [name, setName] = useState('')
  const [invite, setInvite] = useState('')
  const [newInvite, setNewInvite] = useState('')
  const [inviteClassName, setInviteClassName] = useState('')
  const [selected, setSelected] = useState('')
  const [report, setReport] = useState<ClassReport | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const load = async () => {
    const classes = await request<{ owned: OwnedClass[]; joined: JoinedClass[] }>('/api/teacher/classes')
    setOwned(classes.owned)
    setJoined(classes.joined)
  }

  useEffect(() => {
    void load().catch(() => setError('无法读取班级列表。'))
  }, [])

  const create = async () => {
    setBusy(true)
    setError('')
    try {
      const created = await request<{ invite_code: string; name: string }>('/api/teacher/classes', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name }),
      })
      setNewInvite(created.invite_code)
      setInviteClassName(created.name)
      setName('')
      await load()
    } catch (cause) { setError(cause instanceof Error ? cause.message : '创建班级失败。') }
    finally { setBusy(false) }
  }

  const join = async () => {
    setBusy(true)
    setError('')
    try {
      await request('/api/teacher/classes/join', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ invite_code: invite.trim() }),
      })
      setInvite('')
      await load()
    } catch (cause) { setError(cause instanceof Error ? cause.message : '加入班级失败。') }
    finally { setBusy(false) }
  }

  const leave = async (classId: string) => {
    setBusy(true)
    setError('')
    try {
      await request(`/api/teacher/classes/${encodeURIComponent(classId)}/membership`, { method: 'DELETE' })
      await load()
    } catch (cause) { setError(cause instanceof Error ? cause.message : '退出班级失败。') }
    finally { setBusy(false) }
  }

  const renewInvite = async (classId: string) => {
    setBusy(true)
    setError('')
    try {
      const result = await request<{ invite_code: string }>(`/api/teacher/classes/${encodeURIComponent(classId)}/invite`, { method: 'POST' })
      setNewInvite(result.invite_code)
      setInviteClassName(owned.find(item => item.id === classId)?.name ?? '')
    } catch (cause) { setError(cause instanceof Error ? cause.message : '生成邀请码失败。') }
    finally { setBusy(false) }
  }

  const open = async (classId: string) => {
    setSelected(classId)
    setReport(null)
    setError('')
    try {
      const timezone = Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC'
      const result = await request<ClassReport>(`/api/teacher/classes/${encodeURIComponent(classId)}/report?timezone=${encodeURIComponent(timezone)}`)
      setReport(result)
    } catch (cause) { setError(cause instanceof Error ? cause.message : '读取班级报告失败。') }
  }

  return <section className="mt-8 rounded-xl border border-[var(--border)] bg-[var(--card)] p-5">
    <h2 className="font-serif text-xl font-semibold">班级学习概览</h2>
    <p className="mt-1 text-sm text-[var(--muted-foreground)]">学生使用邀请码自行加入后，班级创建者才能查看其练习汇总。学生可随时退出。</p>
    {error && <p role="alert" className="mt-4 rounded-lg border border-[var(--destructive)]/30 p-3 text-sm text-[var(--destructive)]">{error}</p>}
    <div className="mt-5 grid gap-5 md:grid-cols-2">
      <div>
        <label htmlFor="class-name" className="text-sm font-medium">创建班级</label>
        <div className="mt-2 flex gap-2"><input id="class-name" value={name} onChange={event => setName(event.target.value)} maxLength={80} placeholder="例如：九年级数学一班" className="min-w-0 flex-1 rounded-lg border border-[var(--border)] bg-[var(--background)] px-3 py-2 text-sm" /><button type="button" onClick={create} disabled={busy || !name.trim()} className="rounded-lg bg-[var(--foreground)] px-4 py-2 text-sm text-[var(--background)] disabled:opacity-50">创建</button></div>
        {newInvite && <div className="mt-3 rounded-lg border border-emerald-500/40 bg-emerald-500/5 p-3 text-sm"><p>“{inviteClassName}”的邀请码。请保存并发给学生；再次生成后旧码立即失效。</p><code className="mt-2 block select-all break-all font-mono">{newInvite}</code></div>}
      </div>
      <div>
        <label htmlFor="class-invite" className="text-sm font-medium">使用邀请码加入</label>
        <div className="mt-2 flex gap-2"><input id="class-invite" value={invite} onChange={event => setInvite(event.target.value)} placeholder="输入教师提供的邀请码" className="min-w-0 flex-1 rounded-lg border border-[var(--border)] bg-[var(--background)] px-3 py-2 text-sm" /><button type="button" onClick={join} disabled={busy || !invite.trim()} className="rounded-lg border border-[var(--border)] px-4 py-2 text-sm disabled:opacity-50">加入</button></div>
      </div>
    </div>
    <div className="mt-6 grid gap-5 md:grid-cols-2">
      <div><h3 className="text-sm font-semibold">我创建的班级</h3>{owned.length === 0 ? <p className="mt-3 text-sm text-[var(--muted-foreground)]">还没有班级。</p> : <ul className="mt-3 space-y-2">{owned.map(item => <li key={item.id} className="flex items-center gap-2"><button type="button" onClick={() => void open(item.id)} className="min-w-0 flex-1 rounded-lg border border-[var(--border)] p-3 text-left text-sm hover:bg-[var(--muted)]">{item.name}<span className="float-right text-[var(--muted-foreground)]">{item.members} 位学生</span></button><button type="button" disabled={busy} onClick={() => void renewInvite(item.id)} className="shrink-0 rounded-lg border border-[var(--border)] px-3 py-3 text-xs disabled:opacity-50">新邀请码</button></li>)}</ul>}</div>
      <div><h3 className="text-sm font-semibold">我加入的班级</h3>{joined.length === 0 ? <p className="mt-3 text-sm text-[var(--muted-foreground)]">尚未加入班级。</p> : <ul className="mt-3 space-y-2">{joined.map(item => <li key={item.id} className="flex items-center justify-between gap-2 rounded-lg border border-[var(--border)] p-3 text-sm"><span>{item.name}</span><button type="button" disabled={busy} onClick={() => void leave(item.id)} className="shrink-0 text-[var(--destructive)] hover:underline">退出</button></li>)}</ul>}</div>
    </div>
    {selected && <div className="mt-6 border-t border-[var(--border)] pt-5">
      <h3 className="font-serif text-lg font-semibold">{report?.class.name ?? '正在读取班级报告…'}</h3>
      {report && <><p className="mt-1 text-xs text-[var(--muted-foreground)]">练习、知识点与错误诊断均来自已加入学生保存的记录。知识点仅纳入有测评证据的目标。</p>
        {report.incomplete_member_count > 0 && <p role="status" className="mt-3 rounded-lg border border-amber-500/40 p-3 text-sm">{report.incomplete_member_count} 位学生的数据暂时不完整。下方总计仅包含成功读取的数据。</p>}
        <div className="mt-4 grid gap-3 sm:grid-cols-4">{[
          ['练习题目', report.totals.questions], ['错题', report.totals.mistakes],
          ['待复习', report.totals.due], ['近 30 天复习', report.totals.reviews_last_30_days],
        ].map(([label, value]) => <div key={label} className="rounded-lg border border-[var(--border)] p-3"><p className="text-xs text-[var(--muted-foreground)]">{label}</p><p className="mt-1 text-2xl font-semibold tabular-nums">{value}</p></div>)}</div>
        {report.members.length + report.unavailable_members.length === 0 ? <p className="mt-5 text-sm text-[var(--muted-foreground)]">还没有学生主动加入。</p> : <div className="mt-5 overflow-x-auto"><table className="w-full min-w-[560px] text-left text-sm"><thead className="text-xs text-[var(--muted-foreground)]"><tr><th className="py-2">学生</th><th>题目</th><th>错题</th><th>待复习</th><th>近 30 天复习</th></tr></thead><tbody>{report.members.map(member => <tr key={member.id} className="border-t border-[var(--border)]"><td className="py-2">{member.name}{(member.unavailable_workspaces.length > 0 || member.unavailable_paths > 0 || member.mastery_unavailable) && <span className="ml-2 text-amber-600">数据不完整</span>}</td><td>{member.questions}</td><td>{member.mistakes}</td><td>{member.due}</td><td>{member.reviews_last_30_days}</td></tr>)}{report.unavailable_members.map(member => <tr key={member.id} className="border-t border-[var(--border)] text-[var(--muted-foreground)]"><td className="py-2">{member.name}（暂不可读）</td><td>—</td><td>—</td><td>—</td><td>—</td></tr>)}</tbody></table></div>}
        {report.members.length > 0 && <section className="mt-6 rounded-lg border border-[var(--border)] p-4"><h4 className="font-semibold">建议学生下一步</h4><p className="mt-1 text-xs text-[var(--muted-foreground)]">仅根据各学生已共享的记录生成。学习入口需由学生在本人账号中打开。</p><ul className="mt-4 space-y-4">{report.members.map(member => <li key={member.id} className="border-b border-[var(--border)] pb-3 last:border-0 last:pb-0"><p className="text-sm font-medium">{member.name}</p>{member.next_steps.length ? <ul className="mt-2 space-y-2">{member.next_steps.map((step, index) => <li key={`${step.kind}:${index}`} className="text-sm"><span className="font-medium">{step.title}</span><span className="text-[var(--muted-foreground)]"> · {step.reason}请学生在本人账号{step.target_label}。</span></li>)}</ul> : <p className="mt-1 text-sm text-[var(--muted-foreground)]">暂无足够证据生成具体建议。</p>}</li>)}</ul></section>}
        <div className="mt-6 grid gap-5 lg:grid-cols-2">
          <section className="rounded-lg border border-[var(--border)] p-4"><h4 className="font-semibold">需关注的知识点</h4><p className="mt-1 text-xs text-[var(--muted-foreground)]">已测评知识点中，掌握度低于 {report.mastery.weak_threshold_percent}% 的有 {report.mastery.weak_points_count}/{report.mastery.assessed_points} 个。最多显示 20 条，按掌握度排序；同名目标可能属于不同学习路径。</p>{report.mastery.weak_points.length === 0 ? <p className="mt-4 text-sm text-[var(--muted-foreground)]">暂无低于阈值的已测评知识点。</p> : <ul className="mt-4 space-y-3">{report.mastery.weak_points.map((point, index) => <li key={`${point.student_id}:${point.path_name}:${point.knowledge_point}:${index}`} className="flex items-start justify-between gap-2 border-b border-[var(--border)] pb-2 text-sm last:border-0"><div><p className="font-medium">{point.knowledge_point}</p><p className="text-xs text-[var(--muted-foreground)]">{point.student_name} · {point.path_name} · {point.quiz_attempts} 次测验</p></div><span className="shrink-0 tabular-nums">{point.mastery_percent}%</span></li>)}</ul>}</section>
          <section className="rounded-lg border border-[var(--border)] p-4"><h4 className="font-semibold">错误类型</h4><p className="mt-1 text-xs text-[var(--muted-foreground)]">来自掌握路径中尚未结案的结构化错误诊断，共 {report.mastery.unresolved_error_records} 条；不是全部练习错题的分类。</p>{report.mastery.unresolved_error_records === 0 ? <p className="mt-4 text-sm text-[var(--muted-foreground)]">暂无未结案的错误诊断。</p> : <ul className="mt-4 space-y-3">{Object.entries(report.mastery.error_types).sort((a, b) => b[1] - a[1]).map(([type, count]) => <li key={type} className="flex justify-between border-b border-[var(--border)] pb-2 text-sm last:border-0"><span>{ERROR_NAMES[type] ?? type}</span><span className="tabular-nums">{count}</span></li>)}</ul>}</section>
        </div>
      </>}
    </div>}
  </section>
}
