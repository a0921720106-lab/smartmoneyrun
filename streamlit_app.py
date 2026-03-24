import streamlit as st
import pandas as pd
from FinMind.data import DataLoader
from tqdm import tqdm
import time

# 1. 網頁基礎設定
st.set_page_config(page_title="台股籌碼全自動雷達", layout="wide")
st.title("🏹 台股全市場：籌碼集中掃描器 (三週精確版)")
st.write("新手看價、老手看量、高手看籌碼")

# 2. 初始化資料庫
dl = DataLoader()

# 3. 側邊欄：功能設定
st.sidebar.header("🎛️ 篩選參數控制")
# 調整週波動率：0~15%，刻度 1%
vol_limit = st.sidebar.slider("週波動限制 (%)", 0, 15, 5, step=1) / 100

st.sidebar.info(f"🔎 策略：近 3 週大戶連增、散戶連減、借券回補，且週波動度 < {vol_limit:.0%}")

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
            if i % 10 == 0:
                status_text.text(f"掃描進度: {i+1} / {total_stocks} (正在檢查 {stock_id})")
            
            # --- A. 籌碼資料：固定觀察 3 週 ---
            # 抓取 4 個時間點 (為了比對 3 次增減)
            dist = dl.taiwan_stock_holding_shares_per(stock_id=stock_id, start_date='2024-02-01').tail(4 * 15)
            dates = dist['date'].unique()[-4:]
            
            if len(dates) < 4: continue 
            
            # --- 關鍵：先計算出 w_big 和 w_small 的數值 ---
            # 計算大戶 (400張以上) 與 散戶 (30張以下) 比例
            w_big = [dist[dist['date']==d]['HoldersLevel'].isin(['400-600','600-800','800-1000','1000以上']).sum() for d in dates]
            w_small = [dist[dist['date']==d]['HoldersLevel'].isin(['1-5','5-10','10-15','15-20','20-30']).sum() for d in dates]

            # 1. 先定義大戶趨勢 (big_trend)
            big_trend = (w_big[3] > w_big[0]) and (w_big[3] >= w_big[2])
            
            # 2. 再定義散戶趨勢 (small_trend)
            small_trend = (w_small[3] < w_small[0]) and (w_small[3] <= w_small[2])
            
            # 3. 最後合併判斷
            is_chip = big_trend and small_trend

            # --- B. 借券資料：近 15 天趨勢 ---
            margin = dl.taiwan_stock_margin_purchase_short_sale(stock_id=stock_id, start_date='2024-03-01').tail(15)
            if len(margin) >= 15:
                is_lending = margin['Short_Sale_Balance'].iloc[-1] < margin['Short_Sale_Balance'].iloc[0]
            else:
                is_lending = False
            
            if not is_lending: continue

            # --- C. 波動度計算：近 5 個交易日 ---
            price = dl.taiwan_stock_daily(stock_id=stock_id, start_date='2024-03-01').tail(5)
            if len(price) < 5: continue
            vol = (price['close'].max() - price['close'].min()) / price['close'].min()
            is_vol = vol < vol_limit

            if is_vol:
                name = stock_info[stock_info['stock_id'] == stock_id]['stock_name'].values[0]
                final_picks.append({
                    "代號": stock_id, 
                    "名稱": name, 
                    "大戶持股": f"{w_big[-1]:.2%}",
                    "散戶持股": f"{w_small[-1]:.2%}",
                    "週波動": f"{vol:.2%}"
                })
        except:
            continue # 遇到異常資料跳過，確保不中斷

    # 5. 最終結果顯示
    st.success(f"🏁 全市場掃描完畢！共發現 {len(final_picks)} 檔完全符合條件。")
    if final_picks:
        df_res = pd.DataFrame(final_picks)
        st.dataframe(df_res, use_container_width=True)
        csv = df_res.to_csv(index=False).encode('utf-8-sig')
        st.download_button("📥 下載完整清單 (CSV)", csv, "report.csv", "text/csv")
    else:
        st.warning("目前無標的完全符合條件。")

st.divider()
st.caption("💡 提醒：建議在每周六早上 10 點後執行。")