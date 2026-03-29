import streamlit as st
import pandas as pd
import requests
import io
import urllib3
import yfinance as yf
from datetime import datetime

# 1. 環境設定與避坑
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

st.set_page_config(page_title="台股籌碼終極雷達", layout="wide")
st.title("🏹 全市場：大戶增持 + 震幅過濾 + 借券回補掃描器")

# --- 核心數據抓取函數 ---

@st.cache_data(ttl=3600)
def fetch_tdcc_api():
    """自動抓取集保數據"""
    url = "https://opendata.tdcc.com.tw/getOD.ashx?id=1-5"
    try:
        res = requests.get(url, timeout=30, verify=False)
        if res.status_code == 200:
            df = pd.read_csv(io.StringIO(res.text))
            df.columns = ['date', 'stock_id', 'level', 'count', 'shares', 'percent']
            df['stock_id'] = df['stock_id'].astype(str).str.strip()
            return df[df['stock_id'].str.fullmatch(r'\d{4}')]
    except:
        return pd.DataFrame()

def get_real_short_data(stock_id):
    """從證交所 API 抓取真實借券賣出餘額"""
    try:
        # 使用本日日期向證交所請求
        date_str = datetime.now().strftime("%Y%m%d")
        url = f"https://www.twse.com.tw/exchangeReport/TWTASU?response=json&date={date_str}&stockNo={stock_id}"
        res = requests.get(url, timeout=10, verify=False)
        data = res.json()
        
        if data.get('data') and len(data['data']) >= 2:
            # 取得最新兩日的「借券賣出餘額」(索引 11)
            # 格式通常為 '1,234'，需去逗號轉整數
            curr_bal = int(data['data'][-1][11].replace(',', ''))
            prev_bal = int(data['data'][-2][11].replace(',', ''))
            # 餘額減少 = 有回補跡象
            return curr_bal < prev_bal
    except:
        return False
    return False

def get_amplitude(stock_id):
    """計算週震幅"""
    try:
        ticker = f"{stock_id}.TW"
        data = yf.download(ticker, period="10d", progress=False)
        if data.empty:
            ticker = f"{stock_id}.TWO"
            data = yf.download(ticker, period="10d", progress=False)
        
        if not data.empty:
            recent = data.tail(5)
            high = recent['High'].max()
            low = recent['Low'].min()
            amp = ((high - low) / low) * 100
            return round(float(amp), 2)
    except:
        return None
    return None

# --- 側邊欄控制與變數初始化 ---

st.sidebar.header("🎛️ 策略參數控制")
use_short_cover = st.sidebar.toggle("開啟真實借券回補篩選", value=False)
uploaded_files = st.sidebar.file_uploader("上傳歷史集保 CSV", accept_multiple_files=True)

st.sidebar.divider()
threshold = st.sidebar.slider("大戶增持門檻 (%)", 1, 10, 3)
vol_limit = st.sidebar.slider("週震幅上限 (%)", 5, 30, 15)

retail_map = {"50張以下": 8, "100張以下": 9, "200張以下": 10, "400張以下": 11}
retail_choice = st.sidebar.selectbox("散戶定義", list(retail_map.keys()))
retail_lv = retail_map[retail_choice]

# --- 執行邏輯 ---

if st.button("🚀 啟動全市場深度分析"):
    all_dfs = []
    
    # 1. 取得資料
    df_online = fetch_tdcc_api()
    if not df_online.empty: all_dfs.append(df_online)
    if uploaded_files:
        for f in uploaded_files:
            tdf = pd.read_csv(f)
            tdf.columns = ['date', 'stock_id', 'level', 'count', 'shares', 'percent']
            tdf['stock_id'] = tdf['stock_id'].astype(str).str.strip()
            all_dfs.append(tdf)

    if len(all_dfs) < 2:
        st.error("❌ 資料不足。自動抓取失敗且未上傳 CSV。")
    else:
        # 2. 籌碼運算
        full_df = pd.concat(all_dfs).drop_duplicates(subset=['date', 'stock_id', 'level'])
        all_dates = sorted(full_df['date'].unique(), reverse=True)
        
        def get_pivot(lv_cond):
            temp = full_df[lv_cond].groupby(['stock_id', 'date'])['percent'].sum().reset_index()
            pivot = temp.pivot(index='stock_id', columns='date', values='percent')
            if (pivot > 100).any().any(): pivot = pivot / 100
            return pivot

        big_pivot = get_pivot(full_df['level'] >= 11)
        small_pivot = get_pivot(full_df['level'] <= retail_lv)
        t = all_dates[:2]

        # 3. 籌碼初步過濾
        mask = (big_pivot[t[0]] > big_pivot[t[1]]) & (small_pivot[t[0]] < small_pivot[t[1]])
        diff = big_pivot[t[0]] - big_pivot[t[1]]
        candidates = big_pivot[mask & (diff >= threshold)].dropna().index.tolist()

        if candidates:
            st.write(f"🔍 籌碼符合 {len(candidates)} 檔，正在核對震幅與借券數據...")
            results = []
            prog = st.progress(0)
            
            for i, sid in enumerate(candidates):
                amp = get_amplitude(sid)
                
                # 震幅過濾
                if amp is not None and amp <= vol_limit:
                    is_covering = get_real_short_data(sid)
                    
                    # 借券開關邏輯
                    if not use_short_cover or (use_short_cover and is_covering):
                        results.append({
                            "代號": sid,
                            "大戶趨勢": f"{big_pivot.loc[sid, t[1]]:.1f}% -> {big_pivot.loc[sid, t[0]]:.1f}%",
                            "增幅": f"{diff.loc[sid]:+.2f}%",
                            "週震幅": f"{amp}%",
                            "真實回補跡象": "✅" if is_covering else "--"
                        })
                prog.progress((i + 1) / len(candidates))

            if results:
                st.success(f"🎯 篩選完成！共發現 {len(results)} 檔優質標的")
                st.table(pd.DataFrame(results).sort_values(by="增幅", ascending=False))
            else:
                st.warning("符合籌碼面，但被震幅或借券回補條件排除。")
        else:
            st.info("無符合籌碼增持門檻標的。")