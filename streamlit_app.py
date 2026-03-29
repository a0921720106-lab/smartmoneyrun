import streamlit as st
import pandas as pd
import requests
import io
import urllib3
import yfinance as yf
from datetime import datetime

# 1. 解決 SSL 與 Redirects 報錯
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

st.set_page_config(page_title="台股籌碼終極雷達", layout="wide")
st.title("🏹 全市場：籌碼集中 + 週借券回補掃描器")

# --- 側邊欄：先確保變數 100% 被定義 ---

st.sidebar.header("🎛️ 策略參數控制")
# 在最外層定義，避免 Pylance 報 UndefinedVariable
use_short_cover = st.sidebar.toggle("開啟週借券回補篩選 (鎖定集保日)", value=False)
uploaded_files = st.sidebar.file_uploader("上傳歷史集保 CSV (至少兩份)", accept_multiple_files=True)

st.sidebar.divider()
threshold = st.sidebar.slider("大戶增持門檻 (%)", 0.5, 10.0, 1.0, 0.5)
vol_limit = st.sidebar.slider("週震幅上限 (%)", 5, 50, 30)

retail_map = {"50張以下": 8, "100張以下": 9, "200張以下": 10, "400張以下": 11}
retail_choice = st.sidebar.selectbox("散戶定義", list(retail_map.keys()))
retail_lv = retail_map[retail_choice]

# --- 核心邏輯函數 ---

def get_weekly_short_covering(stock_id, date_new, date_old):
    """抓取證交所週借券餘額消長"""
    try:
        def fetch_bal(target_date):
            # 確保日期格式為 YYYYMMDD
            fmt_date = str(target_date).replace('-', '').replace('/', '')
            url = f"https://www.twse.com.tw/exchangeReport/TWTASU?response=json&date={fmt_date}&stockNo={stock_id}"
            # 增加 headers 模擬瀏覽器，降低被阻擋機率
            headers = {'User-Agent': 'Mozilla/5.0'}
            res = requests.get(url, timeout=10, verify=False, headers=headers)
            data = res.json()
            if data.get('data'):
                # 取得該日『本日餘額』(索引 11)
                return int(data['data'][-1][11].replace(',', ''))
            return None

        bal_new = fetch_bal(date_new)
        bal_old = fetch_bal(date_old)
        
        if bal_new is not None and bal_old is not None:
            return bal_new < bal_old
    except Exception as e:
        return False
    return False

# --- 執行雷達掃描 ---

if st.button("🚀 啟動全市場深度分析"):
    all_dfs = []
    if uploaded_files:
        for f in uploaded_files:
            try:
                tdf = pd.read_csv(f)
                # 統一欄位名稱，防止因檔案來源不同出錯
                tdf.columns = ['date', 'stock_id', 'level', 'count', 'shares', 'percent']
                tdf['stock_id'] = tdf['stock_id'].astype(str).str.strip().str.zfill(4)
                all_dfs.append(tdf)
            except:
                continue

    if len(all_dfs) < 2:
        st.error("❌ 請上傳至少兩份不同日期的集保 CSV (例如這週與上週) 。")
    else:
        # 1. 解析日期區間
        full_df = pd.concat(all_dfs).drop_duplicates(subset=['date', 'stock_id', 'level'])
        all_dates = sorted(full_df['date'].unique(), reverse=True)
        t_new = all_dates[0]
        t_old = all_dates[1]
        
        st.info(f"📊 正在對比：{t_old} ➡️ {t_new}")

        # 2. 籌碼運算
        def get_pivot(lv_cond):
            temp = full_df[lv_cond].groupby(['stock_id', 'date'])['percent'].sum().reset_index()
            pivot = temp.pivot(index='stock_id', columns='date', values='percent')
            if (pivot > 100).any().any(): pivot = pivot / 100
            return pivot

        big_pivot = get_pivot(full_df['level'] >= 11)
        small_pivot = get_pivot(full_df['level'] <= retail_lv)
        
        # 3. 籌碼初步篩選：大戶增 + 散戶減
        common_stocks = big_pivot.index.intersection(small_pivot.index)
        mask = (big_pivot.loc[common_stocks, t_new] > big_pivot.loc[common_stocks, t_old]) & \
               (small_pivot.loc[common_stocks, t_new] < small_pivot.loc[common_stocks, t_old])
        
        diff = big_pivot.loc[common_stocks, t_new] - big_pivot.loc[common_stocks, t_old]
        candidates = diff[mask & (diff >= threshold)].index.tolist()

        if candidates:
            st.write(f"🔍 籌碼面符合 {len(candidates)} 檔，進一步核對技術面與借券...")
            results = []
            prog = st.progress(0)
            
            for i, sid in enumerate(candidates):
                # A. 震幅過濾
                amp = None
                try:
                    ticker = f"{sid}.TW"
                    data = yf.download(ticker, period="10d", progress=False)
                    if data.empty: data = yf.download(f"{sid}.TWO", period="10d", progress=False)
                    if not data.empty:
                        recent = data.tail(5)
                        high = recent['High'].max()
                        low = recent['Low'].min()
                        amp = round(float(((high - low) / low) * 100), 2)
                except:
                    pass
                
                if amp is not None and amp <= vol_limit:
                    # B. 借券回補檢查
                    is_covering = False
                    # 即使開關沒開，我們也預設為 True 通過，若開了則需檢查
                    if use_short_cover:
                        is_covering = get_weekly_short_covering(sid, str(t_new), str(t_old))
                        can_pass = is_covering
                    else:
                        can_pass = True
                    
                    if can_pass:
                        results.append({
                            "代號": sid,
                            "大戶(新)": f"{big_pivot.loc[sid, t_new]:.2f}%",
                            "大戶增幅": f"{diff.loc[sid]:+.2f}%",
                            "週震幅": f"{amp}%",
                            "週借券回補": "✅" if is_covering else "--"
                        })
                prog.progress((i + 1) / len(candidates))

            if results:
                st.success(f"🎯 篩選成功，共有 {len(results)} 檔符合條件！")
                st.table(pd.DataFrame(results).sort_values(by="大戶增幅", ascending=False))
            else:
                st.warning("符合籌碼增持，但因週震幅過大或無借券回補跡象被過濾。")
        else:
            st.info("目前的參數與資料下，無符合大戶增持且散戶退出的標的 。")