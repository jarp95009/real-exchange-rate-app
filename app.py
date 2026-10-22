import io
import streamlit as st
import pandas as pd
import requests
import plotly.graph_objects as go
from plotly.subplots import make_subplots

# --- Page Configuration ---
st.set_page_config(page_title="Real Exchange Rate Observer", layout="wide")

# IMF ISO3 Country Codes and Euro Area (G163)
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

BASE_SDMX3 = "https://api.imf.org/external/sdmx/3.0/data/dataflow/IMF.STA"
BASE_SDMX2 = "https://api.imf.org/external/sdmx/2.1/data/IMF.STA"


def parse_imf_dates(s: pd.Series) -> pd.Series:
    """Converts IMF monthly strings (e.g., '1976-M01' or '1976-01') to Timestamps."""
    cleaned = s.astype(str).str.strip().str.replace("-M", "-", regex=False)
    return pd.to_datetime(cleaned, errors="coerce")


@st.cache_data(ttl=86400, show_spinner=False)
def fetch_imf_series(iso3: str, indicator: str) -> pd.Series:
    """
    Retrieves monthly CPI or Exchange Rate series from the IMF SDMX 3.0 API from Jan 1976.
    Handles standard CPI, Euro Area HICP, and local-currency-per-USD rates.
    """
    # USA exchange rate is 1.0 USD per USD by definition
    if indicator == "EXR" and iso3 == "USA":
        idx = pd.date_range("1976-01-01", pd.Timestamp.today().strftime("%Y-%m-01"), freq="MS")
        return pd.Series(1.0, index=idx)

    if indicator == "CPI":
        dataflows = ["CPI", "IFS"]
        # Try exact prompt key first, then HICP fallback for Euro Area (G163)
        keys_to_try = [
            f"{iso3}.CPI._T.IX.M",
            f"{iso3}.HICP._T.IX.M",
            f"{iso3}.CPI+HICP._T.IX.M",
            f"{iso3}.._T.IX.M"
        ]
    else:
        dataflows = ["ER", "EXR", "IFS"]
        keys_to_try = [f"{iso3}.XDC_USD.PA_RT.M"]

    for df_name in dataflows:
        for key in keys_to_try:
            urls = [
                f"{BASE_SDMX3}/{df_name}/~/{key}?c[TIME_PERIOD]=ge:1976-M01",
                f"{BASE_SDMX3}/{df_name}/+/{key}?c[TIME_PERIOD]=ge:1976-M01",
                f"{BASE_SDMX2},{df_name}/{key}?startPeriod=1976-01"
            ]
            for url in urls:
                # 1. Primary attempt: SDMX-CSV
                try:
                    r = requests.get(
                        url,
                        headers={"Accept": "text/csv", "User-Agent": "RER-App/1.0"},
                        timeout=20
                    )
                    if r.status_code == 200 and "TIME_PERIOD" in r.text and "OBS_VALUE" in r.text:
                        df_raw = pd.read_csv(io.StringIO(r.text), low_memory=False)
                        if not df_raw.empty:
                            df_raw["Date"] = parse_imf_dates(df_raw["TIME_PERIOD"])
                            df_raw["Val"] = pd.to_numeric(df_raw["OBS_VALUE"], errors="coerce")
                            df_raw = df_raw.dropna(subset=["Date", "Val"]).sort_values("Date")
                            if not df_raw.empty:
                                s = df_raw.set_index("Date")["Val"]
                                return s[~s.index.duplicated(keep="last")].resample("MS").first()
                except Exception:
                    pass

                # 2. Fallback attempt: SDMX-JSON
                try:
                    hdrs = {
                        "Accept": "application/vnd.sdmx.data+json;version=2.0.0, application/json",
                        "User-Agent": "RER-App/1.0"
                    }
                    r = requests.get(url, headers=hdrs, timeout=20)
                    if r.status_code == 200:
                        payload = r.json()
                        data = payload.get("data", payload)
                        datasets = data.get("dataSets", [])
                        if datasets and datasets[0].get("series"):
                            series_dict = datasets[0]["series"]
                            obs = next(iter(series_dict.values())).get("observations", {})
                            structs = data.get("structures", [data.get("structure", {})])
                            dims = structs[0].get("dimensions", {}).get("observation", [])
                            t_vals = next(
                                (d.get("values", []) for d in dims if d.get("id") == "TIME_PERIOD" or "values" in d),
                                []
                            )
                            rows = []
                            for k, v in obs.items():
                                idx = int(k)
                                if idx < len(t_vals) and v and v[0] is not None:
                                    t_str = t_vals[idx].get("id") or t_vals[idx].get("name")
                                    rows.append((t_str, float(v[0])))
                            if rows:
                                df_j = pd.DataFrame(rows, columns=["T", "Val"])
                                df_j["Date"] = parse_imf_dates(df_j["T"])
                                df_j = df_j.dropna(subset=["Date", "Val"]).sort_values("Date")
                                if not df_j.empty:
                                    s = df_j.set_index("Date")["Val"]
                                    return s[~s.index.duplicated(keep="last")].resample("MS").first()
                except Exception:
                    pass

    return pd.Series(dtype=float)


# --- User Interface ---
st.title("Real Exchange Rate (RER) Observer")
c_list = list(COUNTRY_CODES.keys())

col1, col2 = st.columns(2)
c1_name = col1.selectbox("Country 1 (Base Currency)", c_list, index=0)
c2_name = col2.selectbox("Country 2 (Target Currency)", c_list, index=1)
c1, c2 = COUNTRY_CODES[c1_name], COUNTRY_CODES[c2_name]

if c1 == c2:
    st.error("Please select two different countries.")
    st.stop()

with st.spinner(f"Fetching monthly IMF data for {c1_name} and {c2_name}..."):
    p1 = fetch_imf_series(c1, "CPI")
    p2 = fetch_imf_series(c2, "CPI")
    e1 = fetch_imf_series(c1, "EXR")
    e2 = fetch_imf_series(c2, "EXR")

# Explicit diagnostic reporting if any series fails
missing = []
if p1.empty: missing.append(f"CPI for {c1_name} ({c1})")
if p2.empty: missing.append(f"CPI for {c2_name} ({c2})")
if e1.empty: missing.append(f"Exchange Rate for {c1_name} ({c1})")
if e2.empty: missing.append(f"Exchange Rate for {c2_name} ({c2})")

if missing:
    st.error("Could not retrieve from IMF API: " + ", ".join(missing))
    st.stop()

# Align monthly observations from January 1976 onward
df = pd.DataFrame({"P1": p1, "P2": p2, "E1": e1, "E2": e2})
df = df[df.index >= pd.Timestamp("1976-01-01")].sort_index()

# Nominal S(t): units of Country 2 currency per 1 unit of Country 1 currency
df["S_t"] = df["E2"] / df["E1"]

# Real Exchange Rate: RER(t) = S(t) * P1(t) / P2(t)
df["RER_t"] = df["S_t"] * (df["P1"] / df["P2"])

df_valid = df.dropna(subset=["S_t", "P1", "P2", "RER_t"]).copy()

if df_valid.empty:
    st.error("No overlapping valid months available for the selected pair.")
    st.stop()

# --- Sample Period & Chart Controls ---
st.sidebar.header("Sample Period")
months = df_valid.index.to_pydatetime().tolist()
start_m, end_m = st.sidebar.select_slider(
    "Select Start and End Month",
    options=months,
    value=(months[0], months[-1]),
    format_func=lambda d: d.strftime("%Y-%m")
)

# Filter to selected sample period and recalculate RER* and Real Index(t)
df_sub = df_valid.loc[(df_valid.index >= pd.Timestamp(start_m)) & (df_valid.index <= pd.Timestamp(end_m))].copy()
rer_star = df_sub["RER_t"].mean()
df_sub["Real_Index"] = 100.0 * (df_sub["RER_t"] / rer_star)

view_mode = st.sidebar.radio("Select Chart Series:", ["Both", "Real", "Nominal"], index=0)

# --- Interactive Chart ---
fig = make_subplots(specs=[[{"secondary_y": True}]])

if view_mode in ["Real", "Both"]:
    fig.add_trace(
        go.Scatter(
            x=df_sub.index,
            y=df_sub["Real_Index"],
            name="Real Index (100 × RER(t) / RER*)",
            line=dict(color="#1f77b4", width=2.5)
        ),
        secondary_y=False
    )
    fig.update_yaxes(title_text="Real Index (RER* = 100)", secondary_y=False)

if view_mode in ["Nominal", "Both"]:
    sec = (view_mode == "Both")
    fig.add_trace(
        go.Scatter(
            x=df_sub.index,
            y=df_sub["S_t"],
            name=f"Nominal S(t) ({c2}/{c1})",
            line=dict(color="#ff7f0e", width=2.5)
        ),
        secondary_y=sec
    )
    fig.update_yaxes(title_text=f"Nominal S(t) ({c2} per 1 {c1})", secondary_y=sec)

fig.update_layout(
    title=f"{c1_name} ({c1}) vs. {c2_name} ({c2}) — RER* = {rer_star:.4f}",
    xaxis_title="Month",
    hovermode="x unified",
    height=500,
    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
)
st.plotly_chart(fig, use_container_width=True)

# --- Data Preview & CSV Download ---
out_df = pd.DataFrame({
    "Month": df_sub.index.strftime("%Y-%m"),
    f"EXR_{c1}_per_USD": df_sub["E1"].values,
    f"EXR_{c2}_per_USD": df_sub["E2"].values,
    f"Nominal_S(t)_{c2}_per_{c1}": df_sub["S_t"].values,
    f"P1(t)_CPI_{c1}": df_sub["P1"].values,
    f"P2(t)_CPI_{c2}": df_sub["P2"].values,
    "RER(t)": df_sub["RER_t"].values,
    "RER_Star": rer_star,
    "Real_Index(t)": df_sub["Real_Index"].values
})

st.dataframe(out_df, use_container_width=True, height=260)
st.download_button(
    label="Download Sample Observations & Calculations (CSV)",
    data=out_df.to_csv(index=False).encode("utf-8"),
    file_name=f"RER_{c1}_{c2}_{start_m.strftime('%Y%m')}_{end_m.strftime('%Y%m')}.csv",
    mime="text/csv"
)
# --- END OF FILE ---
