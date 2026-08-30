import { useEffect, useState } from 'react'
import { api, NewsItem, QuoteRow, SymbolDetail } from '../api/client'
import { CandleChart, scoreClass } from '../components/Chart'
import { useData } from '../context/DataContext'

type SubTab = 'latest' | 'watchlist'

export function IntelligencePage({ onSelectSymbol }: { onSelectSymbol: (s: string) => void }) {
  const { feed, watchlist, loading, error } = useData()
  const [sub, setSub] = useState<SubTab>('latest')

  return (
    <div>
      <div className="tabs">
        <button className={`tab ${sub === 'latest' ? 'active' : ''}`} onClick={() => setSub('latest')}>最新</button>
        <button className={`tab ${sub === 'watchlist' ? 'active' : ''}`} onClick={() => setSub('watchlist')}>自選</button>
      </div>

      {loading && !feed.length && <div className="loading">載入情報中…（API 啟動中會自動重試）</div>}
      {error && (
        <div className="error">
          {error}
          <div style={{ marginTop: 8 }}>
            <button type="button" className="btn btn-ghost" onClick={() => window.location.reload()}>重新整理</button>
          </div>
        </div>
      )}

      {sub === 'latest' && feed.map((item) => (
        <div
          className="card card-clickable"
          key={item.headline.slice(0, 40) + (item.published || '')}
          onClick={() => item.url && window.open(item.url, '_blank', 'noopener')}
          style={{ cursor: item.url ? 'pointer' : 'default' }}
        >
          <div className={scoreClass(item.score)}>
            {item.symbols[0] || 'MARKET'} {item.score}/10 · {item.score_label}
          </div>
          <p className="headline">{item.headline}</p>
          <div className="meta">
            {item.source} · 影響 {item.impact}
            {item.url && <span> · 點擊開啟原文 ↗</span>}
          </div>
          {item.quotes && (
            <div className="ticker-row" onClick={(e) => e.stopPropagation()}>
              {item.quotes.map((q: QuoteRow) => (
                <span
                  key={q.symbol}
                  className={`ticker-chip ${q.direction}`}
                  onClick={() => onSelectSymbol(q.symbol)}
                >
                  {q.symbol} {q.direction === 'up' ? '↗' : '↘'} {q.change_pct}%
                </span>
              ))}
            </div>
          )}
        </div>
      ))}

      {sub === 'watchlist' && watchlist.items.map((row) => (
        <div className="list-row" key={row.symbol} onClick={() => onSelectSymbol(row.symbol)}>
          <div>
            <strong>{row.symbol}</strong>
            <div className="meta">{row.name}</div>
          </div>
          <div style={{ textAlign: 'right' }}>
            <div>${row.price?.toFixed(2)}</div>
            <div className={row.direction}>{row.direction === 'up' ? '↗' : '↘'} {row.change_pct}%</div>
          </div>
        </div>
      ))}
    </div>
  )
}

export function SymbolDetailModal({
  symbol,
  onClose,
}: {
  symbol: string | null
  onClose: () => void
}) {
  const [tab, setTab] = useState<'chart' | 'news' | 'earnings'>('chart')
  const [data, setData] = useState<SymbolDetail | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    if (!symbol) return
    setLoading(true)
    setError('')
    setData(null)
    api.symbolDetail(symbol)
      .then(setData)
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false))
  }, [symbol])

  if (!symbol) return null

  return (
    <div
      style={{
        position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.75)',
        zIndex: 100, padding: 16, overflow: 'auto',
      }}
      onClick={onClose}
    >
      <div className="card" style={{ maxWidth: 900, margin: '24px auto' }} onClick={(e) => e.stopPropagation()}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <h2 style={{ margin: 0 }}>{symbol}</h2>
          <button className="btn btn-ghost" onClick={onClose}>關閉</button>
        </div>

        {loading && <div className="loading">載入 K 線與資料…</div>}
        {error && <div className="error">{error}</div>}
        {data && (
          <>
            <div className="meta">
              ${data.quote.price} · {data.quote.change_pct}% · 基本面 {(data.fundamental as { tier?: string }).tier || '—'}
            </div>

            <div className="detail-tabs">
              <button className={`tab ${tab === 'chart' ? 'active' : ''}`} onClick={() => setTab('chart')}>K線</button>
              <button className={`tab ${tab === 'news' ? 'active' : ''}`} onClick={() => setTab('news')}>新聞</button>
              <button className={`tab ${tab === 'earnings' ? 'active' : ''}`} onClick={() => setTab('earnings')}>財報</button>
            </div>

            {tab === 'chart' && (data.ohlcv.length ? <CandleChart data={data.ohlcv} /> : <div className="meta">無 K 線數據</div>)}
            {tab === 'news' && (data.news.length ? data.news.map((n) => (
              <div
                key={n.headline}
                className="card card-clickable"
                onClick={() => n.url && window.open(n.url, '_blank', 'noopener')}
                style={{ cursor: n.url ? 'pointer' : 'default' }}
              >
                <div className={scoreClass(n.score)}>{n.score}/10 · {n.score_label}</div>
                <p className="headline">{n.headline}</p>
                <div className="meta">{n.source}{n.url && ' · 點擊開啟 ↗'}</div>
              </div>
            )) : <div className="meta">暫無新聞</div>)}
            {tab === 'earnings' && (
              data.earnings.length ? data.earnings.map((e) => (
                <div key={e.symbol + e.date} className="card">
                  <div className={scoreClass(e.score)}>財報評分 {e.score}/10 · {e.score_label}</div>
                  <p>{e.analysis}</p>
                  <div className="meta">{e.date} · {e.hour_label} · EPS 預估 {e.eps_estimate ?? '—'}</div>
                </div>
              )) : <div className="meta">近期無財報日程</div>
            )}
          </>
        )}
      </div>
    </div>
  )
}
