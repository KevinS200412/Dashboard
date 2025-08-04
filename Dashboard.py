import pandas as pd
import nltk
from nltk.corpus import words
from dash import Dash, html, dcc, Input, Output, State, dash_table
import dash_bootstrap_components as dbc
import praw
import re
import yfinance as yf
from dash.dash_table.Format import Format, Scheme
import os
from datetime import datetime, timedelta

# Load English dictionary in uppercase
ENGLISH_WORDS = set(w.upper() for w in words.words())
ENGLISH_WORDS.update({
    'ARE', 'CAN', 'DID', 'DO', 'DOES', 'GETS', 'GOES', 'HAD', 'HAS',
    'HAVE', 'IS', 'MAY', 'MUST', 'SAYS', 'WAS', 'WERE', 'WILL', 'PAYS',
    'WTF', 'WWW', 'DD', 'VS', 'PRE', 'USA', 'CPA'
})

reddit = praw.Reddit(
    client_id='L9FWD3HuL6H_SFayyh1JPg',
    client_secret='xqw4uhgKS_qXm-BEU6jxy6vfkbO8jQ',
    user_agent='stock-tracker-app by u/KevinSmit200412'
)

SUBREDDIT_OPTIONS = [
    {"label": "WallStreetBets", "value": "wallstreetbets"},
    {"label": "PennyStocks", "value": "pennystocks"},
    {"label": "Options", "value": "options"},
    {"label": "ShortSqueeze", "value": "Shortsqueeze"}
]

app = Dash(__name__, external_stylesheets=[dbc.themes.FLATLY], suppress_callback_exceptions=True)

app.index_string = '''
<!DOCTYPE html>
<html>
    <head>
        {%metas%}
        <title>Reddit Tracker</title>
        {%favicon%}
        {%css%}
        <style>
            .Select__multi-value {
                display: none !important;
            }
            .Select__value-container {
                padding-top: 6px;
            }
            .Select__control {
                min-height: 40px;
            }
        </style>
    </head>
    <body>
        {%app_entry%}
        <footer>
            {%config%}
            {%scripts%}
            {%renderer%}
        </footer>
    </body>
</html>
'''

def load_tickers():
    path = "nasdaq_screener_1753260279514.csv"
    df = pd.read_csv(path)
    if 'Symbol' not in df.columns:
        raise ValueError("CSV must contain 'Symbol' column.")
    tickers = df['Symbol'].dropna().astype(str).str.upper()
    return [t for t in tickers if t.isalpha() and 2 <= len(t) <= 5]

def get_mentions_from_reddit(selected_subreddits=None):
    """
    Scrape Reddit for mentions of stock tickers from the last 24 hours.
    """
    tickers = load_tickers()
    ticker_set = set(tickers)
    mention_data = {t: {"mentions": 0, "upvotes": 0, "comments": 0} for t in tickers}
    word_pattern = re.compile(r'\b\w{2,10}\b')
    dollar_pattern = re.compile(r'\$(\w{2,10})')

    if selected_subreddits is None:
        selected_subreddits = ["wallstreetbets", "pennystocks", "options", "Shortsqueeze"]

    try:
        for subreddit in selected_subreddits:
            submissions = reddit.subreddit(subreddit).new(limit=None)  # Fetch all new posts
            cutoff_time = datetime.utcnow() - timedelta(days=1)  # 24 hours ago

            for submission in submissions:
                # Check if the post is within the last 24 hours
                post_time = datetime.utcfromtimestamp(submission.created_utc)
                if post_time < cutoff_time:
                    break  # Stop processing older posts

                text = f"{submission.title} {submission.selftext}".upper()
                upvotes, comments = max(0, submission.score), max(0, submission.num_comments)
                dollar_words = set(match.upper() for match in re.findall(dollar_pattern, text))
                all_words = set(re.findall(word_pattern, text))
                seen = set()
                for word in all_words:
                    if word in ticker_set and (word in dollar_words or word not in ENGLISH_WORDS and word not in seen):
                        mention_data[word]["mentions"] += 1
                        mention_data[word]["upvotes"] += upvotes
                        mention_data[word]["comments"] += comments
                        seen.add(word)
    except Exception as e:
        print("Reddit API error:", e)
        return pd.DataFrame([])

    return pd.DataFrame([{
        "ticker": t,
        "mentions": d["mentions"],
        "Upvotes": d["upvotes"],
        "Total Comments": d["comments"]
    } for t, d in mention_data.items()])

def merge_with_historical(live_df):
    try:
        historical_path = "full_dummy_mentions_with_nulls.csv"
        historical_df = pd.read_csv(historical_path)
        historical_df = historical_df[["Ticker", "2025-07-23"]].rename(columns={"Ticker": "ticker", "2025-07-23": "prev_mentions"})
        df = pd.merge(live_df, historical_df, on="ticker", how="left")
        def compute_change(row):
            today, yesterday = row["mentions"], row["prev_mentions"]
            if pd.isna(yesterday) or pd.isna(today):
                return None
            if yesterday == 0:
                return today * 100 if today > 0 else None
            return (today - yesterday) / yesterday * 100
        df["Change (1d)"] = df.apply(compute_change, axis=1)
        return df.drop(columns=["prev_mentions"])
    except Exception as e:
        print("Error merging historical data:", e)
        live_df["Change (1d)"] = None
        return live_df

def add_price_changes(df):
    tickers = df["ticker"].unique().tolist()
    price_changes = {}
    for ticker in tickers:
        try:
            data = yf.Ticker(ticker).history(period="35d")
            if len(data) >= 8:  # Ensure at least 8 days of data for 7d change
                close = data["Close"]
                price_changes[ticker] = {
                    "ΔP 1d": (close[-1] - close[-2]) / close[-2] * 100,
                    "ΔP 7d": (close[-1] - close[-8]) / close[-8] * 100,
                    "ΔP 30d": (close[-1] - close[-31]) / close[-31] * 100 if len(close) >= 32 else None
                }
            else:
                price_changes[ticker] = {
                    "ΔP 1d": None,
                    "ΔP 7d": None,
                    "ΔP 30d": None
                }
        except:
            price_changes[ticker] = {
                "ΔP 1d": None,
                "ΔP 7d": None,
                "ΔP 30d": None
            }
    price_df = pd.DataFrame.from_dict(price_changes, orient="index").reset_index().rename(columns={"index": "ticker"})
    return df.merge(price_df, on="ticker", how="left")


### Nieuwe functie om de database op te slaan
def save_mentions_to_csv(df, file_path="mentions_database.csv"):
    """
    Save the mentions data to a CSV file. Append new data if the file exists.
    """
    df["date"] = datetime.now().strftime("%Y-%m-%d")  # Add a date column
    if os.path.exists(file_path):
        # Append to the existing file
        existing_df = pd.read_csv(file_path)
        df = pd.concat([existing_df, df], ignore_index=True)
    df.to_csv(file_path, index=False)
### database opslaan functie eindigt hier

def add_mentions_changes(df):
    db = pd.read_csv("mentions_database.csv")
    db["date"] = pd.to_datetime(db["date"])
    today = datetime.now().date()
    for days, col in [(3, "3d Change"), (7, "7d Change")]:
        prev_date = today - timedelta(days=days)
        prev_mentions = db[db["date"] == pd.Timestamp(prev_date)][["ticker", "mentions"]].rename(columns={"mentions": f"mentions_{days}d_ago"})
        df = df.merge(prev_mentions, on="ticker", how="left")
        # Avoid division by zero and handle missing data
        df[col] = df.apply(
            lambda row: ((row["mentions"] - row[f"mentions_{days}d_ago"]) / row[f"mentions_{days}d_ago"] * 100)
            if pd.notnull(row[f"mentions_{days}d_ago"]) and row[f"mentions_{days}d_ago"] != 0 else None,
            axis=1
        )
        df.drop(columns=[f"mentions_{days}d_ago"], inplace=True)
    return df

app.layout = dbc.Container(fluid=True, children=[
    dcc.Location(id="url"),
    dcc.Store(id="top-n-store", data={
        "top_n": 1000,
        "min_mcap": None,
        "max_mcap": None,
        "min_volume": None,
        "selected_subreddits": ["wallstreetbets", "pennystocks", "options", "Shortsqueeze"]
    }),
    dcc.Store(id="update-trigger"),
    dbc.Row([
        dbc.Col(
            [
                html.H2("Dashboard", className="mb-3"),
                dbc.Label("Min Market Cap (B USD):"),
                dbc.Input(id="min-mcap-input", type="number", min=0, debounce=True),
                dbc.Label("Max Market Cap (B USD):", className="mt-2"),
                dbc.Input(id="max-mcap-input", type="number", min=0, debounce=True),
                dbc.Label("Min Volume:", className="mt-2"),
                dbc.Input(id="min-volume-input", type="number", min=0, debounce=True),
                dbc.Label("Number of Entries:", className="mt-2"),
                dbc.Input(id="top-n-input", type="number", value=1000, min=1),
                dbc.Label("Select Subreddits:", className="mt-2"),
                dcc.Dropdown(
                    id="subreddit-dropdown",
                    options=SUBREDDIT_OPTIONS,
                    value=["wallstreetbets", "pennystocks", "options", "Shortsqueeze"],
                    placeholder="Select...",
                    multi=True,
                    style={"width": "100%"},
                    clearable=False
                ),
                dbc.Button("Update", id="update-button", color="primary", className="mt-3", style={"width": "100%"})
            ],
            style={"minWidth": "120px", "maxWidth": "140px", "padding": "0 8px"}  # <-- Make sidebar very narrow
        ),
        dbc.Col(
            html.Div(id="page-content"),
            style={"paddingLeft": "0px"}
        )
    ])
])

@app.callback(
    Output("top-n-store", "data"),
    Output("update-trigger", "data"),
    Input("update-button", "n_clicks"),
    State("top-n-input", "value"),
    State("min-mcap-input", "value"),
    State("max-mcap-input", "value"),
    State("min-volume-input", "value"),
    State("subreddit-dropdown", "value"),
    prevent_initial_call=True
)
def update_settings(n_clicks, top_n, min_mcap, max_mcap, min_volume, selected_subreddits):
    return (
        {
            "top_n": 5 if top_n is None else top_n,
            "min_mcap": None if min_mcap is None else min_mcap * 1e9,
            "max_mcap": None if max_mcap is None else max_mcap * 1e9,
            "min_volume": min_volume,
            "selected_subreddits": selected_subreddits
        },
        n_clicks
    )

@app.callback(
    Output("page-content", "children"),
    Input("update-trigger", "data"),
    State("top-n-store", "data")
)
def render_page(_, settings):
    settings = dict(settings) if settings else {}
    settings.setdefault("selected_subreddits", ["wallstreetbets", "pennystocks", "options", "Shortsqueeze"])
    settings.setdefault("top_n", 1000)
    settings.setdefault("min_mcap", None)
    settings.setdefault("max_mcap", None)
    settings.setdefault("min_volume", None)

    # Fetch Reddit mentions and merge with historical data
    df = merge_with_historical(get_mentions_from_reddit(selected_subreddits=settings["selected_subreddits"]))
    if df.empty:
        return html.Div("No Reddit data available. Check credentials or try again later.")

    # Filter out stocks with 0 mentions
    df = df[df["mentions"] > 0]

    # Save mentions data to the CSV database
    save_mentions_to_csv(df)

    # Load metadata and merge
    meta_df = pd.read_csv("nasdaq_screener_1753260279514.csv")
    meta_df['Symbol'] = meta_df['Symbol'].str.upper()
    df = df.merge(meta_df[['Symbol', 'Market Cap', 'Volume']], left_on='ticker', right_on='Symbol', how='left')
    df.drop(columns=['Symbol'], inplace=True)

    # Apply user-defined filters
    if settings.get("min_mcap") is not None:
        df = df[df['Market Cap'] >= settings["min_mcap"]]
    if settings.get("max_mcap") is not None:
        df = df[df['Market Cap'] <= settings["max_mcap"]]
    if settings.get("min_volume") is not None:
        df = df[df['Volume'] >= settings["min_volume"]]

    # Sort and limit results
    df = df.sort_values("mentions", ascending=False).head(settings["top_n"])

    # Add price changes only for filtered stocks
    df = add_price_changes(df)

    # Add 3d and 7d change in mentions
    df = add_mentions_changes(df)

    # Format columns for display
    df["MCap"] = (df["Market Cap"] / 1e9).map(lambda x: f"{x:.1f}B" if pd.notnull(x) else "N/A")
    df["Volume"] = (df["Volume"] / 1e6).map(lambda x: f"{x:.1f}M" if pd.notnull(x) else "N/A")
    for col in [
        "ΔP 1d", "ΔP 7d", "ΔP 30d",
        "1d Change", "3d Change", "7d Change", "Change (1d)"
    ]:
        if col in df:
            df[col] = df[col] / 100

    return dbc.Container([
        html.H3("Top Mentioned Stocks on Reddit (WSB + Finance Subs)", className="my-3"),
        dbc.Card([
            dbc.CardBody([
                dash_table.DataTable(
                    columns=[
                        {"name": "Ticker", "id": "ticker"},
                        {"name": "ΔP 1d", "id": "ΔP 1d", "type": "numeric", "format": Format(precision=1, scheme=Scheme.percentage)},
                        {"name": "ΔP 7d", "id": "ΔP 7d", "type": "numeric", "format": Format(precision=1, scheme=Scheme.percentage)},
                        {"name": "ΔP 30d", "id": "ΔP 30d", "type": "numeric", "format": Format(precision=1, scheme=Scheme.percentage)},
                        {"name": "Mentions", "id": "mentions"},
                        {"name": "1d Change", "id": "Change (1d)", "type": "numeric", "format": Format(precision=1, scheme=Scheme.percentage)}, # mentions
                        {"name": "3d Change", "id": "3d Change", "type": "numeric", "format": Format(precision=1, scheme=Scheme.percentage)},   # mentions
                        {"name": "7d Change", "id": "7d Change", "type": "numeric", "format": Format(precision=1, scheme=Scheme.percentage)},   # mentions
                        {"name": "Upvotes", "id": "Upvotes"},
                        {"name": "Comments", "id": "Total Comments"},
                        {"name": "MCap", "id": "MCap"},
                    ],
                    data=df.to_dict("records"),
                    sort_action="native",
                    sort_mode="multi",
                    filter_action="native",
                    page_size=len(df),
                    style_cell={"textAlign": "left", "padding": "8px", "minWidth": "120px", "border": "none"},
                    style_header={"fontWeight": "bold", "border": "none"},
                    style_data={"border": "none"},
                )
            ])
        ])
    ])

if __name__ == "__main__":
    app.run(debug=True)
