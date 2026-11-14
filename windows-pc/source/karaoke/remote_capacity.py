"""Conservative capacity estimate, not an AP benchmark or guaranteed limit."""
def recommended_clients(wifi, audio=False, latency_ms=0):
    rates=[value for value in (wifi.rx_mbps,wifi.tx_mbps) if value>0]
    if not rates: return 5 if audio else 10
    budget=min(rates)*.15
    count=int(budget/(1.5 if audio else .3))
    if wifi.signal and wifi.signal<40:count//=2
    if latency_ms>500:count//=2
    return max(2,min(10 if audio else 40,count))
