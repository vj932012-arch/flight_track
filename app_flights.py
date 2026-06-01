import streamlit as st
import pandas as pd
import sqlite3
import plotly.express as px
from datetime import datetime, timedelta
import random
import os

DB_NAME = 'flight_tracker.db'

# ==========================================
# 1. DATABASE & MOCK DATA SETUP
# ==========================================
def init_db():
    """Initializes the database and populates it with sample data if empty."""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS flights (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp DATETIME,
            airline TEXT,
            destination TEXT,
            source TEXT,
            price REAL,
            checked_bags INTEGER,
            stops INTEGER
        )
    ''')
    
    # Check if table is empty
    c.execute('SELECT COUNT(*) FROM flights')
    if c.fetchone()[0] == 0:
        _generate_mock_data(conn)
        
    conn.commit()
    return conn

def _generate_mock_data(conn):
    """Generates 48 hours of mock data running at 30-min intervals."""
    airlines = ['Etihad Airways', 'Air India', 'Qatar Airways', 'Emirates', 'British Airways', 'Delta']
    destinations = ['ATL', 'MIA', 'MCO', 'JAX']
    sources = ['Google Flights', 'Skyscanner', 'Momondo', 'Cheapflights']
    
    now = datetime.now()
    c = conn.cursor()
    
    for i in range(96): # 48 hours * 2 (every 30 mins)
        timestamp = now - timedelta(minutes=30 * (96 - i))
        for dest in destinations:
            for source in sources:
                price = random.uniform(950, 1500) if dest != 'JAX' else random.uniform(1300, 1800)
                price = price + random.uniform(-20, 20) # slight price drift
                bags = random.choice([0, 1, 2, 2]) # Weight towards 2 bags
                stops = random.choice([1, 2])
                airline = random.choice(airlines)
                
                c.execute('''
                    INSERT INTO flights (timestamp, airline, destination, source, price, checked_bags, stops)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                ''', (timestamp.strftime('%Y-%m-%d %H:%M:%S'), airline, dest, source, round(price, 2), bags, stops))

# ==========================================
# 2. DATA LOADING & FILTERING
# ==========================================
@st.cache_data(ttl=300) # Cache data for 5 minutes
def load_data():
    conn = sqlite3.connect(DB_NAME)
    df = pd.read_sql_query("SELECT * FROM flights", conn)
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    conn.close()
    return df

# ==========================================
# 3. STREAMLIT UI BUILDER
# ==========================================
st.set_page_config(page_title="Flight Price Tracker", page_icon="✈️", layout="wide")

# Initialize DB and Load Data
init_db()
raw_df = load_data()

st.title("✈️ BLR to US Southeast Price Tracker")
st.markdown("Monitoring routes to ATL, MIA, MCO, and JAX for **Aug 2026** departures.")

# Sidebar Filters
st.sidebar.header("Filter Options")
selected_dests = st.sidebar.multiselect(
    "Destinations", 
    options=raw_df['destination'].unique(),
    default=raw_df['destination'].unique()
)

selected_sources = st.sidebar.multiselect(
    "Data Source (Aggregator)", 
    options=raw_df['source'].unique(),
    default=raw_df['source'].unique()
)

require_two_bags = st.sidebar.checkbox("🎒 Show 2+ Checked Bags Only", value=True)

# Apply Filters
filtered_df = raw_df[
    (raw_df['destination'].isin(selected_dests)) & 
    (raw_df['source'].isin(selected_sources))
]

if require_two_bags:
    filtered_df = filtered_df[filtered_df['checked_bags'] >= 2]

# ==========================================
# 4. DASHBOARD METRICS & CHARTS
# ==========================================
if filtered_df.empty:
    st.warning("No flight data matches your current filter criteria.")
else:
    # --- Top Metrics ---
    latest_time = filtered_df['timestamp'].max()
    latest_data = filtered_df[filtered_df['timestamp'] == latest_time]
    
    col1, col2, col3 = st.columns(3)
    
    global_min = raw_df['price'].min()
    filtered_min = filtered_df['price'].min()
    current_min = latest_data['price'].min() if not latest_data.empty else None
    
    with col1:
        st.metric("All-Time Lowest (Any Bag/Dest)", f"${global_min:,.2f}")
    with col2:
        st.metric("Lowest Matching Filters", f"${filtered_min:,.2f}")
    with col3:
        if current_min:
            best_route = latest_data.loc[latest_data['price'].idxmin()]
            st.metric(f"Current Best ({best_route['destination']})", f"${current_min:,.2f}", 
                      delta=f"Found via {best_route['source']}", delta_color="off")

    st.divider()

    # --- Trend Chart ---
    st.subheader("Price Trends (Last 48 Hours)")
    # Group by timestamp and destination to get the minimum price per interval
    trend_df = filtered_df.groupby(['timestamp', 'destination'])['price'].min().reset_index()
    
    fig = px.line(
        trend_df, 
        x='timestamp', 
        y='price', 
        color='destination',
        markers=True,
        title="Lowest Available Price per Destination Over Time",
        labels={'price': 'Price (USD)', 'timestamp': 'Time Logged'}
    )
    fig.update_layout(hovermode="x unified")
    st.plotly_chart(fig, use_container_width=True)

    st.divider()

    # --- Leaderboard Table ---
    st.subheader(f"Top 5 Cheapest Flights (As of {latest_time.strftime('%I:%M %p')})")
    
    if not latest_data.empty:
        # Sort by price and take top 5
        top_5 = latest_data.sort_values(by='price', ascending=True).head(5)
        
        # Clean up dataframe for display
        display_df = top_5[['airline', 'destination', 'price', 'checked_bags', 'stops', 'source']].copy()
        display_df.columns = ['Airline', 'Destination', 'Price (USD)', 'Checked Bags', 'Stops', 'Source']
        display_df['Price (USD)'] = display_df['Price (USD)'].apply(lambda x: f"${x:,.2f}")
        
        st.dataframe(display_df, use_container_width=True, hide_index=True)
    else:
        st.info("No data available for the most recent interval with the current filters.")