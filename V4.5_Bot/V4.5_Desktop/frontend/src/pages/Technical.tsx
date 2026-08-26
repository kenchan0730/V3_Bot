import { useEffect, useState } from 'react'
import { api, TechnicalOverview } from '../api/client'
import { Sparkline, scoreClass } from '../components/Chart'

export function TechnicalPage() {
  const [data, setData] = useState<TechnicalOverview | null>(null)
  const [section, setSection] = useState<'overview' | 'sectors' | 'headlines' | 'fundamentals'>('overview')

  useEffect(() => {
    api.technical().then(setData).catch(console.error)
    const t = setInterval(() => api.technical().then(setData), 180000)
    return () => clearInterval(t)
  }, [])

  if (!data) return <div className="loading">載入技術面…</div>

  const env = data.market_environment
  const markerPct = Math.min(100, Math.max(0, env.score))

  return (
    <div>
      <div className="tabs">
        {(['overview', 'sectors', 'headlines', 'fundamentals'] as const).map((s) => (
          <button key={s} className={`tab ${section === s ? 'active' : ''}`} onClick={() => setSection(s)}>
            {s === 'overview' ? '概覽' : s === 'sectors' ? '板塊' : s === 'headlines' ? '頭條' : '基本面'}
          </button>
        ))}
      </div>

      {section === 'overview' && (
        <>
          <div className="card">
            <div className="stat-label">市場環境</div>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <div className="stat-value">{env.label}</div>
              <div className="stat-value">{env.score}/100</div>
            </div>
            <div className="gauge">
              <div className="gauge-marker" style={{ left: `${markerPct}%` }} />
            </div>
            <div className="meta">Risk-Off · 中性 · Risk-On</div>
          </div>

          <div className="card">
            <h3 style={{ margin: '0 0 12px' }}>Overall Market · ETF</h3>
            <div className="grid-desktop-2">
              {data.overall_market.map((etf) => (
                <div key={etf.symbol} className="stat-card">
                  <div className="stat-label">{etf.name} ({etf.symbol})</div>
                  <div className="stat-value" style={{ color: etf.change_pct >= 0 ? 'var(--green)' : 'var(--red)' }}>
                    {etf.change_pct >= 0 ? '+' : ''}{etf.change_pct}%
                  </div>
                  <div className="meta">${etf.price}</div>
                  <Sparkline values={etf.sparkline} />
                </div>
              ))}
            </div>
          </div>

          <div className="card">
            <h3 style={{ margin: '0 0 12px' }}>市場內部指標</h3>
            <div className="grid-2">
              <div className="stat-card">
                <div className="stat-label">上漲佔比</div>
                <div className="stat-value">{data.internals.up_ratio}%</div>
              </div>
              <div className="stat-card">
                <div className="stat-label">下跌佔比</div>
                <div className="stat-value">{data.internals.down_ratio}%</div>
              </div>
              <div className="stat-card">
                <div className="stat-label">上漲家數</div>
                <div className="stat-value">{data.internals.advancing}</div>
              </div>
              <div className="stat-card">
                <div className="stat-label">平盤家數</div>
                <div className="stat-value">{data.internals.unchanged}</div>
              </div>
            </div>
          </div>
        </>
      )}

      {section === 'sectors' && data.sectors.map((s) => (
        <div className="list-row" key={s.symbol}>
          <div>
            <strong>{s.name}</strong>
            <div className="meta">{s.symbol}</div>
          </div>
          <div style={{ textAlign: 'right' }}>
            <div style={{ color: s.change_pct >= 0 ? 'var(--green)' : 'var(--red)' }}>
              {s.change_pct >= 0 ? '+' : ''}{s.change_pct}%
            </div>
            <div className="meta">vs SPY {s.vs_spy}%</div>
          </div>
        </div>
      ))}

      {section === 'headlines' && data.headlines.map((h) => (
        <div className="card" key={h.headline}>
          <div className={scoreClass(h.score)}>{h.score}/10 · {h.score_label}</div>
          <p className="headline">{h.headline}</p>
          <div className="meta">{h.source}</div>
        </div>
      ))}

      {section === 'fundamentals' && data.fundamentals_hot.map((f) => (
        <div className="list-row" key={f.symbol}>
          <div>
            <strong>{f.symbol}</strong>
            <div className="meta">等級 {f.tier} · {f.tier_label}</div>
          </div>
          <div style={{ textAlign: 'right' }}>
            <div>${f.price?.toFixed(2)}</div>
            <div className={f.direction}>{f.change_pct}%</div>
          </div>
        </div>
      ))}
    </div>
  )
}
