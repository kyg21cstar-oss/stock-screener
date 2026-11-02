import streamlit as st
import pandas as pd
import FinanceDataReader as fdr
from datetime import datetime, timedelta
import requests
from bs4 import BeautifulSoup
import io
import time
import plotly.graph_objects as go
from plotly.subplots import make_subplots

st.set_page_config(layout="wide", page_title="20년차 애널리스트: 정통 기준봉 중심선 스크리너")

@st.cache_data(ttl=3600)
def get_market_universe():
    try:
        df = fdr.StockListing('KRX')
        # [핵심 속도 최적화] 우선주(코드가 0으로 안 끝남), 스팩주, 리츠 등 쓰레기 종목 사전 제거
        df = df[df['Code'].str.endswith('0')]
        df = df[~df['Name'].str.contains('스팩|리츠')]
        
        # 전체 2500개 중 의미 있는 500억 자금이 들어올 수 있는 시가총액 상위 800개로 압축 (약 1~2분 컷)
        return df.sort_values(by="Marcap", ascending=False).head(800)
    except:
        return pd.DataFrame()

def check_fundamentals(ticker):
    url = f"https://finance.naver.com/item/main.naver?code={ticker}"
    headers = {'User-Agent': 'Mozilla/5.0'}
    try:
        res = requests.get(url, headers=headers, timeout=3)
        tables = pd.read_html(io.StringIO(res.text), encoding='euc-kr')
        
        df_fin = None
        for t in tables:
            if '당기순이익' in t.to_string():
                df_fin = t
                break
                
        if df_fin is None: return False
        
        df_fin.columns = ['_'.join(str(c) for c in col).strip() for col in df_fin.columns]
        first_col = df_fin.columns[0]
        df_fin.set_index(first_col, inplace=True)
        
        net_income_row = df_fin[df_fin.index.str.contains('당기순이익', na=False)].iloc[0]
        net_incomes = pd.to_numeric(net_income_row, errors='coerce').dropna().values
        
        if len(net_incomes) >= 3:
            if all(x < 0 for x in net_incomes[:3]): 
                return False
                
        debt_row = df_fin[df_fin.index.str.contains('부채비율', na=False)].iloc[0]
        reserve_row = df_fin[df_fin.index.str.contains('유보율', na=False)].iloc[0]
        
        debts = pd.to_numeric(debt_row, errors='coerce').dropna().values
        reserves = pd.to_numeric(reserve_row, errors='coerce').dropna().values
        
        if len(debts) > 0 and len(reserves) > 0:
            latest_debt = debts[-1]
            latest_reserve = reserves[-1]
            if latest_reserve <= latest_debt:
                return False
                
        return True
    except:
        return False

@st.cache_data(ttl=600)
def run_analyst_screener(universe_df):
    temp_results = []
    progress_text = "상위 800개 핵심 종목 차트 및 재무 건전성 분석 중... (약 1~2분 소요)"
    my_bar = st.progress(0, text=progress_text)
    
    start_date = (datetime.today() - timedelta(days=60)).strftime("%Y-%m-%d")
    tickers, names, markets = universe_df['Code'].tolist(), universe_df['Name'].tolist(), universe_df['Market'].tolist()
    
    for i, ticker in enumerate(tickers):
        try:
            df = fdr.DataReader(ticker, start_date)
            if len(df) < 15: continue
            
            recent_14 = df.tail(14).copy()
            latest = df.iloc[-1]
            
            recent_14['Amount'] = recent_14['Close'] * recent_14['Volume']
            
            peak_idx = recent_14['Amount'].idxmax()
            peak_candle = df.loc[peak_idx]
            
            if peak_idx == df.index[-1]: continue
            
            is_huge_volume = peak_candle['Amount'] >= 50000000000
            is_long_body = peak_candle['Close'] >= (peak_candle['Open'] * 1.10)
            
            if not (is_huge_volume and is_long_body):
                continue
                
            peak_open = peak_candle['Open']
            peak_close = peak_candle['Close']
            mid_price = (peak_open + peak_close) / 2
            
            is_at_midline = (mid_price * 0.95 <= latest['Close'] <= mid_price * 1.05)
            
            if is_at_midline:
                if check_fundamentals(ticker):
                    temp_results.append({
                        "종목코드": ticker,
                        "종목명": names[i],
                        "시장": markets[i],
                        "현재가": int(latest['Close']),
                        "중심선(1/2)": int(mid_price),
                        "기준봉대금": f"{int(peak_candle['Amount'] / 100000000)}억",
                        "달성조건": "⭐500억 중심선 & 재무통과"
                    })
        except: pass
        
        # 딜레이를 최소화하여 분석 속도 극대화
        time.sleep(0.01)
        if i % 5 == 0:
            my_bar.progress((i + 1) / len(tickers), text=progress_text)
            
    my_bar.empty()
    if not temp_results: return pd.DataFrame()
    return pd.DataFrame(temp_results)

def draw_chart(ticker, ticker_name):
    start_date = (datetime.today() - timedelta(days=90)).strftime("%Y-%m-%d")
    df = fdr.DataReader(ticker, start_date)

    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.7, 0.3], vertical_spacing=0.05)
    fig.add_trace(go.Candlestick(x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'], name='주가', increasing_line_color='red', decreasing_line_color='blue'), row=1, col=1)
    
    recent_14 = df.tail(14).copy()
    recent_14['Amount'] = recent_14['Close'] * recent_14['Volume']
    peak_idx = recent_14['Amount'].idxmax()
    peak_open = df.loc[peak_idx, 'Open']
    peak_close = df.loc[peak_idx, 'Close']
    mid_price = (peak_open + peak_close) / 2
    
    fig.add_hline(y=mid_price, line_dash="dot", line_color="green", annotation_text="⭐ 기준봉 1/2 중심선", annotation_position="bottom right")
    fig.add_hline(y=peak_open, line_dash="dot", line_color="black", annotation_text="시초가", annotation_position="bottom right")
    
    colors = ['red' if df['Close'].iloc[i] > df['Open'].iloc[i] else 'blue' for i in range(len(df))]
    fig.add_trace(go.Bar(x=df.index, y=df['Volume'], marker_color=colors, name='거래량'), row=2, col=1)
    
    fig.update_layout(title=f"📈 {ticker_name} ({ticker}) 정통 중심선 타점 차트", yaxis_title="가격 (원)", yaxis2_title="거래량", xaxis_rangeslider_visible=False, height=550, template="plotly_white", margin=dict(l=0, r=0, t=40, b=0), showlegend=False)
    return fig

st.title("💼 20년차 애널리스트: 정통 기준봉 중심선 스크리너")
st.markdown("**[차트 1차]** 우량주 800개 대상 14일 내 500억 & 10% 이상 터진 장대양봉의 1/2 중심선 지지 포착<br>**[재무 2차]** 3년 연속 적자 기업 원천 차단 및 유보율이 부채비율보다 높은 기업 선별", unsafe_allow_html=True)

if st.button("우량주 중심선 스윙 탐지 시작", type="primary"):
    st.session_state['run_screener'] = True

if st.session_state.get('run_screener', False):
    universe_df = get_market_universe()
    if not universe_df.empty:
        result_df = run_analyst_screener(universe_df)
        if not result_df.empty:
            st.dataframe(result_df.style.format({"현재가": "{:,}", "중심선(1/2)": "{:,}"}), use_container_width=True)
            
            stock_options = [f"{row['종목명']} ({row['종목코드']})" for i, row in result_df.iterrows()]
            selected_stock = st.selectbox("정밀 차트 분석 (초록색 1/2 방어선 확인):", stock_options)
            
            sel_name = selected_stock.split(" (")[0]
            sel_code = selected_stock.split(" (")[1].replace(")", "")
            
            current_price = result_df[result_df['종목코드'] == sel_code]['현재가'].values[0]
            mid_price = result_df[result_df['종목코드'] == sel_code]['중심선(1/2)'].values[0]
            peak_amt = result_df[result_df['종목코드'] == sel_code]['기준봉대금'].values[0]
            
            col1, col2 = st.columns([3, 1])
            with col1: st.plotly_chart(draw_chart(sel_code, sel_name), use_container_width=True)
            with col2: 
                st.info(f"**현재가:** {current_price:,} 원")
                st.warning(f"**중심선 가격:** {mid_price:,} 원")
                st.error(f"**기준봉 대금:** {peak_amt}")
                st.success("**재무 상태:** 건전 (적자 X, 비상금 > 빚)")
                st.markdown("""
                **💡 애널리스트 실전 가이드**
                * 500억 이상의 자금은 개인이 절대 만들 수 없는 '기관/외인'의 발자국입니다.
                * 재무 건전성(유보율>부채)이 확보되었으므로, **초록색 중심선**에서 분할 매수 시 편안하게 수익을 낼 수 있습니다.
                """)
        else:
            st.warning("현재 까다로운 500억 중심선 차트 조건과 재무 건전성을 동시에 만족하는 종목이 없습니다.")
