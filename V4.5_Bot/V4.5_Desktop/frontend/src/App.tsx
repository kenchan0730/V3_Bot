import { useState } from 'react'
import { api } from './api/client'
import { IntelligencePage, SymbolDetailModal } from './pages/Intelligence'
import { TechnicalPage } from './pages/Technical'
import { InsiderPage } from './pages/Insider'
import { CalendarPage } from './pages/Calendar'
import { AIPage } from './pages/AI'
import { SearchPage } from './pages/Search'

type Tab = 'intel' | 'technical' | 'insider' | 'calendar' | 'ai' | 'search'

const NAV: { id: Tab; label: string; icon: string }[] = [
  { id: 'intel', label: '情報', icon: '◆' },
  { id: 'technical', label: '技術', icon: '⌁' },
  { id: 'insider', label: '內部', icon: '▦' },
  { id: 'calendar', label: '日曆', icon: '▣' },
  { id: 'ai', label: 'AI', icon: '⚡' },
  { id: 'search', label: '搜尋', icon: '⌕' },
]

export default function App() {
  const [tab, setTab] = useState<Tab>('intel')
  const [symbol, setSymbol] = useState<string | null>(null)

  const addWatchlist = async (s: string) => {
    await api.addWatchlist(s)
    alert(`${s} 已加入自選`)
  }

  return (
    <div className="app-shell">
      <header className="app-header">
        <h1>V4.5 Intelligence</h1>
        <span className="badge">分析模式 · 無自動交易</span>
      </header>

      <main className="app-main">
        {tab === 'intel' && <IntelligencePage onSelectSymbol={setSymbol} />}
        {tab === 'technical' && <TechnicalPage />}
        {tab === 'insider' && <InsiderPage />}
        {tab === 'calendar' && <CalendarPage />}
        {tab === 'ai' && <AIPage />}
        {tab === 'search' && (
          <SearchPage onSelectSymbol={setSymbol} onAddWatchlist={addWatchlist} />
        )}
      </main>

      <nav className="nav-bar">
        {NAV.map((n) => (
          <button
            key={n.id}
            className={`nav-btn ${tab === n.id ? 'active' : ''}`}
            onClick={() => setTab(n.id)}
          >
            <span className="icon">{n.icon}</span>
            {n.label}
          </button>
        ))}
      </nav>

      <SymbolDetailModal symbol={symbol} onClose={() => setSymbol(null)} />
    </div>
  )
}
