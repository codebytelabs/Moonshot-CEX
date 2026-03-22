"use client";
import { useState, useEffect } from "react";
import Sidebar from "@/components/Sidebar";
import { Building2, RefreshCw, ExternalLink, AlertCircle, Loader2 } from "lucide-react";

const TINYOFFICE_URL = "http://localhost:3000";

type ConnState = "checking" | "online" | "offline";

export default function OfficePage() {
  const [connState, setConnState] = useState<ConnState>("checking");
  const [iframeKey, setIframeKey] = useState(0);

  const checkConn = () => {
    setConnState("checking");
    fetch(TINYOFFICE_URL, { mode: "no-cors" })
      .then(() => setConnState("online"))
      .catch(() => setConnState("offline"));
  };

  useEffect(() => {
    checkConn();
  }, []);

  const reload = () => {
    setIframeKey((k) => k + 1);
    checkConn();
  };

  return (
    <div className="flex h-screen bg-[#050505] overflow-hidden">
      <Sidebar />
      <main className="flex-1 flex flex-col min-w-0 overflow-hidden">
        <header className="h-11 shrink-0 border-b border-cyan-900/20 bg-[#0A0F0D]/90 backdrop-blur flex items-center px-4 gap-3">
          <Building2 size={14} className="text-cyan-400" />
          <span className="text-xs font-bold tracking-[0.25em] mono text-cyan-400">AGENT OFFICE</span>
          <span className="text-[10px] mono text-slate-600">// TinyClaw framework</span>
          <div className="ml-auto flex items-center gap-3">
            {connState === "online" && (
              <span className="flex items-center gap-1 text-[9px] mono text-green-400">
                <span className="w-1.5 h-1.5 rounded-full bg-green-400 animate-pulse inline-block" />
                CONNECTED
              </span>
            )}
            {connState === "offline" && (
              <span className="flex items-center gap-1 text-[9px] mono text-red-400">
                <AlertCircle size={10} />
                OFFLINE
              </span>
            )}
            {connState === "checking" && (
              <span className="flex items-center gap-1 text-[9px] mono text-slate-500">
                <Loader2 size={10} className="animate-spin" />
                CHECKING
              </span>
            )}
            <a
              href={TINYOFFICE_URL}
              target="_blank"
              rel="noreferrer"
              className="text-slate-600 hover:text-cyan-400 transition-colors"
              title="Open TinyOffice in new tab"
            >
              <ExternalLink size={12} />
            </a>
            <button onClick={reload} className="text-slate-600 hover:text-cyan-400 transition-colors" title="Reload">
              <RefreshCw size={12} />
            </button>
          </div>
        </header>

        <div className="flex-1 min-h-0 relative">
          {connState === "offline" ? (
            <div className="h-full flex flex-col items-center justify-center gap-4 text-center px-6">
              <Building2 size={40} className="text-slate-700" />
              <div className="space-y-1">
                <p className="text-sm mono font-bold text-slate-400">TinyOffice Not Running</p>
                <p className="text-[11px] mono text-slate-600">
                  Start the TinyClaw framework service to use the Agent Office.
                </p>
              </div>
              <div className="bg-[#0A0F0D] border border-cyan-900/30 rounded p-4 text-left w-full max-w-md">
                <p className="text-[9px] mono text-slate-600 mb-2">START COMMAND</p>
                <code className="text-[11px] mono text-cyan-400 block">
                  cd /Users/vishnuvardhanmedara/Moonshot-CEX/tinyclaw/tinyoffice<br />
                  npm install &amp;&amp; npm run dev
                </code>
                <p className="text-[9px] mono text-slate-600 mt-3">
                  Runs on <span className="text-cyan-400">{TINYOFFICE_URL}</span>
                </p>
              </div>
              <button
                onClick={reload}
                className="px-4 py-2 bg-cyan-500/10 hover:bg-cyan-500/20 border border-cyan-500/20 rounded text-xs mono text-cyan-400 transition-colors flex items-center gap-2"
              >
                <RefreshCw size={12} />
                Retry Connection
              </button>
            </div>
          ) : (
            <iframe
              key={iframeKey}
              src={TINYOFFICE_URL}
              className="w-full h-full border-0"
              title="TinyOffice — Agent Framework"
              sandbox="allow-scripts allow-same-origin allow-forms allow-popups allow-modals"
              onLoad={() => setConnState("online")}
              onError={() => setConnState("offline")}
            />
          )}
        </div>
      </main>
    </div>
  );
}
