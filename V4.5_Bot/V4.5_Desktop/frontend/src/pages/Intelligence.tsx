import { useCallback, useEffect, useState } from 'react'
import { api, NewsItem, QuoteRow } from '../api/client'
import { CandleChart, scoreClass } from '../components/Chart'

type SubTab = 'latest' | 'watchlist'

export function IntelligencePage({ onSelectSymbol }: { onSelectSymbol: (s: string) => void }) {
  const [sub, setSub] = useState<SubTab>('latest')
  const [feed, setFeed] = useState<NewsItem[]>([])
  const [watchlist, setWatchlist] = useState<QuoteRow[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const [f, w] = await Promise.all([api.intelligenceFeed(), api.watchlist()])
      setFeed(f.items)
      setWatchlist(w.items)
    } catch (e) {
      setError(String(e))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load()
    const t = setInterval(load, 120000)
    return () => clearInterval(t)
  }, [load])

  return (
    <div>
      <div className="tabs">
        <button className={`tab ${sub === 'latest' ? 'active' : ''}`} onClick={() => setSub('latest')}>最新</button>
        <button className={`tab ${sub === 'watchlist' ? 'active' : ''}`} onClick={() => setSub('watchlist')}>自選</button>
      </div>

      {loading && <div className="loading">載入情報中…</div>}
      {error && <div className="error">{error}</div>}

      {sub === 'latest' && feed.map((item) => (
        <div className="card" key={item.headline.slice(0, 40)}>
          <div className={scoreClass(item.score)}>
            {item.symbols[0] || 'MARKET'} {item.score}/10 · {item.score_label}
          </div>
          <p className="headline">{item.headline}</p>
          <div className="meta">{item.source} · 影響 {item.impact}</div>
          {item.quotes && (
            <div className="ticker-row">
              {item.quotes.map((q) => (
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

      {sub === 'watchlist' && watchlist.map((row) => (
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
  const [data, setData] = useState<Awaited<ReturnType<typeof api.symbolDetail>> | null>(null)
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (!symbol) return
    setLoading(true)
    api.symbolDetail(symbol)
      .then(setData)
      .catch(console.error)
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

        {loading && <div className="loading">載入詳情…</div>}
        {data && (
          <>
            <div className="meta">
              ${data.quote.price} · {data.quote.change_pct}% · 基本面 {String((data.fundamental as { tier?: string }).tier || '—')}
            </div>

            <div className="detail-tabs">
              <button className={`tab ${tab === 'chart' ? 'active' : ''}`} onClick={() => setTab('chart')}>K線</button>
              <button className={`tab ${tab === 'news' ? 'active' : ''}`} onClick={() => setTab('news')}>新聞</button>
              <button className={`tab ${tab === 'earnings' ? 'active' : ''}`} onClick={() => setTab('earnings')}>財報</button>
            </div>

            {tab === 'chart' && <CandleChart data={data.ohlcv} />}
            {tab === 'news' && data.news.map((n) => (
              <div key={n.headline} className="card">
                <div className={scoreClass(n.score)}>{n.score}/10 · {n.score_label}</div>
                <p className="headline">{n.headline}</p>
                <div className="meta">{n.source}</div>
              </div>
            ))}
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
