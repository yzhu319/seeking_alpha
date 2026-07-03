import { useState, useEffect, useMemo, useCallback, Fragment } from "react";
import {
  ComposedChart, Line, Area, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, ReferenceLine, ReferenceArea, ReferenceDot, LineChart,
} from "recharts";
import {
  Loader2, RefreshCw, ChevronDown, ChevronUp, AlertTriangle, Activity,
} from "lucide-react";

// ---------------------------------------------------------------------------
// Universe: a cross-section of the AI infrastructure value chain, not just chips
// ---------------------------------------------------------------------------
const TICKERS = [
  { symbol: "NVDA", name: "Nvidia",              sector: "Compute",     color: "#5B8DEF" },
  { symbol: "AVGO", name: "Broadcom",             sector: "Networking",  color: "#A78BFA" },
  { symbol: "ANET", name: "Arista Networks",      sector: "Networking",  color: "#A78BFA" },
  { symbol: "MU",   name: "Micron",               sector: "Memory",      color: "#F472B6" },
  { symbol: "STX",  name: "Seagate",              sector: "Storage",     color: "#FB923C" },
  { symbol: "VRT",  name: "Vertiv",               sector: "Cooling",     color: "#22D3EE" },
  { symbol: "CEG",  name: "Constellation Energy", sector: "Power",       color: "#FDE047" },
  { symbol: "VST",  name: "Vistra",               sector: "Power",       color: "#FDE047" },
];

// ---------------------------------------------------------------------------
// Signal definition — kept deliberately simple: a Donchian breakout,
// confirmed by volume, filtered to only fire inside an established uptrend.
// ---------------------------------------------------------------------------
const LOOKBACK_HIGH = 60; // ~3 trading months
const VOL_WINDOW = 20;
const SMA_FAST = 20;
const SMA_SLOW = 50;
const VOL_MULT = 1.3;
const COOLDOWN = 10; // trading days before the same name can fire again

const PROXY = (url) => `https://api.allorigins.win/raw?url=${encodeURIComponent(url)}`;

function withTimeout(promise, ms) {
  return Promise.race([
    promise,
    new Promise((_, reject) => setTimeout(() => reject(new Error("timeout")), ms)),
  ]);
}

async function fetchText(url) {
  const res = await fetch(url);
  if (!res.ok) throw new Error("http " + res.status);
  return res.text();
}

function parseStooqCSV(text) {
  const lines = text.trim().split("\n");
  if (!lines[0] || !lines[0].toLowerCase().startsWith("date")) throw new Error("bad csv");
  return lines.slice(1).map((line) => {
    const [date, open, high, low, close, volume] = line.split(",");
    return { date, open: +open, high: +high, low: +low, close: +close, volume: +volume };
  });
}

function parseYahooJSON(json) {
  const result = json?.chart?.result?.[0];
  if (!result) throw new Error("bad json");
  const ts = result.timestamp || [];
  const q = result.indicators?.quote?.[0] || {};
  return ts.map((t, i) => ({
    date: new Date(t * 1000).toISOString().slice(0, 10),
    open: q.open?.[i], high: q.high?.[i], low: q.low?.[i],
    close: q.close?.[i], volume: q.volume?.[i],
  }));
}

function cleanRows(rows) {
  const map = new Map();
  rows.forEach((r) => {
    if (r.date && Number.isFinite(r.close) && r.close > 0 && Number.isFinite(r.volume)) {
      map.set(r.date, {
        ...r,
        high: Number.isFinite(r.high) ? r.high : r.close,
        low: Number.isFinite(r.low) ? r.low : r.close,
      });
    }
  });
  return [...map.values()].sort((a, b) => (a.date < b.date ? -1 : a.date > b.date ? 1 : 0)).slice(-460);
}

async function fetchSymbol(symbol) {
  const stooqUrl = `https://stooq.com/q/d/l/?s=${symbol.toLowerCase()}.us&i=d`;
  const yahooUrl = `https://query1.finance.yahoo.com/v8/finance/chart/${symbol}?range=2y&interval=1d`;
  const attempts = [
    () => withTimeout(fetchText(stooqUrl), 7000).then(parseStooqCSV),
    () => withTimeout(fetchText(PROXY(stooqUrl)), 9000).then(parseStooqCSV),
    () => withTimeout(fetchText(PROXY(yahooUrl)), 9000).then((t) => parseYahooJSON(JSON.parse(t))),
  ];
  let lastErr;
  for (const attempt of attempts) {
    try {
      const rows = cleanRows(await attempt());
      if (rows.length >= 100) return rows;
      lastErr = new Error("insufficient rows");
    } catch (e) {
      lastErr = e;
    }
  }
  throw lastErr || new Error("failed to fetch " + symbol);
}

function computeSeries(rows) {
  const out = rows.map((r, i) => ({ ...r, i, fired: false }));
  let lastFired = -Infinity;
  for (let i = 0; i < out.length; i++) {
    if (i < LOOKBACK_HIGH) continue;
    const priorWindow = out.slice(i - LOOKBACK_HIGH, i);
    const priorHigh = Math.max(...priorWindow.map((r) => r.high));
    const volWindow = out.slice(i - VOL_WINDOW, i);
    const volAvg = volWindow.reduce((s, r) => s + r.volume, 0) / VOL_WINDOW;
    const sma20 = out.slice(i - SMA_FAST + 1, i + 1).reduce((s, r) => s + r.close, 0) / SMA_FAST;
    const sma50 = out.slice(i - SMA_SLOW + 1, i + 1).reduce((s, r) => s + r.close, 0) / SMA_SLOW;
    const breakout = out[i].close > priorHigh;
    const volOK = out[i].volume > VOL_MULT * volAvg;
    const trendOK = sma20 > sma50;
    const fired = breakout && volOK && trendOK && i - lastFired > COOLDOWN;
    out[i].fired = fired;
    out[i].donchianHigh = priorHigh;
    if (fired) lastFired = i;
  }
  return out;
}

function fmtDate(iso) {
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(y, m - 1, d).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
}
function fmtMonth(iso) {
  const [y, m] = iso.split("-").map(Number);
  return new Date(y, m - 1, 1).toLocaleDateString("en-US", { month: "short", year: "2-digit" });
}
function pct(n, digits = 1) {
  if (n == null || !Number.isFinite(n)) return "—";
  const sign = n > 0 ? "+" : "";
  return `${sign}${n.toFixed(digits)}%`;
}

function CustomTooltip({ active, payload, label }) {
  if (!active || !payload?.length) return null;
  const index = payload.find((p) => p.dataKey === "index")?.value;
  const score = payload.find((p) => p.dataKey === "score")?.value;
  return (
    <div className="aib-tooltip">
      <div className="aib-tooltip-date">{fmtDate(label)}</div>
      <div className="aib-tooltip-row"><span style={{ color: "#5FD3A6" }}>Index</span><span>{index?.toFixed(1)}</span></div>
      <div className="aib-tooltip-row"><span style={{ color: "#E8A33D" }}>Breakout score</span><span>{score}%</span></div>
    </div>
  );
}

function MiniTooltip({ active, payload, label }) {
  if (!active || !payload?.length) return null;
  const close = payload.find((p) => p.dataKey === "close")?.value;
  return (
    <div className="aib-tooltip">
      <div className="aib-tooltip-date">{fmtDate(label)}</div>
      <div className="aib-tooltip-row"><span style={{ color: "#8993A4" }}>Close</span><span>${close?.toFixed(2)}</span></div>
    </div>
  );
}

export default function AIInfraBreakoutBacktester() {
  const [status, setStatus] = useState("loading"); // loading | ready | error
  const [progress, setProgress] = useState({});
  const [dataBySymbol, setDataBySymbol] = useState({});
  const [failedSymbols, setFailedSymbols] = useState([]);
  const [playheadIndex, setPlayheadIndex] = useState(null);
  const [expanded, setExpanded] = useState(null);

  const loadAll = useCallback(async () => {
    setStatus("loading");
    setProgress({});
    setFailedSymbols([]);
    setPlayheadIndex(null);

    const promises = TICKERS.map((t) =>
      fetchSymbol(t.symbol)
        .then((rows) => {
          setProgress((p) => ({ ...p, [t.symbol]: "ok" }));
          return { symbol: t.symbol, rows };
        })
        .catch((err) => {
          setProgress((p) => ({ ...p, [t.symbol]: "fail" }));
          throw err;
        })
    );

    const settled = await Promise.allSettled(promises);
    const okData = {};
    const failed = [];
    settled.forEach((res, idx) => {
      if (res.status === "fulfilled") okData[res.value.symbol] = computeSeries(res.value.rows);
      else failed.push(TICKERS[idx].symbol);
    });

    setFailedSymbols(failed);
    if (Object.keys(okData).length < 4) {
      setStatus("error");
      return;
    }
    setDataBySymbol(okData);
    setStatus("ready");
  }, []);

  useEffect(() => { loadAll(); }, [loadAll]);

  const activeSymbols = useMemo(() => Object.keys(dataBySymbol), [dataBySymbol]);

  const dateIdxMaps = useMemo(() => {
    const maps = {};
    activeSymbols.forEach((sym) => {
      const m = new Map();
      dataBySymbol[sym].forEach((r, i) => m.set(r.date, i));
      maps[sym] = m;
    });
    return maps;
  }, [dataBySymbol, activeSymbols]);

  const masterDates = useMemo(() => {
    if (activeSymbols.length === 0) return [];
    let common = new Set(dataBySymbol[activeSymbols[0]].map((r) => r.date));
    for (let k = 1; k < activeSymbols.length; k++) {
      const s = new Set(dataBySymbol[activeSymbols[k]].map((r) => r.date));
      common = new Set([...common].filter((d) => s.has(d)));
    }
    return [...common].sort();
  }, [dataBySymbol, activeSymbols]);

  const compositeIndex = useMemo(() => {
    if (!masterDates.length) return [];
    const base = {};
    activeSymbols.forEach((sym) => { base[sym] = dataBySymbol[sym][dateIdxMaps[sym].get(masterDates[0])].close; });
    return masterDates.map(
      (date) =>
        (activeSymbols.reduce((s, sym) => s + dataBySymbol[sym][dateIdxMaps[sym].get(date)].close / base[sym], 0) /
          activeSymbols.length) *
        100
    );
  }, [masterDates, activeSymbols, dataBySymbol, dateIdxMaps]);

  const scoreSeries = useMemo(() => {
    if (!masterDates.length) return [];
    return masterDates.map((date) => {
      let active = 0;
      activeSymbols.forEach((sym) => {
        const i = dateIdxMaps[sym].get(date);
        if (i == null) return;
        const start = Math.max(0, i - COOLDOWN + 1);
        if (dataBySymbol[sym].slice(start, i + 1).some((r) => r.fired)) active++;
      });
      return Math.round((active / activeSymbols.length) * 100);
    });
  }, [masterDates, activeSymbols, dataBySymbol, dateIdxMaps]);

  const chartData = useMemo(
    () => masterDates.map((date, j) => ({ date, index: +compositeIndex[j]?.toFixed(2), score: scoreSeries[j] })),
    [masterDates, compositeIndex, scoreSeries]
  );

  const earliestBreakoutIndex = useMemo(() => scoreSeries.findIndex((s) => s >= 50), [scoreSeries]);

  useEffect(() => {
    if (status === "ready" && playheadIndex == null && masterDates.length) {
      setPlayheadIndex(Math.max(0, masterDates.length - 1 - 105)); // ~5 months back
    }
  }, [status, masterDates, playheadIndex]);

  function statsAtPlayhead(sym) {
    const series = dataBySymbol[sym];
    const idx = dateIdxMaps[sym].get(masterDates[playheadIndex]);
    if (idx == null) return null;
    const start = Math.max(0, idx - COOLDOWN + 1);
    const window = series.slice(start, idx + 1);
    let fireEntry = null;
    for (let k = window.length - 1; k >= 0; k--) {
      if (window[k].fired) { fireEntry = window[k]; break; }
    }
    const priceAtD = series[idx].close;
    const priceToday = series[series.length - 1].close;
    return {
      active: !!fireEntry,
      priceAtD,
      priceToday,
      fire: fireEntry
        ? {
            date: fireEntry.date,
            price: fireEntry.close,
            retToD: (priceAtD / fireEntry.close - 1) * 100,
            retToToday: (priceToday / fireEntry.close - 1) * 100,
          }
        : null,
    };
  }

  const ready = status === "ready" && playheadIndex != null;
  const playheadDate = ready ? masterDates[playheadIndex] : null;
  const lastDate = ready ? masterDates[masterDates.length - 1] : null;
  const activeCount = ready ? activeSymbols.filter((sym) => statsAtPlayhead(sym)?.active).length : 0;
  const compositeHindsight = ready ? (compositeIndex[masterDates.length - 1] / compositeIndex[playheadIndex] - 1) * 100 : null;
  const tradingDaysAgo = ready ? masterDates.length - 1 - playheadIndex : 0;

  return (
    <div className="aib-root">
      <style>{`
        .aib-root { background:#0A0D12; color:#E7EBF0; font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Inter,sans-serif; padding:28px 20px 40px; border-radius:16px; max-width:980px; margin:0 auto; }
        .mono { font-family: ui-monospace,"SF Mono","Cascadia Code","JetBrains Mono",Consolas,monospace; }
        .aib-eyebrow { font-family: ui-monospace,monospace; font-size:11px; letter-spacing:0.14em; text-transform:uppercase; color:#5FD3A6; margin-bottom:8px; }
        .aib-title { font-size:26px; font-weight:600; letter-spacing:-0.01em; margin:0 0 6px; }
        .aib-subtitle { color:#8993A4; font-size:14px; line-height:1.5; max-width:640px; margin:0 0 22px; }
        .aib-card { background:#12161D; border:1px solid #232935; border-radius:12px; padding:20px; margin-bottom:16px; }
        .aib-loading { display:flex; flex-direction:column; gap:10px; align-items:center; padding:50px 20px; }
        .aib-progress-grid { display:grid; grid-template-columns:repeat(4,1fr); gap:8px; width:100%; max-width:420px; margin-top:8px; }
        .aib-progress-item { display:flex; align-items:center; gap:6px; font-size:12px; padding:6px 8px; border-radius:6px; background:#181D26; color:#8993A4; }
        .aib-progress-item.ok { color:#5FD3A6; }
        .aib-progress-item.fail { color:#E8607A; }
        .aib-error { display:flex; flex-direction:column; align-items:center; gap:12px; padding:40px 20px; text-align:center; color:#8993A4; }
        .aib-btn { font-family:inherit; font-size:13px; font-weight:500; color:#E7EBF0; background:#181D26; border:1px solid #2A313D; border-radius:8px; padding:8px 14px; cursor:pointer; display:inline-flex; align-items:center; gap:6px; transition:border-color .15s; }
        .aib-btn:hover { border-color:#5FD3A6; }
        .aib-btn:disabled { opacity:0.4; cursor:not-allowed; }
        .aib-btn-primary { background:#173327; border-color:#2E5C46; color:#5FD3A6; }
        .aib-controls-row { display:flex; flex-wrap:wrap; gap:10px; align-items:center; justify-content:space-between; margin-bottom:14px; }
        .aib-btn-group { display:flex; gap:8px; flex-wrap:wrap; }
        .aib-playhead-label { font-family:ui-monospace,monospace; font-size:13px; color:#E7EBF0; }
        .aib-playhead-sub { font-size:11px; color:#8993A4; }
        .aib-slider { -webkit-appearance:none; width:100%; height:4px; border-radius:2px; background:#2A313D; outline:none; margin:14px 0 4px; }
        .aib-slider::-webkit-slider-thumb { -webkit-appearance:none; width:16px; height:16px; border-radius:50%; background:#E7EBF0; border:3px solid #5FD3A6; cursor:pointer; margin-top:-6px; }
        .aib-slider::-moz-range-thumb { width:16px; height:16px; border-radius:50%; background:#E7EBF0; border:3px solid #5FD3A6; cursor:pointer; }
        .aib-legend { display:flex; gap:18px; font-size:12px; color:#8993A4; margin-top:6px; }
        .aib-legend-dot { display:inline-block; width:9px; height:9px; border-radius:2px; margin-right:6px; vertical-align:middle; }
        .aib-tooltip { background:#181D26; border:1px solid #2A313D; border-radius:8px; padding:8px 12px; font-size:12px; }
        .aib-tooltip-date { color:#8993A4; margin-bottom:4px; }
        .aib-tooltip-row { display:flex; justify-content:space-between; gap:16px; }
        .aib-banner { display:flex; flex-wrap:wrap; align-items:center; justify-content:space-between; gap:18px; }
        .aib-banner-text { font-size:14px; color:#C5CCD6; max-width:520px; line-height:1.5; }
        .aib-banner-text b { color:#E7EBF0; }
        .aib-stat-big { text-align:right; }
        .aib-stat-big .num { font-family:ui-monospace,monospace; font-size:32px; font-weight:600; line-height:1; }
        .aib-stat-big .lbl { font-size:11px; color:#8993A4; text-transform:uppercase; letter-spacing:0.08em; margin-top:4px; }
        .aib-table { width:100%; border-collapse:collapse; font-size:13px; }
        .aib-table th { text-align:left; font-size:11px; text-transform:uppercase; letter-spacing:0.06em; color:#8993A4; font-weight:500; padding:0 10px 10px; border-bottom:1px solid #232935; }
        .aib-table td { padding:11px 10px; border-bottom:1px solid #181D26; vertical-align:middle; }
        .aib-table tr:last-child td { border-bottom:none; }
        .aib-table tr.expandable { cursor:pointer; }
        .aib-table tr.expandable:hover { background:#151A22; }
        .aib-sector-pill { font-size:11px; padding:2px 8px; border-radius:999px; background:rgba(255,255,255,0.06); }
        .aib-badge { font-size:11px; font-weight:600; padding:3px 9px; border-radius:999px; display:inline-block; }
        .aib-badge-active { background:rgba(95,211,166,0.14); color:#5FD3A6; }
        .aib-badge-none { background:rgba(255,255,255,0.06); color:#8993A4; }
        .aib-ret-pos { color:#5FD3A6; }
        .aib-ret-neg { color:#E8607A; }
        .aib-mini-row td { background:#0E1218; padding:0 10px 16px; }
        details.aib-details { color:#C5CCD6; font-size:13px; line-height:1.6; }
        details.aib-details summary { cursor:pointer; color:#E7EBF0; font-weight:500; padding:4px 0; }
        details.aib-details p { margin:10px 0; }
        .aib-foot { font-size:11px; color:#5B6472; line-height:1.6; margin-top:18px; }
      `}</style>

      <div className="aib-eyebrow">Walk-forward signal backtest</div>
      <h1 className="aib-title">AI Infra Breakout — Time Machine</h1>
      <p className="aib-subtitle">
        Drag the date back in time and the signal engine recomputes using only the data that existed on that day —
        no lookahead. A basket spanning compute, memory, storage, cooling, networking and power tracks a Donchian
        breakout confirmed by volume and trend, live from market data.
      </p>

      {status === "loading" && (
        <div className="aib-card aib-loading">
          <Loader2 className="mono" size={26} style={{ animation: "spin 1s linear infinite", color: "#5FD3A6" }} />
          <div style={{ fontSize: 13, color: "#8993A4" }}>Fetching live daily prices for {TICKERS.length} tickers…</div>
          <div className="aib-progress-grid">
            {TICKERS.map((t) => (
              <div key={t.symbol} className={`aib-progress-item ${progress[t.symbol] || ""}`}>
                {progress[t.symbol] === "ok" ? "✓" : progress[t.symbol] === "fail" ? "✕" : "…"} {t.symbol}
              </div>
            ))}
          </div>
        </div>
      )}

      {status === "error" && (
        <div className="aib-card aib-error">
          <AlertTriangle size={28} color="#E8607A" />
          <div>Couldn't load enough live market data to run the backtest right now.</div>
          {failedSymbols.length > 0 && <div style={{ fontSize: 12 }}>Failed: {failedSymbols.join(", ")}</div>}
          <button className="aib-btn aib-btn-primary" onClick={loadAll}><RefreshCw size={14} /> Retry</button>
        </div>
      )}

      {ready && (
        <>
          {failedSymbols.length > 0 && (
            <div style={{ fontSize: 12, color: "#8993A4", marginBottom: 12 }}>
              Showing {activeSymbols.length} of {TICKERS.length} names — no live data for {failedSymbols.join(", ")}.
            </div>
          )}

          <div className="aib-card">
            <div className="aib-controls-row">
              <div>
                <div className="aib-playhead-label">{fmtDate(playheadDate)}</div>
                <div className="aib-playhead-sub">{tradingDaysAgo} trading days before latest close ({fmtDate(lastDate)})</div>
              </div>
              <div className="aib-btn-group">
                <button
                  className="aib-btn"
                  disabled={earliestBreakoutIndex < 0}
                  onClick={() => setPlayheadIndex(earliestBreakoutIndex)}
                  title={earliestBreakoutIndex < 0 ? "No majority breakout found in the loaded window" : ""}
                >
                  <Activity size={13} /> Jump to first breakout
                </button>
                <button className="aib-btn" onClick={() => setPlayheadIndex(masterDates.length - 1)}>Jump to today</button>
              </div>
            </div>

            <ResponsiveContainer width="100%" height={340}>
              <ComposedChart data={chartData} margin={{ top: 10, right: 8, left: -18, bottom: 0 }}>
                <CartesianGrid stroke="#1B212B" vertical={false} />
                <XAxis dataKey="date" tickFormatter={fmtMonth} tick={{ fill: "#8993A4", fontSize: 11 }}
                  axisLine={{ stroke: "#232935" }} tickLine={false} minTickGap={44} />
                <YAxis yAxisId="price" domain={["auto", "auto"]} tick={{ fill: "#8993A4", fontSize: 11 }} axisLine={false} tickLine={false} width={44} />
                <YAxis yAxisId="score" orientation="right" domain={[0, 100]} tick={{ fill: "#8993A4", fontSize: 11 }} axisLine={false} tickLine={false} width={34} />
                <Tooltip content={<CustomTooltip />} />
                <ReferenceLine yAxisId="score" y={50} stroke="#E8A33D" strokeDasharray="4 4" strokeOpacity={0.55} />
                <Area yAxisId="score" type="stepAfter" dataKey="score" stroke="#E8A33D" strokeWidth={1.2} fill="#E8A33D" fillOpacity={0.10} />
                <Line yAxisId="price" type="monotone" dataKey="index" stroke="#5FD3A6" strokeWidth={2.2} dot={false} />
                {playheadDate && (
                  <ReferenceArea yAxisId="price" x1={playheadDate} x2={lastDate} fill="#5FD3A6" fillOpacity={0.05} />
                )}
                {playheadDate && (
                  <ReferenceLine yAxisId="price" x={playheadDate} stroke="#E7EBF0" strokeWidth={1.4} />
                )}
              </ComposedChart>
            </ResponsiveContainer>

            <input
              type="range" className="aib-slider" min={0} max={masterDates.length - 1}
              value={playheadIndex} onChange={(e) => setPlayheadIndex(+e.target.value)}
            />
            <div className="aib-legend">
              <span><span className="aib-legend-dot" style={{ background: "#5FD3A6" }} />Basket index (rebased to 100)</span>
              <span><span className="aib-legend-dot" style={{ background: "#E8A33D" }} />Breakout score (% of basket confirmed)</span>
            </div>
          </div>

          <div className="aib-card aib-banner">
            <div className="aib-banner-text">
              As of <b>{fmtDate(playheadDate)}</b>, <b>{activeCount} of {activeSymbols.length}</b> AI infra names show a
              confirmed breakout (new {LOOKBACK_HIGH}-day high, on volume, inside an uptrend).{" "}
              {activeCount / activeSymbols.length >= 0.5
                ? "That's a majority — sector breakout regime active."
                : activeCount > 0
                ? "Below the majority threshold for a sector-wide call."
                : "No individual breakouts on that date."}
            </div>
            <div className="aib-stat-big">
              <div className={`num ${compositeHindsight >= 0 ? "aib-ret-pos" : "aib-ret-neg"}`}>{pct(compositeHindsight)}</div>
              <div className="lbl">Basket return, then → now</div>
            </div>
          </div>

          <div className="aib-card">
            <table className="aib-table">
              <thead>
                <tr>
                  <th>Ticker</th><th>Sector</th><th>Signal</th><th>Fired</th>
                  <th>Price @ fire</th><th>Return to {fmtMonth(playheadDate)}</th><th>Return to today</th>
                </tr>
              </thead>
              <tbody>
                {TICKERS.filter((t) => activeSymbols.includes(t.symbol)).map((t) => {
                  const s = statsAtPlayhead(t.symbol);
                  const isOpen = expanded === t.symbol;
                  return (
                    <Fragment key={t.symbol}>
                      <tr className="expandable" onClick={() => setExpanded(isOpen ? null : t.symbol)}>
                        <td>
                          <span className="mono" style={{ fontWeight: 600 }}>{t.symbol}</span>
                          <span style={{ color: "#8993A4", marginLeft: 8, fontSize: 12 }}>{t.name}</span>
                        </td>
                        <td><span className="aib-sector-pill" style={{ color: t.color }}>{t.sector}</span></td>
                        <td>{s?.active ? <span className="aib-badge aib-badge-active">Active</span> : <span className="aib-badge aib-badge-none">No signal</span>}</td>
                        <td className="mono" style={{ color: "#8993A4" }}>{s?.fire ? fmtDate(s.fire.date) : "—"}</td>
                        <td className="mono">{s?.fire ? `$${s.fire.price.toFixed(2)}` : "—"}</td>
                        <td className={`mono ${s?.fire && s.fire.retToD >= 0 ? "aib-ret-pos" : s?.fire ? "aib-ret-neg" : ""}`}>{s?.fire ? pct(s.fire.retToD) : "—"}</td>
                        <td className={`mono ${s?.fire && s.fire.retToToday >= 0 ? "aib-ret-pos" : s?.fire ? "aib-ret-neg" : ""}`}>
                          {s?.fire ? pct(s.fire.retToToday) : "—"} {isOpen ? <ChevronUp size={12} style={{ marginLeft: 4 }} /> : <ChevronDown size={12} style={{ marginLeft: 4 }} />}
                        </td>
                      </tr>
                      {isOpen && (
                        <tr className="aib-mini-row">
                          <td colSpan={7}>
                            <MiniChart symbol={t.symbol} color={t.color} dataBySymbol={dataBySymbol}
                              dateIdxMaps={dateIdxMaps} masterDates={masterDates} playheadDate={playheadDate} />
                          </td>
                        </tr>
                      )}
                    </Fragment>
                  );
                })}
              </tbody>
            </table>
          </div>

          <div className="aib-card">
            <details className="aib-details">
              <summary>Methodology</summary>
              <p><b>Breakout:</b> today's close exceeds the highest high of the prior {LOOKBACK_HIGH} trading days (~3 months).</p>
              <p><b>Volume confirmation:</b> today's volume exceeds {VOL_MULT}× the trailing {VOL_WINDOW}-day average.</p>
              <p><b>Trend filter:</b> {SMA_FAST}-day average price is above the {SMA_SLOW}-day average, i.e. the stock is already in an established uptrend.</p>
              <p><b>Cooldown:</b> once a name fires, it can't fire again for {COOLDOWN} trading days, so a signal marks the start of a move, not every day inside it.</p>
              <p><b>Basket index:</b> the eight names are rebased to 100 at the start of the window and equal-weighted. "Breakout score" is the share of the basket with a fresh signal in the trailing {COOLDOWN} days.</p>
              <p>This is a mechanical, rules-based screen for research purposes — not investment advice. Past signals say nothing certain about what happens next, and every free data source used here can have gaps or delays.</p>
            </details>
          </div>

          <div className="aib-foot">
            Data: live daily prices via Stooq/Yahoo Finance, fetched in your browser. Not investment advice — for
            research and educational use only. Refresh the page to pull the latest close.
          </div>
        </>
      )}
      <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
    </div>
  );
}

function MiniChart({ symbol, color, dataBySymbol, dateIdxMaps, masterDates, playheadDate }) {
  const series = dataBySymbol[symbol];
  const map = dateIdxMaps[symbol];
  const data = masterDates.map((date) => ({ date, close: series[map.get(date)].close }));
  const fireDates = masterDates.filter((date) => series[map.get(date)].fired);
  return (
    <ResponsiveContainer width="100%" height={150}>
      <LineChart data={data} margin={{ top: 10, right: 8, left: 0, bottom: 0 }}>
        <XAxis dataKey="date" tickFormatter={fmtMonth} tick={{ fill: "#5B6472", fontSize: 10 }} axisLine={{ stroke: "#1B212B" }} tickLine={false} minTickGap={60} />
        <YAxis domain={["auto", "auto"]} tick={{ fill: "#5B6472", fontSize: 10 }} axisLine={false} tickLine={false} width={40} />
        <Tooltip content={<MiniTooltip />} />
        <Line type="monotone" dataKey="close" stroke={color} strokeWidth={1.6} dot={false} />
        {playheadDate && <ReferenceLine x={playheadDate} stroke="#E7EBF0" strokeWidth={1} strokeDasharray="3 3" />}
        {fireDates.map((d) => (
          <ReferenceDot key={d} x={d} y={series[map.get(d)].close} r={4} fill={color} stroke="#0A0D12" strokeWidth={1.5} />
        ))}
      </LineChart>
    </ResponsiveContainer>
  );
}
