import json
from datetime import datetime, timezone
from pathlib import Path
import requests

STATE_FILE = Path('data/state.json')
STARTING_BALANCE = 10000
SEARCH_URL = 'https://api.dexscreener.com/latest/dex/search'
SEARCH_WORDS = ['meme', 'pepe', 'doge', 'cat', 'pump']
MIN_LIQUIDITY_USD = 10000
MIN_VOLUME_USD = 5000
MAX_CANDIDATES = 10

def now_iso():
    return datetime.now(timezone.utc).isoformat()

def load_state():
    if not STATE_FILE.exists():
        return {'updated_at':'not_started','mode':'PAPER','starting_balance':STARTING_BALANCE,'cash':STARTING_BALANCE,'equity':STARTING_BALANCE,'pnl':0,'pnl_pct':0,'win_rate':0,'max_drawdown_pct':0,'consecutive_losses':0,'cooldown':False,'open_positions':[],'candidates':[],'trades':[],'risk':{'max_risk_per_trade_pct':1,'max_daily_loss_pct':5,'max_open_positions':2,'max_consecutive_losses':3,'stop_loss_pct':8,'take_profit_pct':16,'max_hold_ticks':80}}
    with open(STATE_FILE, encoding='utf-8') as f: return json.load(f)

def save_state(state):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(STATE_FILE, 'w', encoding='utf-8') as f: json.dump(state, f, ensure_ascii=False, indent=2)

def search_market(keyword):
    try:
        r = requests.get(SEARCH_URL, params={'q':keyword}, timeout=15, headers={'User-Agent':'meme-ai-trader-paper/1.0'})
        r.raise_for_status()
        return r.json().get('pairs', [])
    except Exception as e:
        print(f'API error [{keyword}]: {e}')
        return []

def collect_candidates():
    unique = {}
    for keyword in SEARCH_WORDS:
        print(f'Searching: {keyword}')
        for pair in search_market(keyword):
            liq = pair.get('liquidity') or {}; vol = pair.get('volume') or {}; pc = pair.get('priceChange') or {}
            try:
                liquidity_usd = float(liq.get('usd') or 0); volume_24h = float(vol.get('h24') or 0); price_usd = float(pair.get('priceUsd') or 0); change_24h = float(pc.get('h24') or 0)
            except (TypeError, ValueError): continue
            if liquidity_usd < MIN_LIQUIDITY_USD or volume_24h < MIN_VOLUME_USD or price_usd <= 0: continue
            base = pair.get('baseToken') or {}; addr = pair.get('pairAddress')
            if not addr: continue
            unique[addr] = {'chain':pair.get('chainId'),'dex':pair.get('dexId'),'pair_address':addr,'symbol':base.get('symbol','UNKNOWN'),'name':base.get('name','UNKNOWN'),'price':price_usd,'liquidity_usd':liquidity_usd,'volume_24h_usd':volume_24h,'price_change_24h_pct':change_24h,'url':pair.get('url')}
    candidates = list(unique.values())
    candidates.sort(key=lambda x:(x['volume_24h_usd'], x['liquidity_usd']), reverse=True)
    return candidates[:MAX_CANDIDATES]

def calculate_score(c):
    s=0; l=c['liquidity_usd']; v=c['volume_24h_usd']; ch=c['price_change_24h_pct']
    if l>=10000: s+=20
    if l>=50000: s+=10
    if v>=10000: s+=20
    if v>=50000: s+=10
    if 0<ch<=20: s+=20
    if ch>20: s+=5
    if ch<-20: s-=10
    return max(0,min(100,s))

def main():
    print('Meme AI Trader - PAPER MODE / Real market data / NO LIVE TRADING')
    state=load_state(); candidates=collect_candidates()
    for c in candidates: c['score']=calculate_score(c)
    state['updated_at']=now_iso(); state['mode']='PAPER'; state['candidates']=candidates
    state['cash']=STARTING_BALANCE; state['equity']=STARTING_BALANCE; state['pnl']=0; state['pnl_pct']=0
    save_state(state)
    print(f'Candidates found: {len(candidates)}')
    print('state.json updated.')

if __name__=='__main__': main()
