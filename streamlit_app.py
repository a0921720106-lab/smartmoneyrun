import streamlit as st
import pandas as pd
import requests
import io
import urllib3

# 1. 解決 SSL 報錯問題
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

st.set_page_config(page_title="台股籌碼終極雷達", layout="wide")
st.title("🏹 台股全市場：籌碼 4 碼標的掃描器 (2/3週彈性版)")

# --- 核心抓取函數 ---
@st.cache_data(ttl=3600)
def fetch_tdcc_api():
    """使用最新提供網址自動抓取集保週報"""
    # 更新為你提供的網址
    url = "https://opendata.tdcc.com.tw/getOD.ashx?id=1-5"
    try:
        # verify=False 繞過 SSL 檢查
        res = requests.get(url, timeout=30, verify=False)
        if res.status_code == 200:
            df = pd.read_csv(io.StringIO(res.text))
            df.columns = ['date', 'stock_id', 'level', 'count', 'shares', 'percent']
            # 過濾 4 碼個股，排除雜訊
            df['stock_id'] = df['stock_id'].astype(str).str.strip()
            df = df[df['stock_id'].str.fullmatch(r'\d{4}')]
            return df
    except Exception as e:
        st.sidebar.warning(f"線上抓取暫時無法使用：{e}")
    return pd.DataFrame()

# --- 側邊欄控制 ---
st.sidebar.header("🎛️ 參數與資料上傳")
st.sidebar.markdown(f"🔗 [手動下載連結](https://opendata.tdcc.com.tw/getOD.ashx?id=1-5)")

# 保留使用者上傳功能
uploaded_files = st.sidebar.file_uploader("上傳近期歷史 CSV (若線上抓取不足時使用)", accept_multiple_files=True)

st.sidebar.divider()
vol_limit = st.sidebar.slider("週震幅限制 (%)", 0, 30, 20)
use_short_sale = st.sidebar.checkbox("開啟借券回補篩選", value=False)

retail_map = {"50張以下": 8, "100張以下": 9, "200張以下": 10, "400張以下": 11}
retail_choice = st.sidebar.selectbox("散戶定義 (含此等級以下)", list(retail_map.keys()))
retail_lv = retail_map[retail_choice]

# --- 掃描執行邏輯 ---
if st.button("🚀 開始分析全市場籌碼"):
    data_list = []
    
    # 1. 嘗試線上抓取最新一週
    df_online = fetch_tdcc_api()
    if not df_online.empty:
        data_list.append(df_online)
        st.info(f"📅 已自動取得最新資料日期：{df_online['date'].iloc[0]}")
    
    # 2. 加入手動上傳資料
    if uploaded_files:
        for f in uploaded_files:
            tdf = pd.read_csv(f)
            tdf.columns = ['date', 'stock_id', 'level', 'count', 'shares', 'percent']
            tdf['stock_id'] = tdf['stock_id'].astype(str).str.strip()
            tdf = tdf[tdf['stock_id'].str.fullmatch(r'\d{4}')]
            data_list.append(tdf)

    # 3. 合併並整理日期
    if len(data_list) < 2:
        st.error("❌ 資料不足！請至少需有 2 週資料（自動抓取 + 手動上傳）方可比對。")
    else:
        full_df = pd.concat(data_list).drop_duplicates()
        all_dates = sorted(full_df['date'].unique(), reverse=True)
        num_weeks = len(all_dates)
        
        # 4. 矩陣化運算
        # 大戶 (Level 11-15 總和)
        big_pivot = full_df[full_df['level'] >= 11].pivot_table(
            index='stock_id', columns='date', values='percent', aggfunc='sum'
        ).dropna(subset=all_dates[:2]) # 至少要有最近兩週
        
        # 散戶 (使用者定義等級總和)
        small_pivot = full_df[full_df['level'] <= retail_lv].pivot_table(
            index='stock_id', columns='date', values='percent', aggfunc='sum'
        ).dropna(subset=all_dates[:2])

        # 5. 判斷邏輯 (依週數切換)
        if num_weeks >= 3:
            t_dates = all_dates[:3]
            # 條件：大戶連 3 增 且 散戶連 3 減
            big_inc = (big_pivot[t_dates[0]] > big_pivot[t_dates[1]]) & (big_pivot[t_dates[1]] > big_pivot[t_dates[2]])
            small_dec = (small_pivot[t_dates[0]] < small_pivot[t_dates[1]]) & (small_pivot[t_dates[1]] < small_pivot[t_dates[2]])
            mode_text = "執行：3 週籌碼連增減模式"
        else:
            t_dates = all_dates[:2]
            # 條件：2 週大戶增、散戶減
            big_inc = (big_pivot[t_dates[0]] > big_pivot[t_dates[1]])
            small_dec = (small_pivot[t_dates[0]] < small_pivot[t_dates[1]])
            mode_text = "執行：2 週籌碼對比模式"

        # 6. 篩選與顯示
        final_mask = big_inc & small_dec
        candidates = big_pivot[final_mask].index.tolist()
        
        st.subheader(f"📊 分析結果 ({mode_text})")
        
        if candidates:
            res_data = []
            for sid in candidates:
                # 計算趨勢顯示字串
                b_trend = " -> ".join([f"{big_pivot.loc[sid, d]:.1f}%" for d in reversed(t_dates)])
                s_trend = " -> ".join([f"{small_pivot.loc[sid, d]:.1f}%" for d in reversed(t_dates)])
                
                res_data.append({
                    "股票代號": sid,
                    "大戶持股比例趨勢": b_trend,
                    "散戶持股比例趨勢": s_trend,
                    "本週大戶增幅": f"{(big_pivot.loc[sid, t_dates[0]] - big_pivot.loc[sid, t_dates[1]]):+.2f}%"
                })
            
            st.table(pd.DataFrame(res_data))
            st.balloons()
        else:
            st.info("查無符合條件之標的，建議調整散戶定義或放寬週震幅。")