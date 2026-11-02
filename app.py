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
        # 코스피/코스닥 전 종목 제한 없이 호출
        df = fdr.StockListing('KRX')
        return df
    except:
        return pd.DataFrame()

def check_fundamentals(ticker):
    """
    네이버 금융 재무제표를 실시간 크롤링하여 다음을 검증합니다.
    1. 3년 연속 당기순이익 적자 필터링
    2. 최근 유보율 > 부채비율 필터링
    """
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
        
        # MultiIndex 컬럼 평탄화
        df_fin.columns = ['_'.join(str(c) for c in col).strip() for col in df_fin.columns]
        first_col = df_fin.columns[0]
        df_fin.set_index(first_col, inplace=True)
        
        # 1. 3년 연속 적자 확인 ('최근 연간 실적' 기준 앞의 3개 연도 데이터 확인)
        net_income_row = df_fin[df_fin.index.str.contains('당기순이익', na=False)].iloc[0]
        net_incomes = pd.to_numeric(net_income_row, errors='coerce').dropna().values
        
        if len(net_incomes) >= 3:
            # 과거 3년 데이터가 모두 0 미만(적자)이면 탈락
            if all(x < 0 for x in net_incomes[:3]): 
                return False
                
        # 2. 유보율 > 부채비율 확인
        debt_row = df_fin[df_fin.index.str.contains('부채비율', na=False)].iloc[0]
        reserve_row = df_fin[df_fin.index.str.contains('유보율', na=False)].iloc[0]
        
        debts = pd.to_numeric(debt_row, errors='coerce').dropna().values
        reserves = pd.to_numeric(reserve_row, errors='coerce').dropna().values
        
        if len(debts) > 0 and len(reserves) > 0:
            latest_debt = debts[-1]
            latest_reserve = reserves[-1]
            # 부채가 유보율(비상금)보다 많거나 같으면 탈락
            if latest_reserve <= latest_debt:
                return False
                
        return True
    except:
        # 재무 데이터를 불러올 수 없는 우선주/스팩주 등은 안전을 위해 탈락
        return False

@st.cache_data(ttl=600)
def run_analyst_screener(universe_df):
    temp_results = []
    progress_text = "전 종목 1차 차트 스캔 및 2차 재무 건전성 분석 중... (약 2~3분 소요)"
    my_bar = st.progress(0, text=progress_text)
    
    start_date = (datetime.today() - timedelta(days=60)).strftime("%Y-%m-%d")
    tickers, names, markets = universe_df['Code'].tolist(), universe_df['Name'].tolist(), universe_df['Market'].tolist()
    
    for i, ticker in enumerate(tickers):
        try:
            df = fdr.DataReader(ticker, start_date)
            if len(df) < 15: continue
            
            # 14일 이내 데이터
            recent_14 = df.tail(14)
            latest = df.iloc[-1]
            
            # 거래대금(Amount) = 종가 * 거래량 추산
            recent_14 = recent_14.copy()
            recent_14['Amount'] = recent_14['Close'] * recent_14['Volume']
            
            # 1. 14일 내 최대 거래대금 발생일(기준봉) 찾기
            peak_idx = recent_14['Amount'].idxmax()
            peak_candle = df.loc[peak_idx]
            
            # 당일 터진 기준봉은 눌림목이 아니므로 제외 (최소 1일 이상 경과 필요)
            if peak_idx == df.index[-1]: continue
            
            # 2. 거래대금 500억 이상 & 시가 대비 10% 이상 상승한 장대양봉 확인
            is_huge_volume = peak_candle['Amount'] >= 50000000000
            is_long_body = peak_candle['Close'] >= (peak_candle['Open'] * 1.10)
            
            if not (is_huge_volume and is_long_body):
                continue # 기준봉 자격 미달 시 즉시 패스 (속도 최적화)
                
            # 3. 기준봉 1/2 중심선 가격 계산
            peak_open = peak_candle['Open']
            peak_close = peak_candle['Close']
            mid_price = (peak_open + peak_close) / 2
            
            # 4. 현재가가 중심선(1/2) 부근에서 지지 중인지 확인 (-5% ~ +5% 오차 허용)
            is_at_midline = (mid_price * 0.95 <= latest['Close'] <= mid_price * 1.05)
            
            if is_at_midline:
                # 5. 차트 조건을 완벽히 통과한 종목에 한해 2차 재무제표(적자/유보율) 실시간 검증
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
        
        # UI 업데이트 주기
        if i % 10 == 0:
            my_bar.progress((i + 1) / len(tickers), text=progress_text)
            
    my_bar.empty()
    if not temp_results: return pd.DataFrame()
    return pd.DataFrame(temp_results)

def draw_chart(ticker, ticker_name):
    start_date = (datetime.today() - timedelta(days=90)).strftime("%Y-%m-%d")
    df = fdr.DataReader(ticker, start_date)

    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.7, 0.3], vertical_spacing=0.05)
    fig.add_trace(go.Candlestick(x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'], name='주가', increasing_line_color='red', decreasing_line_color='blue'), row=1, col=1)
    
    # 기준봉 탐색 후 중심선 긋기
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
st.markdown("**[차트 1차]** 전 종목 대상 14일 내 500억 & 10% 이상 터진 장대양봉의 1/2 중심선 지지 포착<br>**[재무 2차]** 3년 연속 적자 기업 원천 차단 및 유보율이 부채비율보다 높은 우량 기업만 최종 선별", unsafe_allow_html=True)

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
                * 재무 건전성(유보율>부채)이 확보되었으므로, **초록색 중심선**에서 분할 매수 시 상폐 걱정 없이 편안하게 수익을 낼 수 있습니다.
                """)
        else:
            st.warning("현재 까다로운 500억 중심선 차트 조건과 재무 건전성을 동시에 만족하는 종목이 없습니다.")
