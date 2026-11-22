"""
Solar PV Digital Twin - Stage 5 (Streamlit dashboard)
Same simulation as Stage 4, but the settings come from sliders on a web page.
Run it with:   streamlit run app.py
All default numbers are ILLUSTRATIVE assumptions, not measured values.
"""

import random
import pandas as pd
import streamlit as st

DAYS = 365

st.set_page_config(page_title="Solar PV Digital Twin", layout="wide")
st.title("Solar PV Digital Twin for Smart Cleaning Optimization")
st.caption("A simulation-based digital twin: it models dust buildup, rain washing "
           "and cleaning on a solar panel, and compares cleaning strategies.")

# ---------------- SIDEBAR: the user's inputs ----------------
st.sidebar.header("Panel and weather")
base_energy = st.sidebar.slider("Energy of a clean panel per day (kWh)", 5.0, 100.0, 22.0, 1.0)
dust_rate = st.sidebar.slider("Dust loss added per dry day (%)", 0.05, 1.5, 0.5, 0.05)
max_loss = st.sidebar.slider("Maximum dust loss (%)", 5.0, 50.0, 30.0, 1.0)
rain_chance = st.sidebar.slider("Chance of rain on any day", 0.0, 0.4, 0.03, 0.01)
rain_wash = st.sidebar.slider("Rain needed to wash the panel (mm)", 1.0, 20.0, 5.0, 0.5)

st.sidebar.header("Money")
price = st.sidebar.slider("Electricity price (Rs per kWh)", 1.0, 15.0, 6.0, 0.5)
cleaning_cost = st.sidebar.slider("Cost of one cleaning (Rs)", 10.0, 1000.0, 100.0, 10.0)

st.sidebar.header("Strategies")
fixed_days = st.sidebar.slider("Fixed: clean every N days", 3, 120, 30, 1)
threshold = st.sidebar.slider("Threshold: clean when loss reaches (%)", 1.0, 25.0, 10.0, 0.5)

st.sidebar.header("Accuracy")
n_years = st.sidebar.slider("Random years to average", 10, 300, 100, 10)

# ---------------- THE SIMULATION ----------------
def make_weather(seed):
    """Make one random year of rain and sunshine."""
    random.seed(seed)
    rain_list = []
    energy_list = []
    for day in range(DAYS):
        if random.random() < rain_chance:
            rain_list.append(random.uniform(1, 20))
        else:
            rain_list.append(0.0)
        energy_list.append(base_energy * random.uniform(0.85, 1.15))
    return rain_list, energy_list


def run_strategy(kind, value, rain_list, energy_list):
    """Simulate one year for one strategy."""
    soiling_loss = 0.0
    energy_lost = 0.0
    cleanings = 0
    lost_since_clean = 0.0
    history = []                      # dust loss on each day, for the chart

    for day in range(DAYS):
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


strategies = [
    ("Never clean", "never", 0),
    (f"Fixed: every {fixed_days} days", "fixed", fixed_days),
    (f"Threshold: {threshold:g}%", "threshold", threshold),
    ("Cost-aware", "cost", 0),
]

# test every strategy on many random years and add up the results
sums = {name: [0.0, 0.0, 0.0, 0.0] for name, kind, value in strategies}
wins = {name: 0 for name, kind, value in strategies}

for year in range(n_years):
    rain_list, energy_list = make_weather(year)
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

rows = []
for name, kind, value in strategies:
    s = sums[name]
    rows.append({
        "Strategy": name,
        "Avg cleanings per year": round(s[0] / n_years, 1),
        "Avg lost revenue (Rs)": round(s[1] / n_years),
        "Avg cleaning cost (Rs)": round(s[2] / n_years),
        "Avg total cost (Rs)": round(s[3] / n_years),
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

st.subheader(f"Results averaged over {n_years} random years")
st.dataframe(results, hide_index=True)

left, right = st.columns(2)
with left:
    st.subheader("Where the money goes")
    cost_chart = results.set_index("Strategy")[["Avg lost revenue (Rs)", "Avg cleaning cost (Rs)"]]
    st.bar_chart(cost_chart)
with right:
    st.subheader("Dust loss over one example year")
    rain_list, energy_list = make_weather(0)
    history_table = {}
    for name, kind, value in strategies:
        history_table[name] = run_strategy(kind, value, rain_list, energy_list)[4]
    st.line_chart(pd.DataFrame(history_table))
    st.caption("Percentage of output lost to dust on each day (day 1 to 365). "
               "Drops to zero mean the panel was cleaned or washed by rain.")

with st.expander("How this works and what to be careful about"):
    st.write(
        "Each day the model creates random weather, adds dust if it did not rain, "
        "washes the panel if enough rain fell, and lets each strategy decide whether "
        "to clean. Lost electricity is converted to rupees once, using the price you chose. "
        "Every strategy is tested on the same random weather. "
        "The cost-aware strategy cleans when the money lost to dust since the last "
        "cleaning reaches the cost of one cleaning. "
        "This tool uses no machine learning: it follows fixed rules."
    )
    st.warning("The default numbers are illustrative assumptions, not measured values, "
               "and the weather is simulated, not real. Results are only as good as these inputs.")
