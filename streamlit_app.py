import streamlit as st
import pandas as pd
import requests
import io
import urllib3

# 解決 SSL 與 Redirect 問題
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

st.set_page_config(page_title="台股籌碼終極雷達", layout="wide")
st.title("🏹 台股全市場：籌碼 4 碼標的掃描器 (精確加總版)")

@st.cache_data(ttl=3600)
def fetch_tdcc_api():
    """自動抓取集保週報"""
    url = "https://opendata.tdcc.com.tw/getOD.ashx?id=1-5"
    try:
        # 加入 allow_redirects 解決 image_d15b86.png 中的 Redirects 錯誤
        res = requests.get(url, timeout=30, verify=False, allow_redirects=True)
        if res.status_code == 200:
            df = pd.read_csv(io.StringIO(res.text))
            df.columns = ['date', 'stock_id', 'level', 'count', 'shares', 'percent']
            df['stock_id'] = df['stock_id'].astype(str).str.strip()
            # 過濾 4 碼
            df = df[df['stock_id'].str.fullmatch(r'\d{4}')]
            return df
    except:
        return pd.DataFrame()

# --- 側邊欄 ---
st.sidebar.header("🎛️ 參數與資料上傳")
uploaded_files = st.sidebar.file_uploader("上傳歷史 CSV", accept_multiple_files=True)

retail_map = {"50張以下": 8, "100張以下": 9, "200張以下": 10, "400張以下": 11}
retail_choice = st.sidebar.selectbox("散戶定義", list(retail_map.keys()))
retail_lv = retail_map[retail_choice]

if st.button("🚀 開始分析"):
    all_data = []
    
    # 讀取線上
    df_on = fetch_tdcc_api()
    if not df_on.empty:
        all_data.append(df_on)
    
    # 讀取上傳
    if uploaded_files:
        for f in uploaded_files:
            tdf = pd.read_csv(f)
            tdf.columns = ['date', 'stock_id', 'level', 'count', 'shares', 'percent']
            tdf['stock_id'] = tdf['stock_id'].astype(str).str.strip()
            tdf = tdf[tdf['stock_id'].str.fullmatch(r'\d{4}')]
            all_data.append(tdf)

    if len(all_data) == 0:
        st.error("請上傳資料或確認網路連線。")
    else:
        # --- 關鍵修正：徹底去重 ---
        # 確保同日期、同個股、同 Level 只有一筆資料，避免 image_d15b86.png 的 100% 爆表問題
        full_df = pd.concat(all_data).drop_duplicates(subset=['date', 'stock_id', 'level'])
        
        all_dates = sorted(full_df['date'].unique(), reverse=True)
        num_weeks = len(all_dates)
        
        if num_weeks < 2:
            st.warning("資料週數不足，無法比對。")
        else:
            # 只取大戶 (Level 11-15) 並依據日期加總
            # 這裡的 sum() 就不會因為重複檔案而翻倍
            big_df = full_df[full_df['level'] >= 11].groupby(['stock_id', 'date'])['percent'].sum().reset_index()
            small_df = full_df[full_df['level'] <= retail_lv].groupby(['stock_id', 'date'])['percent'].sum().reset_index()
            
            big_pivot = big_df.pivot(index='stock_id', columns='date', values='percent')
            small_pivot = small_df.pivot(index='stock_id', columns='date', values='percent')
            
            # 判斷邏輯 (同前版)
            t_dates = all_dates[:3] if num_weeks >= 3 else all_dates[:2]
            
            if num_weeks >= 3:
                mask = (big_pivot[t_dates[0]] > big_pivot[t_dates[1]]) & \
                       (big_pivot[t_dates[1]] > big_pivot[t_dates[2]]) & \
                       (small_pivot[t_dates[0]] < small_pivot[t_dates[1]]) & \
                       (small_pivot[t_dates[1]] < small_pivot[t_dates[2]])
            else:
                mask = (big_pivot[t_dates[0]] > big_pivot[t_dates[1]]) & \
                       (small_pivot[t_dates[0]] < small_pivot[t_dates[1]])
            
            candidates = big_pivot[mask].dropna().index.tolist()
            
            if candidates:
                res = []
                for sid in candidates:
                    b_vals = [f"{big_pivot.loc[sid, d]:.2f}%" for d in t_dates]
                    s_vals = [f"{small_pivot.loc[sid, d]:.2f}%" for d in t_dates]
                    res.append({
                        "代號": sid,
                        "大戶持股 (新->舊)": " / ".join(b_vals),
                        "散戶持股 (新->舊)": " / ".join(s_vals),
                        "大戶增幅": f"{(big_pivot.loc[sid, t_dates[0]] - big_pivot.loc[sid, t_dates[1]]):+.2f}%"
                    })
                st.table(pd.DataFrame(res))
            else:
                st.info("無符合條件標的。")