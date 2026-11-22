"""
Solar PV Digital Twin - Stage 6 (Streamlit dashboard, real-weather option)
Same simulation as app.py, but the weather can now come from:
  1. Simulated weather (random, based on assumptions)   <- default
  2. Real daily weather from NASA POWER (free, no key)
If the real data cannot be fetched, the app falls back to simulated weather.
Run it with:   streamlit run app.py   (or app_v2.py)
All default numbers are ILLUSTRATIVE assumptions, not measured values.
"""

import json
import random
import urllib.request

import pandas as pd
import streamlit as st

st.set_page_config(page_title="Solar PV Digital Twin", layout="wide")
st.title("Solar PV Digital Twin for Smart Cleaning Optimization")
st.caption("A simulation-based digital twin: it models dust buildup, rain washing "
           "and cleaning on a solar panel, and compares cleaning strategies.")

# ---------------- SIDEBAR: the user's inputs ----------------
st.sidebar.header("Weather source")
source = st.sidebar.radio("Where should the weather come from?",
                          ["Simulated (assumptions)", "Real data (NASA POWER)"])
use_real = source == "Real data (NASA POWER)"

# default values, used when the simulated weather is needed
base_energy = 22.0
rain_chance = 0.03

if use_real:
    PLACES = {
        "Bengaluru": (12.97, 77.59),
        "Chennai": (13.08, 80.27),
        "Mumbai": (19.08, 72.88),
        "Delhi": (28.61, 77.21),
        "Jaisalmer (dry, dusty)": (26.92, 70.90),
        "Custom location": None,
    }
    place = st.sidebar.selectbox("Location", list(PLACES.keys()))
    if PLACES[place] is None:
        lat = st.sidebar.number_input("Latitude", value=12.97, min_value=-90.0, max_value=90.0)
        lon = st.sidebar.number_input("Longitude", value=77.59, min_value=-180.0, max_value=180.0)
    else:
        lat, lon = PLACES[place]
    year_range = st.sidebar.slider("Years of real weather to use", 2015, 2025, (2020, 2025), 1)
    system_kw = st.sidebar.slider("Panel system size (kW)", 1.0, 100.0, 5.0, 1.0)
    perf_ratio = st.sidebar.slider("System efficiency factor (without dust)", 0.60, 0.90, 0.75, 0.01)
else:
    st.sidebar.header("Panel and weather")
    base_energy = st.sidebar.slider("Energy of a clean panel per day (kWh)", 5.0, 100.0, 22.0, 1.0)
    rain_chance = st.sidebar.slider("Chance of rain on any day", 0.0, 0.4, 0.03, 0.01)
    n_years = st.sidebar.slider("Random years to average", 10, 300, 100, 10)

st.sidebar.header("Dust and rain")
dust_rate = st.sidebar.slider("Dust loss added per dry day (%)", 0.05, 1.5, 0.5, 0.05)
max_loss = st.sidebar.slider("Maximum dust loss (%)", 5.0, 50.0, 30.0, 1.0)
rain_wash = st.sidebar.slider("Rain needed to wash the panel (mm)", 1.0, 20.0, 5.0, 0.5)

st.sidebar.header("Money")
price = st.sidebar.slider("Electricity price (Rs per kWh)", 1.0, 15.0, 6.0, 0.5)
cleaning_cost = st.sidebar.slider("Cost of one cleaning (Rs)", 10.0, 1000.0, 100.0, 10.0)

st.sidebar.header("Strategies")
fixed_days = st.sidebar.slider("Fixed: clean every N days", 3, 120, 30, 1)
threshold = st.sidebar.slider("Threshold: clean when loss reaches (%)", 1.0, 25.0, 10.0, 0.5)


# ---------------- WEATHER: simulated ----------------
def make_weather(seed):
    """One random year of rain (mm) and clean-panel energy (kWh)."""
    random.seed(seed)
    rain_list = []
    energy_list = []
    for day in range(365):
        if random.random() < rain_chance:
            rain_list.append(random.uniform(1, 20))
        else:
            rain_list.append(0.0)
        energy_list.append(base_energy * random.uniform(0.85, 1.15))
    return rain_list, energy_list


# ---------------- WEATHER: real (NASA POWER) ----------------
@st.cache_data(show_spinner=False, ttl=86400)
def fetch_nasa(lat, lon, start_year, end_year):
    """Ask NASA POWER for daily sunshine and rain. Returns plain lists."""
    url = ("https://power.larc.nasa.gov/api/temporal/daily/point"
           f"?start={start_year}0101&end={end_year}1231"
           f"&latitude={lat}&longitude={lon}"
           "&community=re&parameters=ALLSKY_SFC_SW_DWN,PRECTOTCORR&format=json")
    with urllib.request.urlopen(url, timeout=30) as response:
        data = json.loads(response.read().decode("utf-8"))
    values = data["properties"]["parameter"]
    sun = values["ALLSKY_SFC_SW_DWN"]
    rain = values["PRECTOTCORR"]
    dates = sorted(sun.keys())
    return dates, [sun[d] for d in dates], [rain.get(d, -999) for d in dates]


def load_real_years(lat, lon, start_year, end_year):
    """Turn the NASA data into a list of (label, rain_list, energy_list), one per year."""
    dates, sun, rain = fetch_nasa(lat, lon, start_year, end_year)

    good_sun = [s for s in sun if s > -900]
    if not good_sun:
        raise ValueError("no sunshine data returned")
    sun_average = sum(good_sun) / len(good_sun)
    sun = [s if s > -900 else sun_average for s in sun]     # fill gaps (-999 = missing)
    rain = [r if r > -900 else 0.0 for r in rain]
    if max(sun) > 15:                                        # looks like MJ/m2, convert to kWh/m2
        sun = [s / 3.6 for s in sun]

    years = []
    for year in range(start_year, end_year + 1):
        idx = [i for i, d in enumerate(dates) if d.startswith(str(year))]
        if len(idx) < 300:                                   # skip incomplete years
            continue
        rain_list = [rain[i] for i in idx]
        # sun is in kWh per m2 per day (= "peak sun hours")
        energy_list = [system_kw * sun[i] * perf_ratio for i in idx]
        years.append((str(year), rain_list, energy_list))
    if not years:
        raise ValueError("no complete years returned")
    return years


# ---------------- THE SIMULATION ----------------
def run_strategy(kind, value, rain_list, energy_list):
    """Simulate one year for one strategy."""
    soiling_loss = 0.0
    energy_lost = 0.0
    cleanings = 0
    lost_since_clean = 0.0
    history = []

    for day in range(len(rain_list)):
        if rain_list[day] >= rain_wash:
            soiling_loss = 0.0
            lost_since_clean = 0.0
        else:
            soiling_loss = min(soiling_loss + dust_rate, max_loss)

        clean_today = False
        if kind == "fixed" and (day + 1) % value == 0:
            clean_today = True
        elif kind == "threshold" and soiling_loss >= value:
            clean_today = True
        elif kind == "cost" and lost_since_clean >= cleaning_cost:
            clean_today = True

        if clean_today:
            soiling_loss = 0.0
            lost_since_clean = 0.0
            cleanings += 1

        lost_today = energy_list[day] * soiling_loss / 100
        energy_lost += lost_today
        lost_since_clean += lost_today * price
        history.append(soiling_loss)

    lost_rs = energy_lost * price
    clean_rs = cleanings * cleaning_cost
    return cleanings, lost_rs, clean_rs, lost_rs + clean_rs, history


# ---------------- CHOOSE THE WEATHER ----------------
weather_years = None
if use_real:
    try:
        weather_years = load_real_years(lat, lon, year_range[0], year_range[1])
        st.info(f"Using real daily weather from NASA POWER for {place} "
                f"({lat:.2f}, {lon:.2f}), years {weather_years[0][0]} to {weather_years[-1][0]}. "
                "This is satellite and model data on a grid of roughly 55 km, "
                "not a rain gauge at the exact spot.")
    except Exception:
        st.warning("Could not get real weather from NASA POWER right now "
                   "(no internet or the service is busy). "
                   "Showing SIMULATED weather instead.")
        weather_years = None

if weather_years is None:
    simulated_count = 100 if use_real else n_years
    weather_years = [(f"Random year {i + 1}", *make_weather(i)) for i in range(simulated_count)]
    weather_label = f"{len(weather_years)} random simulated years"
else:
    weather_label = f"{len(weather_years)} real years"

strategies = [
    ("Never clean", "never", 0),
    (f"Fixed: every {fixed_days} days", "fixed", fixed_days),
    (f"Threshold: {threshold:g}%", "threshold", threshold),
    ("Cost-aware", "cost", 0),
]

# test every strategy on every year and add up the results
sums = {name: [0.0, 0.0, 0.0, 0.0] for name, kind, value in strategies}
wins = {name: 0 for name, kind, value in strategies}

for label, rain_list, energy_list in weather_years:
    totals_this_year = {}
    for name, kind, value in strategies:
        cleanings, lost_rs, clean_rs, total, history = run_strategy(
            kind, value, rain_list, energy_list)
        sums[name][0] += cleanings
        sums[name][1] += lost_rs
        sums[name][2] += clean_rs
        sums[name][3] += total
        totals_this_year[name] = total
    wins[min(totals_this_year, key=totals_this_year.get)] += 1

n = len(weather_years)
rows = []
for name, kind, value in strategies:
    s = sums[name]
    rows.append({
        "Strategy": name,
        "Avg cleanings per year": round(s[0] / n, 1),
        "Avg lost revenue (Rs)": round(s[1] / n),
        "Avg cleaning cost (Rs)": round(s[2] / n),
        "Avg total cost (Rs)": round(s[3] / n),
        "Years it was cheapest": wins[name],
    })
results = pd.DataFrame(rows)

# ---------------- THE PAGE ----------------
best_row = results.loc[results["Avg total cost (Rs)"].idxmin()]
never_cost = results.loc[results["Strategy"] == "Never clean", "Avg total cost (Rs)"].iloc[0]

c1, c2, c3 = st.columns(3)
c1.metric("Lowest average total cost", best_row["Strategy"])
c2.metric("Its average yearly cost", f"Rs {int(best_row['Avg total cost (Rs)'])}")
c3.metric("Saving compared with never cleaning",
          f"Rs {int(never_cost - best_row['Avg total cost (Rs)'])}")

st.subheader(f"Results averaged over {weather_label}")
st.dataframe(results, hide_index=True)

left, right = st.columns(2)
with left:
    st.subheader("Where the money goes")
    cost_chart = results.set_index("Strategy")[["Avg lost revenue (Rs)", "Avg cleaning cost (Rs)"]]
    st.bar_chart(cost_chart)
with right:
    example_label, rain_list, energy_list = weather_years[0]
    st.subheader(f"Dust loss over one example year ({example_label})")
    history_table = {}
    for name, kind, value in strategies:
        history_table[name] = run_strategy(kind, value, rain_list, energy_list)[4]
    st.line_chart(pd.DataFrame(history_table))
    st.caption("Percentage of output lost to dust on each day. "
               "Drops to zero mean the panel was cleaned or washed by rain.")

with st.expander("How this works and what to be careful about"):
    st.write(
        "Each day the model adds dust if it did not rain, washes the panel if enough "
        "rain fell, and lets each strategy decide whether to clean. Lost electricity is "
        "converted to rupees once, using the price you chose. Every strategy is tested on "
        "the same weather. The cost-aware strategy cleans when the money lost to dust "
        "since the last cleaning reaches the cost of one cleaning. "
        "This tool uses no machine learning: it follows fixed rules. "
        "With real data, daily energy = system size x sunshine x efficiency factor."
    )
    st.warning("The dust rate, the rain needed to wash the panel, the efficiency factor "
               "and the prices are assumptions, not measured values. "
               "Real weather improves the weather part only.")
