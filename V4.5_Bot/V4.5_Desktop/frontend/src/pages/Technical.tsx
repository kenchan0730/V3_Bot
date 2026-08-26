import { useState } from 'react'
import { Sparkline, scoreClass } from '../components/Chart'
import { useData } from '../context/DataContext'
import type { TechnicalOverview } from '../api/client'

export function TechnicalPage() {
  const { technical, loading } = useData()
  const [section, setSection] = useState<'overview' | 'sectors' | 'headlines' | 'fundamentals'>('overview')

  if (loading && !technical) return <div className="loading">載入技術面…</div>
  if (!technical) return <div className="error">無法載入技術面數據</div>

  const env = technical.market_environment
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
          </div>

          <div className="card">
            <h3 style={{ margin: '0 0 12px' }}>Overall Market · ETF</h3>
            {technical.overall_market.length === 0 && <div className="meta">載入 ETF 數據中…</div>}
            <div className="grid-desktop-2">
              {technical.overall_market.map((etf: TechnicalOverview['overall_market'][0]) => (
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
                <div className="stat-value">{technical.internals.up_ratio}%</div>
              </div>
              <div className="stat-card">
                <div className="stat-label">下跌佔比</div>
                <div className="stat-value">{technical.internals.down_ratio}%</div>
              </div>
              <div className="stat-card">
                <div className="stat-label">上漲家數</div>
                <div className="stat-value">{technical.internals.advancing}</div>
              </div>
              <div className="stat-card">
                <div className="stat-label">平盤家數</div>
                <div className="stat-value">{technical.internals.unchanged}</div>
              </div>
            </div>
          </div>
        </>
      )}

      {section === 'sectors' && technical.sectors.map((s: TechnicalOverview['sectors'][0]) => (
        <div className="list-row" key={s.symbol}>
          <div>
            <strong>{s.name}</strong>
            <div className="meta">
              ETF {s.symbol}
              {(s as { lead_stock?: string }).lead_stock && (
                <> · 龍頭 {(s as { lead_stock?: string }).lead_stock} ${(s as { lead_price?: number }).lead_price} ({(s as { lead_change_pct?: number }).lead_change_pct}%)</>
              )}
            </div>
          </div>
          <div style={{ textAlign: 'right' }}>
            <div style={{ color: s.change_pct >= 0 ? 'var(--green)' : 'var(--red)' }}>
              {s.change_pct >= 0 ? '+' : ''}{s.change_pct}%
            </div>
            <div className="meta">vs SPY {s.vs_spy}%</div>
          </div>
        </div>
      ))}

      {section === 'headlines' && (
        technical.headlines.length ? technical.headlines.map((h: import('../api/client').NewsItem) => (
          <div
            className="card card-clickable"
            key={h.headline}
            onClick={() => h.url && window.open(h.url, '_blank', 'noopener')}
            style={{ cursor: h.url ? 'pointer' : 'default' }}
          >
            <div className={scoreClass(h.score)}>{h.score}/10 · {h.score_label}</div>
            <p className="headline">{h.headline}</p>
            <div className="meta">{h.source}{h.url && ' · 點擊開啟 ↗'}</div>
          </div>
        )) : <div className="meta">暫無極端頭條，請稍後刷新</div>
      )}

      {section === 'fundamentals' && technical.fundamentals_hot.map((f: TechnicalOverview['fundamentals_hot'][0]) => (
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
