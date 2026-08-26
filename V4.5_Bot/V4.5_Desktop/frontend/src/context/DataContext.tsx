import { createContext, useContext, useEffect, useState, ReactNode } from 'react'
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

export function DataProvider({ children }: { children: ReactNode }) {
  const [feed, setFeed] = useState<NewsItem[]>([])
  const [watchlist, setWatchlist] = useState<{ symbols: string[]; items: QuoteRow[] }>({ symbols: [], items: [] })
  const [technical, setTechnical] = useState<TechnicalOverview | null>(null)
  const [earningsWeek, setEarningsWeek] = useState<EarningsItem[]>([])
  const [trends, setTrends] = useState<NewsItem[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const applyBootstrap = (data: Awaited<ReturnType<typeof api.bootstrap>>) => {
    setFeed(data.feed)
    setWatchlist(data.watchlist)
    setTechnical(data.technical)
    setEarningsWeek(data.earnings_week || data.earnings_today || [])
    setTrends(data.trends)
  }

  const load = async (silent = false) => {
    if (!silent) setError('')
    try {
      const data = await api.bootstrap()
      applyBootstrap(data)
    } catch (e) {
      if (!silent) setError(String(e))
    } finally {
      setLoading(false)
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
