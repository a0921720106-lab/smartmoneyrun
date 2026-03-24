import streamlit as st
import pandas as pd
from FinMind.data import DataLoader
import time

# 1. 網頁基礎設定
st.set_page_config(page_title="台股籌碼全自動雷達", layout="wide")
st.title("🏹 台股全市場：籌碼集中掃描器 (三週趨勢版)")
st.write("新手看價、老手看量、高手看籌碼")

# 2. 初始化資料庫
dl = DataLoader()

# 3. 側邊欄：功能設定
st.sidebar.header("🎛️ 篩選參數控制")
# 調整週波動率：0~15%，刻度 1%
vol_input = st.sidebar.slider("週波動限制 (%)", 0, 15, 5, step=1)
vol_limit = vol_input / 100

st.sidebar.info(f"🔎 策略：近 3 週大戶增、散戶減、借券未暴增，且週震幅 < {vol_input}%")

# 4. 執行按鈕
if st.button("🚀 啟動全市場深度掃描"):
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
            
            # --- A. 籌碼資料 ---
            dist = dl.taiwan_stock_holding_shares_per(stock_id=stock_id, start_date='2024-02-01').tail(4 * 15)
            dates = dist['date'].unique()[-4:]
            
            if len(dates) < 4: continue 
            
            # 修正：必須指定 ['percent'] 欄位進行加總，否則會抓到錯誤數值
            w_big = [dist[(dist['date']==d) & (dist['HoldersLevel'].isin(['400-600','600-800','800-1000','1000以上']))]['percent'].sum() for d in dates]
            w_small = [dist[(dist['date']==d) & (dist['HoldersLevel'].isin(['1-5','5-10','10-15','15-20','20-30']))]['percent'].sum() for d in dates]

            # 趨勢邏輯：這週比3週前好，且這週比上週好 (容許中間一週小波動)
            big_trend = (w_big[3] > w_big[0]) and (w_big[3] >= w_big[2])
            small_trend = (w_small[3] < w_small[0]) and (w_small[3] <= w_small[2])
            
            if not (big_trend and small_trend): continue

            # --- B. 借券資料 ---
            # 抓取最近的信用交易資料
            margin = dl.taiwan_stock_margin_purchase_short_sale(stock_id=stock_id, start_date='2024-03-01').tail(10)
            is_lending = True 
            if len(margin) >= 2:
                # 判斷最新借券賣出餘額是否小於或等於期初 (只要沒暴增即可)
                is_lending = margin['short_sale_balance'].iloc[-1] <= margin['short_sale_balance'].iloc[0]
            
            if not is_lending: continue

            # --- C. 波動度計算 ---
            price = dl.taiwan_stock_daily(stock_id=stock_id, start_date='2024-03-01').tail(5)
            if len(price) < 5: continue
            
            # 修正：FinMind 回傳欄位為小寫 'max' 與 'min'
            vol = (price['max'].max() - price['min'].min()) / price['min'].min()
            
            if vol <= vol_limit:
                name = stock_info[stock_info['stock_id'] == stock_id]['stock_name'].values[0]
                final_picks.append({
                    "代號": stock_id, 
                    "名稱": name, 
                    "目前大戶%": f"{w_big[-1]:.2f}%",
                    "目前散戶%": f"{w_small[-1]:.2f}%",
                    "週震幅": f"{vol:.2%}"
                })
        except:
            continue 

    # 5. 最終結果顯示
    st.success(f"🏁 全市場掃描完畢！共發現 {len(final_picks)} 檔符合趨勢條件。")
    if final_picks:
        df_res = pd.DataFrame(final_picks)
        st.dataframe(df_res, use_container_width=True)
        csv = df_res.to_csv(index=False).encode('utf-8-sig')
        st.download_button("📥 下載完整清單 (CSV)", csv, "chip_report.csv", "text/csv")
    else:
        st.warning("目前無標的完全符合條件，建議可調高波動限制或在週六更新數據後再試。")

st.divider()
st.caption("📌 註：波動度計算基準為「近 5 個交易日之最高與最低價價差比例」。")