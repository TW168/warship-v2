# whsh/pages/5_Warehouse.py

# ✅ Step 1: Imports
import streamlit as st
import pandas as pd
from datetime import timedelta, date
import plotly.express as px
import plotly.graph_objects as go
import calendar
import requests
from sklearn.preprocessing import MinMaxScaler
import re



# Page configuration
st.set_page_config(page_title="Warehouse", page_icon="🏢", layout="wide")
st.title("Warehouse")


col1, col2 = st.columns(2)
with col1:
    with st.expander("Today Hourly UDC", expanded=True):
        udc_hourly_url = "http://172.17.15.228:8000/udc_hourly_missions"
        try:
            response = requests.get(udc_hourly_url)
            data = response.json()
            df = pd.DataFrame(data)

            # Convert dt_start to datetime, then extract hour
            df["dt_start"] = pd.to_datetime(df["dt_start"])
            df["hour"] = df["dt_start"].dt.hour

            # Filter today's data only
            today = pd.Timestamp.now().normalize()
            df = df[df["dt_start"].dt.date == today.date()]

            # Group by hour and mission, count records
            df_grouped = (
                df.groupby(["hour", "mission"]).size().reset_index(name="count")
            )

            # Plot
            fig = px.bar(
                df_grouped,
                x="hour",
                y="count",
                color="mission",
                barmode="group",
                title="UDC by Hour (Today)",
                labels={"count": "Total", "hour": "Hour"},
            )
            st.plotly_chart(fig, use_container_width=True)
            st.caption("API: http://172.17.15.228:8000/udc_hourly_missions")
            st.caption("Data source: https://ash123.azurewebsites.net/cfpwh/udcsort")

        except Exception as e:
            st.error(f"Error loading UDC hourly data: {e}")


with col2:
    with st.expander("UDC History", expanded=True):
        # Calculate default start and end dates for the last 30 days
        today = date.today()
        end_date_default = today
        start_date_default = today - timedelta(days=29)

        start_date = st.date_input(
            "Start date",
            value=start_date_default,
            help="Data begins 2025-04-22"
        )
        end_date = st.date_input(
            "End date",
            value=end_date_default,
        )

        # Ensure start_date is not after end_date if user manually changes it
        # This block handles the error, but the rest of the code should run if dates are valid
        if start_date > end_date:
            st.error("Error: Start date cannot be after end date. Please adjust the dates.")
            st.stop() # This stops the app from running further with invalid dates
        else:
            # Fetch summary (THIS BLOCK WAS MOVED AND UNINDENTED)
            try:
                summary_url = (
                    f"http://172.17.15.228:8000/udc_summary/"
                    f"?start={start_date}&end={end_date}"
                )
                resp = requests.get(summary_url)
                resp.raise_for_status() # Raise HTTPError for bad responses (4xx or 5xx)
                data_sum = resp.json()

                # Check if data_sum is empty or a list of empty objects
                if not data_sum:
                    st.warning("No data returned from the API for the selected date range.")
                    # You might want to stop here or display an empty chart
                    st.stop() # Or just let it try to plot, which will likely result in an empty chart

                df_summary = pd.DataFrame(data_sum)

                # Important check: If the API returns data but it's not suitable for plotting (e.g., missing 'date' column)
                if 'date' not in df_summary.columns:
                    st.error("API response missing 'date' column required for plotting.")
                    st.dataframe(df_summary) # Show the raw data for debugging
                    st.stop()

                # Ensure 'date' column is datetime for proper plotting
                df_summary['date'] = pd.to_datetime(df_summary['date'])
                df_summary = df_summary.sort_values(by='date') # Good practice for time series plots

                # Show table (uncomment if you want to see the raw table)
                # st.dataframe(df_summary)

                # Plot summary
                fig2 = px.line(
                    df_summary,
                    x="date",
                    y=["Entry", "Exit", "Entry-1", "Entry-5"],
                    title="UDC Summary (Last 30 Days)",
                    color_discrete_sequence=px.colors.qualitative.Set1,
                )
                st.plotly_chart(fig2, use_container_width=True)
                st.caption("API: http://172.17.15.228:8000/udc_summary/")
                st.caption("Data source: https://ash123.azurewebsites.net/cfpwh/udcsort")

            except requests.exceptions.HTTPError as e:
                st.error(f"HTTP Error fetching UDC summary data: {e}. Check API server (Status Code: {e.response.status_code}).")
            except requests.exceptions.ConnectionError as e:
                st.error(f"Connection Error: Could not connect to the API server at {summary_url}. Is it running?")
            except requests.exceptions.Timeout as e:
                st.error(f"Timeout Error: The API request to {summary_url} took too long.")
            except requests.exceptions.RequestException as e:
                st.error(f"An unexpected error occurred while fetching data: {e}")
            except ValueError as e:
                st.error(f"Data processing error: {e}. Check if API returns valid JSON and expected columns.")
                # Optionally, print raw data for debugging if ValueError occurs
                # st.json(data_sum)
            except Exception as e:
                st.error(f"An unknown error occurred: {e}")
st.divider()


with st.expander("ASH Event", expanded=True):
    # ✅ Step 2: API Config (edit base if needed)
    API_BASE = "http://172.17.15.228:8000"
    SUMMARY_URL = f"{API_BASE}/event_ash_summary"
    DESCRIPTIONS_URL = f"{API_BASE}/event_ash_descriptions"  # optional, used if available

    # ✅ Step 3: Helpers
    def clean_descriptions(s: pd.Series) -> pd.Series:
        """Normalize description strings to avoid accidental category merges."""
        s = s.astype(str)
        s = s.str.replace("\u00A0", " ", regex=False)   # NBSP -> space
        s = s.str.replace(r"\s+", " ", regex=True)      # collapse multiple spaces
        return s.str.strip()

    @st.cache_data(ttl=3600)
    def load_description_catalog() -> list[str]:
        """
        Preferred: call /event_ash_descriptions (if your API provides it).
        Fallback: build from the last 180 days of summary data.
        """
        # Try dedicated endpoint
        try:
            r = requests.get(DESCRIPTIONS_URL, params={"last_n_days": 365}, timeout=10)
            r.raise_for_status()
            raw = r.json().get("descriptions", [])
            if isinstance(raw, list) and raw:
                ser = pd.Series(raw, dtype="object")
                cat = sorted({x for x in clean_descriptions(ser).tolist() if x})
                if cat:
                    return cat
        except Exception:
            pass

        # Fallback: pull from last 180 days of summary
        try:
            end = date.today()
            start = end - timedelta(days=179)
            r = requests.get(
                SUMMARY_URL,
                params={"start_date": start.isoformat(), "end_date": end.isoformat()},
                timeout=15,
            )
            r.raise_for_status()
            df = pd.DataFrame(r.json())
            if not df.empty and "description" in df.columns:
                cat = sorted({x for x in clean_descriptions(df["description"]).tolist() if x})
                if cat:
                    return cat
        except Exception:
            pass

        return []  # last resort: will just show what’s in the current slice

    def ensure_numeric(series: pd.Series) -> pd.Series:
        """Coerce to numeric, replacing invalid/NaN with zeros."""
        return pd.to_numeric(series, errors="coerce").fillna(0)

    # ✅ Step 4: UI (no expander)
    st.subheader("ASH Event")

    # Last 30 days (inclusive)
    today = date.today()
    end_default = today
    start_default = today - timedelta(days=29)

    col1, col2 = st.columns(2)
    with col1:
        start_date = st.date_input("Start Date", start_default)
    with col2:
        end_date = st.date_input("End Date", end_default)

    # ✅ Step 5: Validate dates
    if start_date > end_date:
        st.error("Start Date must be on or before End Date.")
        st.stop()

    # ✅ Step 6: Fetch selected-range data
    try:
        res = requests.get(
            SUMMARY_URL,
            params={"start_date": start_date.isoformat(), "end_date": end_date.isoformat()},
            timeout=15,
        )
        res.raise_for_status()
        df_filtered = pd.DataFrame(res.json())
    except Exception as e:
        st.error(f"Error loading data: {e}")
        st.stop()

    if df_filtered.empty:
        st.warning("No data found for the selected date range.")
        st.caption("API: " + SUMMARY_URL)
        st.caption("Data source: https://ash123.azurewebsites.net/cfpwh/eventsort")
        st.stop()

    # ✅ Step 7: Clean & normalize
    # Dates
    if "event_date" not in df_filtered.columns:
        st.error("API response missing 'event_date' column.")
        st.stop()
    df_filtered["event_date"] = pd.to_datetime(df_filtered["event_date"], errors="coerce").dt.date
    df_filtered = df_filtered.dropna(subset=["event_date"]).sort_values("event_date")

    # Counts
    if "total_count" not in df_filtered.columns:
        st.error("API response missing 'total_count' column.")
        st.stop()
    df_filtered["total_count"] = ensure_numeric(df_filtered["total_count"])

    # Descriptions
    if "description" not in df_filtered.columns:
        st.error("API response missing 'description' column.")
        st.stop()
    df_filtered["description"] = clean_descriptions(df_filtered["description"])

    # ✅ Step 8: Build catalog & pivot with reindex (guarantees all descriptions show)
    all_descriptions = load_description_catalog()
    if not all_descriptions:  # fallback to what’s present if catalog unavailable
        all_descriptions = sorted(df_filtered["description"].unique().tolist())

    df_pivot = df_filtered.pivot_table(
        index="description",
        columns="event_date",
        values="total_count",
        aggfunc="sum",
        fill_value=0,
    )
    df_pivot = df_pivot.reindex(index=all_descriptions, fill_value=0)

    if df_pivot.empty:
        st.warning("No aggregated data to display after cleaning for this range.")
        st.stop()

    # ✅ Step 9: Plot heatmap (height adapts so labels are readable)
    n_rows = len(df_pivot.index)
    fig_height = min(1400, max(360, 22 * n_rows))

    fig = px.imshow(
        df_pivot,
        labels=dict(x="Event Date", y="Description", color="Total Count"),
        title="ASH Event Heatmap",
        aspect="auto",
    )
    fig.update_traces(colorscale="Blues_r", showscale=True)
    fig.update_xaxes(type="category")
    fig.update_layout(height=fig_height)

    st.plotly_chart(fig, use_container_width=True)

    # ✅ Step 10: References
    st.caption("API: " + SUMMARY_URL)
    st.caption("Data source: https://ash123.azurewebsites.net/cfpwh/eventsort")
    st.caption("Note: Approx. November 3 `Data Shift` occurred to clear the abnormal, took 2 days, task ended at November 6, 2024.")

st.divider()
# Date filter defaults (current month)
# # Calculate default start and end dates for the last 30 days
end_default = today # End date is today
start_default = today - timedelta(days=29) # Start date is 29 days before today, for a 30-day range
col1, col2 = st.columns(2)
# Date selectors
col1, col2 = st.columns(2)
with col1:
    start_date = st.date_input(
        "Start Date", value=start_default, key="start_date_shift_avg"
    )
with col2:
    end_date = st.date_input("End Date", value=end_default, key="end_date_shift_avg")


# # Fetch data from FastAPI
# url = "http://172.17.15.228:8000/shift_averages"
# response = requests.get(url)
# data = response.json()
# df = pd.DataFrame(data)
# df["Date"] = pd.to_datetime(df["Date"])

# # Enrich data
# df["Shift In"] = df["avg_day_shift_in"] + df["avg_night_shift_in"]
# df["Shift Out"] = (
#     df["avg_1st_shift_out"] + df["avg_2nd_shift_out"] + df["avg_3rd_shift_out"]
# )
# df["Net Diff"] = df["Shift In"] - df["Shift Out"]

# # Filter by calendar input
# mask = (df["Date"].dt.date >= start_date) & (df["Date"].dt.date <= end_date)
# filtered_df = df[mask]

# # # 📈 Daily Shifts Overview
# # with st.expander("📈 Daily Shifts Overview", expanded=True):
# #     fig_line = px.line(
# #         filtered_df,
# #         x="Date",
# #         y=[
# #             "avg_day_shift_in",
# #             "avg_night_shift_in",
# #             "avg_1st_shift_out",
# #             "avg_2nd_shift_out",
# #             "avg_3rd_shift_out",
# #         ],
# #         labels={"value": "Average Count", "variable": "Shift Type"},
# #         title="Average Shift In/Out by Date",
# #     )
# #     st.plotly_chart(fig_line, use_container_width=True)
# #     st.caption("API: http://172.17.15.228:8001/shift_averages")
# #     st.caption("Data source: https://cfpwh-web.azurewebsites.net/cfpwhdailystat.php")

# # 📊 Shift In vs Out per Day
# with st.expander("📊 Shift In vs Out Per Day", expanded=False):
#     fig_bar = px.bar(
#         filtered_df,
#         x="Date",
#         y=["Shift In", "Shift Out"],
#         barmode="group",
#         title="Daily Shift In vs Out",
#     )
#     st.plotly_chart(fig_bar, use_container_width=True)

# # 🗓️ Weekday Averages
# with st.expander("🗓️ Weekly Averages by Weekday", expanded=False):
#     weekday_avg = (
#         filtered_df.groupby("Weekday")[["Shift In", "Shift Out", "Net Diff"]]
#         .mean()
#         .reset_index()
#     )
#     # Optional: sort weekdays manually
#     ordered_weekdays = [
#         "Monday",
#         "Tuesday",
#         "Wednesday",
#         "Thursday",
#         "Friday",
#         "Saturday",
#         "Sunday",
#     ]
#     weekday_avg["Weekday"] = pd.Categorical(
#         weekday_avg["Weekday"], categories=ordered_weekdays, ordered=True
#     )
#     weekday_avg = weekday_avg.sort_values("Weekday")

#     fig_weekday = px.bar(
#         weekday_avg,
#         x="Weekday",
#         y=["Shift In", "Shift Out"],
#         barmode="group",
#         title="Average Shift In/Out by Weekday",
#     )
#     st.plotly_chart(fig_weekday, use_container_width=True)

# col1, col2 = st.columns(2)
# with col1:
#     # ⚖️ Net Difference Chart
#     with st.expander("⚖️ Net Shift Difference per Day", expanded=True):
#         fig_net = px.bar(
#             filtered_df,
#             x="Date",
#             y="Net Diff",
#             title="Net Shift Difference (In - Out) per Day",
#             color="Net Diff",
#             color_continuous_scale="RdBu",
#         )
#         st.plotly_chart(fig_net, use_container_width=True)
#         st.caption(
#             "Positive Net Diff (+) → Pallets entering the warehouse are more than pallets shipped."
#         )
#         st.caption(
#             "Negative Net Diff (-) → Pallets shipped are more than the pallets that entered the warehouse."
#         )


# with col2:
#     # Fetch daily shipment summary for total pallets
#     shipment_url = "http://172.17.15.228:8000/daily_shipment_summary"
#     # Assume default parameters are used or hardcoded site/group/date range
#     params = {"site": "AMJK", "group": "SW", "appt_date": ""}

#     # Build a daily loop to gather total_pallets per day
#     shipment_records = []

#     for single_date in pd.date_range(start=start_date, end=end_date):
#         params["appt_date"] = single_date.date().isoformat()
#         try:
#             response = requests.get(shipment_url, params=params)
#             if response.status_code == 200:
#                 data = response.json()
#                 if data:
#                     df_daily = pd.DataFrame(data)
#                     total = df_daily["total_pallets"].sum()
#                 else:
#                     total = 0
#                 shipment_records.append(
#                     {"Date": single_date.date(), "Total Pallets": total}
#                 )
#         except Exception as e:
#             shipment_records.append({"Date": single_date.date(), "Total Pallets": None})

#     shipment_df = pd.DataFrame(shipment_records)
#     shipment_df["Date"] = pd.to_datetime(shipment_df["Date"])
#     combined_df = pd.merge(filtered_df, shipment_df, on="Date", how="left")

#     with st.expander("📦 Net Difference: Shipped - Enter warehouse ", expanded=True):
#         combined_df["Pallet Diff"] = (
#             combined_df["Shift In"] - combined_df["Total Pallets"]
#         )

#         fig_pallet_diff = px.bar(
#             combined_df,
#             x="Date",
#             y="Pallet Diff",
#             title="Net Difference (Pallet enter the warehouse - pallet shipped) per Day",
#             color="Pallet Diff",
#             color_continuous_scale="RdBu",
#             labels={"Pallet Diff": "Net Pallet Difference"},
#         )

#         st.plotly_chart(fig_pallet_diff, use_container_width=True)
#         st.caption(
#             "Positive → Pallets entering the warehouse are more than pallets shipped."
#         )
#         st.caption(
#             "Negative → Pallets shipped are more than the pallets that entered the warehouse."
#         )


# with st.expander("📦 Pallets enter the warehouse vs Shipped", expanded=True):
#     fig_combo = px.bar(
#         combined_df,
#         x="Date",
#         y=["Shift In", "Total Pallets"],
#         barmode="group",
#         title="Pallets enter the warehouse vs Shipped",
#         labels={"value": "Count", "Date": "Date", "variable": "Metric"},
#     )
#     st.plotly_chart(fig_combo, use_container_width=True)

# with st.expander("🏷️ Warehouse Summary (Pallet Entry - Shipped)", expanded=True):
#     # the data source R:\1-DAILY_DATA_AUTO_WAREHOUSE_2025.xlsx or mysql table auto_wh
#     wh_url = "http://172.17.15.228:8000/auto_wh_summary"

#     try:
#         response = requests.get(wh_url)
#         response.raise_for_status()
#         wh_data = response.json()
#         wh_df = pd.DataFrame(wh_data)
#         wh_df["Date"] = pd.to_datetime(wh_df["Date"])

#         # Filter by selected start/end dates
#         wh_df = wh_df[
#             (wh_df["Date"].dt.date >= start_date) & (wh_df["Date"].dt.date <= end_date)
#         ]

#         # Calculate difference
#         wh_df["Entry Minus Shipped"] = wh_df["Pallet_Entry"] - wh_df["Pallet_Shipped"]

#         # Plot the chart
#         fig_wh_diff = px.bar(
#             wh_df,
#             x="Date",
#             y="Entry Minus Shipped",
#             color="Entry Minus Shipped",
#             color_continuous_scale="Tealrose",
#             title="Warehouse Net Movement: Pallet Entry - Shipped",
#             labels={"Entry Minus Shipped": "Net Movement"},
#         )
#         st.plotly_chart(fig_wh_diff, use_container_width=True)
#         st.caption(
#             "Positive = More pallets entered than shipped. Negative = More pallets shipped than entered."
#         )
#         st.caption("Data source: tabel auto_wh")

#     except Exception as e:
#         st.error(f"Failed to fetch warehouse summary: {e}")


# st.divider()
# # with st.expander("📊 Warehouse Status History", expanded=False):
# #     # Use the same start_date and end_date from UDC History inputs or define new ones
# #     status_start = start_date  # from UDC History date_input
# #     status_end = end_date
# #     status_url = (
# #         f"http://172.17.15.228:8000/wh_status_history"
# #         f"?start={status_start}&end={status_end}"
# #     )
# #     try:
# #         status_resp = requests.get(status_url)
# #         status_resp.raise_for_status()
# #         df_status = pd.DataFrame(status_resp.json())
# #         df_status["Date"] = pd.to_datetime(df_status["Date"]).dt.date
        
# #         if df_status.empty:
# #             st.warning("No warehouse status history found for the selected date range.")
# #         else:
# #             # Show raw table
# #             st.dataframe(df_status)

# #             # Compute total in (sum of Day_In and Night_In)
# #             df_status["Pallet_to_WH"] = df_status["Day_In"].fillna(0) + df_status["Night_In"].fillna(0)

# #             # Plot sum of in and Pallet_Shipped over time
# #             metrics = [
# #                 "Pallet_to_WH",
# #                 "Pallet_Shipped",
# #             ]
# #             fig_status = px.line(
# #                 df_status,
# #                 x="Date",
# #                 y=metrics,
# #                 title="Warehouse Status History: Pallet to WH vs Pallet Shipped",
# #                 labels={"value": "Count", "variable": "Metric"}
# #             )
# #             st.plotly_chart(fig_status, use_container_width=True)
# #         st.caption(f"API: {status_url}")
# #     except Exception as e:
# #         st.error(f"Error loading Warehouse Status History: {e}")



# # === 📊 Warehouse Status History ===

# status_start = start_date  # reuse your date inputs
# status_end = end_date
# status_url = f"http://172.17.15.228:8000/wh_status_history?start={status_start}&end={status_end}"

# df_status = None

# with st.expander("📊 Warehouse Status History", expanded=True):
#     try:
#         status_resp = requests.get(status_url)
#         status_resp.raise_for_status()
#         df_status = pd.DataFrame(status_resp.json())
#         df_status["Date"] = pd.to_datetime(df_status["Date"]).dt.date

#         if df_status.empty:
#             st.warning("No warehouse status history found for the selected date range.")
#         else:
#             st.dataframe(df_status)

#             # Plot raw totals
#             df_status["Pallet_to_WH"] = df_status["Day_In"].fillna(0) + df_status["Night_In"].fillna(0)
#             fig_raw = px.line(
#                 df_status,
#                 x="Date",
#                 y=["Pallet_to_WH", "Pallet_Shipped"],
#                 title="Raw: Pallets to Warehouse vs Shipped",
#                 labels={"value": "Count", "variable": "Metric"}
#             )
#             st.plotly_chart(fig_raw, use_container_width=True)

#         st.caption(f"API: {status_url}")

#     except Exception as e:
#         st.error(f"Error loading Warehouse Status History: {e}")


# # === 🧮 Min-Max Scaled Metrics (separate expander!) ===

# if df_status is not None and not df_status.empty:
#     columns_to_scale = [
#         "Day_In", "Night_In", "Day_Out", "Night_Out", "After_Hours_Out",
#         "Pallet_Shipped", "Pallet_Abnormal_AS400", "Pallet_Abnormal_CMA",
#         "Status_0", "Status_1", "Status_2", "Status_3",
#         "Status_31", "Status_32", "Status_33", "Status_41",
#         "Status_5", "Status_51", "Status_52", "Status_53",
#         "Status_Other", "total_cell_counts"
#     ]

#     scaler = MinMaxScaler()
#     scaled_data = scaler.fit_transform(df_status[columns_to_scale])
#     df_scaled = pd.DataFrame(scaled_data, columns=columns_to_scale)
#     df_scaled["Date"] = df_status["Date"]
#     df_scaled = df_scaled[["Date"] + columns_to_scale]

#     with st.expander("🧮 Min-Max Scaled Metrics (0–1 Range)", expanded=True):
#         st.dataframe(df_scaled)

#     # Example chart from normalized data
#     fig_scaled = px.line(
#         df_scaled,
#         x="Date",
#         y=["Status_2", "Status_3", "Status_5"],
#         title="Normalized Status Metrics Over Time",
#         labels={"value": "Normalized", "variable": "Status"}
#     )
#     st.plotly_chart(fig_scaled, use_container_width=True)



# st.divider()


# with st.expander('Hourly Stacker Stats', expanded=True):

#     # Fetch data from FastAPI
#     url = "http://172.17.15.228:8000/wh_today"
#     response = requests.get(url)
#     data = response.json()
#     # Convert JSON to DataFrame
#     df = pd.DataFrame(data["wh_today"])
#     # Convert hour_group to a string for consistent sorting
#     df["hour_group"] = df["hour_group"].astype(str)

#     # Filter for missions of interest
#     mission_df = df[df["mission"].isin(["Exit", "Entry", "Entry-1", "Entry-5"])]

#     # Plotly Bar Chart: Group bars by mission
#     fig_mission = px.bar(
#         mission_df,
#         x="hour_group",
#         y="total",
#         color="mission",
#         title="Mission Over Time",
#         labels={"hour_group": "Hour", "total": "Count"},
#         barmode="group"  # Ensures bars are grouped, not stacked
#     )

#     # Streamlit Layout
#     # st.title("Mission Analysis Dashboard")

#     # Display the Bar Chart
#     st.plotly_chart(fig_mission, use_container_width=True)


# with st.expander("Eric"):
#     url = "http://172.17.15.228:8000/table"
#     response = requests.get(url)
#     data = response.json()

#     # Convert JSON to DataFrame
#     df = pd.DataFrame(data["table_data"])
#     # st.dataframe(df, use_container_width=True)

#     # Calculate sums for DayShiftIn + NightShiftIn and 1stShiftOut + 2ndShiftOut + 3rdShiftOut
#     df["ShiftInTotal"] = df["DayShiftIn"] + df["NightShiftIn"]
#     df["ShiftOutTotal"] = df["1stShiftOut"] + df["2ndShiftOut"] + df["3rdShiftOut"]

#     # Prepare data for Plotly
#     melted_data = df.melt(
#         id_vars=["date"],
#         value_vars=["ShiftInTotal", "ShiftOutTotal"],
#         var_name="ShiftType",
#         value_name="Value"
#     )

#     # Create the line chart
#     fig = px.line(
#         melted_data,
#         x="date",
#         y="Value",
#         color="ShiftType",
#         title="Shift In and Out Over Time",
#         labels={"Value": "Shift Count", "date": "Date"}
#     )

#     # Streamlit App
#     st.title("Shift In and Out Visualization")
#     st.plotly_chart(fig)


# Streamlit app: Two charts side by side in an expander
# with st.expander('Warehouse', expanded=True):
#     # --- Chart 1: Mission Over Time ---
#     url1 = 'http://172.17.15.228:8001/wh_today'
#     resp1 = requests.get(url1)
#     data1 = resp1.json()
#     df1 = pd.DataFrame(data1['wh_today'])
#     df1['hour_group'] = df1['hour_group'].astype(str)
#     mission_df = df1[df1['mission'].isin(['Exit', 'Entry', 'Entry-1', 'Entry-5'])]
#     fig_mission = px.bar(
#         mission_df,
#         x='hour_group',
#         y='total',
#         color='mission',
#         title='Mission Over Time',
#         labels={'hour_group': 'Hour', 'total': 'Count'},
#         barmode='group'
#     )

# --- Chart 2: pallet In and Out Over Time ---
# url2 = 'http://172.17.15.228:8000/table'
# resp2 = requests.get(url2)
# data2 = resp2.json()
# df2 = pd.DataFrame(data2['table_data'])
# df2['Pallet In'] = df2['DayShiftIn'] + df2['NightShiftIn']
# df2['Pallet Out'] = df2['1stShiftOut'] + df2['2ndShiftOut'] + df2['3rdShiftOut']
# melted = df2.melt(
#     id_vars=['date'],
#     value_vars=['Pallet In', 'Pallet Out'],
#     var_name='ShiftType',
#     value_name='Value'
# )
# fig_shift = px.line(
#     melted,
#     x='date',
#     y='Value',
#     color='ShiftType',
#     title='Pallet In and Out Over Time',
#     labels={'date': 'Date', 'Value': 'Count'}
# )

# Display charts in two columns
# col1, col2 = st.columns(2)
# with col1:
#     st.plotly_chart(fig_mission, use_container_width=True, key="mission_chart")
#     st.caption('Data source: https://ash123.azurewebsites.net/cfpwh/udcs?_token=K4F2bzlX01CzzLHkEC3XqhXH41XphQRuTA7c3a6t&udate=2025-05-01&utype=All')
#     st.caption('')

# with col2:

#     # st.plotly_chart(fig_shift, use_container_width=True, key="shift_chart")
#     # st.caption('Data source: https://cfpwh-web.azurewebsites.net/')
#     # st.caption('')


#     def fetch_stacker_stats(engine):
#         # query = "SELECT stacker, height, status, COUNT(*) AS count, scraped_dt FROM yiduo.scraped_all_cells GROUP BY stacker, status, height, scraped_dt ORDER BY stacker, status"
#         query = "SELECT stacker, height, status, COUNT(*) AS count, scraped_dt FROM warship2_db.hourly_all_cells GROUP BY stacker, status, height, scraped_dt ORDER BY stacker, status"
#         df = pd.read_sql(query, engine)
#         return df

#     df = fetch_stacker_stats(engine)
#     max_dt = df['scraped_dt'].max()

#     # Define custom order for 'status' for the pie charts
#     custom_order = ['Empty', 'Couple', '48 inch', '96 inch', 'Disabled', 'Not used', '9', '12', 'Duplicate', 'Engaged']

#     # Function to plot pie chart
#     def plot_pie_chart(df, title, order):
#         df = df.copy()  # Make a copy of the DataFrame to avoid SettingWithCopyWarning
#         df.loc[:, 'status'] = pd.Categorical(df['status'], categories=order, ordered=True)
#         df = df.sort_values(by='status')
#         fig = px.pie(df, values='count', names='status', title=title, category_orders={'status': order})
#         return fig

#     st.info(f"Last Update: {max_dt}")
#     col1, col2, col3, col4, col5 =st.columns(5)
#     with col1:
#         # df = fetch_stacker_stats(engine)
#         stacker_stats = df.loc[df['stacker'] == '1']
#         fig = plot_pie_chart(stacker_stats, f"Stacker 1 Status Distribution", custom_order)
#         st.plotly_chart(fig, use_container_width=True)
#     with col2:
#         # df = fetch_stacker_stats(engine)

#         stacker_stats = df.loc[df['stacker'] == '2']
#         fig = plot_pie_chart(stacker_stats, f"Stacker 2 Status Distribution", custom_order)
#         st.plotly_chart(fig, use_container_width=True)
#     with col3:
#         # df = fetch_stacker_stats(engine)
#         stacker_stats = df.loc[df['stacker'] == '3']
#         fig = plot_pie_chart(stacker_stats, f"Stacker 3 Status Distribution", custom_order)
#         st.plotly_chart(fig, use_container_width=True)
#     with col4:
#         #df = fetch_stacker_stats(engine)
#         stacker_stats = df.loc[df['stacker'] == '4']
#         fig = plot_pie_chart(stacker_stats, f"Stacker 4 Status Distribution", custom_order)
#         st.plotly_chart(fig, use_container_width=True)
#     with col5:
#         # df = fetch_stacker_stats(engine)
#         stacker_stats = df.loc[df['stacker'] == '5']
#         fig = plot_pie_chart(stacker_stats, f"Stacker 5 Status Distribution", custom_order)
#         st.plotly_chart(fig, use_container_width=True)

#     st.caption('Data source: https://ash123.azurewebsites.net/cfpwh/cells/all_cells')

# def today_UDC_data():
#     # base_url = "http://172.17.8.96/cfpwh/udcs?_token=CaR4OweWoYnkEAbc9x1ZymzDRQdxeQB3g7Sa1IrQ&udate={}&utype=All"
#     base_url = "http://ash123.azurewebsites.net/cfpwh/udcs?_token=CaR4OweWoYnkEAbc9x1ZymzDRQdxeQB3g7Sa1IrQ&udate={}&utype=All"
#     today = datetime.today().strftime("%Y-%m-%d")
#     url = base_url.format(today)
#     df = pd.read_html(url)[0]
#     df['Date_cvt'] = pd.to_datetime(df['Date'])
#     df['Start_cvt'] = pd.to_datetime(df['Start'], format='%H:%M:%S')
#     df['End_cvt'] = pd.to_datetime(df['End'], format='%H:%M:%S')
#     df['Duration'] = df['End_cvt'] - df['Start_cvt']
#     df['Duration_sec'] = df['Duration'].dt.total_seconds()
#     df['Duration_minutes'] = (df['Duration'].dt.total_seconds() / 60)
#     return df

# def read_data_to_df(udc_url, event_url, date):
#     udc_df = pd.read_html(udc_url)[0]
#     event_df = pd.read_html(event_url)[0]
#     event_df['date'] = pd.to_datetime(date)
#     return udc_df, event_df


# with st.expander('Stacker Entry and Exit', expanded=False):
#     with st.spinner('Fetching data...'):
#         df = today_UDC_data()
#     df['Duration_minutes'] = pd.to_numeric(df['Duration_minutes'], errors='coerce').round(0)
#     df_done = df[(df['Status'] == 'Done') & (df['Pallet 1'] != 9999999999) & (df['Pallet 2'] != 9999999999)]
#     average_duration = df_done.groupby(['Stacker', 'Mission'])['Duration_minutes'].mean()
#     fig = px.bar(average_duration.reset_index(), x='Stacker', y='Duration_minutes', color='Mission', title='Average Duration by Stacker and Mission')
#     fig.update_layout(barmode='group')
#     st.plotly_chart(fig, use_container_width=True)
#     st.markdown("<small>source: http://172.17.8.96/cfpwh/udcs?_token=CaR4OweWoYnkEAbc9x1ZymzDRQdxeQB3g7Sa1IrQ&udate={}&utype=All</small>", unsafe_allow_html=True)


# with st.expander('Warehouse Entry, Exit and Shipped Analysis', expanded=True):
#     with st.spinner('Fetching and displaying box plot data...'):
#         # Load data
#         data_file_path = "D:\\Shipping_Daily_Report\\DAILY_DATA_AUTO_WAREHOUSE_All.xlsx"
#         data = wh_in_out.load_data(data_file_path)

#         df = data.copy()

#         # Convert `Date` column to datetime
#         df['Date'] = pd.to_datetime(df['Date'])

#         # Date range selection
#         start_date = st.date_input("Start Date", df['Date'].min().date(), key="start_date_input")
#         end_date = st.date_input("End Date", df['Date'].max().date(), key="end_date_input")
#         # Filter data based on selected date range
#         filtered_df = df[(df['Date'].dt.date >= start_date) & (df['Date'].dt.date <= end_date)]

#         # Calculate descriptive statistics
#         desc_stats = filtered_df.describe()
#         # Select only the desired columns
#         selected_columns = ['Pallet Entry', 'Pallet Exit', 'Pallet Shipped']
#         selected_stats = desc_stats[selected_columns]

#         col1, col2 = st.columns(2)
#         with col1:
#             # Aggregate data by month within the selected date range
#             monthly_data = filtered_df.groupby(filtered_df['Date'].dt.to_period("M"))[selected_columns].sum()
#             monthly_data.index = monthly_data.index.to_timestamp()  # Convert PeriodIndex to timestamp for Plotly

#             fig_line2 = go.Figure()

#             for col in selected_columns:
#                 fig_line2.add_trace(go.Scatter(
#                     x=monthly_data.index,  # Month
#                     y=monthly_data[col],
#                     mode='lines+markers',
#                     name=col
#                 ))

#             fig_line2.update_layout(
#                 title="Monthly Aggregated Pallet Counts",
#                 xaxis_title="Month",
#                 yaxis_title="Total Pallet Count",
#                 xaxis=dict(tickformat="%b %Y", type="date" )
#             )

#             st.plotly_chart(fig_line2)

#         with col2:
#             # Select only the desired columns
#             selected_columns = ['Pallet Entry', 'Pallet Exit', 'Pallet Shipped']
#             selected_stats = desc_stats[selected_columns]

#             fig = go.Figure()

#             for col in selected_stats.columns:
#                 fig.add_trace(go.Box(
#                     y=filtered_df[col],  # Use original data for the box plot
#                     name=col,
#                     boxmean=True  # Show the mean as a marker in the box plot
#                 ))

#             fig.update_layout(title="Interquartile Range Plot")

#             st.plotly_chart(fig)

#         st.markdown("""
#         ##  Here's how to interpret the interquartile range plot:

#         * **Big Box (Wide IQR):** High variability in pallet counts, indicating inconsistent demand or operation, possibly due to fluctuating production or shipment scheduling.
#         * **Narrow Box (Small IQR):** Low variability, representing stable and consistent operations.
#         * **High Outliers:** Sudden peaks, possibly from special orders or demand surges.
#         * **Low Outliers:** Rare dips, possibly due to downtime or reduced operations.
#         * **Increasing Box Size from Entry to Shipped:** Indicates possible accumulation of pallets in later stages, suggesting bottlenecks or overproduction relative to demand (1).

#         (1) assumption: Pallet Entry = Daily production
#         """)


# with st.expander('Warehouse operations vs. Abnormal', expanded=True):
#     # Create a dropdown to select the granularity
#     granularity = st.selectbox(
#         'Select Time Granularity',
#         ['By Year', 'By Year-Month', 'By Year-Quarter']
#     )

#     if granularity == 'By Year':
#         data['Year'] = data['Date'].dt.year  # Extract the year as integer
#         data['Year'] = data['Year'].astype(int)  # Ensure it's in integer format
#         grouped_data = data.groupby('Year').sum().reset_index()
#         x_values = grouped_data['Year']
#         x_title = 'Year'

#     elif granularity == 'By Year-Month':
#         data['Year-Month'] = data['Date'].dt.to_period('M')  # Year-Month format
#         grouped_data = data.groupby('Year-Month').sum().reset_index()
#         x_values = grouped_data['Year-Month'].astype(str)  # Convert to string for display
#         x_title = 'Year-Month'

#     elif granularity == 'By Year-Quarter':
#         data['Year-Quarter'] = data['Date'].dt.to_period('Q')  # Year-Quarter format
#         grouped_data = data.groupby('Year-Quarter').sum().reset_index()
#         x_values = grouped_data['Year-Quarter'].astype(str)  # Convert to string for display
#         x_title = 'Year-Quarter'

#     # Extract values for the plots
#     pallet_entry = grouped_data['Pallet Entry']
#     pallet_exit = grouped_data['Pallet Exit']
#     pallet_shipped = grouped_data['Pallet Shipped']
#     pallet_abnormal_as400 = grouped_data['Pallet Abnormal AS400']
#     pallet_abnormal_cma = grouped_data['Pallet Abnormal CMA']

#     # Create the figure
#     fig = go.Figure()

#     # Add traces for the primary y-axis
#     fig.add_trace(go.Scatter(x=x_values, y=pallet_entry, mode='lines+markers', name='Pallet Entry'))
#     fig.add_trace(go.Scatter(x=x_values, y=pallet_exit, mode='lines+markers', name='Pallet Exit'))
#     fig.add_trace(go.Scatter(x=x_values, y=pallet_shipped, mode='lines+markers', name='Pallet Shipped'))

#     # Add traces for the secondary y-axis
#     fig.add_trace(go.Scatter(
#         x=x_values,
#         y=pallet_abnormal_as400,
#         mode='lines+markers',
#         name='Pallet Abnormal AS400',
#         yaxis='y2'
#     ))
#     fig.add_trace(go.Scatter(
#         x=x_values,
#         y=pallet_abnormal_cma,
#         mode='lines+markers',
#         name='Pallet Abnormal CMA',
#         yaxis='y2'
#     ))

#     # Update layout for dual y-axes
#     fig.update_layout(
#         title=f'Pallet Operations Overview (Grouped by {x_title})',
#         xaxis_title=x_title,
#         yaxis=dict(
#             title='Pallet Entry, Exit, and Shipped',  # Primary y-axis title
#             titlefont=dict(color='blue'),
#             tickfont=dict(color='blue')
#         ),
#         yaxis2=dict(
#             title='Pallet Abnormal AS400 and CMA',  # Secondary y-axis title
#             titlefont=dict(color='red'),
#             tickfont=dict(color='red'),
#             overlaying='y',  # Overlay the secondary y-axis on the primary y-axis
#             side='right'  # Place the secondary y-axis on the right
#         ),
#         legend=dict(
#             title='Legend',
#             x=0.5,
#             y=1.15,
#             xanchor='center',
#             orientation='h'
#         ),
#         template='plotly'
#     )


#     with st.container():
#         st.plotly_chart(fig, use_container_width=True)
#         st.caption('Data source: CFPWH Web App, AS400 SWXFREP3 and SWXFREP4')


# with st.expander('Monthly Trends of Pallet Entry', expanded=True):
#     col1, col2 = st.columns(2)
#     with col1:
#         # Load the provided Excel file
#         df = pd.read_excel(r"D:\Shipping_Daily_Report\DAILY_DATA_AUTO_WAREHOUSE_All.xlsx")

#         # Create the 'Year' column
#         df['Date'] = pd.to_datetime(df['Date'])
#         df['Year'] = df['Date'].dt.year
#         df['Month'] = df['Date'].dt.month
#         years = df['Year'].unique()

#         fpp_data = []

#         for year in years:
#             year_data = df.loc[(df['Year'] == year)]
#             monthly_data = []
#             for month in range(1, 13):
#                 monthly_entry = year_data.loc[year_data['Month'] == month, 'Pallet Entry'].sum()
#                 monthly_data.append({'Month': month, 'Year': year, 'Pallet Entry': monthly_entry})

#             fpp_data.append(pd.DataFrame(monthly_data))

#         # Combine all the data into a single DataFrame
#         fpp_df = pd.concat(fpp_data)

#         # Plotting the data using Plotly Express
#         fig = px.line(fpp_df, x='Month', y='Pallet Entry', color='Year',
#                     title='Monthly Trends of Pallet Entry', labels={'Month': 'Month', 'Pallet Entry': 'Pallet Entry'}, markers=True)

#         # Adjust the tick marks on the x-axis
#         fig.update_xaxes(tickvals=np.arange(1, 13, 1), ticktext=[str(i) for i in range(1, 13)])

#         # Show the plot
#         st.plotly_chart(fig)
#         st.caption('Data Source: DAILY_DATA_AUTO_WAREHOUSE_All.xlsx')
#         st.markdown("""
#             ### Monthly Trends of Total Pallet Entry

#             This chart visualizes the total monthly pallet entry data for different years to identify seasonal or yearly trends in pallet inflow.

#             By plotting data for multiple years in a single line chart, it becomes easier to:
#             - Compare and contrast patterns, such as peak and low periods for pallet entry.
#             - Recognize recurring patterns or anomalies in pallet entry throughout the year.
#             - Identify months with the highest or lowest activity, which can aid in resource planning or operational adjustments.

#             These insights can help optimize warehouse operations and ensure efficient resource allocation.
#             """)


#     with col2:
#         # Ensure 'Date' column is in datetime format
#         df['Date'] = pd.to_datetime(df['Date'])

#         # Resample data to monthly frequency, summing values for each month
#         df_monthly = df.resample('M', on='Date').sum()

#         # Add Month-Year column for labeling
#         df_monthly['Month'] = df_monthly.index.month.map(lambda x: calendar.month_abbr[x])
#         df_monthly['Year'] = df_monthly.index.year
#         df_monthly['Month-Year'] = df_monthly['Month'] + '-' + df_monthly['Year'].astype(str)

#         # Calculate Over/underproduce
#         df_monthly['Over/underproduce'] = df_monthly['Pallet Entry'] - df_monthly['Pallet Shipped']

#         # Calculate cumulative Over/underproduce
#         df_monthly['Cumulative Over/underproduce'] = df_monthly['Over/underproduce'].cumsum()

#         # Create figure for cumulative over/underproduction
#         fig = go.Figure()

#         # Add cumulative over/underproduce trace
#         fig.add_trace(
#             go.Scatter(
#                 x=df_monthly['Month-Year'],
#                 y=df_monthly['Cumulative Over/underproduce'],
#                 name='Cumulative Over/underproduce',
#                 line=dict(color='blue')
#             )
#         )

#         # Update layout
#         fig.update_layout(
#             title_text='Cumulative Over/Underproduce Trends',
#             xaxis_title='Date',
#             yaxis=dict(
#                 title='Cumulative Over/underproduce',
#                 titlefont=dict(color='blue'),
#                 tickfont=dict(color='blue')
#             ),
#             xaxis=dict(
#                 tickangle=-45  # Rotate x-axis labels for better readability
#             )
#         )

#         st.plotly_chart(fig)
#         st.caption('Data Source: DAILY_DATA_AUTO_WAREHOUSE_All.xlsx')
#         st.markdown("""
#                 ### Cumulative Over/Underproduction Trends

#                 This chart examines the cumulative difference between pallets entering and those shipped out over time. It highlights whether production is consistently meeting demand or if there are periods of overproduction or underproduction.

#                 - **Upward Slope**: Indicates overproduction (more pallet entries than shipments).
#                 - **Downward Slope**: Indicates underproduction (more pallets shipped than entered).
#                 - **Sudden Spikes or Dips**: Can signify specific events or issues in production or logistics.

#                 By analyzing this trend, you can identify patterns and take corrective measures to maintain a balance between production and shipping.
#                 """)
