import { createContext, useContext, useEffect, useRef, useState, ReactNode } from 'react'
import { api, TechnicalOverview, NewsItem, QuoteRow, EarningsItem } from '../api/client'

interface BootstrapData {
  feed: NewsItem[]
  watchlist: { symbols: string[]; items: QuoteRow[] }
  technical: TechnicalOverview | null
  earningsWeek: EarningsItem[]
  trends: NewsItem[]
  loading: boolean
  error: string
  refresh: () => void
}

const DataContext = createContext<BootstrapData | null>(null)

const MAX_RETRIES = 12
const RETRY_MS = 2500

function friendlyError(err: unknown): string {
  const raw = String(err)
  if (raw.includes('Failed to fetch') || raw.includes('NetworkError')) {
    return '無法連接 API：請確認「V4.5 API」命令視窗已開啟，然後重新整理頁面。'
  }
  if (raw.includes('404') || raw.includes('Not Found')) {
    return 'API 路徑錯誤：請用 open.bat 啟動，不要直接開啟 dist/index.html。'
  }
  return raw.length > 200 ? `${raw.slice(0, 200)}…` : raw
}

export function DataProvider({ children }: { children: ReactNode }) {
  const [feed, setFeed] = useState<NewsItem[]>([])
  const [watchlist, setWatchlist] = useState<{ symbols: string[]; items: QuoteRow[] }>({ symbols: [], items: [] })
  const [technical, setTechnical] = useState<TechnicalOverview | null>(null)
  const [earningsWeek, setEarningsWeek] = useState<EarningsItem[]>([])
  const [trends, setTrends] = useState<NewsItem[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const retryRef = useRef(0)

  const applyBootstrap = (data: Awaited<ReturnType<typeof api.bootstrap>>) => {
    setFeed(data.feed)
    setWatchlist(data.watchlist)
    setTechnical(data.technical)
    setEarningsWeek(data.earnings_week || data.earnings_today || [])
    setTrends(data.trends)
  }

  const load = async (silent = false) => {
    if (!silent) {
      setError('')
      setLoading(true)
    }
    try {
      const data = await api.bootstrap()
      applyBootstrap(data)
      retryRef.current = 0
      setError('')
    } catch (e) {
      if (retryRef.current < MAX_RETRIES) {
        retryRef.current += 1
        window.setTimeout(() => load(true), RETRY_MS)
        return
      }
      if (!silent) setError(friendlyError(e))
    } finally {
      if (retryRef.current === 0 || retryRef.current >= MAX_RETRIES) {
        setLoading(false)
      }
    }
  }

  useEffect(() => {
    load()
    const t = setInterval(() => load(true), 120000)
    return () => clearInterval(t)
  }, [])

  return (
    <DataContext.Provider value={{ feed, watchlist, technical, earningsWeek, trends, loading, error, refresh: () => load() }}>
      {children}
    </DataContext.Provider>
  )
}

export function useData() {
  const ctx = useContext(DataContext)
  if (!ctx) throw new Error('useData outside provider')
  return ctx
}
