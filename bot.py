#!/usr/bin/env python3
"""Meme AI Trader PAPER backend v2.
Uses public DEX Screener data for discovery only. PAPER ONLY: no wallet/private key/execution.
"""
import json, urllib.request, urllib.parse, random
from datetime import datetime, timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]; STATE=ROOT/'data/state.json'
RISK={"max_risk_per_trade_pct":1.0,"max_daily_loss_pct":5.0,"max_open_positions":2,"max_consecutive_losses":3,"stop_loss_pct":8.0,"take_profit_pct":16.0,"max_hold_ticks":80}

def get_json(url):
    req=urllib.request.Request(url,headers={"User-Agent":"MemeAITraderPaper/2.0"})
    with urllib.request.urlopen(req,timeout=15) as r: return json.loads(r.read().decode())

def latest_profiles():
    return get_json('https://api.dexscreener.com/token-profiles/latest/v1')

def pairs(address):
    return get_json('https://api.dexscreener.com/token-pairs/v1/solana/'+urllib.parse.quote(address,safe=''))

def safe_num(x,default=0.0):
    try:return float(x or default)
    except:return default

def candidate(profile):
    addr=profile.get('tokenAddress') or profile.get('address');
    if not addr:return None
    try: ps=pairs(addr)
    except Exception:return None
    if not ps:return None
    p=max([x for x in ps if x.get('chainId')=='solana'],key=lambda x:safe_num((x.get('liquidity') or {}).get('usd')),default=None)
    if not p:return None
    liq=safe_num((p.get('liquidity') or {}).get('usd')); vol=safe_num((p.get('volume') or {}).get('h24')); tx=(p.get('txns') or {}).get('h24') or {}; buys=safe_num(tx.get('buys')); sells=safe_num(tx.get('sells')); price=safe_num(p.get('priceUsd')); ch=safe_num((p.get('priceChange') or {}).get('h1')); fdv=safe_num(p.get('fdv')); mc=safe_num(p.get('marketCap')) or fdv
    buy_ratio=buys/max(1,buys+sells); liq_score=min(1,liq/100000); vol_score=min(1,vol/500000); mom=max(0,min(1,(ch+20)/40)); activity=min(1,(buys+sells)/1000)
    # Conservative gate: liquidity/volume/activity plus no extreme 1h move.
    gate=(liq>=15000 and vol>=25000 and buys+sells>=50 and abs(ch)<=80)
    score=round(100*(.30*liq_score+.25*vol_score+.20*buy_ratio+.15*activity+.10*mom),1)
    return {"symbol":p.get('baseToken',{}).get('symbol','?'),"address":addr,"pair":p.get('pairAddress'),"dex":p.get('dexId'),"liquidity_usd":round(liq,2),"volume_24h_usd":round(vol,2),"buys":int(buys),"sells":int(sells),"price_usd":price,"price_change_1h_pct":ch,"market_cap_usd":mc,"security_gate":"PASS" if gate else "BLOCK","score":score,"action":"PAPER_CANDIDATE" if gate and score>=60 else "SKIP","url":p.get('url')}

def main():
    s=json.loads(STATE.read_text(encoding='utf-8'))
    try: profiles=latest_profiles()
    except Exception as e:
        s['updated_at']=datetime.now(timezone.utc).isoformat(); s['data_status']='market_data_error'; s['error']=str(e); STATE.write_text(json.dumps(s,ensure_ascii=False,indent=2),encoding='utf-8'); return
    cs=[]
    for prof in profiles[:30]:
        c=candidate(prof)
        if c: cs.append(c)
    cs.sort(key=lambda x:x['score'],reverse=True)
    s['mode']='PAPER'; s['data_source']='DEX Screener public API'; s['data_status']='live_market_data'; s['updated_at']=datetime.now(timezone.utc).isoformat(); s['candidates']=cs[:12]; s['risk']=RISK
    # No automatic simulated fills from real data yet: discovery first, execution validation second.
    s['execution_note']='Real market discovery only; no paper fills from live prices in this v2.'
    STATE.write_text(json.dumps(s,ensure_ascii=False,indent=2),encoding='utf-8')
if __name__=='__main__': main()
