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
    
    if not all_dfs:
        return None, None, None
        
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
    if st.button("啟動全市場分析", key="run_all_market"):
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
                
                # 【優化點 1】改用 st.status 容器，這在前端 React 機制中非常穩定，專門處理長負載進度
                with st.status("🔍 正在下載市場價格並計算震幅...", expanded=True) as status:
                    total_count = len(candidates)
                    
                    for i, sid in enumerate(candidates):
                        # 【優化點 2】不每檔都用大元件更新，直接更新 status 的文本提示即可
                        status.update(label=f"⏳ 正在分析中... 目前進度 {i+1}/{total_count} (個股: {sid})")
                        
                        amp = 999
                        try:
                            data = yf.download(f"{sid}.TW", period="10d", progress=False, multi_level_index=False)
                            if data.empty:
                                data = yf.download(f"{sid}.TWO", period="10d", progress=False, multi_level_index=False)
                            
                            if not data.empty:
                                recent = data.tail(5)
                                hi, lo = float(recent['High'].max()), float(recent['Low'].min())
                                amp = round(((hi - lo) / lo) * 100, 2)
                        except: 
                            pass
                        
                        if amp <= vol_limit:
                            diff = big_pivot.loc[sid, t_new] - big_pivot.loc[sid, 'avg_big']
                            results.append({
                                "代號": sid, 
                                "目前大戶%": f"{big_pivot.loc[sid, t_new]*100:.2f}%" if big_pivot.loc[sid, t_new] <= 1 else f"{big_pivot.loc[sid, t_new]:.2f}%", 
                                "超額增持%": f"{diff*100:+.2f}%" if diff <= 1 and diff >= -1 else f"{diff:+.2f}%",
                                "週震幅": f"{amp}%",
                                "_sort_key": diff
                            })
                    
                    # 結束後把進度狀態改成完成
                    status.update(label="✅ 股價資料比對完成！", state="complete", expanded=False)
                
                # 【優化點 3】最後在一起將結果繪製出來，徹底與迴圈隔離
                if results:
                    st.success(f"🎯 篩選完成，符合震幅限制共 {len(results)} 檔")
                    res_df = pd.DataFrame(results).sort_values(by="_sort_key", ascending=False).drop(columns=["_sort_key"])
                    st.dataframe(res_df, use_container_width=True)
                else:
                    st.warning(f"❌ 籌碼合格，但這 {len(candidates)} 檔股票的週震幅皆超過 {vol_limit}%。")
            else:
                st.info("目前沒有標的符合籌碼增持條件。")