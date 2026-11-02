import streamlit as st
import pandas as pd
import FinanceDataReader as fdr
from datetime import datetime, timedelta
import requests
from bs4 import BeautifulSoup
import io
import time
import concurrent.futures
import plotly.graph_objects as go
from plotly.subplots import make_subplots

st.set_page_config(layout="wide", page_title="20년차 애널리스트: 정통 기준봉 중심선 스크리너")

@st.cache_data(ttl=3600)
def get_market_universe():
    try:
        df = fdr.StockListing('KRX')
        df = df[df['Code'].str.endswith('0')]
        df = df[~df['Name'].str.contains('스팩|리츠')]
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

def process_ticker(args):
    ticker, name, market, start_date = args
    try:
        df = fdr.DataReader(ticker, start_date)
        if len(df) < 25: return None
        
        recent_20 = df.tail(20).copy()
        latest = df.iloc[-1]
        
        recent_20['Amount'] = recent_20['Close'] * recent_20['Volume']
        peak_idx = recent_20['Amount'].idxmax()
        peak_candle = df.loc[peak_idx]
        
        # 당일 터진 건 눌림목이 아님
        if peak_idx == df.index[-1]: return None
        
        # 1. 자금력: 300억 이상
        is_huge_volume = peak_candle['Amount'] >= 30000000000
        
        # 2. 장대양봉: 전일 대비 9% 이상 상승(Change) & 양봉(종가>시가)
        is_long_body = (peak_candle['Change'] >= 0.09) and (peak_candle['Close'] > peak_candle['Open'])
        
        if not (is_huge_volume and is_long_body): return None
            
        peak_open = peak_candle['Open']
        peak_close = peak_candle['Close']
        mid_price = (peak_open + peak_close) / 2
        
        # 3. 방어선 확장: 중심선(1/2)부터 시초가 아래(-5%)까지 넉넉하게 지지 확인
        is_supported = (peak_open * 0.95 <= latest['Close'] <= mid_price * 1.05)
        
        # 4. 거래량 감소: 기준봉 터진 날 대비 거래량이 반토막(50%) 이하로 말랐는지
        is_vol_dried = latest['Volume'] <= (peak_candle['Volume'] * 0.50)
        
        if is_supported and is_vol_dried:
            if check_fundamentals(ticker):
                return {
                    "종목코드": ticker,
                    "종목명": name,
                    "시장": market,
                    "현재가": int(latest['Close']),
                    "중심선(1/2)": int(mid_price),
                    "시초가": int(peak_open),
                    "기준봉대금": f"{int(peak_candle['Amount'] / 100000000)}억",
                    "달성조건": "⭐중심선~시초가 지지"
                }
    except:
        pass
    return None

@st.cache_data(ttl=600)
def run_analyst_screener_fast(universe_df):
    temp_results = []
    progress_text = "⚡ 초고속 멀티스레딩 스캔 중 (상위 800개)..."
    my_bar = st.progress(0, text=progress_text)
    
    start_date = (datetime.today() - timedelta(days=60)).strftime("%Y-%m-%d")
    tasks = [(row['Code'], row['Name'], row['Market'], start_date) for _, row in universe_df.iterrows()]
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(process_ticker, task) for task in tasks]
        for i, future in enumerate(concurrent.futures.as_completed(futures)):
            result = future.result()
            if result:
                temp_results.append(result)
            if i % 10 == 0 or i == len(tasks) - 1:
                my_bar.progress((i + 1) / len(tasks), text=progress_text)
                
    my_bar.empty()
    if not temp_results: return pd.DataFrame()
    return pd.DataFrame(temp_results).sort_values(by="기준봉대금", ascending=False)

def draw_chart(ticker, ticker_name):
    start_date = (datetime.today() - timedelta(days=90)).strftime("%Y-%m-%d")
    df = fdr.DataReader(ticker, start_date)

    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.7, 0.3], vertical_spacing=0.05)
    fig.add_trace(go.Candlestick(x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'], name='주가', increasing_line_color='red', decreasing_line_color='blue'), row=1, col=1)
    
    recent_20 = df.tail(20).copy()
    recent_20['Amount'] = recent_20['Close'] * recent_20['Volume']
    peak_idx = recent_20['Amount'].idxmax()
    peak_open = df.loc[peak_idx, 'Open']
    peak_close = df.loc[peak_idx, 'Close']
    mid_price = (peak_open + peak_close) / 2
    
    # 2개의 방어선 (중심선, 시초가) 표시
    fig.add_hline(y=mid_price, line_dash="dot", line_color="green", annotation_text="⭐ 기준봉 1/2 중심선", annotation_position="bottom right")
    fig.add_hline(y=peak_open, line_dash="dot", line_color="black", annotation_text="시초가 최후 방어선", annotation_position="bottom right")
    
    colors = ['red' if df['Close'].iloc[i] > df['Open'].iloc[i] else 'blue' for i in range(len(df))]
    fig.add_trace(go.Bar(x=df.index, y=df['Volume'], marker_color=colors, name='거래량'), row=2, col=1)
    
    fig.update_layout(title=f"📈 {ticker_name} ({ticker}) 스윙 타점 차트", yaxis_title="가격 (원)", yaxis2_title="거래량", xaxis_rangeslider_visible=False, height=550, template="plotly_white", margin=dict(l=0, r=0, t=40, b=0), showlegend=False)
    return fig

st.title("💼 20년차 애널리스트: 정통 기준봉 중심선 스크리너")
st.markdown("**[차트 1차]** 우량주 800개 대상 20일 내 **300억** & 전일비 9% 이상 급등한 장대양봉 탐색, 이후 **중심선(1/2)부터 시초가 사이**로 거래량 급감하며 눌린 종목 포착<br>**[재무 2차]** 3년 연속 적자 기업 원천 차단 및 유보율 > 부채비율 검증<br>⚡ **멀티스레딩(병렬 처리) 가속 엔진 탑재 완료**", unsafe_allow_html=True)

if st.button("우량주 중심선 스윙 탐지 시작", type="primary"):
    st.session_state['run_screener'] = True

if st.session_state.get('run_screener', False):
    universe_df = get_market_universe()
    if not universe_df.empty:
        result_df = run_analyst_screener_fast(universe_df)
        if not result_df.empty:
            st.dataframe(result_df.style.format({"현재가": "{:,}", "중심선(1/2)": "{:,}", "시초가": "{:,}"}), use_container_width=True)
            
            stock_options = [f"{row['종목명']} ({row['종목코드']})" for i, row in result_df.iterrows()]
            selected_stock = st.selectbox("정밀 차트 분석 (매수 타점 방어선 확인):", stock_options)
            
            sel_name = selected_stock.split(" (")[0]
            sel_code = selected_stock.split(" (")[1].replace(")", "")
            
            current_price = result_df[result_df['종목코드'] == sel_code]['현재가'].values[0]
            mid_price = result_df[result_df['종목코드'] == sel_code]['중심선(1/2)'].values[0]
            peak_open = result_df[result_df['종목코드'] == sel_code]['시초가'].values[0]
            peak_amt = result_df[result_df['종목코드'] == sel_code]['기준봉대금'].values[0]
            
            col1, col2 = st.columns([3, 1])
            with col1: st.plotly_chart(draw_chart(sel_code, sel_name), use_container_width=True)
            with col2: 
                st.info(f"**현재가:** {current_price:,} 원")
                st.warning(f"**중심선 가격:** {mid_price:,} 원")
                st.warning(f"**시초가 가격:** {peak_open:,} 원")
                st.error(f"**기준봉 대금:** {peak_amt}")
                st.success("**재무 상태:** 건전 (적자 X, 비상금 > 빚)")
                st.markdown("""
                **💡 애널리스트 실전 가이드**
                * 현재 주가가 **초록색 중심선**과 **검은색 시초가** 사이에 있다면 완벽한 세력의 매집(눌림목) 구간입니다.
                * 하단의 거래량이 터졌던 날 대비 절반 이하로 뚝 떨어져 있어야 안전합니다.
                """)
        else:
            st.warning("현재 완화된 300억 중심선 차트 조건과 재무 건전성을 동시에 만족하는 종목이 없습니다.")
