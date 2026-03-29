import streamlit as st
import pandas as pd
import requests
import io
import urllib3
import yfinance as yf

# 基礎設定
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
st.set_page_config(page_title="台股籌碼終極雷達", layout="wide")
st.title("🏹 全市場：大戶增持 + 震幅過濾 + 借券回補掃描器")

# --- 核心數據抓取 ---

@st.cache_data(ttl=3600)
def fetch_tdcc_api():
    """抓取集保數據"""
    url = "https://opendata.tdcc.com.tw/getOD.ashx?id=1-5"
    try:
        res = requests.get(url, timeout=30, verify=False)
        if res.status_code == 200:
            df = pd.read_csv(io.StringIO(res.text))
            df.columns = ['date', 'stock_id', 'level', 'count', 'shares', 'percent']
            df['stock_id'] = df['stock_id'].astype(str).str.strip()
            return df[df['stock_id'].str.fullmatch(r'\d{4}')]
    except:
        return pd.DataFrame()

def get_market_data(stock_id):
    """抓取股價震幅與借券數據"""
    try:
        ticker = f"{stock_id}.TW"
        # 抓取稍長時間以確保有足夠數據計算
        data = yf.download(ticker, period="10d", progress=False)
        if data.empty:
            ticker = f"{stock_id}.TWO"
            data = yf.download(ticker, period="10d", progress=False)
        
        if not data.empty:
            # 1. 計算週震幅 (近5日)
            recent_5d = data.tail(5)
            high = recent_5d['High'].max()
            low = recent_5d['Low'].min()
            amplitude = ((high - low) / low) * 100
            
            # 2. 借券餘額趨勢 (簡化判定：近兩日成交量與股價關係或 yfinance 提供的實務指標)
            # 註：yfinance 對台股借券細節支援有限，實務上常以「股價站上均線且量縮」輔助判定
            # 此處邏輯設為：若收盤價 > 前一日，且震幅穩定，視為回補力道支撐
            is_covering = data['Close'].iloc[-1] > data['Close'].iloc[-2]
            
            return round(float(amplitude), 2), is_covering
    except:
        return None, None
    return None, None

# --- 側邊欄參數 ---

st.sidebar.header("🎛️ 策略參數控制")
uploaded_files = st.sidebar.file_uploader("上傳歷史 CSV", accept_multiple_files=True)

st.sidebar.divider()
threshold = st.sidebar.slider("大戶增持門檻 (%)", 1, 10, 3)
vol_limit = st.sidebar.slider("週震幅上限 (%)", 5, 30, 15)

# 借券回補開關
use_short_cover = st.sidebar.toggle("開啟借券回補篩選", value=False, help="開啟後，僅顯示股價表現有空方回補跡象的標的")

retail_map = {"50張以下": 8, "100張以下": 9, "200張以下": 10, "400張以下": 11}
retail_choice = st.sidebar.selectbox("散戶定義", list(retail_map.keys()))
retail_lv = retail_map[retail_choice]

# --- 執行邏輯 ---

if st.button("🚀 啟動全市場深度分析"):
    all_dfs = []
    df_online = fetch_tdcc_api()
    if not df_online.empty:
        all_dfs.append(df_online)
        st.info(f"📅 最新資料日期：{df_online['date'].iloc[0]}")
    
    if uploaded_files:
        for f in uploaded_files:
            tdf = pd.read_csv(f)
            tdf.columns = ['date', 'stock_id', 'level', 'count', 'shares', 'percent']
            tdf['stock_id'] = tdf['stock_id'].astype(str).str.strip()
            all_dfs.append(tdf)

    if len(all_dfs) < 2:
        st.error("❌ 資料不足。請上傳歷史 CSV 以對比趨勢。")
    else:
        # 籌碼矩陣運算
        combined = pd.concat(all_dfs).drop_duplicates(subset=['date', 'stock_id', 'level'])
        all_dates = sorted(combined['date'].unique(), reverse=True)
        
        def get_pivot(lv_cond):
            temp = combined[lv_cond].groupby(['stock_id', 'date'])['percent'].sum().reset_index()
            pivot = temp.pivot(index='stock_id', columns='date', values='percent')
            if (pivot > 100).any().any(): pivot = pivot / 100
            return pivot

        big_pivot = get_pivot(combined['level'] >= 11)
        small_pivot = get_pivot(combined['level'] <= retail_lv)
        t = all_dates[:2] # 比對最近兩週
        
        # 1. 籌碼初步篩選
        mask = (big_pivot[t[0]] > big_pivot[t[1]]) & (small_pivot[t[0]] < small_pivot[t[1]])
        diff = big_pivot[t[0]] - big_pivot[t[1]]
        candidates = big_pivot[mask & (diff >= threshold)].dropna().index.tolist()

        if candidates:
            st.write(f"🔍 籌碼符合標的 {len(candidates)} 檔，進行二階篩選...")
            results = []
            prog = st.progress(0)
            
            for i, sid in enumerate(candidates):
                amp, covering = get_market_data(sid)
                
                # 判斷是否符合過濾條件
                if amp is not None and amp <= vol_limit:
                    # 借券回補開關邏輯
                    if not use_short_cover or (use_short_cover and covering):
                        results.append({
                            "代號": sid,
                            "大戶趨勢": f"{big_pivot.loc[sid, t[1]]:.1f}% -> {big_pivot.loc[sid, t[0]]:.1f}%",
                            "本週增幅": f"{diff.loc[sid]:+.2f}%",
                            "週震幅": f"{amp}%",
                            "回補跡象": "✅" if covering else "--"
                        })
                prog.progress((i + 1) / len(candidates))

            if results:
                st.success(f"🎯 篩選完成！共找到 {len(results)} 檔標的")
                st.table(pd.DataFrame(results).sort_values(by="本週增幅", ascending=False))
            else:
                st.warning("符合籌碼面，但被震幅或借券回補開關過濾掉了。")
        else:
            st.info("目前無符合籌碼門檻的標的。")