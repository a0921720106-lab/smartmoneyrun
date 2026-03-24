import streamlit as st
import pandas as pd
import requests
import io
import urllib3

# 關閉 SSL 安全警告 (因為政府網站憑證偶爾會失效)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

st.set_page_config(page_title="台股大戶雷達", layout="wide")
st.title("🏹 台股全市場：籌碼 4 碼標的高效掃描器")

# --- 核心抓取功能 ---
@st.cache_data(ttl=3600)
def fetch_tdcc_api():
    """自動抓取集保『最新一週』全市場彙總 (繞過驗證)"""
    url = "https://smart.tdcc.com.tw/opendata/getOD.ashx?id=1-5"
    try:
        # verify=False 解決 image_d5036e.png 顯示的 SSL 錯誤
        res = requests.get(url, timeout=30, verify=False)
        if res.status_code == 200:
            df = pd.read_csv(io.StringIO(res.text))
            df.columns = ['date', 'stock_id', 'level', 'count', 'shares', 'percent']
            # 強制過濾：代號必須是 4 碼且全部為數字 (排除 image_d5036e.png 出現的 000218 等)
            df['stock_id'] = df['stock_id'].astype(str).str.strip()
            df = df[df['stock_id'].str.fullmatch(r'\d{4}')]
            return df
    except Exception as e:
        st.error(f"自動抓取失敗：{e}")
    return pd.DataFrame()

# --- 介面佈局 ---
st.sidebar.header("📊 歷史資料與設定")
st.sidebar.markdown(f"[點我前往：歷史 CSV 下載頁](https://data.gov.tw/dataset/14417)")
uploaded_files = st.sidebar.file_uploader("上傳『前兩週』全市場 CSV", accept_multiple_files=True)

retail_map = {"50張以下": 8, "100張以下": 9, "200張以下": 10, "400張以下": 11}
retail_choice = st.sidebar.selectbox("散戶定義", list(retail_map.keys()))
retail_lv = retail_map[retail_choice]

# --- 掃描邏輯 ---
if st.button("🚀 啟動全自動對齊掃描"):
    all_dfs = []
    
    # 1. 抓取最新一週
    df_now = fetch_tdcc_api()
    if not df_now.empty:
        all_dfs.append(df_now)
        st.success(f"✅ 自動抓取最新一週資料成功！日期：{df_now['date'].iloc[0]}")
    
    # 2. 加入上傳的歷史資料
    if uploaded_files:
        for f in uploaded_files:
            tdf = pd.read_csv(f)
            tdf.columns = ['date', 'stock_id', 'level', 'count', 'shares', 'percent']
            tdf['stock_id'] = tdf['stock_id'].astype(str).str.strip()
            # 同樣執行 4 碼過濾
            tdf = tdf[tdf['stock_id'].str.fullmatch(r'\d{4}')]
            all_dfs.append(tdf)

    if len(all_dfs) < 3:
        st.warning(f"目前僅有 {len(all_dfs)} 週資料。請到上述網址下載前兩週 CSV 並上傳，才能判定『連續 3 週增』。")
        if all_dfs:
            st.write("最新週籌碼概況（前 100 檔）：")
            st.dataframe(all_dfs[0].head(100))
    else:
        # 3. 執行連 3 增判斷邏輯
        full_df = pd.concat(all_dfs).drop_duplicates()
        dates = sorted(full_df['date'].unique(), reverse=True)
        t_dates = dates[:3] # 取最近三週
        
        # 矩陣化運算大戶與散戶
        big_pivot = full_df[full_df['level'] >= 11].pivot_table(
            index='stock_id', columns='date', values='percent', aggfunc='sum'
        ).dropna(subset=t_dates)
        
        small_pivot = full_df[full_df['level'] <= retail_lv].pivot_table(
            index='stock_id', columns='date', values='percent', aggfunc='sum'
        )

        # 判定：大戶連 3 增
        mask = (big_pivot[t_dates[0]] > big_pivot[t_dates[1]]) & \
               (big_pivot[t_dates[1]] > big_pivot[t_dates[2]])
        
        candidates = big_pivot[mask].index.tolist()
        
        results = []
        for sid in candidates:
            b_vals = big_pivot.loc[sid, t_dates].tolist()
            s_val = small_pivot.loc[sid, t_dates[0]] if sid in small_pivot.index else 0
            results.append({
                "代號": sid,
                "大戶趨勢(最新⬅️舊)": " / ".join([f"{x:.1f}%" for x in b_vals]),
                "最新散戶%": f"{s_val:.2f}%",
                "三週總增幅": f"{(b_vals[0]-b_vals[2]):+.2f}%"
            })
            
        if results:
            st.balloons()
            st.table(pd.DataFrame(results))
        else:
            st.info("符合標的為 0。建議放寬散戶定義或檢查上傳日期是否連續。")