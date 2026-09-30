'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import Link from 'next/link'
import { ArrowRight, ClipboardCheck } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { PRACTICE_HOME } from '@/lib/learning-routes'
import { getPracticeSummary, type PracticeSummary } from '@/lib/practice-api'
import { LearningErrorState } from './LearningShell'

/** The same all-workspace review scope learners see when they open Practice. */
export function PracticeAtAGlance() {
  const { t } = useTranslation()
  const [summary, setSummary] = useState<PracticeSummary | null>(null)
  const [error, setError] = useState(false)
  const sequence = useRef(0)

  const refresh = useCallback(async () => {
    const request = ++sequence.current
    try {
      const next = await getPracticeSummary('', '*')
      if (request !== sequence.current) return
      setSummary(next)
      setError(false)
    } catch {
      if (request === sequence.current) setError(true)
    }
  }, [])

  useEffect(() => {
    void refresh()
    const onFocus = () => {
      if (!document.hidden) void refresh()
    }
    window.addEventListener('focus', onFocus)
    document.addEventListener('visibilitychange', onFocus)
    const timer = window.setInterval(onFocus, 60_000)
    return () => {
      sequence.current++
      window.clearInterval(timer)
      window.removeEventListener('focus', onFocus)
      document.removeEventListener('visibilitychange', onFocus)
    }
  }, [refresh])

  return (
    <section aria-labelledby="learning-practice" className="mb-9">
      <h2 id="learning-practice" className="mb-3 text-[13.5px] font-semibold">
        {t("Today's review")}
      </h2>
      {error && (
        <LearningErrorState
          message={t(summary ? 'Could not refresh statistics. Showing the last loaded data.' : 'Could not load statistics.')}
          onRetry={() => void refresh()}
        />
      )}
      {!error && summary && summary.unavailable_workspaces?.length ? (
        <LearningErrorState
          message={t('Some workspaces could not be loaded. Available content is shown.')}
          onRetry={() => void refresh()}
        />
      ) : null}
      <Link
        href={PRACTICE_HOME}
        className="flex flex-wrap items-center gap-4 rounded-2xl border border-border bg-card p-5 transition hover:border-primary/30 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring sm:flex-nowrap"
      >
        <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-sky-500/10 text-sky-600 dark:text-sky-400">
          <ClipboardCheck size={21} aria-hidden="true" />
        </span>
        <div className="min-w-0 flex-1">
          <p aria-live="polite" className="text-sm font-medium">
            {summary
              ? summary.due > 0
                ? t('{{count}} questions are ready to revisit.', { count: summary.due })
                : error
                  ? t('Statistics unavailable')
                  : summary.unavailable_workspaces?.length
                    ? t('Some workspaces could not be loaded. Available content is shown.')
                : t('You are caught up. Come back when your next reviews are due.')
              : error ? t('Statistics unavailable') : t('Loading…')}
          </p>
          {summary && (
            <p className="mt-1 text-xs text-muted-foreground">
              {t('{{done}} reviewed today · {{overdue}} overdue', {
                done: summary.reviewed_today,
                overdue: summary.overdue,
              })}
              {' · '}{t('Mistakes')}: {summary.mistakes}
            </p>
          )}
        </div>
        <span className="inline-flex items-center gap-1.5 text-xs font-medium text-primary">
          {t('Practice')} <ArrowRight size={15} aria-hidden="true" />
        </span>
      </Link>
    </section>
  )
}
