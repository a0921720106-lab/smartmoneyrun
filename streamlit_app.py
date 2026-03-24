import streamlit as st
import pandas as pd
from FinMind.data import DataLoader

# 1. 網頁基礎設定
st.set_page_config(page_title="台股籌碼全自動雷達", layout="wide")
st.title("🏹 台股全市場：籌碼集中掃描器 (進階開關版)")
st.write("自動抓取最新已結算之 4 週籌碼數據進行比對")

# 2. 初始化資料庫
dl = DataLoader()

# 3. 側邊欄：功能設定
st.sidebar.header("🎛️ 篩選參數控制")

# 波動率設定
vol_input = st.sidebar.slider("週波動限制 (%)", 0, 30, 15, step=1)
vol_limit = vol_input / 100

# 借券開關
use_lending = st.sidebar.checkbox("開啟借券回補篩選 (最新 < 10天前)", value=False)

st.sidebar.info(f"🔎 策略：大戶增、散戶減，週震幅 < {vol_input}%" + (" + 借券回補" if use_lending else ""))

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
            if i % 25 == 0:
                status_text.text(f"掃描進度: {i+1} / {total_stocks} (正在檢查 {stock_id})")
            
            # --- A. 籌碼資料：日期對齊與空值剔除 ---
            dist = dl.taiwan_stock_holding_shares_per(stock_id=stock_id, start_date='2024-01-01')
            
            # 確保抓到的是有資料的日期，並由舊到新排序
            available_dates = sorted(dist['date'].unique())
            if len(available_dates) < 4: continue
            
            # 自動抓取最新已結算的 4 個週五
            dates = available_dates[-4:] 
            
            # 計算大戶(400+)與散戶(30-)持股%
            w_big = [dist[(dist['date']==d) & (dist['HoldersLevel'].isin(['400-600','600-800','800-1000','1000以上']))]['percent'].sum() for d in dates]
            w_small = [dist[(dist['date']==d) & (dist['HoldersLevel'].isin(['1-5','5-10','10-15','15-20','20-30']))]['percent'].sum() for d in dates]

            # 趨勢：本週比三週前增，且本週不輸上週
            big_trend = (w_big[3] > w_big[0]) and (w_big[3] >= w_big[2])
            small_trend = (w_small[3] < w_small[0]) and (w_small[3] <= w_small[2])
            
            if not (big_trend and small_trend): continue

            # --- B. 借券資料 (開關控制) ---
            is_lending = True 
            if use_lending:
                margin = dl.taiwan_stock_margin_purchase_short_sale(stock_id=stock_id, start_date='2024-03-01').tail(10)
                if len(margin) >= 2:
                    is_lending = margin['short_sale_balance'].iloc[-1] < margin['short_sale_balance'].iloc[0]
                else:
                    is_lending = False
            
            if not is_lending: continue

            # --- C. 波動度計算 ---
            price = dl.taiwan_stock_daily(stock_id=stock_id, start_date='2024-03-01').tail(5)
            if len(price) < 5: continue
            
            vol = (price['max'].max() - price['min'].min()) / price['min'].min()
            
            if vol <= vol_limit:
                name = stock_info[stock_info['stock_id'] == stock_id]['stock_name'].values[0]
                final_picks.append({
                    "代號": stock_id, 
                    "名稱": name, 
                    "大戶比例%": round(w_big[-1], 2),
                    "大戶增減%": round(w_big[3] - w_big[0], 2),
                    "散戶比例%": round(w_small[-1], 2),
                    "週震幅": f"{vol:.2%}",
                    "資料日期": dates[-1]
                })
        except:
            continue 

    # 5. 結果顯示與排序
    st.success(f"🏁 掃描完畢！共發現 {len(final_picks)} 檔符合條件。")
    if final_picks:
        df_res = pd.DataFrame(final_picks)
        # 依大戶增減幅度排序
        df_res = df_res.sort_values(by="大戶增減%", ascending=False)
        st.dataframe(df_res, use_container_width=True)
        
        csv = df_res.to_csv(index=False).encode('utf-8-sig')
        st.download_button("📥 下載清單 (CSV)", csv, "report.csv", "text/csv")
    else:
        st.warning("目前無標的完全符合。建議先關閉「借券篩選」或調高「週波動限制」再試一次。")

st.divider()
st.caption("💡 技巧：週一至週五掃描會自動對準上週五資料；週六、日掃描則對準當週五。")