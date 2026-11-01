import streamlit as st
import pandas as pd
import FinanceDataReader as fdr
from datetime import datetime, timedelta
import requests
from bs4 import BeautifulSoup
import time
import plotly.graph_objects as go
from plotly.subplots import make_subplots

st.set_page_config(layout="wide", page_title="국내주식 세력 매집 & 지표 통합 스크리너")

@st.cache_data(ttl=300)
def get_market_universe():
    try:
        df = fdr.StockListing('KOSDAQ')
        return df.sort_values(by="Amount", ascending=False).head(100)
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
def run_advanced_screener(universe_df):
    temp_results = []
    progress_text = "지표 종합 분석 중 (BB, OBV, MACD, RSI, 수급)..."
    my_bar = st.progress(0, text=progress_text)
    
    start_date = (datetime.today() - timedelta(days=90)).strftime("%Y-%m-%d")
    tickers, names = universe_df['Code'].tolist(), universe_df['Name'].tolist()
    
    for i, ticker in enumerate(tickers):
        try:
            df = fdr.DataReader(ticker, start_date)
            if len(df) < 30: continue
            
            # 1. 볼린저 밴드
            df['SMA_20'] = df['Close'].rolling(window=20).mean()
            df['STD_20'] = df['Close'].rolling(window=20).std()
            df['BB_Upper'] = df['SMA_20'] + (df['STD_20'] * 2)
            df['BB_Lower'] = df['SMA_20'] - (df['STD_20'] * 2)
            df['Band_Width'] = (df['BB_Upper'] - df['BB_Lower']) / df['SMA_20']
            
            # 2. OBV
            delta = df['Close'].diff()
            df['OBV'] = (df['Volume'] * delta.apply(lambda x: 1 if x > 0 else (-1 if x < 0 else 0))).cumsum()
            
            # 3. MACD
            exp1 = df['Close'].ewm(span=12, adjust=False).mean()
            exp2 = df['Close'].ewm(span=26, adjust=False).mean()
            df['MACD'] = exp1 - exp2
            df['Signal'] = df['MACD'].ewm(span=9, adjust=False).mean()
            
            # 4. RSI (14일)
            up, down = delta.clip(lower=0), -1 * delta.clip(upper=0)
            rs = up.ewm(com=13, adjust=False).mean() / down.ewm(com=13, adjust=False).mean()
            df['RSI'] = 100 - (100 / (1 + rs))
            
            latest = df.iloc[-1]
            recent_10 = df.tail(10)
            
            # 코어 조건 판단
            is_bb_squeeze = latest['Band_Width'] < 0.15
            is_obv_accum = ((recent_10['Close'].iloc[-1] - recent_10['Close'].iloc[0]) / recent_10['Close'].iloc[0] <= 0.05) and (recent_10['OBV'].iloc[-1] > recent_10['OBV'].iloc[0])
            
            score = 0
            matched = []
            
            # [기본 점수] 밴드 응축 및 OBV 매집
            if is_bb_squeeze: matched.append("BB밀집"); score += 30
            if is_obv_accum: matched.append("OBV매집"); score += 30
            
            if score >= 30 and latest['Band_Width'] < 0.20:
                # [가점 1] MACD 및 RSI 지표
                if latest['MACD'] > latest['Signal']: matched.append("MACD(Up)"); score += 10
                if 30 < latest['RSI'] < 55: matched.append("RSI(턴어라운드)"); score += 10
                
                # [가점 2] 실시간 수급
                f_net, i_net = get_naver_supply(ticker)
                if f_net > 0: matched.append("외인순매수"); score += 10
                if i_net > 0: matched.append("기관순매수"); score += 10
                    
                temp_results.append({
                    "종목코드": ticker,
                    "종목명": names[i],
                    "만족조건": ", ".join(matched),
                    "현재가": int(latest['Close']),
                    "밴드폭": round(latest['Band_Width'] * 100, 2),
                    "RSI": round(latest['RSI'], 1),
                    "종합점수": score
                })
        except: pass
        time.sleep(0.01)
        my_bar.progress((i + 1) / len(tickers), text=progress_text)
        
    my_bar.empty()
    if not temp_results: return pd.DataFrame()
    return pd.DataFrame(temp_results).sort_values(by=["종합점수", "밴드폭"], ascending=[False, True]).head(15).reset_index(drop=True)

st.title("🏆 멀티 지표 스코어링 주식 스크리너")
st.markdown("핵심 매집 신호(BB, OBV)에 **MACD, RSI, 외인/기관 수급**을 가점제로 결합하여 겹치는 지표가 많은 1순위 종목을 추출합니다.")

if st.button("종합 지표 스크리닝 실행", type="primary"):
    st.session_state['run_screener'] = True

if st.session_state.get('run_screener', False):
    universe_df = get_market_universe()
    if not universe_df.empty:
        result_df = run_advanced_screener(universe_df)
        if not result_df.empty:
            st.dataframe(result_df.style.highlight_max(axis=0, subset=['종합점수'], color='#ff4b4b').format({"현재가": "{:,}", "밴드폭": "{:.1f}%"}), use_container_width=True)
        else:
            st.warning("현재 종합 조건을 충족하는 종목이 없습니다.")
