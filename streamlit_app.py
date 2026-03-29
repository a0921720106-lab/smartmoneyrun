import streamlit as st
import pandas as pd
import requests
import io
import urllib3
import yfinance as yf

# 1. 解決 SSL 認證失敗問題
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

st.set_page_config(page_title="台股籌碼終極雷達", layout="wide")
st.title("🏹 全市場：籌碼大增 + 股價震幅雙重篩選器")

@st.cache_data(ttl=3600)
def fetch_tdcc_api():
    """自動從政府平台抓取最新週資料"""
    # 更新後的 API 網址
    url = "https://opendata.tdcc.com.tw/getOD.ashx?id=1-5"
    try:
        # 使用 verify=False 繞過 SSL 錯誤
        res = requests.get(url, timeout=30, verify=False)
        if res.status_code == 200:
            df = pd.read_csv(io.StringIO(res.text))
            df.columns = ['date', 'stock_id', 'level', 'count', 'shares', 'percent']
            df['stock_id'] = df['stock_id'].astype(str).str.strip()
            # 僅保留 4 位數股票代號
            df = df[df['stock_id'].str.fullmatch(r'\d{4}')]
            return df
    except Exception as e:
        st.sidebar.warning(f"自動抓取失敗（SSL或網路問題），請手動上傳 CSV。")
        return pd.DataFrame()

def get_market_data(stock_id):
    """計算週震幅與回補跡象"""
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
            # 簡單判定回補：收盤價站上前一日高點
            is_covering = data['Close'].iloc[-1] > data['High'].iloc[-2]
            return round(float(amp), 2), is_covering
    except:
        return None, None
    return None, None

# --- 側邊欄設計 ---
st.sidebar.header("🎛️ 策略參數控制")
# 確保變數在一開始就初始化
use_short_cover = st.sidebar.toggle("開啟借券回補篩選", value=False)
uploaded_files = st.sidebar.file_uploader("上傳歷史 CSV (TDCC_OD_1-5)", accept_multiple_files=True)

threshold = st.sidebar.slider("大戶增持門檻 (%)", 1, 10, 3)
vol_limit = st.sidebar.slider("週震幅上限 (%)", 5, 30, 15)

retail_map = {"50張以下": 8, "100張以下": 9, "200張以下": 10, "400張以下": 11}
retail_choice = st.sidebar.selectbox("散戶定義", list(retail_map.keys()))
retail_lv = retail_map[retail_choice]

if st.button("🚀 啟動全市場深度分析"):
    all_dfs = []
    
    # A. 嘗試自動抓取
    df_online = fetch_tdcc_api()
    if not df_online.empty:
        all_dfs.append(df_online)
        st.success(f"✅ 已成功抓取網路最新資料日期：{df_online['date'].iloc[0]}")
    
    # B. 讀取上傳檔案
    if uploaded_files:
        for f in uploaded_files:
            tdf = pd.read_csv(f)
            tdf.columns = ['date', 'stock_id', 'level', 'count', 'shares', 'percent']
            tdf['stock_id'] = tdf['stock_id'].astype(str).str.strip()
            all_dfs.append(tdf)

    # C. 檢查是否有任何資料
    if not all_dfs:
        st.error("❌ 目前沒有任何資料。請上傳從集保下載的 CSV 檔案。")
    elif len(all_dfs) < 2:
        st.warning("⚠️ 目前僅有 1 週資料，無法判定『趨勢』。請至少上傳一週歷史資料。")
    else:
        # 合併並去重
        full_df = pd.concat(all_dfs).drop_duplicates(subset=['date', 'stock_id', 'level'])
        all_dates = sorted(full_df['date'].unique(), reverse=True)
        
        # 籌碼計算邏輯
        def get_pivot(lv_cond):
            temp = full_df[lv_cond].groupby(['stock_id', 'date'])['percent'].sum().reset_index()
            pivot = temp.pivot(index='stock_id', columns='date', values='percent')
            if (pivot > 100).any().any(): pivot = pivot / 100
            return pivot

        big_pivot = get_pivot(full_df['level'] >= 11)
        small_pivot = get_pivot(full_df['level'] <= retail_lv)
        t = all_dates[:2] # 取最近兩週

        # 篩選條件
        mask = (big_pivot[t[0]] > big_pivot[t[1]]) & (small_pivot[t[0]] < small_pivot[t[1]])
        diff = big_pivot[t[0]] - big_pivot[t[1]]
        candidates = big_pivot[mask & (diff >= threshold)].dropna().index.tolist()

        if candidates:
            st.write(f"🔍 找到 {len(candidates)} 檔初步標的，進行市場過濾...")
            final_list = []
            for sid in candidates:
                amp, covering = get_market_data(sid)
                if amp is not None and amp <= vol_limit:
                    if not use_short_cover or (use_short_cover and covering):
                        final_list.append({
                            "代號": sid,
                            "大戶趨勢": f"{big_pivot.loc[sid, t[1]]:.1f}% -> {big_pivot.loc[sid, t[0]]:.1f}%",
                            "增幅": f"{diff.loc[sid]:+.2f}%",
                            "週震幅": f"{amp}%"
                        })
            
            if final_list:
                st.table(pd.DataFrame(final_list).sort_values(by="增幅", ascending=False))
            else:
                st.info("符合籌碼面，但被震幅或回補開關過濾掉了。")