"use client";
import { useState, useRef, useEffect } from "react";
import Sidebar from "@/components/Sidebar";
import { apiFetch } from "@/lib/api";
import { Send } from "lucide-react";

interface Message {
  role: "user" | "assistant";
  content: string;
  ts: number;
}

export default function ChatPage() {
  const [messages, setMessages] = useState<Message[]>([
    { role: "assistant", content: "Hi! I'm your Moonshot-CEX assistant. Ask me about positions, strategy, or market conditions.", ts: Date.now() },
  ]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const send = async () => {
    const text = input.trim();
    if (!text || loading) return;
    setInput("");
    setMessages((prev) => [...prev, { role: "user", content: text, ts: Date.now() }]);
    setLoading(true);
    try {
      const res = await apiFetch("/api/tc/api/message", {
        method: "POST",
        body: JSON.stringify({ message: text }),
      });
      const reply = (res.responseText ?? res.response ?? res.message ?? "No response") as string;
      setMessages((prev) => [...prev, { role: "assistant", content: reply, ts: Date.now() }]);
    } catch (e) {
      setMessages((prev) => [
        ...prev,
        { role: "assistant", content: `Error: ${(e as Error).message ?? "Request failed"}`, ts: Date.now() },
      ]);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex h-screen bg-[#050505] overflow-hidden">
      <Sidebar />
      <main className="flex-1 flex flex-col min-h-0">
        <header className="h-11 shrink-0 border-b border-cyan-900/20 bg-[#0A0F0D]/90 flex items-center px-4">
          <span className="text-xs font-bold tracking-[0.25em] uppercase neon-text-cyan mono">AI Chat</span>
          <span className="ml-3 text-[10px] mono text-slate-600">TinyOffice</span>
        </header>

        <div className="flex-1 overflow-y-auto p-4 space-y-3 min-h-0">
          {messages.map((m, i) => (
            <div key={i} className={`flex ${m.role === "user" ? "justify-end" : "justify-start"}`}>
              <div className={`max-w-[70%] rounded-xl px-3 py-2 text-xs mono ${
                m.role === "user"
                  ? "bg-cyan-500/15 border border-cyan-500/20 text-cyan-100"
                  : "bg-[#0d1410] border border-white/5 text-slate-300"
              }`}>
                {m.content}
              </div>
            </div>
          ))}
          {loading && (
            <div className="flex justify-start">
              <div className="bg-[#0d1410] border border-white/5 rounded-xl px-3 py-2 text-xs mono text-slate-500">
                <span className="animate-pulse">thinking...</span>
              </div>
            </div>
          )}
          <div ref={bottomRef} />
        </div>

        <div className="shrink-0 border-t border-white/5 p-3 flex gap-2">
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && !e.shiftKey && send()}
            placeholder="Ask about positions, strategy, risk..."
            className="flex-1 bg-[#0d1410] border border-white/10 rounded-lg px-3 py-2 text-xs mono text-slate-300 placeholder-slate-700 focus:border-cyan-500/30 focus:outline-none"
          />
          <button
            onClick={send}
            disabled={loading || !input.trim()}
            title="Send message"
            className="px-3 py-2 bg-cyan-500/15 border border-cyan-500/30 rounded-lg text-cyan-400 hover:bg-cyan-500/25 transition-colors disabled:opacity-40"
          >
            <Send size={14} />
          </button>
        </div>
      </main>
    </div>
  );
}
