import streamlit as st
import pandas as pd
import FinanceDataReader as fdr
from datetime import datetime, timedelta
import requests
from bs4 import BeautifulSoup
import time
import plotly.graph_objects as go
from plotly.subplots import make_subplots

st.set_page_config(layout="wide", page_title="국내주식 스윙 타점 & 매집 통합 스크리너")

@st.cache_data(ttl=300)
def get_market_universe():
    try:
        # KRX(코스피+코스닥) 전체 시장에서 거래대금 상위 250종목 추출
        df = fdr.StockListing('KRX')
        return df.sort_values(by="Amount", ascending=False).head(250)
    except:
        return pd.DataFrame()

def get_naver_supply(ticker):
    url = f"https://finance.naver.com/item/frgn.naver?code={ticker}"
    headers = {'User-Agent': 'Mozilla/5.0'}
    try:
        res = requests.get(url, headers=headers, timeout=2)
        soup = BeautifulSoup(res.text, 'html.parser')
        trs = soup.find('table', {'class': 'type2'}).find_all('tr')
        for tr in trs:
            tds = tr.find_all('td')
            if len(tds) >= 9:
                f_val = int(tds[6].text.strip().replace(',', '')) if tds[6].text.strip().replace(',', '').lstrip('-').isdigit() else 0
                i_val = int(tds[7].text.strip().replace(',', '')) if tds[7].text.strip().replace(',', '').lstrip('-').isdigit() else 0
                return f_val, i_val
    except: pass
    return 0, 0

@st.cache_data(ttl=300)
def run_stock_swing_screener(universe_df):
    temp_results = []
    progress_text = "코스피/코스닥 스윙 눌림목 및 수급 스캔 중..."
    my_bar = st.progress(0, text=progress_text)
    
    start_date = (datetime.today() - timedelta(days=90)).strftime("%Y-%m-%d")
    tickers, names, markets = universe_df['Code'].tolist(), universe_df['Name'].tolist(), universe_df['Market'].tolist()
    
    for i, ticker in enumerate(tickers):
        try:
            df = fdr.DataReader(ticker, start_date)
            if len(df) < 30: continue
            
            recent_30 = df.tail(30)
            latest = df.iloc[-1]
            
            df['SMA_20'] = df['Close'].rolling(window=20).mean()
            df['STD_20'] = df['Close'].rolling(window=20).std()
            df['BB_Upper'] = df['SMA_20'] + (df['STD_20'] * 2)
            df['BB_Lower'] = df['SMA_20'] - (df['STD_20'] * 2)
            df['Band_Width'] = (df['BB_Upper'] - df['BB_Lower']) / df['SMA_20']
            
            delta = df['Close'].diff()
            df['OBV'] = (df['Volume'] * delta.apply(lambda x: 1 if x > 0 else (-1 if x < 0 else 0))).cumsum()
            
            recent_10 = df.tail(10)
            price_trend = (recent_10['Close'].iloc[-1] - recent_10['Close'].iloc[0]) / recent_10['Close'].iloc[0]
            obv_trend = recent_10['OBV'].iloc[-1] > recent_10['OBV'].iloc[0]
            
            is_bb_squeeze = latest['Band_Width'] < 0.15
            is_obv_accum = price_trend <= 0.05 and obv_trend
            
            peak_high = recent_30['High'].max()
            peak_vol = recent_30['Volume'].max()
            
            drop_rate = (latest['Close'] - peak_high) / peak_high if peak_high > 0 else 0
            vol_dry_rate = latest['Volume'] / peak_vol if peak_vol > 0 else 1
            
            is_swing_dip = (-0.40 <= drop_rate <= -0.10) and (vol_dry_rate < 0.25) and (latest['Close'] > latest['SMA_20'] * 0.85)
            
            score = 0
            matched = []
            
            if is_swing_dip: matched.append("⭐거래량급감(스윙)"); score += 30
            if is_bb_squeeze: matched.append("BB밀집"); score += 20
            if is_obv_accum: matched.append("OBV매집"); score += 20
            
            if score >= 20:
                f_net, i_net = get_naver_supply(ticker)
                if f_net > 0: matched.append("외인(매수)"); score += 15
                if i_net > 0: matched.append("기관(매수)"); score += 15
            
            if score >= 30:
                temp_results.append({
                    "종목코드": ticker,
                    "종목명": names[i],
                    "시장": markets[i],
                    "만족조건": ", ".join(matched),
                    "현재가": int(latest['Close']),
                    "고점대비하락": f"{round(drop_rate*100, 1)}%",
                    "종합점수": score
                })
        except: pass
        time.sleep(0.01)
        my_bar.progress((i + 1) / len(tickers), text=progress_text)
        
    my_bar.empty()
    if not temp_results: return pd.DataFrame()
    return pd.DataFrame(temp_results).sort_values(by=["종합점수", "고점대비하락"], ascending=[False, True]).head(15).reset_index(drop=True)

def draw_chart(ticker, ticker_name):
    start_date = (datetime.today() - timedelta(days=90)).strftime("%Y-%m-%d")
    df = fdr.DataReader(ticker, start_date)
    
    df['SMA_20'] = df['Close'].rolling(window=20).mean()
    df['STD_20'] = df['Close'].rolling(window=20).std()
