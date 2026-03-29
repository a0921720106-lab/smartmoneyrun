import streamlit as st
import pandas as pd
import requests
import io
import urllib3
import yfinance as yf
from datetime import datetime

# 1. 基礎避坑設定
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
st.set_page_config(page_title="台股籌碼終極雷達", layout="wide")
st.title("🏹 全市場：籌碼集中 + 週借券回補篩選器")

# --- 側邊欄：先定義所有變數以防報錯 ---

st.sidebar.header("🎛️ 策略參數控制")
# 強制在最外層定義變數，徹底解決 UndefinedVariable
use_short_cover = st.sidebar.toggle("開啟週借券回補篩選 (對齊集保日)", value=False)
uploaded_files = st.sidebar.file_uploader("上傳歷史集保 CSV", accept_multiple_files=True)

st.sidebar.divider()
threshold = st.sidebar.slider("大戶增持門檻 (%)", 1, 10, 3)
vol_limit = st.sidebar.slider("週震幅上限 (%)", 5, 30, 15)

retail_map = {"50張以下": 8, "100張以下": 9, "200張以下": 10, "400張以下": 11}
retail_choice = st.sidebar.selectbox("散戶定義", list(retail_map.keys()))
retail_lv = retail_map[retail_choice]

# --- 核心數據抓取函數 ---

def get_weekly_short_covering(stock_id, date_new, date_old):
    """
    對齊集保結算日抓取證交所借券餘額
    判定：本週五餘額 < 上週五餘額 = 回補 ✅
    """
    try:
        def fetch_bal(target_date):
            # 轉換為 YYYYMMDD
            fmt_date = target_date.replace('-', '').replace('/', '')
            url = f"https://www.twse.com.tw/exchangeReport/TWTASU?response=json&date={fmt_date}&stockNo={stock_id}"
            res = requests.get(url, timeout=10, verify=False)
            data = res.json()
            if data.get('data'):
                # 取得該日『本日餘額』(索引 11)
                return int(data['data'][-1][11].replace(',', ''))
            return None

        bal_new = fetch_bal(date_new)
        bal_old = fetch_bal(date_old)
        
        if bal_new is not None and bal_old is not None:
            return bal_new < bal_old
    except:
        return False
    return False

# --- 執行邏輯 ---

if st.button("🚀 啟動全市場深度分析"):
    all_dfs = []
    if uploaded_files:
        for f in uploaded_files:
            tdf = pd.read_csv(f)
            # 標準化欄位
            tdf.columns = ['date', 'stock_id', 'level', 'count', 'shares', 'percent']
            tdf['stock_id'] = tdf['stock_id'].astype(str).str.strip()
            all_dfs.append(tdf)

    if len(all_dfs) < 2:
        st.error("❌ 請上傳至少兩週的集保資料（例如本週與上週的 CSV） 。")
    else:
        # 合併與提取日期
        full_df = pd.concat(all_dfs).drop_duplicates(subset=['date', 'stock_id', 'level'])
        all_dates = sorted(full_df['date'].unique(), reverse=True)
        t_new = all_dates[0]  # 最新週五
        t_old = all_dates[1]  # 上週五
        
        st.info(f"📊 正在分析區間：{t_old} ➡️ {t_new}")

        # 籌碼矩陣計算
        def get_pivot(lv_cond):
            temp = full_df[lv_cond].groupby(['stock_id', 'date'])['percent'].sum().reset_index()
            pivot = temp.pivot(index='stock_id', columns='date', values='percent')
            if (pivot > 100).any().any(): pivot = pivot / 100
            return pivot

        big_pivot = get_pivot(full_df['level'] >= 11)
        small_pivot = get_pivot(full_df['level'] <= retail_lv)
        
        # 籌碼過濾條件
        mask = (big_pivot[t_new] > big_pivot[t_old]) & (small_pivot[t_new] < small_pivot[t_old])
        diff = big_pivot[t_new] - big_pivot[t_old]
        candidates = big_pivot[mask & (diff >= threshold)].dropna().index.tolist()

        if candidates:
            st.write(f"🔍 籌碼初步符合 {len(candidates)} 檔，開始核對週震幅與借券...")
            results = []
            prog = st.progress(0)
            
            for i, sid in enumerate(candidates):
                # 1. 震幅檢查
                ticker = f"{sid}.TW"
                data = yf.download(ticker, period="10d", progress=False)
                if data.empty: data = yf.download(f"{sid}.TWO", period="10d", progress=False)
                
                amp = None
                if not data.empty:
                    recent = data.tail(5)
                    amp = round(float(((recent['High'].max() - recent['Low'].min()) / recent['Low'].min()) * 100), 2)
                
                if amp is not None and amp <= vol_limit:
                    # 2. 借券回補檢查 (僅當開關開啟時)
                    is_covering = False
                    if use_short_cover:
                        is_covering = get_weekly_short_covering(sid, str(t_new), str(t_old))
                    
                    if not use_short_cover or (use_short_cover and is_covering):
                        results.append({
                            "代號": sid,
                            "大戶(新)": f"{big_pivot.loc[sid, t_new]:.2f}%",
                            "大戶(舊)": f"{big_pivot.loc[sid, t_old]:.2f}%",
                            "增幅": f"{diff.loc[sid]:+.2f}%",
                            "週震幅": f"{amp}%",
                            "週借券回補": "✅" if is_covering else "--"
                        })
                prog.progress((i + 1) / len(candidates))

            if results:
                st.table(pd.DataFrame(results).sort_values(by="增幅", ascending=False))
            else:
                st.warning("符合籌碼面，但被週震幅或借券回補過濾。")
        else:
            st.info("目前的參數與資料下，無符合籌碼大增標的。")