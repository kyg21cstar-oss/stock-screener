import streamlit as st
import pandas as pd
import FinanceDataReader as fdr
from datetime import datetime, timedelta
import requests
from bs4 import BeautifulSoup
import time
import plotly.graph_objects as go
from plotly.subplots import make_subplots

st.set_page_config(layout="wide", page_title="국내주식 세력 매집 포착 스크리너")

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
        table = soup.find('table', {'class': 'type2'})
        trs = table.find_all('tr')
        for tr in trs:
            tds = tr.find_all('td')
            if len(tds) >= 9:
                frgn_str = tds[6].text.strip().replace(',', '')
                inst_str = tds[7].text.strip().replace(',', '')
                frgn_val = int(frgn_str) if frgn_str.lstrip('-').isdigit() else 0
                inst_val = int(inst_str) if inst_str.lstrip('-').isdigit() else 0
                return frgn_val, inst_val
    except: pass
    return 0, 0

@st.cache_data(ttl=300)
def run_stock_accumulation_screener(universe_df):
    temp_results = []
    progress_text = "네이버 금융 연동: 차트 매집 및 수급 분석 중..."
    my_bar = st.progress(0, text=progress_text)
    
    start_date = (datetime.today() - timedelta(days=90)).strftime("%Y-%m-%d")
    tickers = universe_df['Code'].tolist()
    names = universe_df['Name'].tolist()
    
    for i, ticker in enumerate(tickers):
        try:
            df = fdr.DataReader(ticker, start_date)
            if len(df) < 30: continue
            
            # 지표 1: 볼린저 밴드
            df['SMA_20'] = df['Close'].rolling(window=20).mean()
            df['STD_20'] = df['Close'].rolling(window=20).std()
            df['BB_Upper'] = df['SMA_20'] + (df['STD_20'] * 2)
            df['BB_Lower'] = df['SMA_20'] - (df['STD_20'] * 2)
            df['Band_Width'] = (df['BB_Upper'] - df['BB_Lower']) / df['SMA_20']
            
            # 지표 2: OBV (누적 거래량)
            delta = df['Close'].diff()
            direction = delta.apply(lambda x: 1 if x > 0 else (-1 if x < 0 else 0))
            df['OBV'] = (df['Volume'] * direction).cumsum()
            
            latest = df.iloc[-1]
            recent_10 = df.tail(10)
            price_trend = (recent_10['Close'].iloc[-1] - recent_10['Close'].iloc[0]) / recent_10['Close'].iloc[0]
            obv_trend = recent_10['OBV'].iloc[-1] > recent_10['OBV'].iloc[0]
            
            # 조건 판단
            is_bb_squeeze = latest['Band_Width'] < 0.15 # 밴드폭 15% 이내 극도 응축
            is_obv_accum = price_trend <= 0.05 and obv_trend # 가격 횡보/하락 중 OBV 상승
            
            score = 0
            matched = []
            
            if is_bb_squeeze: 
                matched.append("밴드밀집(응축)")
                score += 30
            if is_obv_accum: 
                matched.append("OBV 매집")
                score += 30
            
            # 밴드폭이 좁고 기본 매집 조건이 하나라도 맞을 때만 수급(외인/기관) 추가 확인
            if score >= 30 and latest['Band_Width'] < 0.20:
                f_net, i_net = get_naver_supply(ticker)
                if f_net > 0: 
                    matched.append("외인(매수)")
                    score += 20
                if i_net > 0: 
                    matched.append("기관(매수)")
                    score += 20
                    
                temp_results.append({
                    "종목코드": ticker,
                    "종목명": names[i],
                    "만족조건": ", ".join(matched),
                    "현재가": int(latest['Close']),
                    "밴드폭": round(latest['Band_Width'] * 100, 2),
                    "종합점수": score
                })
        except: pass
        
        time.sleep(0.01)
        my_bar.progress((i + 1) / len(tickers), text=progress_text)
        
    my_bar.empty()
    if not temp_results: return pd.DataFrame()
    return pd.DataFrame(temp_results).sort_values(by=["종합점수", "밴드폭"], ascending=[False, True]).head(15).reset_index(drop=True)

def draw_stock_chart(ticker, ticker_name):
    start_date = (datetime.today() - timedelta(days=90)).strftime("%Y-%m-%d")
    df = fdr.DataReader(ticker, start_date)
    
    df['SMA_20'] = df['Close'].rolling(window=20).mean()
    df['STD_20'] = df['Close'].rolling(window=20).std()
    df['BB_Upper'] = df['SMA_20'] + (df['STD_20'] * 2)
    df['BB_Lower'] = df['SMA_20'] - (df['STD_20'] * 2)
    
    delta = df['Close'].diff()
    df['OBV'] = (df['Volume'] * delta.apply(lambda x: 1 if x > 0 else (-1 if x < 0 else 0))).cumsum()

    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.7, 0.3], vertical_spacing=0.05)
    
    fig.add_trace(go.Candlestick(x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'], name='주가', increasing_line_color='red', decreasing_line_color='blue'), row=1, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=df['BB_Upper'], line=dict(color='gray', width=1, dash='dot'), name='BB 상단'), row=1, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=df['BB_Lower'], line=dict(color='gray', width=1, dash='dot'), name='BB 하단', fill='tonexty', fillcolor='rgba(128,128,128,0.1)'), row=1, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=df['SMA_20'], line=dict(color='orange', width=2), name='20일선'), row=1, col=1)
    
    fig.add_trace(go.Scatter(x=df.index, y=df['OBV'], line=dict(color='purple', width=2), name='OBV (누적 거래량)'), row=2, col=1)
    
    fig.update_layout(title=f"📈 {ticker_name} ({ticker}) 매집 포착 정밀 차트", yaxis_title="가격 (원)", yaxis2_title="OBV", xaxis_rangeslider_visible=False, height=600, template="plotly_white", margin=dict(l=0, r=0, t=40, b=0))
    return fig

st.title("🕵️‍♂️ 국내주식 폭풍전야 매집 포착 스크리너")
st.markdown("차트가 조용히 횡보할 때(볼린저 밴드 밀집), **누군가 물량을 매집하며 외인/기관의 수급이 들어오는 종목**을 한발 앞서 찾아냅니다.")

if st.button("주식 매집 탐지 시작", type="primary"):
    st.session_state['run_screener'] = True

if st.session_state.get('run_screener', False):
    universe_df = get_market_universe()
    if not universe_df.empty:
        result_df = run_stock_accumulation_screener(universe_df)
        
        if not result_df.empty:
            st.dataframe(result_df.style.highlight_max(axis=0, subset=['종합점수'], color='#ff4b4b').format({"현재가": "{:,}", "밴드폭": "{:.1f}%"}), use_container_width=True)
            
            stock_options = [f"{row['종목명']} ({row['종목코드']})" for i, row in result_df.iterrows()]
            selected_stock = st.selectbox("정밀 차트 분석할 종목을 선택하세요:", stock_options)
            
            sel_name = selected_stock.split(" (")[0]
            sel_code = selected_stock.split(" (")[1].replace(")", "")
            
            current_price = result_df[result_df['종목코드'] == sel_code]['현재가'].values[0]
            bb_width = result_df[result_df['종목코드'] == sel_code]['밴드폭'].values[0]
            
            col1, col2 = st.columns([3, 1])
            with col1:
                st.plotly_chart(draw_stock_chart(sel_code, sel_name), use_container_width=True)
            with col2:
                st.info(f"**현재가:** {current_price:,}원")
                st.warning(f"**현재 밴드폭:** {bb_width}%")
                st.markdown(f"""
                **💡 영웅문S# 매집주 세팅 가이드**
                1. **자동매수:** {current_price:,}원 부근 (밴드 하단선 분할 진입)
                2. **자동매도 (익절):** 밴드 상단 강하게 돌파 시 (+5% 이상)
                3. **자동매도 (손절):** 20일선 이탈 후 회복 실패 시 (-3%)
                """)
        else:
            st.warning("현재 완벽한 매집 조건을 충족하는 주식이 없습니다.")
