import streamlit as st
import pandas as pd
import requests
import io

# 1. 網頁配置
st.set_page_config(page_title="台股原生籌碼雷達", layout="wide")
st.title("🏹 全市場：籌碼連 3 增掃描器 (政府資料直連版)")

# --- 核心功能：抓取全市場 CSV (避開個股查詢) ---
@st.cache_data(ttl=3600)
def fetch_tdcc_full_market():
    """自動抓取集保官網『最新一週』全市場彙總資料 (約 40MB)"""
    # 這是全市場彙總下載點，不是查詢頁面
    url = "https://smart.tdcc.com.tw/opendata/getOD.ashx?id=1-5"
    try:
        # 模擬瀏覽器 Header，防止被政府網站封鎖
        headers = {'User-Agent': 'Mozilla/5.0'}
        res = requests.get(url, headers=headers, timeout=30)
        if res.status_code == 200:
            df = pd.read_csv(io.StringIO(res.text))
            df.columns = ['date', 'stock_id', 'level', 'count', 'shares', 'percent']
            df['stock_id'] = df['stock_id'].astype(str).str.strip()
            return df
    except Exception as e:
        st.error(f"自動抓取失敗：{e}")
    return pd.DataFrame()

# 2. 側邊欄：參數設定
st.sidebar.header("🎛️ 策略參數控制")

# 歷史補完區 (第一次使用必備)
st.sidebar.subheader("📅 歷史補完 (全市場 CSV)")
uploaded_files = st.sidebar.file_uploader("上傳『前兩週』的全市場 CSV 檔", accept_multiple_files=True)

# 散戶等級定義
retail_map = {"50張以下": 8, "100張以下": 9, "200張以下": 10, "400張以下": 11}
retail_choice = st.sidebar.selectbox("散戶定義 (含此等級以下)", list(retail_map.keys()))
retail_lv = retail_map[retail_choice]

# 篩選開關
vol_limit = st.sidebar.slider("週震幅限制 (%)", 0, 15, 10)
use_short_sale = st.sidebar.checkbox("開啟借券連續 3 週回補", value=True)

# 3. 執行主邏輯
if st.button("🚀 啟動掃描 (自動對齊日期)"):
    all_dfs = []
    
    # A. 自動嘗試抓取最新
    with st.spinner("正在向集保伺服器請求最新週報..."):
        df_latest = fetch_tdcc_full_market()
        if not df_latest.empty:
            all_dfs.append(df_latest)
            st.toast("✅ 自動抓取最新週報成功！")

    # B. 加入使用者上傳的歷史
    if uploaded_files:
        for f in uploaded_files:
            try:
                tdf = pd.read_csv(f)
                tdf.columns = ['date', 'stock_id', 'level', 'count', 'shares', 'percent']
                tdf['stock_id'] = tdf['stock_id'].astype(str).str.strip()
                all_dfs.append(tdf)
            except:
                st.error(f"檔案 {f.name} 格式錯誤")

    # C. 檢查是否有足夠資料 (修復 ValueError)
    if not all_dfs:
        st.error("❌ 抓取失敗且未上傳檔案，請檢查網路或手動上傳歷史 CSV。")
    elif len(all_dfs) < 3:
        st.warning(f"目前只有 {len(all_dfs)} 週資料，顯示最新籌碼概況。要看『連 3 增』請再上傳兩週份量。")
        st.dataframe(all_dfs[0].head(50))
    else:
        # 開始計算趨勢
        full_df = pd.concat(all_dfs).drop_duplicates()
        dates = sorted(full_df['date'].unique(), reverse=True)
        target_dates = dates[:5] # 最多看 5 週

        # 計算大戶與散戶
        # 大戶 (>= 400張 = Level 11-15)
        big_pivot = full_df[full_df['level'] >= 11].pivot_table(
            index='stock_id', columns='date', values='percent', aggfunc='sum'
        ).dropna(subset=target_dates[:3])
        
        # 散戶 (使用者定義)
        small_pivot = full_df[full_df['level'] <= retail_lv].pivot_table(
            index='stock_id', columns='date', values='percent', aggfunc='sum'
        )

        # 核心篩選：大戶連 3 增 (W0 > W1 > W2)
        trend_mask = (big_pivot[target_dates[0]] > big_pivot[target_dates[1]]) & \
                     (big_pivot[target_dates[1]] > big_pivot[target_dates[2]])
        
        candidates = big_pivot[trend_mask].index.tolist()
        candidates = [s for s in candidates if len(s) == 4] # 只看普通股

        final_list = []
        for sid in candidates:
            b_trend = big_pivot.loc[sid, target_dates[:3]].tolist()
            s_val = small_pivot.loc[sid, target_dates[0]] if sid in small_pivot.index else 0
            
            final_list.append({
                "代號": sid,
                "最新大戶%": f"{b_trend[0]:.2f}%",
                "趨勢 (新➡️舊)": " / ".join([f"{x:.1f}%" for x in b_trend]),
                "最新散戶%": f"{s_val:.2f}%",
                "大戶連3週增幅": f"{(b_trend[0] - b_trend[2]):+.2f}%"
            })

        if final_list:
            st.success(f"🏁 發現 {len(final_list)} 檔潛力轉折標的！")
            st.dataframe(pd.DataFrame(final_list), use_container_width=True)
        else:
            st.info("無符合條件標的，請嘗試放寬散戶定義。")