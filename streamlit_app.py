import streamlit as st
import pandas as pd
import requests
import urllib3
import yfinance as yf

# 關閉不安全的請求警告
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
st.set_page_config(page_title="台股籌碼終極雷達", layout="wide")
st.title("🏹 全市場：大戶增 + 散戶減 + 週借券掃描")

# --- 側邊欄：使用 session_state 徹底解決 Pylance 報錯 ---

st.sidebar.header("🎛️ 策略參數控制")
# 透過 key 註冊進 session_state，避開變數未定義的問題
st.sidebar.toggle("開啟週借券回補篩選 (鎖定集保日)", value=False, key="toggle_short_cover")
uploaded_files = st.sidebar.file_uploader("上傳歷史集保 CSV (至少兩份)", accept_multiple_files=True)

st.sidebar.divider()
threshold = st.sidebar.slider("大戶增持門檻 (%)", 0.5, 10.0, 1.0, 0.5)
vol_limit = st.sidebar.slider("週震幅上限 (%)", 5, 50, 30)

retail_map = {"50張以下": 8, "100張以下": 9, "200張以下": 10, "400張以下": 11}
retail_choice = st.sidebar.selectbox("散戶定義", list(retail_map.keys()))
retail_lv = retail_map[retail_choice]

# --- 核心邏輯 ---

def get_weekly_short_covering(stock_id, date_new, date_old):
    """抓取證交所週借券餘額消長"""
    try:
        def fetch_bal(target_date):
            fmt_date = str(target_date).replace('-', '').replace('/', '')
            url = f"https://www.twse.com.tw/exchangeReport/TWTASU?response=json&date={fmt_date}&stockNo={stock_id}"
            headers = {'User-Agent': 'Mozilla/5.0'}
            res = requests.get(url, timeout=5, verify=False, headers=headers)
            data = res.json()
            if data.get('data'):
                return int(data['data'][-1][11].replace(',', ''))
            return None

        bal_new = fetch_bal(date_new)
        bal_old = fetch_bal(date_old)
        if bal_new is not None and bal_old is not None:
            return bal_new < bal_old
    except Exception:
        return False
    return False

# --- 啟動掃描 ---

if st.button("🚀 啟動全市場深度分析"):
    if not uploaded_files or len(uploaded_files) < 2:
        st.error("❌ 請上傳至少兩份不同日期的集保 CSV (例如這週與上週)。")
    else:
        all_dfs = []
        for f in uploaded_files:
            try:
                tdf = pd.read_csv(f)
                tdf.columns = ['date', 'stock_id', 'level', 'count', 'shares', 'percent']
                # 強化代碼清理，確保都是 4 碼以上的乾淨字串
                tdf['stock_id'] = tdf['stock_id'].astype(str).str.replace(r'\.0$', '', regex=True).str.strip().str.zfill(4)
                all_dfs.append(tdf)
            except:
                pass
        
        full_df = pd.concat(all_dfs).drop_duplicates(subset=['date', 'stock_id', 'level'])
        all_dates = sorted(full_df['date'].unique(), reverse=True)
        t_new = all_dates[0]
        t_old = all_dates[1]
        
        st.info(f"📊 正在對比：{t_old} ➡️ {t_new}")

        def get_pivot(lv_cond):
            temp = full_df[lv_cond].groupby(['stock_id', 'date'])['percent'].sum().reset_index()
            pivot = temp.pivot(index='stock_id', columns='date', values='percent')
            if (pivot > 100).any().any(): 
                pivot = pivot / 100
            return pivot

        big_pivot = get_pivot(full_df['level'] >= 11)
        small_pivot = get_pivot(full_df['level'] <= retail_lv)
        
        # 💡 核心修正：將資料結合成單一 DataFrame 並丟棄缺失值，避免索引不對齊導致漏篩
        summary = pd.DataFrame({
            'big_new': big_pivot[t_new],
            'big_old': big_pivot[t_old],
            'small_new': small_pivot[t_new],
            'small_old': small_pivot[t_old]
        }).dropna()
        
        summary['diff'] = summary['big_new'] - summary['big_old']
        
        # 籌碼大戶增 + 散戶減
        mask = (summary['big_new'] > summary['big_old']) & \
               (summary['small_new'] < summary['small_old']) & \
               (summary['diff'] >= threshold)
               
        candidates = summary[mask].index.tolist()

        if candidates:
            st.write(f"🔍 籌碼面初步符合 {len(candidates)} 檔，核對技術面與借券...")
            results = []
            prog = st.progress(0)
            
            # 從 session_state 取出開關狀態
            check_short_cover = st.session_state.toggle_short_cover
            
            for i, sid in enumerate(candidates):
                amp = None
                try:
                    ticker = f"{sid}.TW"
                    data = yf.download(ticker, period="10d", progress=False)
                    if data.empty: data = yf.download(f"{sid}.TWO", period="10d", progress=False)
                    if not data.empty:
                        recent = data.tail(5)
                        high = float(recent['High'].max())
                        low = float(recent['Low'].min())
                        amp = round(((high - low) / low) * 100, 2)
                except:
                    pass
                
                if amp is not None and amp <= vol_limit:
                    is_covering = False
                    can_pass = True
                    
                    if check_short_cover:
                        is_covering = get_weekly_short_covering(sid, str(t_new), str(t_old))
                        can_pass = is_covering
                        
                    if can_pass:
                        results.append({
                            "代號": sid,
                            "大戶(新)": f"{summary.loc[sid, 'big_new']:.2f}%",
                            "大戶增幅": f"{summary.loc[sid, 'diff']:+.2f}%",
                            "週震幅": f"{amp}%",
                            "週借券回補": "✅" if is_covering else "--"
                        })
                prog.progress((i + 1) / len(candidates))

            if results:
                st.success(f"🎯 篩選成功，共有 {len(results)} 檔符合條件！")
                st.table(pd.DataFrame(results).sort_values(by="大戶增幅", ascending=False))
            else:
                st.warning("符合籌碼增持，但被週震幅或借券回補條件過濾掉。")
        else:
            st.info("目前的參數與資料下，無符合大戶增持且散戶退出的標的 。")