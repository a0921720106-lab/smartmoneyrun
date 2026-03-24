import streamlit as st
import pandas as pd
from FinMind.data import DataLoader

st.set_page_config(page_title="6187 籌碼診斷工具", layout="wide")
st.title("🔍 股票代碼 6187 (萬潤) 籌碼資料深層診斷")

dl = DataLoader()
stock_id = '6187'

# 1. 抓取原始籌碼資料
st.subheader("第一步：抓取原始集保資料")
dist = dl.taiwan_stock_holding_shares_per(stock_id=stock_id, start_date='2024-01-01')

if dist.empty:
    st.error("❌ 錯誤：API 回傳 6187 的籌碼資料是空的！可能是流量限制或 API 暫時失效。")
else:
    st.success(f"✅ 成功抓取資料，共 {len(dist)} 筆。")
    
    # 檢查日期
    available_dates = sorted(dist['date'].unique())
    st.write(f"📅 資料庫中的最新 4 個日期：{available_dates[-4:]}")
    
    # 檢查 HoldersLevel 的名稱 (這最關鍵)
    st.write("📊 API 回傳的持股分級名稱 (請檢查是否有空格或全形字)：")
    st.write(dist['HoldersLevel'].unique().tolist())

    # 2. 模擬計算邏輯
    st.subheader("第二步：模擬大戶/散戶計算")
    dates = available_dates[-4:]
    
    # 定義我們要比對的字串
    big_levels = ['400-600','600-800','800-1000','1000以上']
    small_levels = ['1-5','5-10','10-15','15-20','20-30']
    
    diag_data = []
    for d in dates:
        day_df = dist[dist['date'] == d]
        # 計算大戶
        b_val = day_df[day_df['HoldersLevel'].isin(big_levels)]['percent'].sum()
        # 計算散戶
        s_val = day_df[day_df['HoldersLevel'].isin(small_levels)]['percent'].sum()
        diag_data.append({"日期": d, "大戶%": b_val, "散戶%": s_val})
    
    df_diag = pd.DataFrame(diag_data)
    st.table(df_diag)

    # 3. 邏輯判定診斷
    st.subheader("第三步：趨勢判定檢查")
    w_big = df_diag['大戶%'].tolist()
    w_small = df_diag['散戶%'].tolist()
    
    c1 = w_big[3] > w_big[0]
    c2 = w_big[3] >= w_big[2]
    c3 = w_small[3] < w_small[0]
    c4 = w_small[3] <= w_small[2]
    
    st.write(f"1. 本週大戶 > 三週前 ({w_big[3]} > {w_big[0]}): {'✅' if c1 else '❌'}")
    st.write(f"2. 本週大戶 >= 上週 ({w_big[3]} >= {w_big[2]}): {'✅' if c2 else '❌'}")
    st.write(f"3. 本週散戶 < 三週前 ({w_small[3]} < {w_small[0]}): {'✅' if c3 else '❌'}")