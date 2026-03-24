import streamlit as st
import pandas as pd
from FinMind.data import DataLoader

st.set_page_config(page_title="6187 籌碼診斷工具", layout="wide")
st.title("🔍 股票代碼 6187 (萬潤) 資料穩定性診斷")

dl = DataLoader()
stock_id = '6187'

# 1. 安全抓取資料函數
def safe_get_data(func, **kwargs):
    try:
        data = func(**kwargs)
        if data is None or data.empty:
            return pd.DataFrame()
        return data
    except Exception as e:
        st.warning(f"⚠️ 抓取資料時發生小插曲: {e}")
        return pd.DataFrame()

# 開始診斷
st.subheader("第一步：檢查籌碼資料來源")
dist = safe_get_data(dl.taiwan_stock_holding_shares_per, stock_id=stock_id, start_date='2024-01-01')

if dist.empty:
    st.error("❌ 無法從 FinMind 取得 6187 的籌碼資料。這可能是 API 流量限制或該股票資料尚未更新。")
    st.info("💡 建議：如果您頻繁重新整理網頁，請稍等一分鐘再試，或申請 FinMind Token 加入程式中。")
else:
    st.success(f"✅ 成功抓取到 {len(dist)} 筆籌碼數據")
    
    # 顯示原始資料片段，確認欄位名稱
    with st.expander("查看原始數據前 5 筆"):
        st.write(dist.head())

    # 執行原本的計算邏輯...
    available_dates = sorted(dist['date'].unique())
    dates = available_dates[-4:] if len(available_dates) >= 4 else available_dates
    
    st.write(f"📅 診斷日期對象: {dates}")

    # 計算大戶/散戶 (加入 HoldersLevel 字串檢查)
    big_levels = ['400-600','600-800','800-1000','1000以上']
    
    res = []
    for d in dates:
        temp = dist[dist['date'] == d]
        # 這裡多加一個 debug，看看有沒有抓到任何等級
        b_sum = temp[temp['HoldersLevel'].isin(big_levels)]['percent'].sum()
        res.append({"Date": d, "Big_Percent": b_sum})
    
    st.table(pd.DataFrame(res))

st.divider()
st.subheader("第二步：檢查股價資料")
price = safe_get_data(dl.taiwan_stock_daily, stock_id=stock_id, start_date='2024-03-01')
if not price.empty:
    st.write(f"📈 最新收盤價: {price['close'].iloc[-1]}")
else:
    st.warning("⚠️ 暫時抓不到股價資料，請檢查 API 狀態。")