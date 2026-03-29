import streamlit as st
import pandas as pd
import requests
import io
import urllib3
import yfinance as yf

# 解決 SSL 報錯
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

st.set_page_config(page_title="台股籌碼終極雷達", layout="wide")
st.title("🏹 全市場：籌碼大增 + 股價震幅雙重篩選器")

@st.cache_data(ttl=3600)
def fetch_tdcc_api():
    url = "https://opendata.tdcc.com.tw/getOD.ashx?id=1-5"
    try:
        res = requests.get(url, timeout=30, verify=False, allow_redirects=True)
        if res.status_code == 200:
            df = pd.read_csv(io.StringIO(res.text))
            df.columns = ['date', 'stock_id', 'level', 'count', 'shares', 'percent']
            df['stock_id'] = df['stock_id'].astype(str).str.strip()
            df = df[df['stock_id'].str.fullmatch(r'\d{4}')]
            return df
    except:
        return pd.DataFrame()

def get_weekly_amplitude(stock_id):
    try:
        ticker = f"{stock_id}.TW"
        data = yf.download(ticker, period="5d", interval="1d", progress=False)
        if data.empty:
            ticker = f"{stock_id}.TWO"
            data = yf.download(ticker, period="5d", interval="1d", progress=False)
        
        if not data.empty:
            high = data['High'].max()
            low = data['Low'].min()
            amp = ((high - low) / low) * 100
            return round(float(amp), 2)
    except:
        return None
    return None

# --- 側邊欄 ---
st.sidebar.header("🎛️ 策略參數控制")
uploaded_files = st.sidebar.file_uploader("上傳歷史 CSV", accept_multiple_files=True)
threshold = st.sidebar.slider("大戶增持比例門檻 (%)", 1, 10, 3, step=1)
vol_limit = st.sidebar.slider("週震幅上限限制 (%)", 5, 30, 15, step=1)

retail_map = {"50張以下": 8, "100張以下": 9, "200張以下": 10, "400張以下": 11}
retail_choice = st.sidebar.selectbox("散戶定義", list(retail_map.keys()))
retail_lv = retail_map[retail_choice]

if st.button("🚀 啟動全市場深度分析"):
    all_dfs = []
    df_online = fetch_tdcc_api()
    if not df_online.empty:
        all_dfs.append(df_online)
    
    if uploaded_files:
        for f in uploaded_files:
            tdf = pd.read_csv(f)
            tdf.columns = ['date', 'stock_id', 'level', 'count', 'shares', 'percent']
            tdf['stock_id'] = tdf['stock_id'].astype(str).str.strip()
            tdf = tdf[tdf['stock_id'].str.fullmatch(r'\d{4}')]
            all_dfs.append(tdf)

    if len(all_dfs) < 2:
        st.error("❌ 資料週數不足，請上傳歷史 CSV。")
    else:
        full_df = pd.concat(all_dfs).drop_duplicates(subset=['date', 'stock_id', 'level'])
        full_df = full_df[full_df['level'] <= 15]
        all_dates = sorted(full_df['date'].unique(), reverse=True)
        
        def get_pivot(lv_cond):
            temp = full_df[lv_cond].groupby(['stock_id', 'date'])['percent'].sum().reset_index()
            pivot = temp.pivot(index='stock_id', columns='date', values='percent')
            if (pivot > 100).any().any():
                pivot = pivot / 100
            return pivot

        big_pivot = get_pivot(full_df['level'] >= 11)
        small_pivot = get_pivot(full_df['level'] <= retail_lv)
        t_dates = all_dates[:3] if len(all_dates) >= 3 else all_dates[:2]
        
        # 修正後的判定邏輯
        if len(all_dates) >= 3:
            mask = (big_pivot[t_dates[0]] > big_pivot[t_dates[1]]) & \
                   (big_pivot[t_dates[1]] > big_pivot[t_dates[2]]) & \
                   (small_pivot[t_dates[0]] < small_pivot[t_dates[1]]) & \
                   (small_pivot[t_dates[1]] < small_pivot[t_dates[2]])
        else:
            mask = (big_pivot[t_dates[0]] > big_pivot[t_dates[1]]) & \
                   (small_pivot[t_dates[0]] < small_pivot[t_dates[1]])

        diff = big_pivot[t_dates[0]] - big_pivot[t_dates[1]]
        candidates = big_pivot[mask & (diff >= threshold)].dropna().index.tolist()

        if candidates:
            st.write(f"🔍 籌碼符合標的共 {len(candidates)} 檔，核對震幅中...")
            final_results = []
            prog = st.progress(0)
            for i, sid in enumerate(candidates):
                amp = get_weekly_amplitude(sid)
                if amp is not None and amp <= vol_limit:
                    # 修正此處的趨勢字串格式
                    b_trend = " -> ".join([f"{big_pivot.loc[sid, d]:.1f}%" for d in reversed(t_dates)])
                    final_results.append({
                        "代號": sid,
                        "大戶持股趨勢": b_trend,
                        "週震幅": f"{amp}%",
                        "本週增幅": f"{diff.loc[sid]:+.2f}%"
                    })
                prog.progress((i + 1) / len(candidates))

            if final_results:
                st.table(pd.DataFrame(final_results).sort_values(by="本週增幅", ascending=False))
            else:
                st.info("無符合震幅限制標的。")