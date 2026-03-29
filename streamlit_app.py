import streamlit as st
import pandas as pd
import requests
import io
import urllib3
import yfinance as yf
from datetime import datetime

# 基礎設定
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
st.set_page_config(page_title="台股籌碼終極雷達", layout="wide")
st.title("🏹 全市場：籌碼集中 + 週借券回補篩選器")

# --- 強化版借券抓取：對齊集保日期 ---

def get_weekly_short_covering(stock_id, current_date, previous_date):
    """
    抓取兩個特定結算日的借券數據進行對比
    日期格式需為 YYYYMMDD
    """
    try:
        def fetch_bal(target_date):
            # 轉換日期格式為證交所要求的 YYYYMMDD
            fmt_date = target_date.replace('-', '').replace('/', '')
            url = f"https://www.twse.com.tw/exchangeReport/TWTASU?response=json&date={fmt_date}&stockNo={stock_id}"
            res = requests.get(url, timeout=10, verify=False)
            data = res.json()
            if data.get('data'):
                # 取得該日最後一筆的借券賣出餘額 (索引 11)
                return int(data['data'][-1][11].replace(',', ''))
            return None

        curr_bal = fetch_bal(current_date)
        prev_bal = fetch_bal(previous_date)
        
        if curr_bal is not None and prev_bal is not None:
            return curr_bal < prev_bal
    except:
        return False
    return False

# --- 側邊欄控制 ---

st.sidebar.header("🎛️ 策略參數控制")
use_short_cover = st.sidebar.toggle("開啟週借券回補篩選", value=False)
uploaded_files = st.sidebar.file_uploader("上傳歷史集保 CSV", accept_multiple_files=True)

st.sidebar.divider()
threshold = st.sidebar.slider("大戶增持門檻 (%)", 1, 10, 3)
vol_limit = st.sidebar.slider("週震幅上限 (%)", 5, 30, 15)

# --- 執行邏輯 ---

if st.button("🚀 啟動全市場深度分析"):
    all_dfs = []
    if uploaded_files:
        for f in uploaded_files:
            tdf = pd.read_csv(f)
            tdf.columns = ['date', 'stock_id', 'level', 'count', 'shares', 'percent']
            tdf['stock_id'] = tdf['stock_id'].astype(str).str.strip()
            all_dfs.append(tdf)

    if len(all_dfs) < 2:
        st.error("❌ 請至少上傳兩週的集保 CSV 檔案以進行趨勢對比 。")
    else:
        full_df = pd.concat(all_dfs).drop_duplicates(subset=['date', 'stock_id', 'level'])
        all_dates = sorted(full_df['date'].unique(), reverse=True)
        t = all_dates[:2] # t[0] 是本週五, t[1] 是上週五
        
        st.info(f"📊 分析區間：{t[1]} ➡️ {t[0]}")

        # 籌碼矩陣運算
        def get_pivot(lv_cond):
            temp = full_df[lv_cond].groupby(['stock_id', 'date'])['percent'].sum().reset_index()
            pivot = temp.pivot(index='stock_id', columns='date', values='percent')
            if (pivot > 100).any().any(): pivot = pivot / 100
            return pivot

        big_pivot = get_pivot(full_df['level'] >= 11)
        small_pivot = get_pivot(full_df['level'] <= 8)
        
        mask = (big_pivot[t[0]] > big_pivot[t[1]]) & (small_pivot[t[0]] < small_pivot[t[1]])
        diff = big_pivot[t[0]] - big_pivot[t[1]]
        candidates = big_pivot[mask & (diff >= threshold)].dropna().index.tolist()

        if candidates:
            results = []
            prog = st.progress(0)
            for i, sid in enumerate(candidates):
                # 1. 抓取震幅
                ticker = f"{sid}.TW"
                data = yf.download(ticker, period="10d", progress=False)
                amp = None
                if not data.empty:
                    recent = data.tail(5)
                    amp = round(float(((recent['High'].max() - recent['Low'].min()) / recent['Low'].min()) * 100), 2)
                
                if amp is not None and amp <= vol_limit:
                    # 2. 抓取週借券對比
                    is_covering = False
                    if use_short_cover:
                        is_covering = get_weekly_short_covering(sid, t[0], t[1])
                    
                    if not use_short_cover or (use_short_cover and is_covering):
                        results.append({
                            "代號": sid,
                            "本週大戶%": f"{big_pivot.loc[sid, t[0]]:.2f}%",
                            "上週大戶%": f"{big_pivot.loc[sid, t[1]]:.2f}%",
                            "大戶增幅": f"{diff.loc[sid]:+.2f}%",
                            "週震幅": f"{amp}%",
                            "週借券回補": "✅" if is_covering else "--"
                        })
                prog.progress((i + 1) / len(candidates))

            if results:
                st.table(pd.DataFrame(results).sort_values(by="大戶增幅", ascending=False))
            else:
                st.warning("符合籌碼面，但未通過週震幅或借券回補篩選。")
        else:
            st.info("目前的參數下無符合標的 。")