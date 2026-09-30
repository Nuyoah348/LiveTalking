"use client";

type Source = { title: string; kb_name?: string; page?: string | number; content?: string; url?: string };

function sourceFrom(value: unknown): Source | null {
  if (!value || typeof value !== "object") return null;
  const raw = value as Record<string, unknown>;
  if (typeof raw.title !== "string" || !raw.title.trim()) return null;
  let url: string | undefined;
  if (typeof raw.url === "string") {
    try {
      const parsed = new URL(raw.url);
      if (["https:", "http:"].includes(parsed.protocol)) url = parsed.href;
    } catch { /* A local file path is shown by title and excerpt instead. */ }
  }
  return {
    title: raw.title,
    kb_name: typeof raw.kb_name === "string" ? raw.kb_name : undefined,
    page: typeof raw.page === "string" || typeof raw.page === "number" ? raw.page : undefined,
    content: typeof raw.content === "string" ? raw.content : undefined,
    url,
  };
}

export default function LearningSources({ sources }: { sources: unknown[] }) {
  const visible = sources.map(sourceFrom).filter((item): item is Source => item !== null);
  if (!visible.length) return null;
  return <details className="mt-4 rounded-xl border border-[var(--border)] bg-[var(--card)] p-4 text-sm">
    <summary className="cursor-pointer font-medium">本轮检索资料（{visible.length}）</summary>
    <p className="mt-2 text-xs text-[var(--muted-foreground)]">以下是智能体检索到的资料片段，可用于核对讲解内容。</p>
    <ol className="mt-3 space-y-3">
      {visible.map((source, index) => <li key={`${source.title}-${source.page ?? ""}-${index}`} className="border-t border-[var(--border)] pt-3 first:border-0 first:pt-0">
        <div className="font-medium">{source.url ? <a href={source.url} target="_blank" rel="noopener noreferrer" className="text-teal-700 underline dark:text-teal-300">{source.title}</a> : source.title}</div>
        <div className="mt-0.5 text-xs text-[var(--muted-foreground)]">{[source.kb_name, source.page != null ? `第 ${source.page} 页` : null].filter(Boolean).join(" · ")}</div>
        {source.content && <p className="mt-2 whitespace-pre-wrap text-xs leading-6 text-[var(--muted-foreground)]">{source.content}</p>}
      </li>)}
    </ol>
  </details>;
}
