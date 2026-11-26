import asyncio, json, os, sqlite3, time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
import yfinance as yf
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

BASE=Path(__file__).parent
DB=os.getenv('DATABASE_PATH','trade_ai.db')
SYMBOLS=[x.strip() for x in os.getenv('SCAN_SYMBOLS','SPY,QQQ,YM=F,EURUSD=X,GBPUSD=X').split(',') if x.strip()]
INTERVALS=[x.strip() for x in os.getenv('SCAN_INTERVALS','15m,1h,4h,1d').split(',') if x.strip()]
SCAN_SECONDS=max(30,int(os.getenv('SCAN_SECONDS','60')))
VAPID_PUBLIC=os.getenv('VAPID_PUBLIC_KEY','')
VAPID_PRIVATE=os.getenv('VAPID_PRIVATE_KEY','')
VAPID_EMAIL=os.getenv('VAPID_CLAIMS_EMAIL','mailto:admin@example.com')


def db():
    con=sqlite3.connect(DB); con.execute('CREATE TABLE IF NOT EXISTS signals (symbol TEXT, interval TEXT, side TEXT, candle_time INTEGER, close REAL, created_at INTEGER, PRIMARY KEY(symbol,interval,candle_time))'); con.execute('CREATE TABLE IF NOT EXISTS subscriptions (endpoint TEXT PRIMARY KEY, data TEXT NOT NULL)'); con.commit(); return con


def get_history(symbol:str, interval:str, period:Optional[str]=None):
    periods={'1m':'5d','2m':'5d','5m':'60d','15m':'60d','30m':'60d','60m':'730d','1h':'730d','90m':'60d','1d':'10y'}
    ticker=yf.Ticker(symbol); df=ticker.history(period=period or periods.get(interval,'60d'),interval='60m' if interval=='1h' else interval,auto_adjust=False)
    if df is None or df.empty: return pd.DataFrame()
    df=df.dropna(subset=['Open','High','Low','Close']).copy()
    # Yahoo can include the currently forming candle. Exclude it conservatively.
    now=pd.Timestamp.now(tz='UTC')
    idx=pd.to_datetime(df.index,utc=True)
    df.index=idx
    durations={'1m':60,'2m':120,'5m':300,'15m':900,'30m':1800,'60m':3600,'1h':3600,'90m':5400,'1d':86400}
    dur=durations.get(interval,3600)
    if interval!='1d': df=df[df.index + pd.to_timedelta(dur,unit='s') <= now]
    else: df=df[df.index.date < now.date()]
    return df


def utbot(df:pd.DataFrame,key=1.0,atr_period=10):
    if len(df)<atr_period+3: return [],[]
    high,low,close=df.High,df.Low,df.Close
    prev=close.shift(1)
    tr=pd.concat([(high-low),(high-prev).abs(),(low-prev).abs()],axis=1).max(axis=1)
    atr=tr.ewm(alpha=1/atr_period,adjust=False,min_periods=atr_period).mean()
    loss=key*atr; stop=[]; pos=0; last=0.0; signals=[]; stops=[]
    values=close.to_numpy(); losses=loss.to_numpy(); times=(df.index.view('int64')//10**9).to_numpy()
    for i,src in enumerate(values):
        nloss=losses[i]
        if not np.isfinite(nloss): stop.append(np.nan); continue
        prevsrc=values[i-1] if i else src
        if src>last and prevsrc>last: last=max(last,src-nloss)
        elif src<last and prevsrc<last: last=min(last,src+nloss)
        else: last=src-nloss if src>last else src+nloss
        oldpos=pos
        if i and values[i-1] < (stop[i-1] if i-1<len(stop) and np.isfinite(stop[i-1]) else 0) and src>last: pos=1
        elif i and values[i-1] > (stop[i-1] if i-1<len(stop) and np.isfinite(stop[i-1]) else 0) and src<last: pos=-1
        stop.append(last)
        if i and np.isfinite(stop[i-1]):
            buy=(src>last and values[i-1]<=stop[i-1])
            sell=(src<last and values[i-1]>=stop[i-1])
            if buy or sell:
                side='BUY' if buy else 'SELL'
                # Independent confirmation: 20 EMA slope/direction and RSI regime.
                ema=close.ewm(span=20,adjust=False).mean()
                rsi_series=_rsi(close,14)
                e=float(ema.iloc[i]); eprev=float(ema.iloc[i-1]); r=float(rsi_series.iloc[i])
                confirmed=(src>e and e>eprev and r>=50) if buy else (src<e and e<eprev and r<=50)
                if confirmed: signals.append({'side':side,'time':int(times[i]),'close':float(src),'confirmation':'EMA20 trend + RSI14'})
        stops.append({'time':int(times[i]),'value':float(last)})
    return signals,stops


def _rsi(close,period=14):
    delta=close.diff(); gain=delta.clip(lower=0).ewm(alpha=1/period,adjust=False,min_periods=period).mean(); loss=(-delta.clip(upper=0)).ewm(alpha=1/period,adjust=False,min_periods=period).mean(); rs=gain/loss.replace(0,np.nan); return 100-(100/(1+rs))


def store_signal(symbol,interval,sig):
    con=db(); cur=con.execute('INSERT OR IGNORE INTO signals VALUES (?,?,?,?,?,?)',(symbol,interval,sig['side'],sig['time'],sig['close'],int(time.time()))); con.commit(); added=cur.rowcount==1; con.close(); return added


def send_push(payload):
    if not (VAPID_PUBLIC and VAPID_PRIVATE): return
    try:
        from pywebpush import webpush, WebPushException
        con=db(); rows=con.execute('SELECT endpoint,data FROM subscriptions').fetchall(); con.close()
        for endpoint,data in rows:
            try: webpush(subscription_info=json.loads(data),data=json.dumps(payload),vapid_private_key=VAPID_PRIVATE,vapid_claims={'sub':VAPID_EMAIL})
            except Exception as exc:
                if '410' in str(exc) or '404' in str(exc):
                    con=db(); con.execute('DELETE FROM subscriptions WHERE endpoint=?',(endpoint,)); con.commit(); con.close()
    except Exception as exc: print('Push delivery error:',exc)


async def scan_loop():
    while True:
        for symbol in SYMBOLS:
            for interval in INTERVALS:
                try:
                    df=await asyncio.to_thread(get_history,symbol,interval)
                    signals,_=utbot(df)
                    if signals:
                        sig=signals[-1]
                        if store_signal(symbol,interval,sig):
                            send_push({'title':f"{sig['side']} · {symbol}",'body':f"{interval} candle closed at {sig['close']:.5f}. UT Bot + EMA/RSI confirmation.",'tag':f"{symbol}-{interval}-{sig['time']}",'url':f"/?symbol={symbol}&interval={interval}"})
                except Exception as exc: print(f'Scan failed {symbol} {interval}:',exc)
        await asyncio.sleep(SCAN_SECONDS)

@asynccontextmanager
async def lifespan(app:FastAPI):
    task=asyncio.create_task(scan_loop()); yield; task.cancel()

app=FastAPI(title='Trade AI',lifespan=lifespan)
app.mount('/static',StaticFiles(directory=BASE/'static'),name='static')

@app.get('/')
def home(): return FileResponse(BASE/'static'/'index.html')
@app.get('/sw.js')
def service_worker(): return FileResponse(BASE/'static'/'sw.js',media_type='application/javascript',headers={'Service-Worker-Allowed':'/'})
@app.get('/manifest.webmanifest')
def manifest(): return FileResponse(BASE/'static'/'manifest.webmanifest',media_type='application/manifest+json')
@app.get('/icon.svg')
def icon(): return FileResponse(BASE/'static'/'icon.svg',media_type='image/svg+xml')
@app.get('/api/health')
def health(): return {'ok':True,'symbols':SYMBOLS,'intervals':INTERVALS,'push_configured':bool(VAPID_PUBLIC and VAPID_PRIVATE)}
@app.get('/api/candles')
def candles(symbol:str='SPY',interval:str='15m'):
    try:
        df=get_history(symbol,interval)
        if df.empty: return {'candles':[],'stops':[],'error':'No completed candles returned by Yahoo Finance for this symbol/interval.'}
        _,stops=utbot(df)
        data=[{'time':int(i.timestamp()),'open':float(r.Open),'high':float(r.High),'low':float(r.Low),'close':float(r.Close)} for i,r in df.tail(500).iterrows()]
        return {'candles':data,'stops':[x for x in stops if x['time']>=data[0]['time']]}
    except Exception as exc: raise HTTPException(502,str(exc))
@app.get('/api/signals')
def signals(symbol:str='SPY',interval:str='15m'):
    con=db(); rows=con.execute('SELECT side,candle_time,close FROM signals WHERE symbol=? AND interval=? ORDER BY candle_time DESC LIMIT 30',(symbol,interval)).fetchall(); con.close()
    return {'signals':[{'side':r[0],'time':r[1],'close':r[2]} for r in rows]}
@app.get('/api/push/public-key')
def push_key(): return {'publicKey':VAPID_PUBLIC or None}
@app.post('/api/push/subscribe')
async def subscribe(request:Request):
    data=await request.json(); endpoint=data.get('endpoint')
    if not endpoint: raise HTTPException(400,'Invalid push subscription')
    con=db(); con.execute('INSERT OR REPLACE INTO subscriptions(endpoint,data) VALUES (?,?)',(endpoint,json.dumps(data))); con.commit(); con.close(); return {'ok':True}
