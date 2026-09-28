import json, random
from datetime import datetime, timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parent
STATE=ROOT/'data/state.json'
RISK={'max_risk_per_trade_pct':1.0,'max_daily_loss_pct':5.0,'max_open_positions':2,'max_consecutive_losses':3,'stop_loss_pct':8.0,'take_profit_pct':16.0,'max_hold_ticks':80}
def load(): return json.loads(STATE.read_text())
def save(s): STATE.write_text(json.dumps(s,ensure_ascii=False,indent=2))
def market(seed=42):
 r=random.Random(seed); names=['PEPE2','DOGEAI','PONSI','BLOB','MOONCAT','FROGGO','NEWT','WIFX']; out=[]
 for n in names:
  out.append({'symbol':n,'age_min':r.randint(2,60),'liquidity_usd':r.randint(12000,180000),'volume_24h_usd':r.randint(25000,900000),'buys':r.randint(80,900),'sells':r.randint(30,850),'holder_concentration':round(r.uniform(.12,.58),3),'anomaly':round(r.uniform(0,.30),3),'momentum':round(r.uniform(-.25,.55),3)})
 return out
def gate(c): return c['liquidity_usd']>=15000 and c['volume_24h_usd']>=25000 and c['holder_concentration']<=.45 and c['anomaly']<=.20 and c['buys']+c['sells']>=100
def score(c):
 br=c['buys']/max(1,c['buys']+c['sells']); liq=min(1,c['liquidity_usd']/100000); vol=min(1,c['volume_24h_usd']/500000); holder=1-c['holder_concentration']; an=1-c['anomaly']; mom=max(0,min(1,(c['momentum']+.25)/.8))
 return round(100*(.22*br+.18*liq+.18*vol+.18*holder+.14*an+.10*mom),1)
def run():
 s=load(); cs=[]
 for c in market():
  passed=gate(c); sc=score(c); x={**c,'security_gate':'PASS' if passed else 'BLOCK','score':sc,'action':'PAPER_BUY_CANDIDATE' if passed and sc>=68 else 'SKIP'}; cs.append(x)
 cs.sort(key=lambda x:x['score'],reverse=True); s['candidates']=cs[:6]; s['cooldown']=s['consecutive_losses']>=RISK['max_consecutive_losses']; s['updated_at']=datetime.now(timezone.utc).isoformat(); s['mode']='PAPER'; s['risk']=RISK
 if not s['cooldown'] and len(s['open_positions'])<2:
  p=next((x for x in cs if x['action']=='PAPER_BUY_CANDIDATE'),None)
  if p:
   notional=round(min(s['equity']*.01/.08,s['cash']*.25),2)
   if notional>=50:
    expected=max(-.08,min(.16,p['momentum']*.25+(p['buys']/(p['buys']+p['sells'])-.5)*.12)); pnl=round(notional*expected,2)
    s['trades'].append({'time':s['updated_at'],'symbol':p['symbol'],'action':'PAPER_BUY','notional':notional,'score':p['score'],'expected_return_pct':round(expected*100,2),'pnl':pnl,'result':'WIN' if pnl>0 else 'LOSS'}); s['cash']=round(s['cash']+pnl,2); s['equity']=s['cash']; s['pnl']=round(s['equity']-s['starting_balance'],2); s['pnl_pct']=round(100*s['pnl']/s['starting_balance'],2); s['consecutive_losses']=0 if pnl>0 else s['consecutive_losses']+1
 wins=sum(t['pnl']>0 for t in s['trades']); s['win_rate']=round(100*wins/len(s['trades']),1) if s['trades'] else 0; s['max_drawdown_pct']=round(max(0,100*(s['starting_balance']-s['equity'])/s['starting_balance']),2); s['open_positions']=[]; save(s)
if __name__=='__main__': run()
