import { useEffect, useState } from 'react'
import { api, EarningsItem } from '../api/client'
import { scoreClass } from '../components/Chart'

export function CalendarPage() {
  const [date, setDate] = useState(new Date().toISOString().slice(0, 10))
  const [items, setItems] = useState<EarningsItem[]>([])
  const [selected, setSelected] = useState<EarningsItem | null>(null)

  useEffect(() => {
    api.earnings(date).then((r) => setItems(r.items)).catch(console.error)
  }, [date])

  const openDetail = async (symbol: string) => {
    const d = await api.earningsDetail(symbol, date)
    setSelected(d)
  }

  return (
    <div>
      <div className="card">
        <h2 style={{ margin: 0 }}>財報日曆</h2>
        <input className="input" type="date" value={date} onChange={(e) => setDate(e.target.value)} style={{ marginTop: 12 }} />
      </div>

      {items.map((e) => (
        <div className="card" key={e.symbol + e.date} onClick={() => openDetail(e.symbol)} style={{ cursor: 'pointer' }}>
          <div className={scoreClass(e.score)}>{e.score}/10 · {e.score_label}</div>
          <strong>{e.symbol}</strong> · {e.name}
          <div className="meta">{e.date} · {e.hour_label} · EPS {e.eps_estimate ?? '—'}</div>
        </div>
      ))}

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
