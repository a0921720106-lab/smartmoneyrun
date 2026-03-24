import streamlit as st
import pandas as pd
from FinMind.data import DataLoader

# 1. 網頁基礎設定
st.set_page_config(page_title="台股籌碼全自動雷達", layout="wide")
st.title("🏹 台股全市場：籌碼集中掃描器 (日期自動對齊版)")
st.write("自動抓取最新已結算的 4 週籌碼進行比對")

# 2. 初始化資料庫
dl = DataLoader()

# 3. 側邊欄：功能設定
st.sidebar.header("🎛️ 篩選參數控制")
vol_input = st.sidebar.slider("週波動限制 (%)", 0, 15, 8, step=1)
vol_limit = vol_input / 100

st.sidebar.info(f"🔎 策略：抓取最新已公佈之 4 週籌碼，判斷大戶增、散戶減，且週震幅 < {vol_input}%")

# 4. 執行按鈕
if st.button("🚀 啟動全市場深度掃描"):
    with st.spinner("正在初始化全市場清單..."):
        stock_info = dl.taiwan_stock_info()
        full_list = stock_info[
            (stock_info['stock_id'].str.len() == 4) & 
            (~stock_info['stock_id'].str.startswith('0'))
        ]['stock_id'].tolist()
        
    total_stocks = len(full_list)
    st.write(f"📊 偵測到全市場共 {total_stocks} 檔標的，開始掃描...")
    
    progress_bar = st.progress(0)
    status_text = st.empty()
    final_picks = []
    
    for i, stock_id in enumerate(full_list):
        try:
            current_progress = (i + 1) / total_stocks
            progress_bar.progress(current_progress)
            if i % 20 == 0:
                status_text.text(f"掃描進度: {i+1} / {total_stocks} (正在檢查 {stock_id})")
            
            # --- A. 籌碼資料：日期對齊修正 ---
            # 抓取較長區間確保有足夠結算日
            dist = dl.taiwan_stock_holding_shares_per(stock_id=stock_id, start_date='2024-01-01')
            
            # 關鍵修正：只取有資料的日期，並確保排序正確
            available_dates = sorted(dist['date'].unique())
            if len(available_dates) < 4: continue
            
            # 自動抓取「最新已出爐」的 4 個週五
            dates = available_dates[-4:] 
            
            # 計算持股百分比 (%)
            w_big = [dist[(dist['date']==d) & (dist['HoldersLevel'].isin(['400-600','600-800','800-1000','1000以上']))]['percent'].sum() for d in dates]
            w_small = [dist[(dist['date']==d) & (dist['HoldersLevel'].isin(['1-5','5-10','10-15','15-20','20-30']))]['percent'].sum() for d in dates]

            # 趨勢判斷：這週比 3 週前增，且這週比上週增 (確保最新動態向上)
            big_trend = (w_big[3] > w_big[0]) and (w_big[3] >= w_big[2])
            small_trend = (w_small[3] < w_small[0]) and (w_small[3] <= w_small[2])
            
            if not (big_trend and small_trend): continue

            # --- B. 借券資料 ---
            margin = dl.taiwan_stock_margin_purchase_short_sale(stock_id=stock_id, start_date='2024-03-01').tail(10)
            is_lending = True 
            if len(margin) >= 2:
                # 欄位修正為小寫 'short_sale_balance'
                is_lending = margin['short_sale_balance'].iloc[-1] <= margin['short_sale_balance'].iloc[0]
            
            if not is_lending: continue

            # --- C. 波動度計算 ---
            price = dl.taiwan_stock_daily(stock_id=stock_id, start_date='2024-03-01').tail(5)
            if len(price) < 5: continue
            
            # 震幅計算：(最高-最低)/最低 (使用小寫欄位名)
            vol = (price['max'].max() - price['min'].min()) / price['min'].min()
            
            if vol <= vol_limit:
                name = stock_info[stock_info['stock_id'] == stock_id]['stock_name'].values[0]
                final_picks.append({
                    "代號": stock_id, 
                    "名稱": name, 
                    "最新大戶%": f"{w_big[-1]:.2f}%",
                    "三週增減": f"{w_big[3] - w_big[0]:+.2f}%",
                    "週震幅": f"{vol:.2%}",
                    "資料日期": dates[-1]  # 顯示抓取到的最新日期供確認
                })
        except:
            continue 

    # 5. 最終結果顯示
    st.success(f"🏁 掃描完畢！發現 {len(final_picks)} 檔符合條件。")
    if final_picks:
        df_res = pd.DataFrame(final_picks)
        st.dataframe(df_res, use_container_width=True)
    else:
        st.warning("目前無標的完全符合，請嘗試調高波動限制。")