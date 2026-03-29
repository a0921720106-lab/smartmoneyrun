import streamlit as st
import pandas as pd
import requests
import urllib3
import yfinance as yf
import re
import time

# 關閉不安全的請求警告
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
st.set_page_config(page_title="台股籌碼終極雷達", layout="wide")
st.title("🏹 全市場：大戶增 + 散戶減 + 週借券掃描")

# --- 側邊欄控制 ---
st.sidebar.header("🎛️ 策略參數控制")
# 這裡維持使用 key，但在程式邏輯中我們會更嚴謹地讀取它
st.sidebar.toggle("開啟週借券回補篩選 (鎖定集保日)", value=False, key="toggle_short_cover")
uploaded_files = st.sidebar.file_uploader("上傳歷史集保 CSV (至少兩份)", accept_multiple_files=True)

st.sidebar.divider()
threshold = st.sidebar.slider("大戶增持門檻 (%)", 0.1, 5.0, 1.0, 0.1)
vol_limit = st.sidebar.slider("週震幅上限 (%)", 5, 100, 30)

retail_map = {"50張以下": 8, "100張以下": 9, "200張以下": 10, "400張以下": 11}
retail_choice = st.sidebar.selectbox("散戶定義", list(retail_map.keys()))
retail_lv = retail_map[retail_choice]

# --- 核心邏輯函數 ---

def get_weekly_short_covering(stock_id, date_new, date_old):
    """抓取證交所週借券餘額消長"""
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
    def fetch_bal(target_date):
        clean_date = re.sub(r'[^0-9]', '', str(target_date))
        url = f"https://www.twse.com.tw/exchangeReport/TWTASU?response=json&date={clean_date}&stockNo={stock_id}"
        try:
            res = requests.get(url, timeout=5, verify=False, headers=headers)
            data = res.json()
            # 修正：確保抓到的是最後一筆（當日結餘）
            if data.get('data'):
                # 借券賣出餘額通常在第 11 欄 (index 11)
                return int(str(data['data'][-1][11]).replace(',', ''))
        except: pass
        return None

    bal_new = fetch_bal(date_new)
    bal_old = fetch_bal(date_old)
    if bal_new is not None and bal_old is not None:
        return bal_new < bal_old
    return False

# --- 啟動掃描 ---

if st.button("🚀 啟動全市場深度分析"):
    if not uploaded_files or len(uploaded_files) < 2:
        st.error("❌ 請上傳至少兩份不同日期的集保 CSV。")
    else:
        all_dfs = []
        for f in uploaded_files:
            try:
                tdf = pd.read_csv(f)
                tdf.columns = [col.strip() for col in tdf.columns]
                tdf.columns = ['date', 'stock_id', 'level', 'count', 'shares', 'percent']
                tdf['date'] = tdf['date'].astype(str).str.replace(r'[^0-9]', '', regex=True)
                tdf['stock_id'] = tdf['stock_id'].astype(str).str.replace(r'\.0$', '', regex=True).str.strip().str.zfill(4)
                all_dfs.append(tdf)
            except Exception as e:
                st.warning(f"檔案 {f.name} 讀取失敗: {e}")
        
        if len(all_dfs) < 2:
            st.stop()

        full_df = pd.concat(all_dfs).drop_duplicates(subset=['date', 'stock_id', 'level'])
        all_dates = sorted(full_df['date'].unique(), reverse=True)
        
        if len(all_dates) < 2:
            st.error(f"❌ 偵測到的日期不足。")
            st.stop()

        t_new, t_old = all_dates[0], all_dates[1]
        st.info(f"📊 正在對比：{t_old} ➡️ {t_new}")

        def get_pivot(lv_cond):
            temp = full_df[lv_cond].groupby(['stock_id', 'date'])['percent'].sum().reset_index()
            # 確保 percent 是數值
            temp['percent'] = pd.to_numeric(temp['percent'], errors='coerce')
            return temp.pivot(index='stock_id', columns='date', values='percent')

        big_pivot = get_pivot(full_df['level'] >= 11)
        small_pivot = get_pivot(full_df['level'] <= retail_lv)
        
        # 修正合併邏輯，確保兩份資料都有該股票才進行分析
        summary = pd.merge(big_pivot[[t_new, t_old]], small_pivot[[t_new, t_old]], 
                          left_index=True, right_index=True, suffixes=('_big', '_small')).dropna()
        
        summary['diff'] = summary[f'{t_new}_big'] - summary[f'{t_old}_big']
        
        # 籌碼篩選
        mask = (summary[f'{t_new}_big'] > summary[f'{t_old}_big']) & \
               (summary[f'{t_new}_small'] < summary[f'{t_old}_small']) & \
               (summary['diff'] >= threshold)
               
        candidates = summary[mask].index.tolist()
        st.write(f"💡 籌碼符合：{len(candidates)} 檔")

        if candidates:
            results = []
            prog = st.progress(0)
            # 確保讀取最新的開關狀態
            check_short_cover = st.session_state.get("toggle_short_cover", False)
            
            for i, sid in enumerate(candidates):
                prog.progress((i + 1) / len(candidates))
                amp = 999
                
                # --- 手術 1：修正 yfinance 資料提取方式 ---
                try:
                    ticker_str = f"{sid}.TW"
                    data = yf.download(ticker_str, period="10d", progress=False, multi_level_index=False)
                    if data.empty:
                        data = yf.download(f"{sid}.TWO", period="10d", progress=False, multi_level_index=False)
                    
                    if not data.empty:
                        recent = data.tail(5)
                        # 核心修正：強制轉為 float 並取單一數值，避免 Series 錯誤
                        hi = float(recent['High'].max())
                        lo = float(recent['Low'].min())
                        amp = round(((hi - lo) / lo) * 100, 2)
                except:
                    pass
                
                # --- 手術 2：修正篩選判斷邏輯 ---
                if amp <= vol_limit:
                    is_covering = False
                    if check_short_cover:
                        # 只有開啟開關時才去戳證交所 API，節省時間
                        is_covering = get_weekly_short_covering(sid, t_new, t_old)
                        if not is_covering:
                            continue # 開關打開但沒回補，跳過此檔
                    
                    # 準備顯示數據，確保是純數值
                    big_diff = float(summary.loc[sid, 'diff'])
                    big_now = float(summary.loc[sid, f'{t_new}_big'])
                    
                    results.append({
                        "代號": sid,
                        "大戶(新)": f"{big_now:.2f}%",
                        "大戶增幅": f"{big_diff:+.2f}%",
                        "週震幅": f"{amp}%" if amp != 999 else "失敗",
                        "週借券回補": "✅" if is_covering else ("--" if not check_short_cover else "❌")
                    })
                
                # 避免頻繁請求 API
                if check_short_cover:
                    time.sleep(0.1)

            if results:
                st.success(f"🎯 篩選出 {len(results)} 檔標的")
                st.table(pd.DataFrame(results).sort_values(by="大戶增幅", ascending=False))
            else:
                st.warning("❌ 剩餘標的不符合技術面或借券條件。")