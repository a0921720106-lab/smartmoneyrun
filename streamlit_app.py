import streamlit as st
import pandas as pd
import requests
import urllib3
import yfinance as yf
import re
import time
from datetime import datetime, timedelta

# 關閉不安全的請求警告
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
st.set_page_config(page_title="台股籌碼終極雷達", layout="wide")
st.title("🏹 全市場：大戶增 + 散戶減 + 週借券掃描")

# --- 側邊欄控制 ---
st.sidebar.header("🎛️ 策略參數控制")
st.sidebar.toggle("開啟週借券回補篩選", value=False, key="toggle_short_cover")
uploaded_files = st.sidebar.file_uploader("上傳歷史集保 CSV (至少兩份)", accept_multiple_files=True)

st.sidebar.divider()
threshold = st.sidebar.slider("大戶增持門檻 (%)", 0.1, 5.0, 1.0, 0.1)
vol_limit = st.sidebar.slider("週震幅上限 (%)", 5, 100, 30)

retail_map = {"50張以下": 8, "100張以下": 9, "200張以下": 10, "400張以下": 11}
retail_choice = st.sidebar.selectbox("散戶定義", list(retail_map.keys()))
retail_lv = retail_map[retail_choice]

# --- 核心邏輯函數 ---

def get_weekly_short_covering(stock_id, date_new, date_old):
    """抓取證交所週借券餘額消長 (含自動日期追蹤)"""
    headers = {'User-Agent': 'Mozilla/5.0'}
    
    def fetch_bal(target_date_str):
        # 嘗試從目標日期往前推 3 天，直到抓到資料為止 (解決假日/還沒收盤問題)
        current_dt = datetime.strptime(target_date_str, "%Y%m%d")
        for _ in range(4):
            check_date = current_dt.strftime("%Y%m%d")
            url = f"https://www.twse.com.tw/exchangeReport/TWTASU?response=json&date={check_date}&stockNo={stock_id}"
            try:
                res = requests.get(url, timeout=5, verify=False, headers=headers)
                data = res.json()
                if data.get('data'):
                    # 借券賣出餘額在 index 11
                    return int(str(data['data'][-1][11]).replace(',', ''))
            except: pass
            current_dt -= timedelta(days=1)
        return None

    bal_new = fetch_bal(date_new)
    bal_old = fetch_bal(date_old)
    
    if bal_new is not None and bal_old is not None:
        return bal_new < bal_old
    return False

# --- 啟動掃描 ---

if st.button("🚀 啟動全市場深度分析"):
    if not uploaded_files or len(uploaded_files) < 2:
        st.error("❌ 請上傳至少兩份集保 CSV。")
    else:
        all_dfs = []
        for f in uploaded_files:
            try:
                tdf = pd.read_csv(f)
                tdf.columns = [col.strip() for col in tdf.columns]
                # 重新命名與清理
                tdf.columns = ['date', 'stock_id', 'level', 'count', 'shares', 'percent']
                tdf['date'] = tdf['date'].astype(str).str.replace(r'[^0-9]', '', regex=True)
                tdf['stock_id'] = tdf['stock_id'].astype(str).str.replace(r'\.0$', '', regex=True).str.strip().str.zfill(4)
                
                # --- 修正 100% 問題：只取 1~15 級，排除 16(差異) 與 17(合計) ---
                tdf = tdf[tdf['level'].between(1, 15)]
                
                # --- 排除 ETF：只留 4 碼的代號 ---
                tdf = tdf[tdf['stock_id'].str.len() == 4]
                
                all_dfs.append(tdf)
            except Exception as e:
                st.warning(f"檔案 {f.name} 格式不符: {e}")
        
        if len(all_dfs) < 2: st.stop()

        full_df = pd.concat(all_dfs).drop_duplicates(subset=['date', 'stock_id', 'level'])
        all_dates = sorted(full_df['date'].unique(), reverse=True)
        t_new, t_old = all_dates[0], all_dates[1]
        
        st.info(f"📊 對比日期：{t_old} ➡️ {t_new} (已排除 ETF 及總計欄位)")

        def get_pivot(lv_cond):
            temp = full_df[lv_cond].groupby(['stock_id', 'date'])['percent'].sum().reset_index()
            # 若數據顯示為 14420 這種萬分比格式，除以 100
            if (temp['percent'] > 100).any():
                temp['percent'] = temp['percent'] / 100
            return temp.pivot(index='stock_id', columns='date', values='percent')

        big_pivot = get_pivot(full_df['level'] >= 11)
        small_pivot = get_pivot(full_df['level'] <= retail_lv)
        
        summary = pd.merge(big_pivot[[t_new, t_old]], small_pivot[[t_new, t_old]], 
                          left_index=True, right_index=True, suffixes=('_big', '_small')).dropna()
        
        summary['diff'] = summary[f'{t_new}_big'] - summary[f'{t_old}_big']
        
        mask = (summary[f'{t_new}_big'] > summary[f'{t_old}_big']) & \
               (summary[f'{t_new}_small'] < summary[f'{t_old}_small']) & \
               (summary['diff'] >= threshold)
               
        candidates = summary[mask].index.tolist()

        if candidates:
            results = []
            prog = st.progress(0)
            check_short_cover = st.session_state.get("toggle_short_cover", False)
            
            for i, sid in enumerate(candidates):
                prog.progress((i + 1) / len(candidates))
                amp = 999
                try:
                    # 優先抓上市，抓不到抓上櫃
                    data = yf.download(f"{sid}.TW", period="10d", progress=False, multi_level_index=False)
                    if data.empty:
                        data = yf.download(f"{sid}.TWO", period="10d", progress=False, multi_level_index=False)
                    
                    if not data.empty:
                        recent = data.tail(5)
                        hi, lo = float(recent['High'].max()), float(recent['Low'].min())
                        amp = round(((hi - lo) / lo) * 100, 2)
                except: pass
                
                if amp <= vol_limit:
                    is_covering = False
                    if check_short_cover:
                        # 使用日期自動追蹤邏輯
                        is_covering = get_weekly_short_covering(sid, t_new, t_old)
                        if not is_covering: continue
                    
                    results.append({
                        "代號": sid,
                        "大戶持股": f"{summary.loc[sid, f'{t_new}_big']:.2f}%",
                        "大戶增幅": f"{summary.loc[sid, 'diff']:+.2f}%",
                        "週震幅": f"{amp}%",
                        "週借券回補": "✅" if is_covering else "--"
                    })
                # 防止證交所鎖 IP，每 5 筆微調休息
                if check_short_cover and i % 5 == 0: time.sleep(0.2)

            if results:
                st.success(f"🎯 篩選完成！共 {len(results)} 檔符合條件")
                st.table(pd.DataFrame(results).sort_values(by="大戶增幅", ascending=False))
            else:
                st.warning("❌ 籌碼面合格，但被技術面或借券條件過濾。")