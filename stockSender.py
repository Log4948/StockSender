import re
import json
import time
import requests
import smtplib
import anthropic
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime, timedelta
from pathlib import Path
import os
import sys
from concurrent.futures import ThreadPoolExecutor

# --- CONFIGURATION ---
NEWS_API_KEY = "cfd2d5ae591849c1b8d2f2e389112993"
API_KEY = "d352l4hr01qhorbgbe1gd352l4hr01qhorbgbe20"
try:
    import config
    EMAIL_ADDRESS     = os.getenv("EMAIL_ADDRESS")     or config.EMAIL_ADDRESS
    EMAIL_PASSWORD    = os.getenv("EMAIL_PASSWORD")    or config.EMAIL_PASSWORD
    TO_EMAIL          = os.getenv("TO_EMAIL")          or config.TO_EMAIL
    ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY") or getattr(config, "ANTHROPIC_API_KEY", None)
    # SMS gateway address, e.g. "5551234567@tmomail.net" — leave blank to get email-only alerts
    PHONE_SMS_EMAIL   = os.getenv("PHONE_SMS_EMAIL")   or getattr(config, "PHONE_SMS_EMAIL", None)
except ImportError:
    EMAIL_ADDRESS     = os.getenv("EMAIL_ADDRESS")
    EMAIL_PASSWORD    = os.getenv("EMAIL_PASSWORD")
    TO_EMAIL          = os.getenv("TO_EMAIL")
    ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
    PHONE_SMS_EMAIL   = os.getenv("PHONE_SMS_EMAIL")

# --- PORTFOLIO ---
tickers = {
    "Nvidia":   "NVDA",
    "Micron":   "MU",
    "Google":   "GOOG",
    "On Cloud": "ONON",
    "EPD":      "EPD",
    "QQQ":      "QQQ",
    "VYM":      "VYM",
    "VTI":      "VTI",
    "Walmart":  "WMT",
}

buy_prices = {
    "Nvidia":   205,
    "Google":   320.08,
    "QQQ":      603.0,
    "VYM":      153.0,
    "VTI":      339.0,
    "Micron":   915,
    "On Cloud": 31.025,
    "EPD":      38.98,
    "Walmart":  103.37,
}

stop_limits = {
    "Nvidia":   None,
    "Micron":   None,
    "Google":   None,
    "On Cloud": None,
    "EPD":      None,
    "QQQ":      None,
    "VYM":      None,
    "VTI":      None,
    "Walmart":  None,
}

share_counts = {
    "Nvidia":   42,
    "Micron":   14,
    "Google":   51,
    "On Cloud": 322,
    "EPD":      150,
    "QQQ":      27,
    "VYM":      113,
    "VTI":      49,
    "Walmart":  100,
}

dividend_yields = {
    "Nvidia":   "~0.03%",
    "Micron":   "~0.4%",
    "Google":   "-",
    "On Cloud": "-",
    "EPD":      "~7.5%",
    "QQQ":      "-",
    "VYM":      "~2.80%",
    "VTI":      "~1.30%",
    "Walmart":  "~1.0%",
}

watchlist = {
    # Former portfolio positions
    "Pfizer":      "PFE",
    "UPS":         "UPS",
    "Noble Corp":  "NE",
    "Amazon":      "AMZN",
    "LuluLemon":   "LULU",
    "Bitcoin ETF": "BITO",
    # Existing watchlist
    "D-Wave":          "QBTS",
    "Tesla":           "TSLA",
    "Broadcom":        "AVGO",
    "AMD":             "AMD",
    "Rigetti":         "RGTI",
    "Verizon":         "VZ",
    "Celsius Holdings": "CELH",
    "TSMC":            "TSM",
    "Rocket Lab":      "RKLB",
    "Mercado Libre":   "MELI",
    "Bloom Energy":    "BE",
    "Sandisk":         "SNDK",
    "ASML":            "ASML",
    "LyondellBasell":  "LYB",
}

focus_companies = {
    "Accenture": "ACN",
    "Mondelez":  "MDLZ",
    "SAP":       "SAP",
}

focus_keywords = [
    "consulting", "snack industry", "tech services", "consumer goods",
    "outsourcing", "chocolate", "digital transformation", "retail trends", "ERP", "enterprise software",
]

TOP_TICKERS = [
    # Tech & Communication
    "AAPL", "MSFT", "GOOGL", "GOOG", "AMZN", "META", "NVDA", "TSLA",
    "ORCL", "CRM", "ADBE", "INTC", "CSCO", "AMD", "QCOM", "IBM", "SNOW",
    # Financials
    "JPM", "BAC", "GS", "MS", "C", "WFC", "V", "MA", "AXP", "BLK", "PYPL", "SCHW",
    # Energy & Materials
    "XOM", "CVX", "COP", "SLB", "EOG", "PSX", "OXY", "HAL", "LIN", "NEM",
    # Industrials
    "CAT", "GE", "UNP", "DE", "HON", "LMT", "RTX", "BA", "UPS", "FDX", "MMM",
    # Healthcare
    "JNJ", "PFE", "UNH", "ABBV", "MRK", "TMO", "ABT", "LLY", "BMY", "CVS",
    # Consumer Staples & Discretionary
    "PG", "KO", "PEP", "MCD", "NKE", "COST", "WMT", "HD", "LOW", "SBUX", "TGT",
    # Utilities & Real Estate
    "NEE", "DUK", "SO", "D", "PLD", "AMT",
    # ETFs
    "SPY", "QQQ", "DIA", "IWM",
]

# --- PRICE ALERTS ---
# direction "below": fires when price drops TO or BELOW target (buy opportunity)
# direction "above": fires when price rises TO or ABOVE target (sell / breakout)
# Each alert fires once per calendar day per target — no repeat spam.
price_alerts = {
    "QBTS": {"target": 17.00,  "direction": "below", "label": "D-Wave"},
    "WMT":  {"target": 110.00, "direction": "above", "label": "Walmart"},
    "RKLB":  {"target": 63.00, "direction": "below", "label": "Rocket Lab"},
    "MU":  {"target": 1000.00, "direction": "above", "label": "Micron"},
    # Add more alerts here, e.g.:
    "MU":   {"target": 850.00,  "direction": "below", "label": "Micron"},
    "NVDA": {"target": 200.00, "direction": "below", "label": "Nvidia"},
}

ALERT_STATE_FILE = Path("alert_state.json")


# --- HELPERS ---
def fetch_quote(ticker):
    url = f"https://finnhub.io/api/v1/quote?symbol={ticker}&token={API_KEY}"
    try:
        data = requests.get(url, timeout=5).json()
        if "c" in data and "pc" in data and data["c"] and data["pc"]:
            change = data["c"] - data["pc"]
            percent_change = (change / data["pc"]) * 100
            return {"Ticker": ticker, "Price": data["c"], "Change": change, "% Change": percent_change}
    except Exception:
        pass
    return None

def format_number(n):
    try:
        return f"{float(n):,.2f}"
    except Exception:
        return n


# --- GET DATA ---
def get_stock_data(ticker, company=None):
    today = datetime.today()
    from_date = (today - timedelta(days=7)).strftime("%Y-%m-%d")
    to_date = today.strftime("%Y-%m-%d")

    url_quote   = f"https://finnhub.io/api/v1/quote?symbol={ticker}&token={API_KEY}"
    url_profile = f"https://finnhub.io/api/v1/stock/profile2?symbol={ticker}&token={API_KEY}"
    url_news    = f"https://finnhub.io/api/v1/company-news?symbol={ticker}&from={from_date}&to={to_date}&token={API_KEY}"
    url_metric  = f"https://finnhub.io/api/v1/stock/metric?symbol={ticker}&metric=all&token={API_KEY}"

    try:
        quote_data    = requests.get(url_quote,   timeout=5).json()
        profile_data  = requests.get(url_profile, timeout=5).json()
        news_data_raw = requests.get(url_news,    timeout=5).json()
        metric_data   = requests.get(url_metric,  timeout=5).json()
        time.sleep(0.3)
    except Exception as e:
        print(f"Error fetching data for {ticker}: {e}")
        return {
            "Ticker": ticker, "Price": None, "Change": None, "% Change": None,
            "Dividend": dividend_yields.get(company, "-"), "Market Cap": "-",
            "News": [], "52W High": None, "52W Low": None,
        }

    price          = quote_data.get("c", 0)
    change         = quote_data.get("d", 0)
    percent_change = quote_data.get("dp", 0)
    market_cap     = profile_data.get("marketCapitalization", "-")
    dividend_yield = dividend_yields.get(company, "-")

    metric      = metric_data.get("metric", {})
    week52_high = metric.get("52WeekHigh")
    week52_low  = metric.get("52WeekLow")

    news_data = []
    if isinstance(news_data_raw, list):
        for item in sorted(news_data_raw, key=lambda x: x.get("datetime", 0), reverse=True):
            headline = item.get("headline")
            url = item.get("url", "")
            if headline and url:
                news_data.append((headline, url))
            if len(news_data) == 3:
                break

    return {
        "Ticker": ticker, "Price": price, "Change": change, "% Change": percent_change,
        "Dividend": dividend_yield, "Market Cap": market_cap, "News": news_data,
        "52W High": week52_high, "52W Low": week52_low,
    }

def get_focus_news():
    today = datetime.today()
    from_date = (today - timedelta(days=5)).strftime("%Y-%m-%d")
    to_date = today.strftime("%Y-%m-%d")

    company_queries = {
        "Accenture": '"Accenture"',
        "Mondelez":  '"Mondelez"',
        "SAP":       '"SAP SE" OR ("SAP" AND "software")',
    }

    def deduplicate(news_list):
        seen = set()
        unique = []
        for headline, url in news_list:
            norm = re.sub(r'[^\w\s]', '', headline).strip().lower()
            if norm not in seen:
                seen.add(norm)
                unique.append((headline.strip(), url))
        return unique

    results = {}
    for name, query in company_queries.items():
        combined_news = []
        url = (
            f"https://newsapi.org/v2/everything?"
            f"qInTitle={query}&from={from_date}&to={to_date}&language=en&sortBy=publishedAt&apiKey={NEWS_API_KEY}"
        )
        try:
            data = requests.get(url, timeout=10).json()
            for article in data.get("articles", []):
                headline = article.get("title")
                link = article.get("url")
                if headline and link:
                    combined_news.append((headline, link))
        except Exception as e:
            print(f"NewsAPI fetch failed for {name}: {e}")
        results[name] = deduplicate(combined_news)[:5]

    return results

def get_stock_news(tickers_dict):
    today = datetime.today()
    from_date = (today - timedelta(days=5)).strftime("%Y-%m-%d")
    to_date = today.strftime("%Y-%m-%d")

    news_results = {}
    for company, ticker in tickers_dict.items():
        url = f"https://finnhub.io/api/v1/company-news?symbol={ticker}&from={from_date}&to={to_date}&token={API_KEY}"
        try:
            data = requests.get(url, timeout=5).json()
            stock_news = []
            if isinstance(data, list):
                for item in sorted(data, key=lambda x: x.get("datetime", 0), reverse=True):
                    if len(stock_news) >= 3:
                        break
                    if "headline" in item and "url" in item:
                        stock_news.append((item["headline"], item["url"]))
            news_results[company] = stock_news
        except Exception:
            news_results[company] = []
        time.sleep(0.3)
    return news_results

def get_market_top_movers():
    stocks = []
    with ThreadPoolExecutor(max_workers=10) as executor:
        results = executor.map(fetch_quote, TOP_TICKERS)
        for r in results:
            if r:
                stocks.append(r)

    gainers = sorted(stocks, key=lambda x: x["% Change"], reverse=True)[:5]
    losers  = sorted(stocks, key=lambda x: x["% Change"])[:5]
    return gainers, losers

def get_upcoming_earnings(portfolio_tickers):
    today     = datetime.today()
    from_date = today.strftime("%Y-%m-%d")
    to_date   = (today + timedelta(days=14)).strftime("%Y-%m-%d")

    upcoming = []
    for company, ticker in portfolio_tickers.items():
        url = f"https://finnhub.io/api/v1/calendar/earnings?from={from_date}&to={to_date}&symbol={ticker}&token={API_KEY}"
        try:
            data = requests.get(url, timeout=5).json()
            for e in data.get("earningsCalendar", []):
                date_str = e.get("date")
                if date_str:
                    days_away = (datetime.strptime(date_str, "%Y-%m-%d") - today).days
                    upcoming.append((company, ticker, date_str, days_away))
        except Exception:
            pass
        time.sleep(0.3)

    upcoming.sort(key=lambda x: x[3])
    return upcoming


# --- PRICE ALERTS ---
def _load_alert_state():
    if ALERT_STATE_FILE.exists():
        with open(ALERT_STATE_FILE) as f:
            return json.load(f)
    return {}

def _save_alert_state(state):
    with open(ALERT_STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)

def check_price_alerts():
    if not price_alerts:
        return []

    today = datetime.today().strftime("%Y-%m-%d")
    state = _load_alert_state()
    today_fired = state.get(today, {})

    triggered = []
    for ticker, cfg in price_alerts.items():
        alert_key = f"{ticker}_{cfg['target']}_{cfg['direction']}"
        if alert_key in today_fired:
            continue

        quote = fetch_quote(ticker)
        if not quote:
            continue

        current = quote["Price"]
        target  = cfg["target"]
        hit = (
            (cfg["direction"] == "below" and current <= target) or
            (cfg["direction"] == "above" and current >= target)
        )

        if hit:
            triggered.append({
                "ticker":    ticker,
                "label":     cfg.get("label", ticker),
                "price":     current,
                "target":    target,
                "direction": cfg["direction"],
                "key":       alert_key,
            })
            today_fired[alert_key] = {"price": current, "fired_at": datetime.now().isoformat()}

    if triggered:
        state[today] = today_fired
        # prune entries older than 7 days
        cutoff = (datetime.today() - timedelta(days=7)).strftime("%Y-%m-%d")
        state = {k: v for k, v in state.items() if k >= cutoff}
        _save_alert_state(state)
        _send_price_alerts(triggered)

    return triggered

def _send_price_alerts(alerts):
    recipients = [TO_EMAIL]
    if PHONE_SMS_EMAIL:
        recipients.append(PHONE_SMS_EMAIL)

    for alert in alerts:
        verb = "dropped to" if alert["direction"] == "below" else "hit"
        subject = f"Price Alert: {alert['label']} ({alert['ticker']}) {verb} ${alert['price']:.2f}"
        body = (
            f"{alert['label']} ({alert['ticker']}) {verb} your target.\n\n"
            f"Current price: ${alert['price']:.2f}\n"
            f"Your target:   ${alert['target']:.2f}\n\n"
            f"Checked at {datetime.now().strftime('%I:%M %p ET')}"
        )

        for recipient in recipients:
            msg = MIMEMultipart()
            msg["From"]    = EMAIL_ADDRESS
            msg["To"]      = recipient
            msg["Subject"] = subject
            msg.attach(MIMEText(body, "plain"))
            try:
                with smtplib.SMTP("smtp.gmail.com", 587) as server:
                    server.starttls()
                    server.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
                    server.send_message(msg)
                print(f"Alert sent to {recipient}: {subject}")
            except Exception as e:
                print(f"Alert send failed ({recipient}): {e}")


# --- EMAIL GENERATION ---
def create_collapsible_news_section(title, news_dict):
    html = f"<h2 style='margin-top:40px;'>{title}</h2>"
    for company, articles in news_dict.items():
        html += "<details style='margin-bottom:10px;'>"
        html += f"<summary style='font-weight:bold; cursor:pointer;'>{company}</summary><ul>"
        for headline, url in articles:
            html += f"<li>{headline} <a href='{url}' target='_blank'>🔗</a></li>"
        html += "</ul></details>"
    return html

def create_summary_section(portfolio_data, watchlist_data, market_gainers, market_losers, upcoming_earnings):
    html  = "<div style='background-color:#f8fafc; border:1px solid #e2e8f0; border-radius:10px; padding:20px; margin-bottom:30px;'>"
    html += "<h2 style='color:#0f172a;'>📊 Daily Market Summary</h2>"
    html += "<table style='width:100%; border-collapse:collapse;'>"
    html += "<tr style='background-color:#0f172a; color:white;'><th>Top Market Gainers</th><th>Top Market Losers</th><th>Average Portfolio Change</th></tr>"

    valid_changes = [s["% Change"] for s in portfolio_data.values() if isinstance(s["% Change"], (int, float))]
    avg_change = sum(valid_changes) / max(len(valid_changes), 1)

    html += "<tr style='text-align:center; background-color:white;'>"
    html += "<td style='vertical-align:top; padding:10px;'>"
    for s in market_gainers[:3]:
        html += f"<div style='color:green;'>{s['Ticker']} +{s['% Change']:.2f}%</div>"
    html += "</td><td style='vertical-align:top; padding:10px;'>"
    for s in market_losers[:3]:
        html += f"<div style='color:red;'>{s['Ticker']} {s['% Change']:.2f}%</div>"
    html += f"</td><td style='color:{'green' if avg_change >= 0 else 'red'};'>{avg_change:+.2f}%</td></tr></table>"

    if upcoming_earnings:
        html += "<h3 style='margin-top:20px;'>📅 Upcoming Earnings (Next 14 Days)</h3><ul>"
        for company, ticker, date_str, days_away in upcoming_earnings:
            if days_away == 0:
                label = "today"
            elif days_away == 1:
                label = "tomorrow"
            else:
                label = f"in {days_away} days"
            html += f"<li><b>{company}</b> ({ticker}) &mdash; {date_str} ({label})</li>"
        html += "</ul>"

    # Portfolio total value and gain/loss
    total_value = 0.0
    total_cost  = 0.0
    for company, stock in portfolio_data.items():
        shares = share_counts.get(company, 0)
        price  = stock.get("Price")
        buy    = buy_prices.get(company)
        if shares > 0 and isinstance(price, (int, float)):
            total_value += price * shares
            if isinstance(buy, (int, float)):
                total_cost += buy * shares

    if total_value > 0:
        total_gl     = total_value - total_cost
        total_gl_pct = (total_gl / total_cost * 100) if total_cost else 0
        gl_color     = "green" if total_gl >= 0 else "red"
        html += (
            "<div style='margin-top:20px; padding:12px 16px; background-color:white; "
            "border:1px solid #e2e8f0; border-radius:8px; display:flex; gap:40px;'>"
            f"<span><b>Portfolio Value:</b> ${total_value:,.0f}</span>"
            f"<span style='color:{gl_color};'><b>Total G/L:</b> ${total_gl:+,.0f} ({total_gl_pct:+.1f}%)</span>"
            "</div>"
        )

    html += "</div>"
    return html

def get_gradient_color(diff_pct):
    max_intensity = 30
    intensity = min(abs(diff_pct), max_intensity)
    alpha = round((intensity / max_intensity), 2)
    if diff_pct >= 0:
        return f"rgba(0, 128, 0, {alpha})"
    else:
        return f"rgba(255, 0, 0, {alpha})"

def get_ai_commentary(portfolio_data, market_gainers, market_losers):
    if not ANTHROPIC_API_KEY:
        return None
    try:
        lines = []
        for company, stock in portfolio_data.items():
            pct    = stock.get("% Change")
            price  = stock.get("Price")
            shares = share_counts.get(company, 0)
            buy    = buy_prices.get(company)
            if pct is not None and price is not None:
                total_gl = f"  total G/L ${(price - buy) * shares:+,.0f}" if shares and buy else ""
                lines.append(f"  {company}: {pct:+.2f}% @ ${price:.2f}{total_gl}")

        gainers_str = ", ".join([f"{s['Ticker']} +{s['% Change']:.2f}%" for s in market_gainers[:3]])
        losers_str  = ", ".join([f"{s['Ticker']} {s['% Change']:.2f}%"  for s in market_losers[:3]])

        stop_lines = []
        for company, stock in portfolio_data.items():
            stop = stop_limits.get(company)
            current_price = stock.get("Price")
            if stop is not None and isinstance(current_price, (int, float)):
                if current_price <= stop:
                    stop_lines.append(f"  {company}: STOP TRIGGERED — price ${current_price:.2f} at/below limit ${stop:.2f}")
                elif current_price <= stop * 1.05:
                    pct_away = ((current_price - stop) / stop) * 100
                    stop_lines.append(f"  {company}: NEAR STOP — price ${current_price:.2f} is {pct_away:.1f}% above limit ${stop:.2f}")

        stop_section = (
            "\n\nStop limits alert:\n" + "\n".join(stop_lines)
            if stop_lines else ""
        )

        prompt = (
            "You are a sharp, concise financial analyst writing a daily morning briefing for one person. "
            "Given their portfolio performance and today's market movers, write 3-4 sentences of direct, "
            "specific commentary. Call out notable movers by name, flag any stop limits that are triggered "
            "or close to triggering as an urgent priority, flag concentration risk if relevant, "
            "and give one actionable observation. No fluff, no disclaimers.\n\n"
            f"Portfolio today:\n" + "\n".join(lines) + stop_section + "\n\n"
            f"Market top gainers: {gainers_str}\n"
            f"Market top losers:  {losers_str}"
        )

        client  = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        message = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=350,
            messages=[{"role": "user", "content": prompt}]
        )
        return message.content[0].text
    except Exception as e:
        print(f"AI commentary failed: {e}")
        return None

def create_stock_table(title, stock_dict, include_buy_prices=True):
    sorted_stocks = dict(sorted(
        stock_dict.items(),
        key=lambda item: item[1]["% Change"] if item[1]["% Change"] is not None else -float('inf'),
        reverse=True,
    ))

    has_shares      = include_buy_prices and any(share_counts.get(c, 0) > 0 for c in stock_dict)
    has_stop_limits = include_buy_prices and any(stop_limits.get(c) is not None for c in stock_dict)
    # show alert distance column on watchlist only
    has_alerts      = (not include_buy_prices) and any(
        price_alerts.get(s.get("Ticker", "")) for s in stock_dict.values()
    )

    html  = f"<h2 style='color:#1E293B; margin-top:40px;'>{title}</h2>"
    html += "<table style='border-collapse:collapse; width:100%; margin-top:10px;'>"
    html += "<tr style='background-color:#0f172a; color:white;'><th style='padding:8px;'>Company</th>"
    if include_buy_prices:
        html += "<th style='padding:8px;'>Buy Price</th>"
    html += "<th style='padding:8px;'>Current Price</th><th style='padding:8px;'>% Change</th><th style='padding:8px;'>Dividend</th>"
    if include_buy_prices:
        html += "<th style='padding:8px;'>Status vs Buy</th>"
    if has_stop_limits:
        html += "<th style='padding:8px;'>Stop Limit</th>"
    if has_shares:
        html += "<th style='padding:8px;'>Gain / Loss ($)</th>"
    if has_alerts:
        html += "<th style='padding:8px;'>Alert Target</th>"
    html += "</tr>"

    for company, stock in sorted_stocks.items():
        buy_price      = buy_prices.get(company, "N/A")
        shares         = share_counts.get(company, 0)
        price          = format_number(stock["Price"]) if stock["Price"] is not None else "N/A"
        percent_change = stock["% Change"] if stock["% Change"] is not None else 0
        dividend       = stock["Dividend"]
        percent_class  = "color:green;" if percent_change >= 0 else "color:red;"

        html += "<tr style='background-color:#f8fafc;'>"
        html += f"<td style='padding:8px;'><b>{company}</b></td>"
        if include_buy_prices:
            html += f"<td style='padding:8px;'>${buy_price if buy_price == 'N/A' else f'{buy_price:,.2f}'}</td>"
        html += f"<td style='padding:8px;'>${price}</td>"
        html += f"<td style='padding:8px; {percent_class}'>{percent_change:+.2f}%</td>"
        html += f"<td style='padding:8px;'>{dividend}</td>"

        if include_buy_prices and isinstance(stock["Price"], (int, float)) and isinstance(buy_price, (int, float)):
            diff_pct = ((stock["Price"] - buy_price) / buy_price) * 100
            bg_color = get_gradient_color(diff_pct)
            html += f"<td style='padding:8px; background-color:{bg_color}; color:white; text-align:center;'>{diff_pct:+.2f}%</td>"
        elif include_buy_prices:
            html += "<td style='padding:8px; text-align:center;'>N/A</td>"

        if has_stop_limits:
            stop = stop_limits.get(company)
            current_price = stock["Price"]
            if stop is not None and isinstance(current_price, (int, float)):
                if current_price <= stop:
                    cell_style = "background-color:#dc2626; color:white; font-weight:bold; text-align:center;"
                    label = f"⚠ ${stop:,.2f} TRIGGERED"
                elif current_price <= stop * 1.05:
                    cell_style = "background-color:#f97316; color:white; font-weight:bold; text-align:center;"
                    label = f"⚡ ${stop:,.2f} NEAR"
                else:
                    cell_style = "text-align:center;"
                    label = f"${stop:,.2f}"
                html += f"<td style='padding:8px; {cell_style}'>{label}</td>"
            else:
                html += "<td style='padding:8px; text-align:center; color:#94a3b8;'>—</td>"

        if has_shares:
            if shares > 0 and isinstance(stock["Price"], (int, float)) and isinstance(buy_price, (int, float)):
                dollar_gl = (stock["Price"] - buy_price) * shares
                gl_color  = "color:green;" if dollar_gl >= 0 else "color:red;"
                html += f"<td style='padding:8px; {gl_color}'>${dollar_gl:+,.2f}</td>"
            else:
                html += "<td style='padding:8px;'>—</td>"

        if has_alerts:
            ticker     = stock.get("Ticker", "")
            alert_cfg  = price_alerts.get(ticker)
            cur        = stock.get("Price")
            if alert_cfg and isinstance(cur, (int, float)):
                target    = alert_cfg["target"]
                direction = alert_cfg["direction"]
                pct_away  = (cur - target) / target * 100
                if direction == "below":
                    if cur <= target:
                        cell_style = "color:green; font-weight:bold;"
                        label = f"✅ ${target:.2f} TRIGGERED"
                    elif pct_away <= 10:
                        cell_style = "color:#f97316; font-weight:bold;"
                        label = f"${target:.2f} ↓  {pct_away:.1f}% above"
                    else:
                        cell_style = "color:#64748b;"
                        label = f"${target:.2f} ↓  {pct_away:.1f}% above"
                else:
                    if cur >= target:
                        cell_style = "color:green; font-weight:bold;"
                        label = f"✅ ${target:.2f} TRIGGERED"
                    elif abs(pct_away) <= 10:
                        cell_style = "color:#f97316; font-weight:bold;"
                        label = f"${target:.2f} ↑  {abs(pct_away):.1f}% below"
                    else:
                        cell_style = "color:#64748b;"
                        label = f"${target:.2f} ↑  {abs(pct_away):.1f}% below"
                html += f"<td style='padding:8px; text-align:center; {cell_style}'>{label}</td>"
            else:
                html += "<td style='padding:8px; text-align:center; color:#94a3b8;'>—</td>"

        html += "</tr>"

    html += "</table>"
    return html

def create_email_content(portfolio_data, watchlist_data, focus_data, market_gainers, market_losers,
                         portfolio_news, upcoming_earnings, ai_commentary=None):
    now_str      = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    summary_html = create_summary_section(portfolio_data, watchlist_data, market_gainers, market_losers, upcoming_earnings)

    html  = "<html><body style='font-family:Arial, sans-serif; background-color:#f1f5f9;'>"
    html += "<div style='max-width:900px; margin:auto; background-color:white; padding:30px; border-radius:12px;'>"
    html += f"<h1>📈 Daily Market Dashboard</h1><p style='color:#64748b;'>Generated at: {now_str}</p>"

    if ai_commentary:
        html += (
            "<div style='background-color:#0f172a; color:#e2e8f0; border-radius:10px; padding:20px; margin-bottom:24px;'>"
            "<p style='margin:0; font-size:15px; line-height:1.6;'>"
            f"🤖 <b>AI Briefing:</b> {ai_commentary}"
            "</p></div>"
        )

    html += summary_html
    html += create_stock_table("Your Portfolio", portfolio_data, include_buy_prices=True)
    html += create_stock_table("Watchlist (Potential Buys)", watchlist_data, include_buy_prices=False)
    html += create_collapsible_news_section("📈 Portfolio Stock News", portfolio_news)

    html += "<h2 style='margin-top:40px;'>📰 Company Digest</h2>"
    for company, headlines in focus_data.items():
        html += f"<h3>{company}</h3><ul>"
        if headlines:
            for headline, url in headlines:
                html += f"<li>{headline} <a href='{url}' target='_blank'>🔗</a></li>"
        else:
            html += "<li>No major headlines found this week.</li>"
        html += "</ul>"

    html += "</div></body></html>"
    return html


# --- EMAIL SENDER ---
def send_email(content):
    msg = MIMEMultipart()
    msg["From"]    = EMAIL_ADDRESS
    msg["To"]      = TO_EMAIL
    msg["Subject"] = "Daily Market Dashboard"
    msg.attach(MIMEText(content, "html"))
    with smtplib.SMTP("smtp.gmail.com", 587) as server:
        server.starttls()
        server.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
        server.send_message(msg)


# --- JOBS ---
def job():
    portfolio_data = {c: get_stock_data(t, c) for c, t in tickers.items()}
    watchlist_data = {c: get_stock_data(t, c) for c, t in watchlist.items()}

    portfolio_news            = get_stock_news(tickers)
    focus_data                = get_focus_news()
    market_gainers, market_losers = get_market_top_movers()
    upcoming_earnings         = get_upcoming_earnings(tickers)
    ai_commentary             = get_ai_commentary(portfolio_data, market_gainers, market_losers)

    email_content = create_email_content(
        portfolio_data, watchlist_data, focus_data,
        market_gainers, market_losers,
        portfolio_news, upcoming_earnings, ai_commentary,
    )
    send_email(email_content)
    print("Email sent successfully!")

def alert_job():
    print(f"Checking price alerts at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    triggered = check_price_alerts()
    if triggered:
        print(f"Fired {len(triggered)} alert(s): {[a['label'] for a in triggered]}")
    else:
        print("No alerts triggered.")


if __name__ == "__main__":
    if "--alerts" in sys.argv:
        alert_job()
    else:
        job()
