import pandas as pd
import nltk
from nltk.corpus import words
from dash import Dash, html, dcc, Input, Output, State, dash_table
import dash_bootstrap_components as dbc
import praw
import re
import yfinance as yf
from dash.dash_table.Format import Format, Scheme

# Load English dictionary in uppercase
ENGLISH_WORDS = set(w.upper() for w in words.words())
ENGLISH_WORDS.update({
    'ARE', 'CAN', 'DID', 'DO', 'DOES', 'GETS', 'GOES', 'HAD', 'HAS',
    'HAVE', 'IS', 'MAY', 'MUST', 'SAYS', 'WAS', 'WERE', 'WILL', 'PAYS',
    'WTF', 'WWW', 'DD', 'VS', 'PRE'
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
    tickers = load_tickers()
    ticker_set = set(tickers)
    mention_data = {t: {"mentions": 0, "upvotes": 0, "comments": 0} for t in tickers}
    word_pattern = re.compile(r'\b\w{2,10}\b')
    dollar_pattern = re.compile(r'\$(\w{2,10})')

    if selected_subreddits is None:
        selected_subreddits = ["wallstreetbets", "pennystocks", "options", "Shortsqueeze"]

    limits = {
        "wallstreetbets": 100,
        "pennystocks": 50,
        "options": 30,
        "Shortsqueeze": 30
    }

    try:
        for subreddit in selected_subreddits:
            max_posts = limits.get(subreddit.lower(), 50)
            submissions = reddit.subreddit(subreddit).new(limit=max_posts)
            for submission in submissions:
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
    } for t, d in mention_data.items() if d["mentions"] > 0])

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
            if len(data) >= 31:
                close = data["Close"]
                price_changes[ticker] = {
                    "1d Change": (close[-1] - close[-2]) / close[-2] * 100,
                    "5d Change": (close[-1] - close[-6]) / close[-6] * 100,
                    "30d Change": (close[-1] - close[-31]) / close[-31] * 100
                }
            else:
                price_changes[ticker] = {"1d Change": None, "5d Change": None, "30d Change": None}
        except:
            price_changes[ticker] = {"1d Change": None, "5d Change": None, "30d Change": None}
    price_df = pd.DataFrame.from_dict(price_changes, orient="index").reset_index().rename(columns={"index": "ticker"})
    return df.merge(price_df, on="ticker", how="left")

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
        dbc.Col(width=2, children=[
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
        ]),
        dbc.Col(width=10, children=[
            html.Div(id="page-content")
        ])
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

    df = merge_with_historical(get_mentions_from_reddit(selected_subreddits=settings["selected_subreddits"]))
    if df.empty:
        return html.Div("No Reddit data available. Check credentials or try again later.")

    meta_df = pd.read_csv("C:/Users/kevin/Downloads/nasdaq_screener_1753260279514.csv")
    meta_df['Symbol'] = meta_df['Symbol'].str.upper()
    df = df.merge(meta_df[['Symbol', 'Market Cap', 'Volume']], left_on='ticker', right_on='Symbol', how='left')
    df.drop(columns=['Symbol'], inplace=True)

    if settings.get("min_mcap") is not None:
        df = df[df['Market Cap'] >= settings["min_mcap"]]
    if settings.get("max_mcap") is not None:
        df = df[df['Market Cap'] <= settings["max_mcap"]]
    if settings.get("min_volume") is not None:
        df = df[df['Volume'] >= settings["min_volume"]]

    df = df.sort_values("mentions", ascending=False).head(settings["top_n"])
    df = add_price_changes(df)

    df["Market Cap"] = (df["Market Cap"] / 1e9).map(lambda x: f"{x:.1f}B" if pd.notnull(x) else "N/A")
    df["Volume"] = (df["Volume"] / 1e6).map(lambda x: f"{x:.1f}M" if pd.notnull(x) else "N/A")

    for col in ["1d Change", "5d Change", "30d Change", "Change (1d)"]:
        df[col] = df[col] / 100

    return dbc.Container([
        html.H3("Top Mentioned Stocks on Reddit (WSB + Finance Subs)", className="my-3"),
        dbc.Card([
            dbc.CardBody([
                dash_table.DataTable(
                    columns=[
                        {"name": "Ticker", "id": "ticker"},
                        {"name": "1d Change", "id": "1d Change", "type": "numeric", "format": Format(precision=1, scheme=Scheme.percentage)},
                        {"name": "5d Change", "id": "5d Change", "type": "numeric", "format": Format(precision=1, scheme=Scheme.percentage)},
                        {"name": "30d Change", "id": "30d Change", "type": "numeric", "format": Format(precision=1, scheme=Scheme.percentage)},
                        {"name": "Mentions", "id": "mentions"},
                        {"name": "Change (1d)", "id": "Change (1d)", "type": "numeric", "format": Format(precision=1, scheme=Scheme.percentage)},
                        {"name": "Upvotes", "id": "Upvotes"},
                        {"name": "Total Comments", "id": "Total Comments"},
                        {"name": "Market Cap", "id": "Market Cap"},
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
