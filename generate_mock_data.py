# ── generate_mock_data.py — SQLite version ────────────────────────
import sqlite3
import uuid
import random
from datetime import datetime, timedelta
from db import get_connection, DB_PATH

# ── Sample data pools ─────────────────────────────────────────────
FIRST_NAMES = [
    "James", "Mary", "John", "Patricia", "Robert", "Jennifer",
    "Michael", "Linda", "William", "Barbara", "David", "Elizabeth",
    "Richard", "Susan", "Joseph", "Jessica", "Thomas", "Sarah",
    "Charles", "Karen", "Christopher", "Lisa", "Daniel", "Nancy",
    "Matthew", "Betty", "Anthony", "Margaret", "Mark", "Sandra"
]

LAST_NAMES = [
    "Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia",
    "Miller", "Davis", "Rodriguez", "Martinez", "Hernandez", "Lopez",
    "Gonzalez", "Wilson", "Anderson", "Thomas", "Taylor", "Moore",
    "Jackson", "Martin", "Lee", "Perez", "Thompson", "White",
    "Harris", "Sanchez", "Clark", "Ramirez", "Lewis", "Robinson"
]

CITIES = [
    "Toronto", "Vancouver", "Montreal", "Calgary", "Ottawa",
    "Edmonton", "Winnipeg", "Quebec City", "Hamilton", "Kitchener"
]

SEGMENTS = [
    "RETAIL", "WEALTH", "CORPORATE",
    "SMALL_BUSINESS", "PRIVATE_BANKING"
]

RISK_PROFILES = ["CONSERVATIVE", "MODERATE", "GROWTH", "AGGRESSIVE"]

RELATIONSHIP_MANAGERS = [
    "Sarah Mitchell", "James Wong", "Emily Chen",
    "David Kumar", "Rachel Thompson", "Michael O'Brien"
]

SECURITIES = [
    ("Royal Bank of Canada",        "RY.TO",   "EQUITIES", "Financials"),
    ("TD Bank",                     "TD.TO",   "EQUITIES", "Financials"),
    ("Shopify Inc",                 "SHOP.TO", "EQUITIES", "Technology"),
    ("Suncor Energy",               "SU.TO",   "EQUITIES", "Energy"),
    ("Canadian Natural Resources",  "CNQ.TO",  "EQUITIES", "Energy"),
    ("Brookfield Asset Management", "BAM.TO",  "EQUITIES", "Financials"),
    ("Canadian Pacific Railway",    "CP.TO",   "EQUITIES", "Industrials"),
    ("BCE Inc",                     "BCE.TO",  "EQUITIES", "Telecom"),
    ("Nutrien Ltd",                 "NTR.TO",  "EQUITIES", "Materials"),
    ("Manulife Financial",          "MFC.TO",  "EQUITIES", "Financials"),
    ("iShares Core Cdn Bond ETF",   "XBB.TO",  "BONDS",    "Fixed Income"),
    ("Vanguard Cdn Aggregate Bond", "VAB.TO",  "BONDS",    "Fixed Income"),
    ("BMO Short Corporate Bond",    "ZCS.TO",  "BONDS",    "Fixed Income"),
    ("iShares S&P/TSX 60 ETF",     "XIU.TO",  "EQUITIES", "Diversified"),
    ("iShares MSCI World ETF",      "XWD.TO",  "EQUITIES", "International"),
    ("Cdn Apartment Properties",    "CAR.UN",  "REAL_ESTATE","Real Estate"),
    ("RioCan REIT",                 "REI.UN",  "REAL_ESTATE","Real Estate"),
    ("US Dollar Cash Position",     "USD.CASH","CASH",     "Cash"),
    ("CAD Cash Position",           "CAD.CASH","CASH",     "Cash"),
    ("Gold ETF",                    "CGL.TO",  "COMMODITIES","Commodities"),
]

PORTFOLIO_TYPES = [
    ("Growth Portfolio",      "TFSA"),
    ("Income Portfolio",      "RRSP"),
    ("Balanced Portfolio",    "Non-Registered"),
    ("Conservative Portfolio","RRSP"),
    ("Aggressive Growth",     "TFSA"),
]

# ── Helpers ───────────────────────────────────────────────────────
def random_name():
    return f"{random.choice(FIRST_NAMES)} {random.choice(LAST_NAMES)}"

def random_email(name):
    parts = name.lower().split()
    domains = ["gmail.com","outlook.com","yahoo.ca","rogers.com","bell.ca"]
    return f"{parts[0]}.{parts[1]}@{random.choice(domains)}"

def random_aum(segment):
    ranges = {
        "RETAIL":          (10_000,    200_000),
        "WEALTH":          (200_000,  2_000_000),
        "CORPORATE":       (500_000,  5_000_000),
        "SMALL_BUSINESS":  (50_000,    500_000),
        "PRIVATE_BANKING": (2_000_000,20_000_000),
    }
    lo, hi = ranges.get(segment, (10_000, 1_000_000))
    return round(random.uniform(lo, hi), 2)

# ── Main generator ────────────────────────────────────────────────
def generate_mock_data(num_customers=1000):
    conn   = get_connection()
    cursor = conn.cursor()

    # Clear existing mock data
    cursor.executescript("""
        DELETE FROM HOLDINGS;
        DELETE FROM PORTFOLIOS;
        DELETE FROM CUSTOMERS;
    """)
    conn.commit()
    print(f"Cleared existing data. Generating {num_customers} customers...")

    customers_inserted  = 0
    portfolios_inserted = 0
    holdings_inserted   = 0

    for i in range(num_customers):
        # ── Customer ──────────────────────────────────────────────
        customer_id  = str(uuid.uuid4())
        name         = random_name()
        segment      = random.choice(SEGMENTS)
        risk_profile = random.choice(RISK_PROFILES)
        aum          = random_aum(segment)
        city         = random.choice(CITIES)
        email        = random_email(name)
        rm           = random.choice(RELATIONSHIP_MANAGERS)

        cursor.execute("""
            INSERT OR IGNORE INTO CUSTOMERS
                (CUSTOMER_ID, CUSTOMER_NAME, SEGMENT, RISK_PROFILE,
                 TOTAL_AUM, CITY, EMAIL, CONTACT_NAME,
                 RELATIONSHIP_MANAGER)
            VALUES (?,?,?,?,?,?,?,?,?)
        """, (customer_id, name, segment, risk_profile,
              aum, city, email, name, rm))

        # ── Portfolios (1-3 per customer) ─────────────────────────
        num_portfolios = random.randint(1, 3)
        portfolio_ids  = []

        for _ in range(num_portfolios):
            ptype, acct = random.choice(PORTFOLIO_TYPES)
            port_id     = str(uuid.uuid4())
            cursor.execute("""
                INSERT INTO PORTFOLIOS
                    (PORTFOLIO_ID, CUSTOMER_ID,
                     PORTFOLIO_NAME, ACCOUNT_TYPE)
                VALUES (?,?,?,?)
            """, (port_id, customer_id, ptype, acct))
            portfolio_ids.append(port_id)
            portfolios_inserted += 1

        # ── Holdings (3-8 per portfolio) ──────────────────────────
        portfolio_value = aum / len(portfolio_ids)
        for port_id in portfolio_ids:
            securities     = random.sample(SECURITIES, random.randint(3, 8))
            num_securities = len(securities)
            weights        = [random.random() for _ in range(num_securities)]
            weight_sum     = sum(weights)
            weights        = [w / weight_sum for w in weights]

            for sec, weight in zip(securities, weights):
                sec_name, ticker, asset_class, sector = sec
                value        = round(portfolio_value * weight, 2)
                price        = round(random.uniform(10, 500), 2)
                quantity     = round(value / price, 4)
                avg_cost     = round(price * random.uniform(0.7, 1.3), 2)
                cost_basis   = avg_cost * quantity
                unrealized   = round(value - cost_basis, 2)
                weight_pct   = round(weight * 100, 2)

                cursor.execute("""
                    INSERT INTO HOLDINGS
                        (HOLDING_ID, PORTFOLIO_ID, SECURITY_NAME,
                         TICKER, ASSET_CLASS, SECTOR, QUANTITY,
                         AVERAGE_COST, CURRENT_PRICE, CURRENT_VALUE,
                         UNREALIZED_PNL, WEIGHT_PCT)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                """, (
                    str(uuid.uuid4()), port_id, sec_name,
                    ticker, asset_class, sector, quantity,
                    avg_cost, price, value,
                    unrealized, weight_pct
                ))
                holdings_inserted += 1

        customers_inserted += 1

        if (i + 1) % 100 == 0:
            conn.commit()
            print(f"   {i+1}/{num_customers} customers done...")

    conn.commit()
    cursor.close()
    conn.close()

    print()
    print("=" * 50)
    print(f"✅ Mock data generation complete!")
    print(f"   Customers:  {customers_inserted:,}")
    print(f"   Portfolios: {portfolios_inserted:,}")
    print(f"   Holdings:   {holdings_inserted:,}")
    print(f"   Database:   {DB_PATH}")
    print("=" * 50)

if __name__ == "__main__":
    generate_mock_data(1000)