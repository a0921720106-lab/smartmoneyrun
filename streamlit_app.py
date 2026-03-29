import streamlit as st
import pandas as pd
import requests
import io
import urllib3

# 1. 解決 SSL 與 Redirect 報錯
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

st.set_page_config(page_title="台股籌碼終極雷達", layout="wide")
st.title("🏹 全市場：籌碼 4 碼標的掃描器 (精確加總 + 震幅恢復版)")

# --- 核心抓取函數 ---
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
            # 排除雜訊：只要 4 碼個股
            df = df[df['stock_id'].str.fullmatch(r'\d{4}')]
            return df
    except:
        return pd.DataFrame()

# --- 側邊欄控制 (找回失蹤的選項) ---
st.sidebar.header("🎛️ 策略參數控制")
uploaded_files = st.sidebar.file_uploader("上傳歷史 CSV", accept_multiple_files=True)

st.sidebar.divider()
# 恢復震幅與借券開關
vol_limit = st.sidebar.slider("週震幅限制 (%)", 0, 30, 20)
use_short_sale = st.sidebar.checkbox("開啟借券回補篩選 (目前為預留開關)", value=False)

retail_map = {"50張以下": 8, "100張以下": 9, "200張以下": 10, "400張以下": 11}
retail_choice = st.sidebar.selectbox("散戶定義 (含此等級以下)", list(retail_map.keys()))
retail_lv = retail_map[retail_choice]

# --- 執行邏輯 ---
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
        st.error("❌ 資料週數不足。請確認網路或上傳歷史 CSV。")
    else:
        # 關鍵：精確去重與比例校正
        full_df = pd.concat(all_dfs).drop_duplicates(subset=['date', 'stock_id', 'level'])
        
        # 排除 Level 16 或 17 (如果有總計項則排除)
        full_df = full_df[full_df['level'] <= 15]
        
        all_dates = sorted(full_df['date'].unique(), reverse=True)
        num_weeks = len(all_dates)
        
        # 加總運算
        def get_pivot(lv_condition):
            p = full_df[lv_condition].groupby(['stock_id', 'date'])['percent'].sum().reset_index()
            pivot = p.pivot(index='stock_id', columns='date', values='percent')
            # 安全檢查：如果數值明顯破百，自動修正 (處理某些 CSV 比例單位問題)
            if (pivot > 100).any().any():
                pivot = pivot / pivot.max().max() * 100 
            return pivot

        big_pivot = get_pivot(full_df['level'] >= 11) # 大戶 400張+
        small_pivot = get_pivot(full_df['level'] <= retail_lv) # 散戶

        # 判定邏輯
        t_dates = all_dates[:3] if num_weeks >= 3 else all_dates[:2]
        
        if num_weeks >= 3:
            mask = (big_pivot[t_dates[0]] > big_pivot[t_dates[1]]) & \
                   (big_pivot[t_dates[1]] > big_pivot[t_dates[2]]) & \
                   (small_pivot[t_dates[0]] < small_pivot[t_dates[1]]) & \
                   (small_pivot[t_dates[1]] < small_pivot[t_dates[2]])
            mode = "3 週連增減"
        else:
            mask = (big_pivot[t_dates[0]] > big_pivot[t_dates[1]]) & \
                   (small_pivot[t_dates[0]] < small_pivot[t_dates[1]])
            mode = "2 週對比"

        candidates = big_pivot[mask].dropna().index.tolist()

        if candidates:
            st.success(f"🏁 分析完成 ({mode})：發現 {len(candidates)} 檔標的")
            res = []
            for sid in candidates:
                b_str = " -> ".join([f"{big_pivot.loc[sid, d]:.2f}%" for d in reversed(t_dates)])
                s_str = " -> ".join([f"{small_pivot.loc[sid, d]:.2f}%" for d in reversed(t_dates)])
                res.append({
                    "代號": sid,
                    "大戶趨勢 (舊->新)": b_str,
                    "散戶趨勢 (舊->新)": s_str,
                    "本週大戶增幅": f"{(big_pivot.loc[sid, t_dates[0]] - big_pivot.loc[sid, t_dates[1]]):+.2f}%"
                })
            st.table(pd.DataFrame(res))
        else:
            st.info("查無符合條件標的，建議放寬散戶定義或檢查資料日期。")