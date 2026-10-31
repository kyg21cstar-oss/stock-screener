import streamlit as st
import pandas as pd
import FinanceDataReader as fdr
from datetime import datetime, timedelta
import requests
from bs4 import BeautifulSoup
import time
import plotly.graph_objects as go

st.set_page_config(layout="wide", page_title="실시간 단타/스윙 스크리너")

@st.cache_data(ttl=300)
def get_market_universe():
    try:
        df = fdr.StockListing('KOSDAQ')
        top_100 = df.sort_values(by="Amount", ascending=False).head(100)
        return top_100
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
    except:
        pass
    return 0, 0

def get_recent_news(ticker):
    url = f"https://finance.naver.com/item/news_news.naver?code={ticker}"
    headers = {'User-Agent': 'Mozilla/5.0'}
    try:
        res = requests.get(url, headers=headers, timeout=2)
        soup = BeautifulSoup(res.text, 'html.parser')
        links = soup.select('.title a')
        titles = [link.text.strip() for link in links[:3]]
        return " / ".join(titles) if titles else "최신 뉴스 없음"
    except:
        return "뉴스 로딩 실패"

@st.cache_data(ttl=300)
def run_screener(universe_df):
    temp_results = []
    progress_text = "네이버 금융 연동: 차트 및 수급 분석 중..."
    my_bar = st.progress(0, text=progress_text)
    
    today = datetime.today()
    start_date = (today - timedelta(days=40)).strftime("%Y-%m-%d")
    
    tickers = universe_df['Code'].tolist()
    names = universe_df['Name'].tolist()
    
    for i, ticker in enumerate(tickers):
        try:
            df = fdr.DataReader(ticker, start_date)
            if len(df) < 20: 
                my_bar.progress((i + 1) / len(tickers), text=progress_text)
                continue
                
            df['SMA_5'] = df['Close'].rolling(window=5).mean()
            df['SMA_20'] = df['Close'].rolling(window=20).mean()
            df['Volume_Ratio'] = df['Volume'] / df['Volume'].rolling(window=5).mean()
            
            expected_sma5 = df['Close'].tail(4).mean()
            
            latest = df.iloc[-1]
            ticker_name = names[i]
            
            is_trend = latest['SMA_5'] > latest['SMA_20']
            is_volume = latest['Volume_Ratio'] > 1.5
            
            if is_trend or is_volume:
                f_net, i_net = get_naver_supply(ticker)
                
                supply_score = 0
                supply_status = []
                if f_net > 0: supply_score += 15; supply_status.append("외인(매수)")
                if i_net > 0: supply_score += 15; supply_status.append("기관(매수)")
                    
                momentum_score = min(latest['Volume_Ratio'] * 10, 40)
                trend_score = 30 if is_trend else 0
                total_score = momentum_score + trend_score + supply_score
                
                matched_conditions = []
                if is_trend: matched_conditions.append("이평선 정배열")
                if is_volume: matched_conditions.append("거래량 급증")
                if supply_status: matched_conditions.append("수급 유입")
                
                temp_results.append({
                    "종목코드": ticker,
                    "종목명": ticker_name,
                    "만족조건": ", ".join(matched_conditions),
                    "현재가": int(latest['Close']),
                    "내일예상타점": int(expected_sma5),
                    "볼륨비율": round(latest['Volume_Ratio'], 2),
                    "수급상태": ", ".join(supply_status) if supply_status else "-",
                    "종합점수": round(total_score, 1)
                })
        except:
            pass 
            
        time.sleep(0.01)
        my_bar.progress((i + 1) / len(tickers), text=progress_text)
        
    if not temp_results:
        my_bar.empty()
        return pd.DataFrame()

    temp_df = pd.DataFrame(temp_results).sort_values(by="종합점수", ascending=False).head(20).reset_index(drop=True)
    for i, row in temp_df.iterrows():
        temp_df.at[i, '최신뉴스'] = get_recent_news(row['종목코드'])
        
    my_bar.empty()
    return temp_df

def draw_chart(ticker, ticker_name):
    start_date = (datetime.today() - timedelta(days=90)).strftime("%Y-%m-%d")
    df = fdr.DataReader(ticker, start_date)
    df['SMA_5'] = df['Close'].rolling(window=5).mean()
    df['SMA_20'] = df['Close'].rolling(window=20).mean()
    expected_sma5 = df['Close'].tail(4).mean()
    
    fig = go.Figure()
    fig.add_trace(go.Candlestick(x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'], name='주가', increasing_line_color='red', decreasing_line_color='blue'))
    fig.add_trace(go.Scatter(x=df.index, y=df['SMA_5'], line=dict(color='orange', width=2), name='5일선'))
    fig.add_trace(go.Scatter(x=df.index, y=df['SMA_20'], line=dict(color='green', width=2), name='20일선'))
    
    next_day = df.index[-1] + timedelta(days=1)
    if next_day.weekday() >= 5: next_day += timedelta(days=(7-next_day.weekday()))
    fig.add_trace(go.Scatter(x=[df.index[-1], next_day], y=[expected_sma5, expected_sma5], line=dict(color='purple', width=2, dash='dot'), name='내일 예상 5일선'))
    
    fig.update_layout(title=f"📈 {ticker_name} ({ticker}) 실시간 캔들 차트", yaxis_title="가격 (원)", xaxis_rangeslider_visible=False, height=400, template="plotly_white", margin=dict(l=0, r=0, t=40, b=0))
    return fig

st.title("🚀 실시간 단타/스윙 공략주 스크리너 (풀오토 시나리오)")
st.markdown("추천 종목 표 아래에서 원하는 종목을 선택하면, **영웅문S# 주식자동감시주문**에 바로 입력할 수 있는 기계적 매매 시나리오를 제시합니다.")

if st.button("현재 기준 스크리닝 실행", type="primary"):
    st.session_state['run_screener'] = True

if st.session_state.get('run_screener', False):
    universe_df = get_market_universe()
    if not universe_df.empty:
        result_df = run_screener(universe_df)
        
        if not result_df.empty:
            st.subheader("🎯 실시간 진입 추천 종목 Top 20")
            st.dataframe(result_df.style.highlight_max(axis=0, subset=['종합점수', '볼륨비율'], color='#ff4b4b').format({"현재가": "{:,}", "내일예상타점": "{:,}"}), use_container_width=True)
            
            st.divider()
            st.subheader("📊 차트 확인 및 영웅문S# 자동 매매 세팅 가이드")
            
            stock_options = [f"{row['종목명']} ({row['종목코드']})" for i, row in result_df.iterrows()]
            selected_stock = st.selectbox("공략할 종목을 선택하세요:", stock_options)
            
            sel_name = selected_stock.split(" (")[0]
            sel_code = selected_stock.split(" (")[1].replace(")", "")
            
            target_expected = int(result_df[result_df['종목코드'] == sel_code]['내일예상타점'].values[0])
            current_price = result_df[result_df['종목코드'] == sel_code]['현재가'].values[0]
            
            # 익절/손절가 계산
            take_profit = int(target_expected * 1.05)
            stop_loss = int(target_expected * 0.97)
            
            col1, col2 = st.columns([2, 1])
            with col1:
                st.plotly_chart(draw_chart(sel_code, sel_name), use_container_width=True)
            with col2:
                st.success(f"**진입 타점 (내일 5일선):** {target_expected:,}원")
                st.info(f"**목표 익절가 (+5%):** {take_profit:,}원")
                st.error(f"**기계적 손절가 (-3%):** {stop_loss:,}원")
            
            st.markdown(f"""
            ---
            ### 📱 영웅문S# 그대로 따라하기 (본업 충실형 세팅)
            앱 하단 **[주문]** ➡️ **[자동감시주문]** 메뉴 진입 후 아래 설정값을 입력하고 반드시 **'▶감시시작'**을 눌러두세요.

            **1️⃣ [신규종목] 자동매수 세팅 (아침 장 시작 전 걸어두기)**
            * **감시조건:** 주가가 **`{target_expected:,}원`** 이하일 때
            * **주문설정:** 매수 / **`시장가`** (체결 보장) / 원하는 수량
            * **효과:** 주가가 급등하지 않고 예상 5일선까지 예쁘게 눌려줄 때만 시스템이 낚아챕니다.

            **2️⃣ [잔고편입종목] 자동매도 세팅 (미리 켜두면 평생 유지)**
            * **감시조건:** 
              * 📈 이익실현: 매입단가 대비 **`+5%`** 도달 시
              * 📉 손실제한: 매입단가 대비 **`-3%`** 도달 시
            * **주문설정:** 매도 / **`시장가`** / 100% (또는 익절 50%)
            * **효과:** 1번 조건으로 매수 체결 즉시, 감정이 배제된 익절/손절 라인이 자동 가동됩니다.
            """)
        else:
            st.warning("조건을 만족하는 종목이 없습니다.")