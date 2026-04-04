"use client";
import { useState, useEffect, useCallback } from "react";
import { apiFetch } from "@/lib/api";

interface Issue {
  id: string;
  severity: "high" | "medium" | "low";
  summary: string;
  count: number;
  ts: number;
  category: string;
}

export default function IssueBanner() {
  const [issues, setIssues] = useState<Issue[]>([]);

  const fetchIssues = useCallback(async () => {
    try {
      const data = await apiFetch("/api/issues");
      setIssues(data.issues || []);
    } catch {
      // silently ignore — banner just won't show
    }
  }, []);

  useEffect(() => {
    fetchIssues();
    const interval = setInterval(fetchIssues, 15000);
    return () => clearInterval(interval);
  }, [fetchIssues]);

  const dismiss = async (issueId: string) => {
    try {
      await apiFetch(`/api/issues/${encodeURIComponent(issueId)}/dismiss`, {
        method: "POST",
      });
      setIssues((prev) => prev.filter((i) => i.id !== issueId));
    } catch {
      // ignore
    }
  };

  if (issues.length === 0) return null;

  return (
    <div className="shrink-0 px-3 pt-1">
      {issues.map((issue) => (
        <div
          key={issue.id}
          className={`flex items-center gap-3 px-3 py-1.5 rounded text-xs mono mb-1 ${
            issue.severity === "high"
              ? "bg-red-500/15 border border-red-500/30 text-red-300"
              : "bg-amber-500/15 border border-amber-500/30 text-amber-300"
          }`}
        >
          <span className="text-sm">
            {issue.severity === "high" ? "🚨" : "⚠️"}
          </span>
          <span className="flex-1 truncate">{issue.summary}</span>
          <span className="text-[10px] text-slate-500 shrink-0">
            {issue.category} · {issue.count}x
          </span>
          <button
            onClick={() => dismiss(issue.id)}
            className="text-slate-500 hover:text-white transition-colors text-[10px] shrink-0 px-1"
            title="Dismiss"
          >
            ✕
          </button>
        </div>
      ))}
    </div>
  );
}
