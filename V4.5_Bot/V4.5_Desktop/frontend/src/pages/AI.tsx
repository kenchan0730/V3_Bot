import { useEffect, useState } from 'react'
import { api, SignalItem } from '../api/client'

export function AIPage() {
  const [q, setQ] = useState('')
  const [answer, setAnswer] = useState('')
  const [signals, setSignals] = useState<SignalItem[]>([])
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    api.aiSignals().then((r) => setSignals(r.signals)).catch(console.error)
    const t = setInterval(() => api.aiSignals().then((r) => setSignals(r.signals)), 300000)
    return () => clearInterval(t)
  }, [])

  const ask = async () => {
    if (!q.trim()) return
    setLoading(true)
    try {
      const res = await api.aiChat(q)
      setAnswer(res.answer)
    } catch (e) {
      setAnswer(String(e))
    } finally {
      setLoading(false)
    }
  }

  return (
    <div>
      <div className="card">
        <h2 style={{ margin: 0 }}>V4.5 AI 助手</h2>
        <p className="meta">情報分析模式 · 不自動下單</p>
        <textarea
          className="input"
          rows={3}
          placeholder="提出問題，例如：NVDA 現在可以買嗎？"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          style={{ marginTop: 12, resize: 'vertical' }}
        />
        <button className="btn" onClick={ask} disabled={loading} style={{ marginTop: 8 }}>
          {loading ? '分析中…' : '提問'}
        </button>
        {answer && <pre style={{ whiteSpace: 'pre-wrap', marginTop: 16, fontSize: '0.9rem' }}>{answer}</pre>}
      </div>

      <div className="card">
        <h3 style={{ margin: '0 0 12px' }}>⚡ 購買訊號提醒</h3>
        {signals.length === 0 && <div className="meta">目前無強烈買入訊號</div>}
        {signals.map((s) => (
          <div className="signal-card" key={s.symbol}>
            <strong>{s.symbol}</strong> · {s.action || s.verdict}
            <div className="meta">${s.price ?? '—'} · {s.reason}</div>
          </div>
        ))}
      </div>
    </div>
  )
}
