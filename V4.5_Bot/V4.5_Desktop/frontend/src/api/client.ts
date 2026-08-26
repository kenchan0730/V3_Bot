const BASE = '/api'

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`)
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

async function post<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`, { method: 'POST' })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

async function del<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`, { method: 'DELETE' })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export const api = {
  bootstrap: () => get<BootstrapPayload>('/bootstrap'),
  intelligenceFeed: (limit = 50) => get<{ items: NewsItem[]; updated_at: string }>(`/intelligence/feed?limit=${limit}`),
  watchlist: () => get<{ symbols: string[]; items: QuoteRow[] }>('/intelligence/watchlist'),
  addWatchlist: (symbol: string) => post<{ symbols: string[] }>(`/intelligence/watchlist/${symbol}`),
  removeWatchlist: (symbol: string) => del<{ symbols: string[] }>(`/intelligence/watchlist/${symbol}`),
  symbolDetail: (symbol: string) => get<SymbolDetail>(`/intelligence/symbol/${symbol}?analyze=false`),
  technical: () => get<TechnicalOverview>('/technical/overview'),
  insider: (date?: string, sort = 'composite') =>
    get<InsiderSummary>(`/insider/summary?sort=${sort}${date ? `&date=${date}` : ''}`),
  earnings: (date?: string) =>
    get<{ items: EarningsItem[] }>(`/calendar/earnings${date ? `?date=${date}` : ''}`),
  earningsDetail: (symbol: string, date?: string) =>
    get<EarningsItem>(`/calendar/earnings/${symbol}${date ? `?date=${date}` : ''}`),
  aiChat: (q: string) => get<AiResponse>(`/ai/chat?q=${encodeURIComponent(q)}`),
  aiSignals: () => get<{ signals: SignalItem[] }>('/ai/signals'),
  search: (q: string) => get<{ results: SearchResult[] }>(`/search?q=${encodeURIComponent(q)}`),
  trends: () => get<{ trends: NewsItem[] }>('/search/trends'),
}

export interface QuoteRow {
  symbol: string
  price: number
  change_pct: number
  direction: string
  name?: string
}

export interface NewsItem {
  headline: string
  source: string
  url: string
  published: string | null
  symbols: string[]
  score: number
  score_label: string
  impact: number
  quotes?: QuoteRow[]
  rank?: number
  article_count?: number
}

export interface BootstrapPayload {
  feed: NewsItem[]
  watchlist: { symbols: string[]; items: QuoteRow[] }
  technical: TechnicalOverview
  earnings_today?: EarningsItem[]
  earnings_week?: EarningsItem[]
  trends: NewsItem[]
  updated_at: string
}

export interface SymbolDetail {
  symbol: string
  quote: QuoteRow
  ohlcv: OhlcvBar[]
  news: NewsItem[]
  fundamental: Record<string, unknown>
  analysis: Record<string, unknown>
  earnings: EarningsItem[]
}

export interface OhlcvBar {
  time: string
  open: number
  high: number
  low: number
  close: number
  volume: number
}

export interface TechnicalOverview {
  market_environment: {
    score: number
    label: string
    regime: Record<string, unknown>
    breadth: Record<string, unknown>
  }
  overall_market: Array<{
    symbol: string
    name: string
    price: number
    change_pct: number
    sparkline: number[]
  }>
  internals: {
    up_ratio: number
    down_ratio: number
    advancing: number
    declining: number
    unchanged: number
  }
  sectors: Array<{
    symbol: string
    name: string
    change_pct: number
    vs_spy: number
    lead_stock?: string
    lead_price?: number
    lead_change_pct?: number
  }>
  headlines: NewsItem[]
  fundamentals_hot: Array<QuoteRow & { tier: string; tier_label: string; metrics: Record<string, unknown> }>
  updated_at: string
}

export interface InsiderSummary {
  date: string
  buy_value: number
  sell_value: number
  buy_count: number
  sell_count: number
  buy_symbols: number
  sell_symbols: number
  high_conviction: number
  cluster_buying: number
  data_available?: boolean
  notice?: string
  ranking: InsiderTx[]
}

export interface InsiderTx {
  symbol: string
  name: string
  title: string
  side: string
  price: number
  shares: number
  value: number
  rank_score: number
  transaction_date: string
}

export interface EarningsItem {
  date: string
  symbol: string
  name: string
  hour_label?: string
  eps_estimate?: number
  revenue_estimate?: number
  score: number
  score_label: string
  analysis: string
  fundamental?: Record<string, unknown>
  news?: Array<{ headline: string; url: string }>
}

export interface SignalItem {
  symbol: string
  action: string
  verdict?: string
  price?: number
  reason?: string
}

export interface AiResponse {
  question: string
  answer: string
  signals: SignalItem[]
}

export interface SearchResult {
  symbol: string
  name: string
  type: string
}
