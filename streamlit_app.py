import streamlit as st
import pandas as pd
import requests
import io
import urllib3

# 1. 解決 SSL 報錯問題
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

st.set_page_config(page_title="台股籌碼終極雷達", layout="wide")
st.title("🏹 全市場：籌碼 4 碼標的掃描器 (大戶增幅篩選版)")

@st.cache_data(ttl=3600)
def fetch_tdcc_api():
    """自動抓取最新集保資料"""
    url = "https://opendata.tdcc.com.tw/getOD.ashx?id=1-5"
    try:
        res = requests.get(url, timeout=30, verify=False, allow_redirects=True)
        if res.status_code == 200:
            df = pd.read_csv(io.StringIO(res.text))
            df.columns = ['date', 'stock_id', 'level', 'count', 'shares', 'percent']
            df['stock_id'] = df['stock_id'].astype(str).str.strip()
            # 過濾 4 碼個股
            df = df[df['stock_id'].str.fullmatch(r'\d{4}')]
            return df
    except:
        return pd.DataFrame()

# --- 側邊欄控制 ---
st.sidebar.header("🎛️ 策略參數控制")
uploaded_files = st.sidebar.file_uploader("上傳歷史 CSV", accept_multiple_files=True)

st.sidebar.divider()
# --- 新功能：大戶增幅門檻 (1% - 10%) ---
threshold = st.sidebar.slider("大戶增持比例門檻 (%)", 1, 10, 1, step=1)
st.sidebar.caption(f"💡 僅顯示本週大戶增加超過 {threshold}% 的標的")

retail_map = {"50張以下": 8, "100張以下": 9, "200張以下": 10, "400張以下": 11}
retail_choice = st.sidebar.selectbox("散戶定義", list(retail_map.keys()))
retail_lv = retail_map[retail_choice]

if st.button("🚀 開始全市場深度分析"):
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

    if len(all_dfs) < 2:
        st.error("❌ 資料不足。請上傳歷史 CSV 以進行比對。")
    else:
        # 去重與校正
        full_df = pd.concat(all_dfs).drop_duplicates(subset=['date', 'stock_id', 'level'])
        full_df = full_df[full_df['level'] <= 15]
        all_dates = sorted(full_df['date'].unique(), reverse=True)
        
        def get_pivot(lv_condition):
            p = full_df[lv_condition].groupby(['stock_id', 'date'])['percent'].sum().reset_index()
            pivot = p.pivot(index='stock_id', columns='date', values='percent')
            # 若數據因原始 CSV 格式破百，自動除以 100 修正 (例如 116.51 -> 1.1651)
            # 但你目前截圖中的數據已經修正過，此處作為安全閥
            if (pivot > 100).any().any():
                pivot = pivot / 100
            return pivot

        big_pivot = get_pivot(full_df['level'] >= 11)
        small_pivot = get_pivot(full_df['level'] <= retail_lv)

        t_dates = all_dates[:3] if len(all_dates) >= 3 else all_dates[:2]
        
        # --- 核心邏輯修正 ---
        # 1. 大戶增、散戶減的基本面
        if len(all_dates) >= 3:
            basic_mask = (big_pivot[t_dates[0]] > big_pivot[t_dates[1]]) & \
                         (big_pivot[t_dates[1]] > big_pivot[t_dates[2]]) & \
                         (small_pivot[t_dates[0]] < small_pivot[t_dates[1]]) & \
                         (small_pivot[t_dates[1]] < small_pivot[t_dates[2]])
        else:
            basic_mask = (big_pivot[t_dates[0]] > big_pivot[t_dates[1]]) & \
                         (small_pivot[t_dates[0]] < small_pivot[t_dates[1]])
        
        # 2. 加入「增幅門檻」篩選
        # 計算本週與上週的差值
        diff = big_pivot[t_dates[0]] - big_pivot[t_dates[1]]
        threshold_mask = diff >= threshold
        
        final_mask = basic_mask & threshold_mask
        candidates = big_pivot[final_mask].dropna().index.tolist()

        if candidates:
            st.success(f"🏁 篩選完成：發現 {len(candidates)} 檔標的大戶增持超過 {threshold}%")
            res = []
            for sid in candidates:
                b_str = " -> ".join([f"{big_pivot.loc[sid, d]:.2f}%" for d in reversed(t_dates)])
                s_str = " -> ".join([f"{small_pivot.loc[sid, d]:.2f}%" for d in reversed(t_dates)])
                res.append({
                    "代號": sid,
                    "大戶持股趨勢": b_str,
                    "散戶持股趨勢": s_str,
                    "本週實際增幅": f"{diff.loc[sid]:+.2f}%"
                })
            st.table(pd.DataFrame(res).sort_values(by="本週實際增幅", ascending=False))
        else:
            st.info(f"查無大戶增持超過 {threshold}% 且散戶減少的標的。")