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
            
            mask = (big_pivot[t_new] > (big_pivot['avg_big'] + strength_offset)) & \
                   (small_pivot[t_new] < small_pivot['avg_small']) & \
                   (big_pivot.index.str.len() == 4)
            
            candidates = big_pivot[mask].index.tolist()
            
            if candidates:
                results = []
                with st.status("🔍 正在下載市場價格並計算震幅...", expanded=True) as status:
                    total_count = len(candidates)
                    for i, sid in enumerate(candidates):
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
                    status.update(label="✅ 股價資料比對完成！", state="complete", expanded=False)
                
                if results:
                    st.success(f"🎯 篩選完成，符合震幅限制共 {len(results)} 檔")
                    res_df = pd.DataFrame(results).sort_values(by="_sort_key", ascending=False).drop(columns=["_sort_key"])
                    st.dataframe(res_df, use_container_width=True)
                else:
                    st.warning(f"❌ 籌碼合格，但這 {len(candidates)} 檔股票的週震幅皆超過 {vol_limit}%。")
            else:
                st.info("目前沒有標的符合籌碼增持條件。")
        else:
            st.error("❌ 請先上傳至少 2 週以上的集保 CSV 資料，並確認側邊欄顯示儲存成功。")

with tab2:
    st.subheader("📋 填入目前持股 (輸入 4 碼代號)")
    
    my_stocks_input = st.text_input("請輸入股票代號，用逗號或空白分隔（最多 10 檔）", value="2330, 2317", key="my_stocks_input_box")
    my_stocks = [s.strip() for s in re.split(r'[ ,]+', my_stocks_input) if len(s.strip()) == 4][:10]
    
    btn_analyze = st.button("分析私藏股趨勢", key="run_my_stocks")

    if btn_analyze:
        if not my_stocks:
            st.warning("⚠️ 請先輸入至少一檔 4 位數的股票代號。")
        else:
            big_pivot, small_pivot, dates = process_trend_data()
            if big_pivot is not None:
                t_new = dates[0]
                valid_stocks = [s for s in my_stocks if s in big_pivot.index]
                
                if not valid_stocks:
                    st.warning("⚠️ 輸入的代號在您上傳的資料庫中找不到，請確認這幾檔股票本週是否有集保資料。")
                else:
                    monitor_results = []
                    for sid in valid_stocks:
                        history = big_pivot.loc[sid, dates].dropna()
                        current = history[t_new]
                        avg = history.mean()
                        rank = (history < current).sum() / len(history) * 100
                        status = "✅ 籌碼高檔" if current >= avg else "⚠️ 跌破均線"
                        
                        c_val = current * 100 if current <= 1 else current
                        a_val = avg * 100 if avg <= 1 else avg
                        
                        # 【已修正】這裡加上了原本漏掉的冒號
                        monitor_results.append({
                            "代號": sid,
                            "本週大戶%": f"{c_val:.2f}%",
                            "歷史平均%": f"{a_val:.2f}%",
                            "增減狀況": f"{c_val - a_val:+.2f}%",
                            "大戶位階": f"贏過前 {rank:.0f}% 的週次",
                            "狀態警示": status
                        })
                    
                    st.dataframe(pd.DataFrame(monitor_results), use_container_width=True)
                    st.write("📈 私藏股大戶軌跡對比")
                    trend_df = big_pivot.loc[valid_stocks, reversed(dates)].T
                    st.line_chart(trend_df)
            else:
                st.error("❌ 雲端資料庫目前沒有足夠的 CSV 檔案。請先在側邊欄上傳資料，或確認檔案是否毀損。")