"use client";
import { useCallback, useEffect, useMemo, useState } from "react";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const BANK = (process.env.NEXT_PUBLIC_BANK_INFO ?? "Configura NEXT_PUBLIC_BANK_INFO").split("|");
const CONTACT = process.env.NEXT_PUBLIC_CONTACT ?? "";
const MAX = 10;
const PACKS: [number, number][] = [[5, 8000], [3, 5000], [1, 2000]];
const price = (n: number) => PACKS.reduce((t, [s, p]) => { const k = Math.floor(n / s); n -= k * s; return t + k * p; }, 0);
const clp = (n: number) => n.toLocaleString("es-CL", { style: "currency", currency: "CLP", maximumFractionDigits: 0 });

type Taken = { total: number; sold: number[]; reserved: number[] };
type Stats = { total: number; sold: number; reserved: number; raised: number };
type Done = { order_id: number; amount: number; hold_minutes: number; numbers: number[] };

class ApiError extends Error {
  constructor(msg: string, public status: number, public taken: number[] = []) { super(msg); }
}

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(`${API}${path}`, { ...init, headers: { "Content-Type": "application/json" }, cache: "no-store" });
  const d = await r.json().catch(() => ({}));
  if (!r.ok) {
    const det = d?.detail;
    const msg = typeof det === "string" ? det : Array.isArray(det) ? "Revisa los datos del formulario." : det?.message ?? "Error inesperado";
    throw new ApiError(msg, r.status, det?.taken ?? []);
  }
  return d as T;
}

function rutOk(raw: string) {
  const r = raw.replace(/[.\-\s]/g, "").toUpperCase();
  if (!/^\d{7,8}[\dK]$/.test(r)) return false;
  let s = 0, m = 2;
  for (const d of r.slice(0, -1).split("").reverse()) { s += Number(d) * m; m = m === 7 ? 2 : m + 1; }
  const x = 11 - (s % 11);
  return r.slice(-1) === (x === 11 ? "0" : x === 10 ? "K" : String(x));
}

const input = "w-full rounded-xl border border-white/15 bg-white/5 px-3 py-2.5 outline-none focus:border-[#39ff88] focus:ring-1 focus:ring-[#39ff88]";

export default function Page() {
  const [taken, setTaken] = useState<Taken>({ total: 100, sold: [], reserved: [] });
  const [stats, setStats] = useState<Stats | null>(null);
  const [sel, setSel] = useState<number[]>([]);
  const [f, setF] = useState({ name: "", rut: "", email: "", phone: "", instagram: "" });
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState<Done | null>(null);

  const load = useCallback(async () => {
    try {
      const [t, s] = await Promise.all([api<Taken>("/api/numbers"), api<Stats>("/api/stats")]);
      setTaken(t); setStats(s);
    } catch { /* reintento silencioso */ }
  }, []);
  useEffect(() => { load(); const id = setInterval(load, 10000); return () => clearInterval(id); }, [load]);

  const blocked = useMemo(() => new Set([...taken.sold, ...taken.reserved]), [taken]);
  useEffect(() => { setSel((s) => s.filter((n) => !blocked.has(n))); }, [blocked]);

  const toggle = (n: number) => {
    if (blocked.has(n)) return;
    setSel((s) => (s.includes(n) ? s.filter((x) => x !== n) : s.length < MAX ? [...s, n].sort((a, b) => a - b) : s));
  };
  const addRandom = (k: number) => {
    const free = Array.from({ length: taken.total }, (_, i) => i + 1).filter((n) => !blocked.has(n) && !sel.includes(n));
    const out = [...sel];
    while (out.length < Math.min(MAX, sel.length + k) && free.length) out.push(free.splice(Math.floor(Math.random() * free.length), 1)[0]);
    setSel(out.sort((a, b) => a - b));
  };

  async function submit(e: React.FormEvent) {
    e.preventDefault(); setErr("");
    if (!sel.length) return setErr("Elige al menos un número.");
    if (!rutOk(f.rut)) return setErr("El RUT no es válido.");
    setBusy(true);
    try {
      setDone(await api<Done>("/api/orders", { method: "POST", body: JSON.stringify({ ...f, method: "transferencia", numbers: sel }) }));
      setSel([]);
    } catch (x) {
      if (x instanceof ApiError) { setErr(x.message); if (x.status === 409) setSel((s) => s.filter((n) => !x.taken.includes(n))); }
      else setErr("No se pudo conectar con el servidor. Intenta nuevamente.");
    } finally { setBusy(false); load(); }
  }

  const pct = stats ? Math.round(((stats.sold + stats.reserved) / stats.total) * 100) : 0;
  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement>) => setF({ ...f, [k]: e.target.value });

  return (
    <main className="min-h-screen bg-[#0b0715] bg-[radial-gradient(circle_at_15%_10%,rgba(139,92,246,.3),transparent_45%),radial-gradient(circle_at_85%_80%,rgba(57,255,136,.18),transparent_40%)] px-4 py-8 text-emerald-50">
      <div className="mx-auto max-w-3xl space-y-5">
        <header>
          <p className="text-sm text-violet-300">Centro de Alumnos · Ingeniería Civil en Biotecnología · UFRO</p>
          <h1 className="text-4xl font-bold md:text-5xl">BioRifa <span className="text-[#39ff88]">Solidaria</span> 🧬</h1>
        </header>

        <section className="rounded-2xl border border-white/10 bg-white/5 p-5 backdrop-blur">
          <div className="h-3 overflow-hidden rounded-full bg-white/10">
            <div className="h-full bg-gradient-to-r from-violet-500 to-[#39ff88] transition-all" style={{ width: `${pct}%` }} />
          </div>
          <p className="mt-2 text-sm text-violet-200">
            {stats ? `${stats.sold} vendidos · ${stats.reserved} reservados de ${stats.total} · ${clp(stats.raised)} recaudados` : "Cargando estadísticas..."}
          </p>
        </section>

        {done ? (
          <section className="space-y-3 rounded-2xl border border-[#39ff88]/60 bg-white/5 p-6 backdrop-blur">
            <h2 className="text-2xl font-bold text-[#39ff88]">✅ Reserva #{done.order_id} creada</h2>
            <p>Números: <b>{done.numbers.join(", ")}</b> · Total a transferir: <b>{clp(done.amount)}</b></p>
            <div className="rounded-xl bg-black/30 p-4 text-sm space-y-1">{BANK.map((l) => <p key={l}>{l}</p>)}</div>
            <p className="text-sm text-violet-200">
              Tus números quedan reservados por {done.hold_minutes >= 60 ? `${done.hold_minutes / 60} horas` : `${done.hold_minutes} minutos`}.
              Cuando validemos tu transferencia recibirás el comprobante con QR por correo{CONTACT ? `. Envía tu comprobante de pago al WhatsApp ${CONTACT} indicando la reserva #${done.order_id}` : ""}.
            </p>
            <button onClick={() => setDone(null)} className="rounded-xl border border-white/20 px-4 py-2 hover:border-[#39ff88] transition-colors">Hacer otra compra</button>
          </section>
        ) : (
          <>
            <section className="rounded-2xl border border-white/10 bg-white/5 p-5 backdrop-blur">
              <h2 className="mb-3 text-xl font-semibold">1 · Elige tus números</h2>
              <div className="mb-3 flex flex-wrap gap-2 text-sm">
                {[[1, "1 · $2.000"], [3, "+3 · pack $5.000"], [5, "+5 · pack $8.000 ★"]].map(([k, l]) => (
                  <button key={k} onClick={() => addRandom(k as number)} className="rounded-xl border border-white/20 px-3 py-2 hover:border-[#39ff88] transition-colors">{l} al azar</button>
                ))}
                <button onClick={() => setSel([])} className="rounded-xl px-3 py-2 text-violet-300 hover:text-white">Limpiar</button>
              </div>
              <div className="grid grid-cols-[repeat(auto-fill,minmax(46px,1fr))] gap-1.5">
                {Array.from({ length: taken.total }, (_, i) => i + 1).map((n) => {
                  const sold = taken.sold.includes(n), res = !sold && taken.reserved.includes(n), on = sel.includes(n);
                  return (
                    <button key={n} disabled={sold || res} onClick={() => toggle(n)} aria-pressed={on}
                      title={sold ? "Vendido" : res ? "Reservado" : "Disponible"}
                      className={`rounded-lg border py-2.5 text-sm transition-all ${on ? "border-[#39ff88] bg-[#39ff88] font-bold text-black" : sold ? "cursor-not-allowed border-white/5 text-white/20 line-through bg-black/20" : res ? "cursor-not-allowed border-violet-500/40 text-violet-400/50 bg-violet-950/20" : "border-white/15 hover:border-[#39ff88] hover:bg-white/10"}`}>
                      {n}
                    </button>
                  );
                })}
              </div>
              <p className="mt-2 text-xs text-violet-300">Máximo {MAX} por compra · violeta = reservado por otra persona</p>
            </section>

            <form onSubmit={submit} className="space-y-3 rounded-2xl border border-white/10 bg-white/5 p-5 backdrop-blur">
              <h2 className="text-xl font-semibold">2 · Tus datos</h2>
              <div className="grid gap-3 md:grid-cols-2">
                <input className={input} placeholder="Nombre completo" value={f.name} onChange={set("name")} required minLength={3} autoComplete="name" />
                <input className={input} placeholder="RUT (12.345.678-5)" value={f.rut} onChange={set("rut")} required autoComplete="off" />
                <input className={input} type="email" placeholder="Correo" value={f.email} onChange={set("email")} required autoComplete="email" />
                <input className={input} type="tel" placeholder="WhatsApp (+56 9 …)" value={f.phone} onChange={set("phone")} required autoComplete="tel" />
                <input className={input} placeholder="@instagram (opcional)" value={f.instagram} onChange={set("instagram")} />
              </div>
              <p className="text-xs text-violet-300">Usamos tus datos solo para gestionar la rifa y contactar al ganador.</p>
              {err && <p role="alert" className="rounded-lg bg-red-500/15 px-3 py-2 text-sm text-red-200">{err}</p>}
              <button disabled={busy || !sel.length} className="w-full rounded-xl bg-gradient-to-r from-violet-500 to-[#39ff88] py-3 font-bold text-black disabled:opacity-40 hover:opacity-90 transition-opacity">
                {busy ? "Reservando…" : `Reservar ${sel.length || ""} número${sel.length === 1 ? "" : "s"} · ${clp(price(sel.length))}`}
              </button>
            </form>
          </>
        )}
      </div>
    </main>
  );
}