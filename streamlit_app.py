import streamlit as st

st.title("$$$大戶哪裡跑")
st.write(
    "Let's start building! For help and inspiration, head over to [docs.streamlit.io](https://docs.streamlit.io/)."
)
import streamlit as st
import pandas as pd
from FinMind.data import DataLoader
import time

# 1. 網頁基礎設定
st.set_page_config(page_title="台股籌碼全自動雷達", layout="wide")
st.title("🏹 台股全市場：籌碼集中掃描器 (無限制版)")
st.markdown("🔍 運作邏輯：**大戶增、散戶減、借券回補、週波動 < 5%**")

# 2. 初始化資料庫
dl = DataLoader()

# 3. 側邊欄：僅保留核心參數調整
st.sidebar.header("⚙️ 篩選參數控制")
vol_limit = st.sidebar.slider("週波動限制 (%)", 1, 10, 5) / 100
st.sidebar.info("💡 提示：掃描全台股約需 15-20 分鐘，請保持網頁開啟。")

# 4. 執行按鈕
if st.button("🚀 啟動全市場 1800+ 檔深度掃描"):
    # 抓取最新股票清單
    with st.spinner("正在初始化全市場清單..."):
        stock_info = dl.taiwan_stock_info()
        # 只取 4 位數代碼的普通股，排除權證與 ETF
        full_list = stock_info[
            (stock_info['stock_id'].str.len() == 4) & 
            (~stock_info['stock_id'].str.startswith('0'))
        ]['stock_id'].tolist()
        total_stocks = len(full_list)
        
    st.write(f"📊 偵測到全市場共 {total_stocks} 檔標的，開始掃描...")
    
    progress_bar = st.progress(0)
    status_text = st.empty()
    final_picks = []
    
    # 開始全市場遍歷
    for i, stock_id in enumerate(full_list):
        try:
            # 更新進度
            current_progress = (i + 1) / total_stocks
            progress_bar.progress(current_progress)
            if i % 10 == 0: # 每 10 檔更新一次文字，避免介面卡頓
                status_text.text(f"掃描進度: {i+1} / {total_stocks} (正在檢查 {stock_id})")
            
            # A. 籌碼資料：抓取近 4 週股權分散
            dist = dl.taiwan_stock_holding_shares_per(stock_id=stock_id, start_date='2024-02-01').tail(60)
            dates = dist['date'].unique()[-4:]
            
            if len(dates) < 4: continue # 資料不足跳過
            
            # 計算每週大戶(400+)與散戶(30-)比例
            w_big = [dist[dist['date']==d][dist['HoldersLevel'].isin(['400-600','600-800','800-1000','1000以上'])]['percent'].sum() for d in dates]
            w_small = [dist[dist['date']==d][dist['HoldersLevel'].isin(['1-5','5-10','10-15','15-20','20-30'])]['percent'].sum() for d in dates]
            
            # 判斷趨勢：大戶連三增、散戶連三減
            is_chip = all(w_big[j] > w_big[j-1] for j in range(1, 4)) and all(w_small[j] < w_small[j-1] for j in range(1, 4))
            
            if not is_chip: continue # 第一關沒過就跳過，省下後續抓資料時間

            # B. 借券資料：還券 > 賣出 (近 15 天)
            lending = dl.taiwan_stock_lending_ticket(stock_id=stock_id, start_date='2024-03-01').tail(15)
            is_lending = lending['return_quantity'].sum() > lending['sale_quantity'].sum()
            
            # C. 波動度計算：近 5 個交易日
            price = dl.taiwan_stock_daily(stock_id=stock_id, start_date='2024-03-01').tail(5)
            vol = (price['close'].max() - price['close'].min()) / price['close'].min()
            is_vol = vol < vol_limit

            if is_lending and is_vol:
                name = stock_info[stock_info['stock_id'] == stock_id]['stock_name'].values[0]
                final_picks.append({
                    "代號": stock_id, 
                    "名稱": name, 
                    "大戶持股": f"{w_big[-1]:.2%}",
                    "散戶持股": f"{w_small[-1]:.2%}",
                    "週波動": f"{vol:.2%}"
                })
        except:
            continue # 遇到異常資料直接跳過，確保程式不中斷
        
    # 5. 最終結果顯示
    st.success(f"🏁 全市場掃描完畢！共發現 {len(final_picks)} 檔完全符合條件的標的。")
    if final_picks:
        df_res = pd.DataFrame(final_picks)
        st.dataframe(df_res, use_container_width=True)
        csv = df_res.to_csv(index=False).encode('utf-8-sig')
        st.download_button("📥 下載完整清單 (CSV)", csv, "full_market_report.csv", "text/csv")
    else:
        st.warning("全市場目前無標的完全符合條件。")

st.divider()
st.caption("自動化執行提醒：建議在每周六早上 10 點後執行，確保集保中心週數據已完整更新。")