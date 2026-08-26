import { useMemo, useState } from 'react'
import { api, EarningsItem } from '../api/client'
import { scoreClass } from '../components/Chart'
import { useData } from '../context/DataContext'

export function CalendarPage() {
  const { earningsWeek, loading } = useData()
  const [date, setDate] = useState(new Date().toISOString().slice(0, 10))
  const [selected, setSelected] = useState<EarningsItem | null>(null)
  const [extraItems, setExtraItems] = useState<EarningsItem[]>([])
  const [fetching, setFetching] = useState(false)

  const items = useMemo(() => {
    const fromCache = earningsWeek.filter((e) => e.date?.slice(0, 10) === date)
    const seen = new Set(fromCache.map((e) => e.symbol))
    const merged = [...fromCache]
    for (const e of extraItems) {
      if (!seen.has(e.symbol)) merged.push(e)
    }
    return merged
  }, [earningsWeek, extraItems, date])

  const loadDate = async (d: string) => {
    setDate(d)
    const cached = earningsWeek.some((e) => e.date?.slice(0, 10) === d)
    if (cached) return
    setFetching(true)
    try {
      const r = await api.earnings(d)
      setExtraItems(r.items)
    } catch (e) {
      console.error(e)
    } finally {
      setFetching(false)
    }
  }

  const openDetail = async (symbol: string) => {
    const d = await api.earningsDetail(symbol, date)
    setSelected(d)
  }

  return (
    <div>
      <div className="card">
        <h2 style={{ margin: 0 }}>財報日曆</h2>
        <input
          className="input"
          type="date"
          value={date}
          onChange={(e) => loadDate(e.target.value)}
          style={{ marginTop: 12 }}
        />
        {(loading || fetching) && !items.length && <div className="loading" style={{ marginTop: 12 }}>載入財報…</div>}
      </div>

      {items.map((e) => (
        <div className="card" key={e.symbol + e.date} onClick={() => openDetail(e.symbol)} style={{ cursor: 'pointer' }}>
          <div className={scoreClass(e.score)}>{e.score}/10 · {e.score_label}</div>
          <strong>{e.symbol}</strong> · {e.name}
          <div className="meta">{e.date} · {e.hour_label} · EPS {e.eps_estimate ?? '—'}</div>
        </div>
      ))}

      {!loading && !fetching && items.length === 0 && (
        <div className="meta" style={{ padding: 16 }}>此日期暫無財報日程（可設定 FINNHUB_KEY 取得完整日曆）</div>
      )}

      {selected && (
        <div className="card" style={{ borderColor: 'var(--accent)' }}>
          <h3>{selected.symbol} 專業分析</h3>
          <p>{selected.analysis}</p>
          {selected.news?.map((n) => (
            <div key={n.headline} className="meta">{n.headline}</div>
          ))}
          <button className="btn btn-ghost" onClick={() => setSelected(null)}>關閉</button>
        </div>
      )}
    </div>
  )
}
