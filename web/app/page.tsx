"use client";

import { useEffect, useMemo, useState } from "react";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";

type EventItem = {
  id: number;
  ts: string;
  type: string;
  message: string;
  actor?: string | null;
  target?: string | null;
  server?: string | null;
  source?: string | null;
};
type StatItem = { type: string; count: number };
type Status = "live" | "waiting" | "offline";

const TYPE_COLORS: Record<string, string> = {
  kill:      "var(--color-kill)",
  join:      "var(--color-join)",
  chat:      "var(--color-chat)",
  leave:     "var(--color-leave)",
  war_alert: "var(--color-war)",
};

const fmtTime = (ts: string) =>
  new Date(ts).toLocaleTimeString("fr-FR", { hour12: false });

// ── Sub-components ────────────────────────────────────────────────────────────

function StatusBadge({ status }: { status: Status }) {
  const labels  = { live: "● LIVE", waiting: "◌ EN ATTENTE", offline: "✕ OFFLINE" };
  const colors  = { live: "var(--color-join)", waiting: "var(--color-waiting)", offline: "var(--color-kill)" };
  return (
    <span style={{
      padding: "2px 10px",
      border: `1px solid ${colors[status]}`,
      color: colors[status],
      fontSize: 10,
      letterSpacing: 1,
      textTransform: "uppercase" as const,
      fontWeight: "bold",
      boxShadow: `0 0 6px ${colors[status]}33`,
    }}>
      {labels[status]}
    </span>
  );
}

function StatCard({ label, value, color }: { label: string; value: number; color: string }) {
  return (
    <div style={{
      background: "var(--bg-card)",
      border: "1px solid var(--border)",
      padding: "10px 14px",
      display: "flex",
      flexDirection: "column" as const,
      gap: 2,
    }}>
      <span style={{ color: "var(--text-muted)", fontSize: 9, textTransform: "uppercase" as const, letterSpacing: 2 }}>
        {label}
      </span>
      <span style={{ fontSize: 28, fontWeight: "bold", color, textShadow: `0 0 10px ${color}55`, lineHeight: 1 }}>
        {value}
      </span>
    </div>
  );
}

function CollectorDot({ source, lastTs }: { source: string; lastTs: Date }) {
  const ageMs = Date.now() - lastTs.getTime();
  const ageS  = Math.floor(ageMs / 1000);
  const color = ageMs < 60_000 ? "var(--color-join)" : ageMs < 300_000 ? "var(--color-waiting)" : "#555";
  const ago   = ageS < 60 ? `${ageS}s` : `${Math.floor(ageS / 60)}min`;
  return (
    <span style={{
      display: "flex", alignItems: "center", gap: 5,
      background: "var(--bg-card)", border: "1px solid var(--border)",
      padding: "2px 8px", fontSize: 10, color: "var(--color-join)",
    }}>
      <span style={{
        width: 6, height: 6, borderRadius: "50%",
        background: color, boxShadow: `0 0 5px ${color}`,
        flexShrink: 0, display: "inline-block",
      }} />
      {source}
      <span style={{ color: "var(--text-muted)", fontSize: 9 }}>il y a {ago}</span>
    </span>
  );
}

function TypeBadge({ type }: { type: string }) {
  const color = TYPE_COLORS[type] || "#555";
  return (
    <span style={{
      fontSize: 9, letterSpacing: 1, textTransform: "uppercase" as const,
      fontWeight: "bold", padding: "1px 5px",
      borderLeft: `2px solid ${color}`,
      background: `${color}18`, color,
      minWidth: 60, display: "inline-block",
    }}>
      {type}
    </span>
  );
}

// ── Main ──────────────────────────────────────────────────────────────────────

export default function Home() {
  const [events,     setEvents]     = useState<EventItem[]>([]);
  const [stats,      setStats]      = useState<StatItem[]>([]);
  const [status,     setStatus]     = useState<Status>("offline");
  const [filterType, setFilterType] = useState<string>("all");
  const [search,     setSearch]     = useState<string>("");
  const [clock,      setClock]      = useState<string>("");
  const [prevMaxId,  setPrevMaxId]  = useState<number>(0);

  // Live clock
  useEffect(() => {
    const tick = () => setClock(new Date().toLocaleTimeString("fr-FR"));
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, []);

  // Poll API every 3s
  useEffect(() => {
    let active = true;
    const load = async () => {
      try {
        const [evRes, stRes] = await Promise.all([
          fetch(`${API_URL}/events?limit=200`),
          fetch(`${API_URL}/stats`),
        ]);
        if (!evRes.ok || !stRes.ok) throw new Error("API not ready");
        const evJson = await evRes.json();
        const stJson = await stRes.json();
        if (!active) return;
        const evs: EventItem[] = evJson.events || [];
        setEvents(prev => {
          setPrevMaxId(prev[0]?.id ?? 0);
          return evs;
        });
        setStats(stJson.by_type || []);
        if (evs.length === 0) {
          setStatus("waiting");
        } else {
          const ageMs = Date.now() - new Date(evs[0].ts).getTime();
          setStatus(ageMs < 60_000 ? "live" : "waiting");
        }
      } catch {
        if (!active) return;
        setStatus("offline");
      }
    };
    load();
    const id = setInterval(load, 3000);
    return () => { active = false; clearInterval(id); };
  }, []);

  // Collectors derived from events
  const collectors = useMemo(() => {
    const map = new Map<string, Date>();
    events.forEach(e => {
      if (!e.source) return;
      const ts = new Date(e.ts);
      if (!map.has(e.source) || ts > map.get(e.source)!) map.set(e.source, ts);
    });
    return Array.from(map.entries()).map(([source, lastTs]) => ({ source, lastTs }));
  }, [events]);

  // Stats by type
  const statMap = useMemo(() => {
    const m: Record<string, number> = {};
    stats.forEach(s => { m[s.type] = s.count; });
    return m;
  }, [stats]);

  // Filtered events
  const filteredEvents = useMemo(() => {
    return events.filter(e => {
      if (filterType !== "all" && e.type !== filterType) return false;
      if (search) {
        const s = search.toLowerCase();
        return !!(
          e.actor?.toLowerCase().includes(s) ||
          e.target?.toLowerCase().includes(s) ||
          e.message?.toLowerCase().includes(s)
        );
      }
      return true;
    });
  }, [events, filterType, search]);

  // Demo mode detection
  const isDemoMode = useMemo(
    () => events.slice(0, 10).some(e => e.source === "demo"),
    [events],
  );

  const FILTER_TYPES = ["all", "kill", "join", "leave", "chat", "war_alert"];

  return (
    <div style={{ padding: "16px 20px", maxWidth: 1100, margin: "0 auto" }}>

      {/* ── HEADER ── */}
      <div style={{
        display: "flex", justifyContent: "space-between", alignItems: "center",
        borderBottom: "1px solid var(--border)", paddingBottom: 10, marginBottom: 14,
      }}>
        <div>
          <span style={{ color: "var(--color-join)", fontSize: 15, letterSpacing: 3, textTransform: "uppercase" as const }}>
            ▶ WARCONTROL
          </span>
          <span style={{ color: "var(--text-muted)", fontSize: 11, marginLeft: 10, letterSpacing: 1 }}>
            NationsGlory
          </span>
        </div>
        <div style={{ display: "flex", gap: 12, alignItems: "center" }}>
          <StatusBadge status={status} />
          <span style={{ color: "#444", fontSize: 11 }}>{clock}</span>
        </div>
      </div>

      {/* ── BANNERS ── */}
      {isDemoMode && (
        <div style={{
          background: "#0d0820", border: "1px solid var(--color-demo)",
          padding: "6px 14px", marginBottom: 10,
          color: "var(--color-demo)", fontSize: 10, letterSpacing: 1,
        }}>
          ⬡ MODE DÉMO — événements simulés — lance Minecraft pour des données réelles
        </div>
      )}
      {status === "waiting" && (
        <div style={{
          background: "#1a1000", border: "1px solid var(--color-waiting)",
          padding: "8px 14px", marginBottom: 10,
          color: "var(--color-waiting)", fontSize: 11,
          display: "flex", gap: 10, alignItems: "center",
        }}>
          <span>⬛</span>
          EN ATTENTE DES LOGS — Lance une partie Minecraft, le collector démarrera automatiquement.
        </div>
      )}

      {/* ── STATS ── */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(4,1fr)", gap: 8, marginBottom: 12 }}>
        <StatCard label="Kills"  value={statMap["kill"]  ?? 0} color="var(--color-kill)"  />
        <StatCard label="Joins"  value={statMap["join"]  ?? 0} color="var(--color-join)"  />
        <StatCard label="Chats"  value={statMap["chat"]  ?? 0} color="var(--color-chat)"  />
        <StatCard label="Leaves" value={statMap["leave"] ?? 0} color="var(--color-leave)" />
      </div>

      {/* ── COLLECTORS ── */}
      {collectors.length > 0 && (
        <div style={{
          display: "flex", gap: 6, alignItems: "center", flexWrap: "wrap" as const,
          padding: "6px 10px", background: "var(--bg-card-dark)",
          border: "1px solid var(--border)", marginBottom: 10,
        }}>
          <span style={{ color: "var(--text-muted)", fontSize: 9, textTransform: "uppercase" as const, letterSpacing: 2, marginRight: 4 }}>
            📡 Collectors
          </span>
          {collectors.map(c => (
            <CollectorDot key={c.source} source={c.source} lastTs={c.lastTs} />
          ))}
        </div>
      )}

      {/* ── TOOLBAR ── */}
      <div style={{ display: "flex", gap: 6, alignItems: "center", marginBottom: 10, flexWrap: "wrap" as const }}>
        {FILTER_TYPES.map(t => {
          const color  = t === "all" ? "#888" : (TYPE_COLORS[t] || "#888");
          const active = filterType === t;
          return (
            <button key={t} onClick={() => setFilterType(t)} style={{
              padding: "3px 10px",
              border: `1px solid ${active ? color : "var(--border)"}`,
              background: active ? `${color}18` : "var(--bg-card)",
              color: active ? color : "var(--text-muted)",
              fontSize: 10, letterSpacing: 1, textTransform: "uppercase" as const,
            }}>
              [{t}]
            </button>
          );
        })}
        <span style={{ color: "var(--border)", margin: "0 4px" }}>|</span>
        <input
          value={search}
          onChange={e => setSearch(e.target.value)}
          placeholder="filtrer par joueur..."
          style={{
            background: "var(--bg-card)", border: "1px solid var(--border)",
            color: "var(--color-join)", fontSize: 11, padding: "3px 10px",
            outline: "none", width: 180,
          }}
        />
        {search && (
          <button onClick={() => setSearch("")} style={{
            background: "none", border: "none",
            color: "var(--text-muted)", fontSize: 11,
          }}>✕</button>
        )}
      </div>

      {/* ── FEED ── */}
      <div style={{ border: "1px solid var(--border)" }}>
        <div style={{
          display: "flex", justifyContent: "space-between", alignItems: "center",
          background: "var(--bg-card)", borderBottom: "1px solid var(--border)",
          padding: "5px 10px",
        }}>
          <span style={{ color: "var(--text-muted)", fontSize: 9, textTransform: "uppercase" as const, letterSpacing: 2 }}>
            Flux en direct
          </span>
          <span style={{ color: "var(--text-dim)", fontSize: 9 }}>
            {filteredEvents.length} événements
          </span>
        </div>

        {filteredEvents.length === 0 && (
          <div style={{ padding: "16px 10px", color: "var(--text-muted)", fontSize: 11, textAlign: "center" as const }}>
            Aucun événement.
          </div>
        )}

        {filteredEvents.map(e => {
          const isNew = e.id > prevMaxId && e.type === "kill";
          return (
            <div
              key={e.id}
              className={isNew ? "event-row flash-kill" : "event-row"}
              style={{
                display: "grid",
                gridTemplateColumns: "52px 80px 1fr 110px",
                padding: "5px 10px",
                borderBottom: "1px solid var(--border-dark)",
                gap: 8,
                alignItems: "center",
              }}
            >
              <span style={{ color: "var(--text-dim)", fontSize: 10 }}>{fmtTime(e.ts)}</span>
              <TypeBadge type={e.type} />
              <span style={{
                color: "var(--text-primary)", fontSize: 11,
                overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" as const,
              }}>
                {e.message}
              </span>
              <span style={{
                color: "var(--text-muted)", fontSize: 10, textAlign: "right" as const,
                overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" as const,
              }}>
                {e.actor && e.target ? `${e.actor} → ${e.target}` : (e.actor ?? "")}
              </span>
            </div>
          );
        })}
      </div>

      <style>{`
        @keyframes flashkill {
          0%   { background: #3a0808; }
          100% { background: transparent; }
        }
        .flash-kill {
          animation: flashkill 0.6s ease-out;
        }
        .event-row:hover {
          background: var(--bg-card-hover);
        }
      `}</style>
    </div>
  );
}
