import streamlit as st
import pandas as pd
import yfinance as yf
import re
import os
import glob
import numpy as np

# 設定頁面
st.set_page_config(page_title="台股籌碼終極雷達-趨勢版", layout="wide")
st.title("🏹 全市場：大戶趨勢追蹤 (支援 30 週洗盤分析)")

# --- 1. 資料持久化設定 ---
STORAGE_DIR = "saved_csv_data"
if not os.path.exists(STORAGE_DIR):
    os.makedirs(STORAGE_DIR)

# --- 2. 側邊欄控制 ---
st.sidebar.header("🎛️ 策略參數控制")
# 篩選強度：本週超過平均值多少 %
strength_offset = st.sidebar.slider("增持強度 (超過平均值 %)", 0.0, 5.0, 0.5, 0.1)
vol_limit = st.sidebar.slider("週震幅上限 (%)", 5, 30, 30)
RETAIL_LV_LIMIT = 8 

st.sidebar.divider()
uploaded_files = st.sidebar.file_uploader("上傳集保 CSV (可持續累加)", accept_multiple_files=True)

if uploaded_files:
    for f in uploaded_files:
        with open(os.path.join(STORAGE_DIR, f.name), "wb") as save_f:
            save_f.write(f.getbuffer())
    st.sidebar.success(f"已儲存檔案。目前累積 {len(glob.glob(os.path.join(STORAGE_DIR, '*.csv')))} 份資料。")

# --- 3. 核心處理邏輯 ---

def process_trend_data():
    saved_paths = glob.glob(os.path.join(STORAGE_DIR, "*.csv"))
    if len(saved_paths) < 2:
        return None, None
    
    all_dfs = []
    for path in saved_paths:
        try:
            tdf = pd.read_csv(path)
            tdf.columns = [col.strip() for col in tdf.columns]
            tdf.columns = ['date', 'stock_id', 'level', 'count', 'shares', 'percent']
            tdf['date'] = tdf['date'].astype(str).str.replace(r'[^0-9]', '', regex=True)
            tdf['stock_id'] = tdf['stock_id'].astype(str).str.replace(r'\.0$', '', regex=True).str.strip().str.zfill(4)
            tdf = tdf[tdf['level'].between(1, 15)]
            tdf = tdf[tdf['stock_id'].str.len() == 4]
            all_dfs.append(tdf)
        except: continue
    
    full_df = pd.concat(all_dfs).drop_duplicates(subset=['date', 'stock_id', 'level'])
    all_dates = sorted(full_df['date'].unique(), reverse=True)[:30] # 限制最高 30 週
    
    # 過濾只保留最近 30 週的資料
    full_df = full_df[full_df['date'].isin(all_dates)]
    
    # 樞紐分析：大戶 (11級以上)
    big_data = full_df[full_df['level'] >= 11].groupby(['stock_id', 'date'])['percent'].sum().reset_index()
    if (big_data['percent'] > 100).any(): big_data['percent'] /= 100
    
    big_pivot = big_data.pivot(index='stock_id', columns='date', values='percent')
    
    # 樞紐分析：散戶 (8級以下)
    small_data = full_df[full_df['level'] <= RETAIL_LV_LIMIT].groupby(['stock_id', 'date'])['percent'].sum().reset_index()
    if (small_data['percent'] > 100).any(): small_data['percent'] /= 100
    small_pivot = small_data.pivot(index='stock_id', columns='date', values='percent')

    return big_pivot, small_pivot, all_dates

# --- 4. 啟動分析 ---

if st.button("🚀 啟動多週趨勢掃描"):
    big_pivot, small_pivot, dates = process_trend_data()
    
    if big_pivot is None:
        st.error("❌ 資料不足，請至少上傳兩份不同日期的 CSV。")
        st.stop()
    
    t_new = dates[0]
    st.info(f"📊 分析區間：{dates[-1]} 至 {t_new} (共 {len(dates)} 週資料)")
    
    # --- 計算指標 ---
    # 1. 歷史平均大戶持股 (Baseline)
    big_pivot['avg_big'] = big_pivot[dates].mean(axis=1)
    # 2. 歷史平均散戶持股
    small_pivot['avg_small'] = small_pivot[dates].mean(axis=1)
    
    # --- 關鍵篩選邏輯 ---
    # 條件 1: 本週大戶 > 歷史平均 + 增持強度
    # 條件 2: 本週散戶 < 歷史平均 (代表散戶籌碼仍屬流出趨勢)
    mask = (big_pivot[t_new] > (big_pivot['avg_big'] + strength_offset)) & \
           (small_pivot[t_new] < small_pivot['avg_small'])
    
    candidates = big_pivot[mask].index.tolist()
    
    if candidates:
        results = []
        prog = st.progress(0)
        for i, sid in enumerate(candidates):
            prog.progress((i + 1) / len(candidates))
            amp = 999
            try:
                data = yf.download(f"{sid}.TW", period="10d", progress=False, multi_level_index=False)
                if data.empty: data = yf.download(f"{sid}.TWO", period="10d", progress=False, multi_level_index=False)
                if not data.empty:
                    recent = data.tail(5)
                    hi, lo = float(recent['High'].max()), float(recent['Low'].min())
                    amp = round(((hi - lo) / lo) * 100, 2)
            except: pass
            
            if amp <= vol_limit:
                # 紀錄本週與平均的差異
                diff_from_avg = big_pivot.loc[sid, t_new] - big_pivot.loc[sid, 'avg_big']
                
                results.append({
                    "代號": sid,
                    "本週大戶%": big_pivot.loc[sid, t_new],
                    "30週平均%": big_pivot.loc[sid, 'avg_big'],
                    "超額增持": diff_from_avg,
                    "週震幅": amp
                })

        if results:
            res_df = pd.DataFrame(results).sort_values(by="超額增持", ascending=False)
            
            # 格式化顯示
            styled_df = res_df.copy()
            styled_df['本週大戶%'] = styled_df['本週大戶%'].map("{:.2f}%".format)
            styled_df['30週平均%'] = styled_df['30週平均%'].map("{:.2f}%".format)
            styled_df['超額增持'] = styled_df['超額增持'].map("{:+.2f}%".format)
            styled_df['週震幅'] = styled_df['週震幅'].map("{:.2f}%".format)
            
            st.success(f"🎯 發現 {len(results)} 檔「高於平均持股」之潛力標的")
            st.table(styled_df)
            
            # --- 額外：洗盤視覺化 (選填) ---
            st.subheader("📈 領先標的籌碼軌跡")
            top_sid = res_df.iloc[0]['代號']
            st.line_chart(big_pivot.loc[top_sid, reversed(dates)])
            st.caption(f"圖表顯示 {top_sid} 過去週次的大戶持股變化，可觀察是否有你說的『買、賣、買』洗盤特徵。")
        else:
            st.warning("❌ 籌碼趨勢合格，但近期震幅過大。")
    else:
        st.info("目前沒有標的符合「超越歷史平均」的篩選條件。")