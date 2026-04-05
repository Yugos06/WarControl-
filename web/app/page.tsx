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

const fmtTime = (ts: string) =>
  new Date(ts).toLocaleTimeString("fr-FR", { hour12: false });

export default function Home() {
  const [events, setEvents] = useState<EventItem[]>([]);
  const [stats, setStats] = useState<StatItem[]>([]);
  const [status, setStatus] = useState<string>("connecting");

  const topEvents = useMemo(() => events.slice(0, 12), [events]);

  useEffect(() => {
    let active = true;

    const load = async () => {
      try {
        const [eventsRes, statsRes] = await Promise.all([
          fetch(`${API_URL}/events?limit=200`),
          fetch(`${API_URL}/stats`),
        ]);
        if (!eventsRes.ok || !statsRes.ok) {
          throw new Error("API not ready");
        }
        const eventsJson = await eventsRes.json();
        const statsJson = await statsRes.json();
        if (!active) return;
        setEvents(eventsJson.events || []);
        setStats(statsJson.by_type || []);
        setStatus("live");
      } catch (err) {
        if (!active) return;
        setStatus("offline");
      }
    };

    load();
    const id = setInterval(load, 3000);
    return () => {
      active = false;
      clearInterval(id);
    };
  }, []);

  return (
    <div className="page">
      <header className="hero">
        <div className="hero-text">
          <span className={`badge ${status}`}>{status}</span>
          <h1>WarControl</h1>
          <p>
            Tableau de bord NationGlory. Données collectées via les logs client
            Java. Couverture partagée par les membres connectés.
          </p>
          <div className="meta">
            <div>
              <strong>API</strong>
              <span>{API_URL}</span>
            </div>
            <div>
              <strong>Événements</strong>
              <span>{events.length}</span>
            </div>
          </div>
        </div>
        <div className="hero-panel">
          <h2>Activité récente</h2>
          <div className="event-list">
            {topEvents.map((event) => (
              <div key={event.id} className={`event ${event.type}`}>
                <div className="event-meta">
                  <span className="event-type">{event.type}</span>
                  <span className="event-time">{fmtTime(event.ts)}</span>
                </div>
                <p>{event.message}</p>
              </div>
            ))}
            {topEvents.length === 0 && (
              <div className="event empty">Aucun événement pour le moment.</div>
            )}
          </div>
        </div>
      </header>

      <section className="grid">
        <div className="panel">
          <h3>Stats par type</h3>
          <div className="stat-grid">
            {stats.map((item) => (
              <div key={item.type} className="stat">
                <span>{item.type}</span>
                <strong>{item.count}</strong>
              </div>
            ))}
            {stats.length === 0 && (
              <div className="stat empty">Pas encore de stats.</div>
            )}
          </div>
        </div>
        <div className="panel">
          <h3>Conseils de couverture</h3>
          <ul className="tips">
            <li>Plusieurs membres lancent le collector pour couvrir le serveur.</li>
            <li>
              Un joueur “observer” connecté longtemps stabilise la visibilité.
            </li>
            <li>
              Les logs sont buffered si l'API est hors-ligne (spool local).
            </li>
          </ul>
        </div>
      </section>

      <section className="panel full">
        <h3>Flux complet</h3>
        <div className="table">
          <div className="table-head">
            <span>Heure</span>
            <span>Type</span>
            <span>Message</span>
            <span>Acteur</span>
            <span>Cible</span>
          </div>
          {events.slice(0, 40).map((event) => (
            <div key={event.id} className="table-row">
              <span>{fmtTime(event.ts)}</span>
              <span className={`pill ${event.type}`}>{event.type}</span>
              <span>{event.message}</span>
              <span>{event.actor || "-"}</span>
              <span>{event.target || "-"}</span>
            </div>
          ))}
          {events.length === 0 && (
            <div className="table-row empty">Flux vide.</div>
          )}
        </div>
      </section>
    </div>
  );
}
