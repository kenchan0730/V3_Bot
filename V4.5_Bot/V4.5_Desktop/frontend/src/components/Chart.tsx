import { useEffect, useRef } from 'react'
import { createChart, ColorType, IChartApi, ISeriesApi } from 'lightweight-charts'
import type { OhlcvBar } from '../api/client'

export function CandleChart({ data }: { data: OhlcvBar[] }) {
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!ref.current || !data.length) return
    const chart: IChartApi = createChart(ref.current, {
      layout: {
        background: { type: ColorType.Solid, color: '#141418' },
        textColor: '#8b8b96',
      },
      grid: {
        vertLines: { color: '#2a2a32' },
        horzLines: { color: '#2a2a32' },
      },
      width: ref.current.clientWidth,
      height: 380,
      timeScale: { borderColor: '#2a2a32' },
      rightPriceScale: { borderColor: '#2a2a32' },
    })

    const series: ISeriesApi<'Candlestick'> = chart.addCandlestickSeries({
      upColor: '#22c55e',
      downColor: '#ef4444',
      borderVisible: false,
      wickUpColor: '#22c55e',
      wickDownColor: '#ef4444',
    })

    const bars = data
      .map((b) => ({
        time: b.time.slice(0, 10),
        open: b.open,
        high: b.high,
        low: b.low,
        close: b.close,
      }))
      .sort((a, b) => a.time.localeCompare(b.time))
    series.setData(bars as any)
    chart.timeScale().fitContent()

    const onResize = () => {
      if (ref.current) chart.applyOptions({ width: ref.current.clientWidth })
    }
    window.addEventListener('resize', onResize)
    return () => {
      window.removeEventListener('resize', onResize)
      chart.remove()
    }
  }, [data])

  return <div className="chart-box" ref={ref} />
}

export function scoreClass(score: number): string {
  if (score >= 7) return 'score-pill score-bull'
  if (score <= 3) return 'score-pill score-bear'
  return 'score-pill score-neutral'
}

export function Sparkline({ values }: { values: number[] }) {
  if (!values.length) return null
  const min = Math.min(...values)
  const max = Math.max(...values)
  const span = max - min || 1
  return (
    <div className="spark">
      {values.map((v, i) => (
        <div
          key={i}
          className="spark-bar"
          style={{ height: `${((v - min) / span) * 100}%` }}
        />
      ))}
    </div>
  )
}
