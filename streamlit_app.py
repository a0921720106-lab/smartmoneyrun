import streamlit as st
import pandas as pd
import yfinance as yf
import re
import os
import glob
import numpy as np

# 設定頁面
st.set_page_config(page_title="台股籌碼終極雷達-趨勢版", layout="wide")
st.title("🏹 台股籌碼：全市場掃描與自選監控")

# --- 1. 資料持久化與基礎設定 ---
STORAGE_DIR = "saved_csv_data"
if not os.path.exists(STORAGE_DIR):
    os.makedirs(STORAGE_DIR)

RETAIL_LV_LIMIT = 8 

# --- 2. 側邊欄控制 ---
st.sidebar.header("🎛️ 全域參數設定")
strength_offset = st.sidebar.slider("增持強度 (超過平均值 %)", 0.0, 5.0, 0.5, 0.1)
vol_limit = st.sidebar.slider("週震幅上限 (%)", 5, 30, 30)

st.sidebar.divider()
uploaded_files = st.sidebar.file_uploader("上傳集保 CSV (可持續累加)", accept_multiple_files=True)

if uploaded_files:
    for f in uploaded_files:
        with open(os.path.join(STORAGE_DIR, f.name), "wb") as save_f:
            save_f.write(f.getbuffer())
    st.sidebar.success(f"檔案已儲存。")

# --- 3. 核心處理邏輯 ---

def process_trend_data():
    saved_paths = glob.glob(os.path.join(STORAGE_DIR, "*.csv"))
    if len(saved_paths) < 2:
        return None, None, None
    
    all_dfs = []
    for path in saved_paths:
        try:
            tdf = pd.read_csv(path)
            tdf.columns = [col.strip() for col in tdf.columns]
            tdf.columns = ['date', 'stock_id', 'level', 'count', 'shares', 'percent']
            tdf['date'] = tdf['date'].astype(str).str.replace(r'[^0-9]', '', regex=True)
            tdf['stock_id'] = tdf['stock_id'].astype(str).str.replace(r'\.0$', '', regex=True).str.strip().str.zfill(4)
            tdf = tdf[tdf['level'].between(1, 15)]
            all_dfs.append(tdf)
        except: continue
    
    full_df = pd.concat(all_dfs).drop_duplicates(subset=['date', 'stock_id', 'level'])
    all_dates = sorted(full_df['date'].unique(), reverse=True)[:30]
    full_df = full_df[full_df['date'].isin(all_dates)]
    
    # 大戶樞紐
    big_data = full_df[full_df['level'] >= 11].groupby(['stock_id', 'date'])['percent'].sum().reset_index()
    if (big_data['percent'] > 100).any(): big_data['percent'] /= 100
    big_pivot = big_data.pivot(index='stock_id', columns='date', values='percent')
    
    # 散戶樞紐
    small_data = full_df[full_df['level'] <= RETAIL_LV_LIMIT].groupby(['stock_id', 'date'])['percent'].sum().reset_index()
    if (small_data['percent'] > 100).any(): small_data['percent'] /= 100
    small_pivot = small_data.pivot(index='stock_id', columns='date', values='percent')

    return big_pivot, small_pivot, all_dates

# --- 4. 分頁邏輯 ---
tab1, tab2 = st.tabs(["🚀 全市場深度掃描", "💎 我的私藏股監控"])

with tab1:
    if st.button("啟動全市場分析"):
        big_pivot, small_pivot, dates = process_trend_data()
        if big_pivot is not None:
            t_new = dates[0]
            big_pivot['avg_big'] = big_pivot[dates].mean(axis=1)
            small_pivot['avg_small'] = small_pivot[dates].mean(axis=1)
            
            # 初步籌碼篩選
            mask = (big_pivot[t_new] > (big_pivot['avg_big'] + strength_offset)) & \
                   (small_pivot[t_new] < small_pivot['avg_small']) & \
                   (big_pivot.index.str.len() == 4)
            
            candidates = big_pivot[mask].index.tolist()
            
            if candidates:
                results = []
                st.write(f"🔍 正在檢查 {len(candidates)} 檔標的的週震幅...")
                prog = st.progress(0)
                
                for i, sid in enumerate(candidates):
                    prog.progress((i + 1) / len(candidates))
                    amp = 999  # 預設震幅無窮大
                    try:
                        # 修正：將 yfinance 邏輯補回
                        data = yf.download(f"{sid}.TW", period="10d", progress=False, multi_level_index=False)
                        if data.empty:
                            data = yf.download(f"{sid}.TWO", period="10d", progress=False, multi_level_index=False)
                        
                        if not data.empty:
                            recent = data.tail(5) # 抓最近 5 個交易日代表本週
                            hi, lo = float(recent['High'].max()), float(recent['Low'].min())
                            amp = round(((hi - lo) / lo) * 100, 2)
                    except: 
                        pass
                    
                    # 真正執行震幅過濾
                    if amp <= vol_limit:
                        diff = big_pivot.loc[sid, t_new] - big_pivot.loc[sid, 'avg_big']
                        results.append({
                            "代號": sid, 
                            "目前大戶%": f"{big_pivot.loc[sid, t_new]:.2f}%", 
                            "超額增持": round(diff, 2),
                            "週震幅": f"{amp}%"
                        })
                
                if results:
                    st.success(f"🎯 篩選完成，符合震幅限制共 {len(results)} 檔")
                    res_df = pd.DataFrame(results).sort_values(by="超額增持", ascending=False)
                    st.table(res_df)
                else:
                    st.warning(f"❌ 籌碼合格，但這 {len(candidates)} 檔股票的週震幅皆超過 {vol_limit}%。")
            else:
                st.info("目前沒有標的符合籌碼增持條件。")
        else:
            st.error("請先上傳 CSV 資料。")

with tab2:
    st.subheader("📋 填入目前持股 (輸入 4 碼代號)")
    my_stocks_input = st.text_input("請輸入股票代號，用逗號或空白分隔（最多 10 檔）", value="")
    my_stocks = [s.strip() for s in re.split(r'[ ,]+', my_stocks_input) if len(s.strip()) == 4][:10]

    if st.button("分析私藏股趨勢") and my_stocks:
        big_pivot, small_pivot, dates = process_trend_data()
        if big_pivot is not None:
            t_new = dates[0]
            valid_stocks = [s for s in my_stocks if s in big_pivot.index]
            
            if not valid_stocks:
                st.warning("輸入的代號在資料庫中找不到。")
            else:
                monitor_results = []
                for sid in valid_stocks:
                    history = big_pivot.loc[sid, dates].dropna()
                    current = history[t_new]
                    avg = history.mean()
                    rank = (history < current).sum() / len(history) * 100
                    status = "✅ 籌碼高檔" if current >= avg else "⚠️ 跌破均線"
                    
                    monitor_results.append({
                        "代號": sid,
                        "本週大戶%": f"{current:.2f}%",
                        "歷史平均%": f"{avg:.2f}%",
                        "增減狀況": f"{current - avg:+.2f}%",
                        "大戶位階": f"贏過前 {rank:.0f}% 的週次",
                        "狀態警示": status
                    })
                
                st.table(pd.DataFrame(monitor_results))
                st.write("📈 私藏股大戶軌跡對比")
                trend_df = big_pivot.loc[valid_stocks, reversed(dates)].T
                st.line_chart(trend_df)
        else:
            st.error("請先上傳 CSV 資料。")