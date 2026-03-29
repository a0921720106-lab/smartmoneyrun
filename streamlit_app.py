import streamlit as st
import pandas as pd
import requests
import io
import urllib3
import yfinance as yf
from datetime import datetime, timedelta

# 1. 初始化設定與繞過驗證
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

st.set_page_config(page_title="台股籌碼終極雷達", layout="wide")
st.title("🏹 全市場：籌碼大增 + 股價震幅雙重篩選器")

# --- 功能函數區 ---

@st.cache_data(ttl=3600)
def fetch_tdcc_api():
    """自動抓取最新集保週報"""
    url = "https://opendata.tdcc.com.tw/getOD.ashx?id=1-5"
    try:
        res = requests.get(url, timeout=30, verify=False, allow_redirects=True)
        if res.status_code == 200:
            df = pd.read_csv(io.StringIO(res.text))
            df.columns = ['date', 'stock_id', 'level', 'count', 'shares', 'percent']
            df['stock_id'] = df['stock_id'].astype(str).str.strip()
            # 僅保留 4 碼個股
            df = df[df['stock_id'].str.fullmatch(r'\d{4}')]
            return df
    except:
        return pd.DataFrame()

def get_weekly_amplitude(stock_id):
    """計算過去 5 個交易日的週震幅"""
    try:
        # 嘗試上市代碼
        ticker = f"{stock_id}.TW"
        data = yf.download(ticker, period="5d", interval="1d", progress=False)
        # 若無資料則嘗試上櫃代碼
        if data.empty:
            ticker = f"{stock_id}.TWO"
            data = yf.download(ticker, period="5d", interval="1d", progress=False)
        
        if not data.empty:
            high = data['High'].max()
            low = data['Low'].min()
            # 震幅公式：(最高 - 最低) / 最低
            amp = ((high - low) / low) * 100
            return round(float(amp), 2)
    except:
        return None
    return None

# --- 側邊欄控制 ---
st.sidebar.header("🎛️ 策略參數控制")
uploaded_files = st.sidebar.file_uploader("上傳歷史 CSV (若線上抓取週數不足時)", accept_multiple_files=True)

st.sidebar.divider()
# 籌碼門檻
threshold = st.sidebar.slider("大戶增持比例門檻 (%)", 1, 10, 3, step=1)
# 震幅限制
vol_limit = st.sidebar.slider("週震幅上限限制 (%)", 5, 30, 15, step=1)
st.sidebar.caption(f"💡 僅顯示大戶增持 >{threshold}% 且震幅 <{vol_limit}% 的標的")

# 散戶定義
retail_map = {"50張以下": 8, "100張以下": 9, "200張以下":