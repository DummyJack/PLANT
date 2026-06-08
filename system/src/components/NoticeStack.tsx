import { AlertCircle, CheckCircle2, Info, X } from "lucide-react";
import { useEffect, useState } from "react";
import { useNoticeStore, type NoticeTone } from "@/stores/noticeStore";
import { cn } from "@/utils/cn";

const TONE_STYLES: Record<NoticeTone, { box: string; icon: string }> = {
  error: {
    box: "border-red-200 bg-red-50 text-red-900",
    icon: "text-red-500",
  },
  success: {
    box: "border-emerald-200 bg-emerald-50 text-emerald-900",
    icon: "text-emerald-500",
  },
  info: {
    box: "border-slate-200 bg-white text-slate-900",
    icon: "text-slate-500",
  },
};

function NoticeIcon({ tone }: { tone: NoticeTone }) {
  if (tone === "success") return <CheckCircle2 className="h-4 w-4" />;
  if (tone === "info") return <Info className="h-4 w-4" />;
  return <AlertCircle className="h-4 w-4" />;
}

export function NoticeStack() {
  const notices = useNoticeStore((s) => s.notices);
  const dismissNotice = useNoticeStore((s) => s.dismissNotice);
  const [now, setNow] = useState(Date.now());

  useEffect(() => {
    if (!notices.length) return;
    const timer = window.setInterval(() => setNow(Date.now()), 250);
    return () => window.clearInterval(timer);
  }, [notices.length]);

  useEffect(() => {
    for (const notice of notices) {
      const ttl = notice.tone === "error" ? 7000 : 3500;
      if (now - notice.createdAt > ttl) dismissNotice(notice.id);
    }
  }, [dismissNotice, notices, now]);

  if (!notices.length) return null;

  return (
    <div className="pointer-events-none fixed right-4 top-16 z-50 flex w-80 flex-col gap-2">
      {notices.map((notice) => {
        const styles = TONE_STYLES[notice.tone];
        const ttl = notice.tone === "error" ? 7000 : 3500;
        const fadeStart = ttl - 900;
        const age = now - notice.createdAt;
        const fadeProgress = Math.max(0, Math.min(1, (age - fadeStart) / 900));
        return (
          <div
            key={notice.id}
            style={{
              opacity: 1 - fadeProgress,
              transform: `translateY(${fadeProgress * -4}px)`,
            }}
            className={cn(
              "pointer-events-auto rounded-card border p-3 shadow-lg transition-[opacity,transform] duration-200",
              styles.box,
            )}
          >
            <div className="flex gap-2">
              <div className={cn("mt-0.5 shrink-0", styles.icon)}>
                <NoticeIcon tone={notice.tone} />
              </div>
              <div className="min-w-0 flex-1">
                <p className="text-sm font-semibold">{notice.title}</p>
                {notice.message && (
                  <p className="mt-1 text-xs leading-5 opacity-80">
                    {notice.message}
                  </p>
                )}
              </div>
              <button
                type="button"
                className="shrink-0 rounded p-1 opacity-60 hover:bg-white/50 hover:opacity-100"
                onClick={() => dismissNotice(notice.id)}
                aria-label="關閉提示"
              >
                <X className="h-3.5 w-3.5" />
              </button>
            </div>
          </div>
        );
      })}
    </div>
  );
}
