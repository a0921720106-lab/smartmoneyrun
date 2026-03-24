import streamlit as st
import pandas as pd
import requests
import io
import urllib3
import time

# 解決 SSL 報錯
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

st.set_page_config(page_title="台股籌碼終極雷達", layout="wide")
st.title("🏹 全市場：籌碼集中度 + 借券 + 波動掃描器")

# --- 核心抓取函數 ---
@st.cache_data(ttl=3600)
def fetch_tdcc_api():
    """自動抓取集保最新週報"""
    url = "https://smart.tdcc.com.tw/opendata/getOD.ashx?id=1-5"
    try:
        res = requests.get(url, timeout=30, verify=False)
        if res.status_code == 200:
            df = pd.read_csv(io.StringIO(res.text))
            df.columns = ['date', 'stock_id', 'level', 'count', 'shares', 'percent']
            df['stock_id'] = df['stock_id'].astype(str).str.strip()
            # 強制過濾 4 碼
            df = df[df['stock_id'].str.fullmatch(r'\d{4}')]
            return df
    except:
        return pd.DataFrame()

def get_market_data(stock_id):
    """二階掃描：針對潛力股抓取股價與借券 (避免被鎖 IP)"""
    # 這裡模擬串接證交所資料，實務上可串接 yfinance 或 FinMind
    # 但僅對過濾後的少數標的執行，效率極高
    return {"amplitude": 5.2, "short_covering": True}

# --- 側邊欄：參數控制 ---
st.sidebar.header("🎛️ 策略參數控制")
st.sidebar.markdown("[點我下載歷史 CSV](https://data.gov.tw/dataset/14417)")
uploaded_files = st.sidebar.file_uploader("上傳歷史 CSV (前兩週)", accept_multiple_files=True)

st.sidebar.divider()
vol_limit = st.sidebar.slider("週震幅限制 (%)", 0, 30, 20)
use_short_sale = st.sidebar.checkbox("開啟借券回補篩選", value=True)

retail_map = {"50張以下": 8, "100張以下": 9, "200張以下": 10, "400張以下": 11}
retail_choice = st.sidebar.selectbox("散戶定義", list(retail_map.keys()))
retail_lv = retail_map[retail_choice]

# --- 掃描邏輯 ---
if st.button("🚀 啟動深度掃描"):
    all_dfs = []
    df_now = fetch_tdcc_api()
    if not df_now.empty:
        all_dfs.append(df_now)
    
    if uploaded_files:
        for f in uploaded_files:
            tdf = pd.read_csv(f)
            tdf.columns = ['date', 'stock_id', 'level', 'count', 'shares', 'percent']
            tdf['stock_id'] = tdf['stock_id'].astype(str).str.strip()
            tdf = tdf[tdf['stock_id'].str.fullmatch(r'\d{4}')]
            all_dfs.append(tdf)

    if len(all_dfs) < 3:
        st.warning("請至少補齊三週資料（自動抓取最新 + 手動上傳兩週）。")
    else:
        full_df = pd.concat(all_dfs).drop_duplicates()
        dates = sorted(full_df['date'].unique(), reverse=True)
        t_dates = dates[:3]
        
        # 1. 大戶連 3 增判斷
        big_pivot = full_df[full_df['level'] >= 11].pivot_table(
            index='stock_id', columns='date', values='percent', aggfunc='sum'
        ).dropna(subset=t_dates)
        
        mask = (big_pivot[t_dates[0]] > big_pivot[t_dates[1]]) & \
               (big_pivot[t_dates[1]] > big_pivot[t_dates[2]])
        
        candidates = big_pivot[mask].index.tolist()
        
        # 2. 進入二階過濾 (波動率與借券)
        results = []
        progress = st.progress(0)
        for idx, sid in enumerate(candidates):
            # 模擬獲取市場數據 (實務上可在此加入股價 API)
            m_data = get_market_data(sid)
            
            # 條件判定
            if m_data["amplitude"] <= vol_limit:
                if not use_short_sale or (use_short_sale and m_data["short_covering"]):
                    b_vals = big_pivot.loc[sid, t_dates].tolist()
                    results.append({
                        "代號": sid,
                        "大戶趨勢": " / ".join([f"{x:.1f}%" for x in b_vals]),
                        "週震幅": f"{m_data['amplitude']}%",
                        "借券回補": "✅" if m_data["short_covering"] else "－"
                    })
            progress.progress((idx + 1) / len(candidates))

        if results:
            st.success(f"發現 {len(results)} 檔標的符合所有開關條件！")
            st.table(pd.DataFrame(results))
        else:
            st.info("目前的參數條件下無符合標的，建議調高『週震幅限制』或關閉『借券篩選』。")