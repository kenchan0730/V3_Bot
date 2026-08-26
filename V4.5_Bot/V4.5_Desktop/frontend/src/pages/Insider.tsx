import { useEffect, useState } from 'react'
import { api, InsiderSummary } from '../api/client'

export function InsiderPage() {
  const [date, setDate] = useState(new Date().toISOString().slice(0, 10))
  const [sort, setSort] = useState('composite')
  const [data, setData] = useState<InsiderSummary | null>(null)

  useEffect(() => {
    api.insider(date, sort).then(setData).catch(console.error)
  }, [date, sort])

  if (!data) return <div className="loading">載入內部交易…</div>

  return (
    <div>
      <div className="card">
        <h2 style={{ margin: '0 0 12px' }}>內部交易</h2>
        <input className="input" type="date" value={date} onChange={(e) => setDate(e.target.value)} />
        <div className="meta" style={{ marginTop: 8 }}>Form 4 · 公開市場</div>
      </div>

      <div className="grid-2">
        <div className="stat-card">
          <div className="stat-label">買入</div>
          <div className="stat-value">${(data.buy_value / 1e6).toFixed(2)}M</div>
          <div className="meta">{data.buy_count} 筆 · {data.buy_count} 檔</div>
        </div>
        <div className="stat-card">
          <div className="stat-label">賣出</div>
          <div className="stat-value">${(data.sell_value / 1e6).toFixed(2)}M</div>
          <div className="meta">{data.sell_count} 筆</div>
        </div>
        <div className="stat-card">
          <div className="stat-label">高確信</div>
          <div className="stat-value">{data.high_conviction}</div>
          <div className="meta">≥25% 持股或新持倉</div>
        </div>
        <div className="stat-card">
          <div className="stat-label">集體買入</div>
          <div className="stat-value">{data.cluster_buying}</div>
          <div className="meta">2+ 內部人同股</div>
        </div>
      </div>

      <div className="tabs">
        {(['composite', 'conviction', 'amount', 'buy'] as const).map((s) => (
          <button key={s} className={`tab ${sort === s ? 'active' : ''}`} onClick={() => setSort(s)}>
            {s === 'composite' ? '綜合' : s === 'conviction' ? '確信' : s === 'amount' ? '金額' : '買入'}
          </button>
        ))}
      </div>

      {data.ranking.map((tx) => (
        <div className="card" key={`${tx.symbol}-${tx.name}-${tx.transaction_date}`}>
          <div style={{ display: 'flex', justifyContent: 'space-between' }}>
            <strong>{tx.symbol}</strong>
            <span style={{ color: tx.side === 'buy' ? 'var(--green)' : 'var(--red)' }}>
              {tx.side === 'buy' ? '買入' : '賣出'}
            </span>
          </div>
          <div className="meta">{tx.name} · {tx.title}</div>
          <div>${tx.value.toLocaleString()} · {tx.shares} 股 @ ${tx.price}</div>
          <div className="meta">排名分數 {tx.rank_score}</div>
        </div>
      ))}
    </div>
  )
}
