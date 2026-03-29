import streamlit as st
import pandas as pd
import yfinance as yf
import re
import os
import glob

# 設定頁面
st.set_page_config(page_title="台股籌碼終極雷達", layout="wide")
st.title("🏹 全市場：大戶增 + 散戶減 (持久化儲存版)")

# --- 1. 資料持久化設定 ---
STORAGE_DIR = "saved_csv_data"
if not os.path.exists(STORAGE_DIR):
    os.makedirs(STORAGE_DIR)

# --- 2. 側邊欄控制 ---
st.sidebar.header("🎛️ 策略參數控制")

# 修正：大戶門檻 0-15%, 步進 1%
threshold = st.sidebar.slider("大戶增持門檻 (%)", 0, 15, 1, 1)

# 修正：震幅上限固定/調整至 30%
vol_limit = st.sidebar.slider("週震幅上限 (%)", 5, 30, 30)

# 修正：移除散戶下拉選單，永久定義 50張以下 (等級 <= 8)
RETAIL_LV_LIMIT = 8 

st.sidebar.divider()
uploaded_files = st.sidebar.file_uploader("新增集保 CSV 資料", accept_multiple_files=True)

# 儲存新上傳的檔案到伺服器
if uploaded_files:
    for f in uploaded_files:
        with open(os.path.join(STORAGE_DIR, f.name), "wb") as save_f:
            save_f.write(f.getbuffer())
    st.sidebar.success(f"已成功儲存 {len(uploaded_files)} 個新檔案")

# --- 3. 自動載入伺服器已有的檔案 ---
saved_paths = glob.glob(os.path.join(STORAGE_DIR, "*.csv"))
if not saved_paths:
    st.warning("⚠️ 目前資料庫無資料，請先從側邊欄上傳集保 CSV 檔案。")
    st.stop()

st.info(f"📁 目前資料庫共有 {len(saved_paths)} 份歷史集保資料")

# --- 4. 核心處理邏輯 ---

def process_data():
    all_dfs = []
    for path in saved_paths:
        try:
            tdf = pd.read_csv(path)
            tdf.columns = [col.strip() for col in tdf.columns]
            tdf.columns = ['date', 'stock_id', 'level', 'count', 'shares', 'percent']
            
            # 清理代號與日期
            tdf['date'] = tdf['date'].astype(str).str.replace(r'[^0-9]', '', regex=True)
            tdf['stock_id'] = tdf['stock_id'].astype(str).str.replace(r'\.0$', '', regex=True).str.strip().str.zfill(4)
            
            # 修正 1：排除總計欄位
            tdf = tdf[tdf['level'].between(1, 15)]
            # 修正 2：排除 ETF (僅留 4 碼)
            tdf = tdf[tdf['stock_id'].str.len() == 4]
            
            all_dfs.append(tdf)
        except:
            continue
    
    if len(all_dfs) < 2:
        return None, None, None

    full_df = pd.concat(all_dfs).drop_duplicates(subset=['date', 'stock_id', 'level'])
    all_dates = sorted(full_df['date'].unique(), reverse=True)
    t_new, t_old = all_dates[0], all_dates[1]
    
    # 樞紐分析
    def get_pivot(lv_cond):
        temp = full_df[lv_cond].groupby(['stock_id', 'date'])['percent'].sum().reset_index()
        if (temp['percent'] > 100).any():
            temp['percent'] = temp['percent'] / 100
        return temp.pivot(index='stock_id', columns='date', values='percent')

    big_pivot = get_pivot(full_df['level'] >= 11)
    small_pivot = get_pivot(full_df['level'] <= RETAIL_LV_LIMIT)
    
    # 合併比對
    summary = pd.merge(big_pivot[[t_new, t_old]], small_pivot[[t_new, t_old]], 
                      left_index=True, right_index=True, suffixes=('_big', '_small')).dropna()
    
    summary['diff'] = (summary[f'{t_new}_big'] - summary[f'{t_old}_big']).round(2)
    
    # 籌碼初步過濾
    mask = (summary[f'{t_new}_big'] > summary[f'{t_old}_big']) & \
           (summary[f'{t_new}_small'] < summary[f'{t_old}_small']) & \
           (summary['diff'] >= threshold)
           
    return summary[mask], t_new, t_old

# --- 5. 啟動分析 ---

if st.button("🚀 開始掃描深度籌碼"):
    summary_filtered, t_new, t_old = process_data()
    
    if summary_filtered is None:
        st.error("❌ 資料庫中不同日期的資料不足兩份，請再多上傳一份 CSV。")
        st.stop()
    
    st.write(f"📊 對比日期：{t_old} ➡️ {t_new}")
    candidates = summary_filtered.index.tolist()
    
    if candidates:
        results = []
        prog = st.progress(0)
        
        for i, sid in enumerate(candidates):
            prog.progress((i + 1) / len(candidates))
            amp = 999
            try:
                # 抓取技術面
                data = yf.download(f"{sid}.TW", period="10d", progress=False, multi_level_index=False)
                if data.empty:
                    data = yf.download(f"{sid}.TWO", period="10d", progress=False, multi_level_index=False)
                
                if not data.empty:
                    recent = data.tail(5)
                    hi, lo = float(recent['High'].max()), float(recent['Low'].min())
                    amp = round(((hi - lo) / lo) * 100, 2)
            except: pass
            
            if amp <= vol_limit:
                results.append({
                    "代號": sid,
                    "目前大戶持股": summary_filtered.loc[sid, f'{t_new}_big'],
                    "大戶增幅": summary_filtered.loc[sid, 'diff'],
                    "週震幅": amp
                })

        if results:
            st.success(f"🎯 篩選完成！共 {len(results)} 檔符合條件")
            # 修正：轉換為 DataFrame 並根據「大戶增幅」由高到低排序
            res_df = pd.DataFrame(results).sort_values(by="大戶增幅", ascending=False)
            
            # 美化輸出 (加上 % 符號)
            styled_df = res_df.copy()
            styled_df['目前大戶持股'] = styled_df['目前大戶持股'].map("{:.2f}%".format)
            styled_df['大戶增幅'] = styled_df['大戶增幅'].map("{:+.2f}%".format)
            styled_df['週震幅'] = styled_df['週震幅'].map("{:.2f}%".format)
            
            st.table(styled_df)
        else:
            st.warning("❌ 籌碼面合格，但週震幅超過限制。")
    else:
        st.info("目前的資料與門檻下，沒有符合大戶增+散戶減的股票。")