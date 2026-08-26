import { useState } from 'react'
import { api, SearchResult } from '../api/client'
import { useData } from '../context/DataContext'

export function SearchPage({ onSelectSymbol, onAddWatchlist }: {
  onSelectSymbol: (s: string) => void
  onAddWatchlist: (s: string) => void
}) {
  const { trends } = useData()
  const [q, setQ] = useState('')
  const [results, setResults] = useState<SearchResult[]>([])

  const search = async () => {
    if (!q.trim()) return
    const r = await api.search(q)
    setResults(r.results)
  }

  return (
    <div>
      <input
        className="search-input"
        placeholder="搜尋新聞、股票代碼、ETF…"
        value={q}
        onChange={(e) => setQ(e.target.value)}
        onKeyDown={(e) => e.key === 'Enter' && search()}
      />
      <button className="btn" onClick={search} style={{ marginTop: 8, width: '100%' }}>搜尋</button>

      {results.map((r) => (
        <div className="list-row" key={r.symbol}>
          <div>
            <strong>{r.symbol}</strong>
            <div className="meta">{r.name} · {r.type}</div>
          </div>
          <div style={{ display: 'flex', gap: 8 }}>
            <button className="btn btn-ghost" onClick={() => onSelectSymbol(r.symbol)}>查看</button>
            <button className="btn" onClick={() => onAddWatchlist(r.symbol)}>自選</button>
          </div>
        </div>
      ))}

      <h3 style={{ margin: '24px 0 12px' }}>熱門趨勢</h3>
      {trends.map((t) => (
        <div
          className="card card-clickable"
          key={t.headline.slice(0, 30)}
          onClick={() => t.url && window.open(t.url, '_blank', 'noopener')}
          style={{ cursor: t.url ? 'pointer' : 'default' }}
        >
          <div className="meta">#{t.rank ?? '—'} · {t.article_count ?? 1} 篇相關</div>
          <p className="headline">{t.headline}</p>
          {t.symbols?.length > 0 && (
            <div className="ticker-row" onClick={(e) => e.stopPropagation()}>
              {t.symbols.slice(0, 4).map((s: string) => (
                <span className="ticker-chip" key={s} onClick={() => onSelectSymbol(s)}>{s}</span>
              ))}
            </div>
          )}
        </div>
      ))}
    </div>
  )
}
