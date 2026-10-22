import io
import streamlit as st
import pandas as pd
import requests
import plotly.graph_objects as go
from plotly.subplots import make_subplots

st.set_page_config(page_title="Real Exchange Rate Observer", layout="wide")

COUNTRY_CODES = {
    "United States": "USA", "Euro Area": "G163", "United Kingdom": "GBR",
    "Japan": "JPN", "Switzerland": "CHE", "Canada": "CAN", "Australia": "AUS",
    "Mexico": "MEX", "Brazil": "BRA", "South Korea": "KOR", "China": "CHN",
    "India": "IND", "Argentina": "ARG", "Chile": "CHL", "Colombia": "COL",
    "Peru": "PER", "South Africa": "ZAF", "Sweden": "SWE", "Norway": "NOR",
    "Denmark": "DNK", "New Zealand": "NZL", "Singapore": "SGP", "Thailand": "THA",
    "Indonesia": "IDN", "Malaysia": "MYS", "Philippines": "PHL", "Turkey": "TUR",
    "Poland": "POL", "Hungary": "HUN", "Czechia": "CZE", "Israel": "ISR"
}

BASE_API_URL = "https://api.imf.org/external/sdmx/3.0/data/dataflow/IMF.STA"


def parse_imf_dates(s: pd.Series) -> pd.Series:
    cleaned = s.astype(str).str.replace("-M", "-", regex=False)
    return pd.to_datetime(cleaned, format="%Y-%m", errors="coerce")


@st.cache_data(ttl=86400, show_spinner=False)
def fetch_imf_series(iso3: str, indicator: str) -> pd.Series:
    dataflow = "CPI" if indicator == "CPI" else "ER"
    key = f"{iso3}.CPI._T.IX.M" if indicator == "CPI" else f"{iso3}.XDC_USD.PA_RT.M"
    url = f"{BASE_API_URL}/{dataflow}/~/{key}?c[TIME_PERIOD]=ge:1976-M01"

    # Primary: SDMX-CSV
    try:
        r = requests.get(url, headers={"Accept": "text/csv", "User-Agent": "RER-App/1.0"}, timeout=25)
        if r.status_code == 200 and "TIME_PERIOD" in r.text:
            df_raw = pd.read_csv(io.StringIO(r.text))
            if not df_raw.empty and "OBS_VALUE" in df_raw.columns:
                df_raw["Date"] = parse_imf_dates(df_raw["TIME_PERIOD"])
                df_raw["Val"] = pd.to_numeric(df_raw["OBS_VALUE"], errors="coerce")
                df_raw = df_raw.dropna(subset=["Date", "Val"]).sort_values("Date")
                s = df_raw.set_index("Date")["Val"]
                return s[~s.index.duplicated(keep="last")].resample("MS").first()
    except Exception:
        pass

    # Fallback: SDMX-JSON
    try:
        hdrs = {"Accept": "application/vnd.sdmx.data+json;version=2.0.0, application/json"}
        r = requests.get(url, headers=hdrs, timeout=25)
        r.raise_for_status()
        data = r.json().get("data", r.json())
        series_dict = data.get("dataSets", [{}])[0].get("series", {})
        if not series_dict:
            return pd.Series(dtype=float)
        obs = next(iter(series_dict.values())).get("observations", {})
        structs = data.get("structures", [data.get("structure", {})])
        dims = structs[0].get("dimensions", {}).get("observation", [])
        t_vals = next((d.get("values", []) for d in dims if d.get("id") == "TIME_PERIOD" or "values" in d), [])
        rows = [(t_vals[int(k)].get("id") or t_vals[int(k)].get("name"), float(v[0])) for k, v in obs.items() if v and v[0] is not None]
        df_j = pd.DataFrame(rows, columns=["T", "Val"])
        df_j["Date"] = parse_imf_dates(df_j["T"])
        s = df_j.dropna().sort_values("Date").set_index("Date")["Val"]
        return s[~s.index.duplicated(keep="last")].resample("MS").first()
    except Exception as e:
        st.warning(f"Could not load {indicator} for {iso3}: {e}")
        return pd.Series(dtype=float)


st.title("Real Exchange Rate (RER) Observer")
c_list = list(COUNTRY_CODES.keys())
col1, col2 = st.columns(2)
c1_name = col1.selectbox("Country 1 (Base Currency)", c_list, index=0)
c2_name = col2.selectbox("Country 2 (Target Currency)", c_list, index=1)
c1, c2 = COUNTRY_CODES[c1_name], COUNTRY_CODES[c2_name]

if c1 == c2:
    st.error("Please select two different countries.")
    st.stop()

with st.spinner("Fetching IMF data..."):
    p1, p2 = fetch_imf_series(c1, "CPI"), fetch_imf_series(c2, "CPI")
    e1 = fetch_imf_series(c1, "EXR")
    if c1 == "USA" and e1.empty:
        e1 = pd.Series(1.0, index=p1.index)
    e2 = fetch_imf_series(c2, "EXR")
    if c2 == "USA" and e2.empty:
        e2 = pd.Series(1.0, index=p2.index)

df = pd.DataFrame({"P1": p1, "P2": p2, "E1": e1, "E2": e2})
df = df[df.index >= pd.Timestamp("1976-01-01")].sort_index()
df["S_t"] = df["E2"] / df["E1"]
df["RER_t"] = df["S_t"] * (df["P1"] / df["P2"])
df_valid = df.dropna(subset=["S_t", "P1", "P2", "RER_t"]).copy()

if df_valid.empty:
    st.error("No overlapping data available for the selected pair.")
    st.stop()

st.sidebar.header("Sample Period")
months = df_valid.index.to_pydatetime().tolist()
start_m, end_m = st.sidebar.select_slider(
    "Select Start and End Month",
    options=months,
    value=(months[0], months[-1]),
    format_func=lambda d: d.strftime("%Y-%m")
)

df_sub = df_valid.loc[(df_valid.index >= pd.Timestamp(start_m)) & (df_valid.index <= pd.Timestamp(end_m))].copy()
rer_star = df_sub["RER_t"].mean()
df_sub["Real_Index"] = 100.0 * (df_sub["RER_t"] / rer_star)

view_mode = st.sidebar.radio("Chart Display:", ["Both", "Real", "Nominal"], index=0)

fig = make_subplots(specs=[[{"secondary_y": True}]])
if view_mode in ["Real", "Both"]:
    fig.add_trace(go.Scatter(x=df_sub.index, y=df_sub["Real_Index"], name="Real Index (Base=100)", line=dict(color="#1f77b4")), secondary_y=False)
    fig.update_yaxes(title_text="Real Index (RER* = 100)", secondary_y=False)

if view_mode in ["Nominal", "Both"]:
    sec = (view_mode == "Both")
    fig.add_trace(go.Scatter(x=df_sub.index, y=df_sub["S_t"], name=f"Nominal S(t) ({c2}/{c1})", line=dict(color="#ff7f0e")), secondary_y=sec)
    fig.update_yaxes(title_text=f"Nominal S(t) ({c2} per {c1})", secondary_y=sec)

fig.update_layout(title=f"{c1_name} vs {c2_name} (RER* = {rer_star:.4f})", hovermode="x unified", height=500)
st.plotly_chart(fig, use_container_width=True)

out_df = pd.DataFrame({
    "Month": df_sub.index.strftime("%Y-%m"),
    f"Nominal_S(t)_{c2}_per_{c1}": df_sub["S_t"].values,
    f"P1_CPI_{c1}": df_sub["P1"].values,
    f"P2_CPI_{c2}": df_sub["P2"].values,
    "RER(t)": df_sub["RER_t"].values,
    "RER_Star": rer_star,
    "Real_Index(t)": df_sub["Real_Index"].values
})
st.download_button("Download CSV", out_df.to_csv(index=False).encode("utf-8"), f"RER_{c1}_{c2}.csv", "text/csv")
# --- END OF FILE ---
