import pandas as pd
import json
import re
import os
from datetime import datetime
import praw
from nltk.corpus import words

# Load Reddit API credentials
reddit = praw.Reddit(
    client_id='L9FWD3HuL6H_SFayyh1JPg',
    client_secret='xqw4uhgKS_qXm-BEU6jxy6vfkbO8jQ',
    user_agent='stock-tracker-app by u/KevinSmit200412'
)

# Load English dictionary in uppercase
ENGLISH_WORDS = set(w.upper() for w in words.words())
ENGLISH_WORDS.update({
    'ARE', 'CAN', 'DID', 'DO', 'DOES', 'GETS', 'GOES', 'HAD', 'HAS',
    'HAVE', 'IS', 'MAY', 'MUST', 'SAYS', 'WAS', 'WERE', 'WILL', 'PAYS',
    'WTF', 'WWW', 'DD', 'VS', 'PRE', 'USA', 'CPA'
})

def load_tickers():
    """
    Load tickers from the NASDAQ screener CSV file.
    """
    path = "nasdaq_screener_1753260279514.csv"
    df = pd.read_csv(path)
    if 'Symbol' not in df.columns:
        raise ValueError("CSV must contain 'Symbol' column.")
    tickers = df['Symbol'].dropna().astype(str).str.upper()
    return [t for t in tickers if t.isalpha() and 2 <= len(t) <= 5 and t not in ENGLISH_WORDS]

def get_mentions_from_reddit(selected_subreddits=None):
    """
    Scrape Reddit for mentions of stock tickers.
    """
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

    # Include all tickers, even those with zero mentions
    return pd.DataFrame([{
        "ticker": t,
        "mentions": d["mentions"],
        "Upvotes": d["upvotes"],
        "Total Comments": d["comments"]
    } for t, d in mention_data.items()])

def save_to_csv(df, file_path="mentions_data.csv"):
    """
    Save the mentions data to a CSV file, adding new days as groups of columns (mentions, Upvotes, Total Comments).
    """
    today = datetime.now().strftime("%Y-%m-%d")  # Get today's date

    # Rename columns to include today's date
    df = df.rename(columns={
        "mentions": f"{today}_mentions",
        "Upvotes": f"{today}_Upvotes",
        "Total Comments": f"{today}_Total Comments"
    })

    # If the file exists, load the existing data
    if os.path.exists(file_path):
        existing_df = pd.read_csv(file_path)

        # Check if today's data already exists
        if any(col.startswith(today) for col in existing_df.columns):
            print(f"Data for {today} already exists in the file. Skipping save.")
            return

        # Merge the new data with the existing data
        existing_df = pd.merge(existing_df, df, on="ticker", how="outer").fillna(0)
    else:
        # Create a new DataFrame if the file doesn't exist
        existing_df = df

    # Save the updated DataFrame to the CSV file
    existing_df.to_csv(file_path, index=False)
    print(f"Data saved to {file_path}")

def main():
    """
    Main function to scrape data and save it to a CSV file.
    """
    print("Fetching Reddit mentions...")
    reddit_data = get_mentions_from_reddit()
    if reddit_data.empty:
        print("No data fetched from Reddit.")
        return

    print("Saving data to CSV...")
    save_to_csv(reddit_data)

if __name__ == "__main__":
    main()
