"""
=============================================================
Canadian Bank POC — Mock Data Generator
=============================================================
Generates realistic mock data for:
  - 1,000 customers  (INTERNAL_DATA.CUSTOMERS)
  - ~1,500 portfolios (INTERNAL_DATA.PORTFOLIOS)
  - ~6,000 holdings  (INTERNAL_DATA.HOLDINGS)

Run:
    cd bank_poc
    venv\Scripts\activate
    pip install faker --quiet
    python generate_mock_data.py
=============================================================
"""

import snowflake.connector
import random
import uuid
from datetime import datetime, timedelta
from dotenv import load_dotenv
import os

load_dotenv()

# ── Snowflake Connection ──────────────────────────────────────────
conn = snowflake.connector.connect(
    account   = os.getenv('SNOWFLAKE_ACCOUNT'),
    user      = os.getenv('SNOWFLAKE_USER'),
    password  = os.getenv('SNOWFLAKE_PASSWORD'),
    database  = os.getenv('SNOWFLAKE_DATABASE'),
    schema    = 'INTERNAL_DATA',
    warehouse = os.getenv('SNOWFLAKE_WAREHOUSE')
)
cursor = conn.cursor()
print("✅ Connected to Snowflake")

# =============================================================
# REFERENCE DATA
# =============================================================

# Canadian first and last names
FIRST_NAMES = [
    "James", "Olivia", "Liam", "Emma", "Noah", "Ava", "William", "Sophia",
    "Benjamin", "Isabella", "Lucas", "Mia", "Henry", "Charlotte", "Alexander",
    "Amelia", "Mason", "Harper", "Ethan", "Evelyn", "Daniel", "Abigail",
    "Matthew", "Emily", "Aiden", "Elizabeth", "Logan", "Sofia", "Jackson",
    "Avery", "Sebastian", "Ella", "Jack", "Scarlett", "Owen", "Grace",
    "Samuel", "Chloe", "Ryan", "Victoria", "Nathan", "Riley", "Adam",
    "Aria", "Tyler", "Lily", "Andrew", "Aurora", "Joshua", "Zoey",
    "Mohammed", "Fatima", "Amir", "Layla", "Ali", "Noor", "Hassan", "Sara",
    "Ranjit", "Priya", "Arjun", "Ananya", "Vikram", "Deepa", "Raj", "Meera",
    "Wei", "Mei", "Jian", "Ling", "Chen", "Xiao", "Tao", "Yan",
    "Pierre", "Marie", "Jean", "Anne", "Michel", "Sophie", "François", "Claire",
    "Patrick", "Siobhan", "Brendan", "Aoife", "Connor", "Niamh", "Sean", "Erin"
]

LAST_NAMES = [
    "Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller",
    "Davis", "Wilson", "Anderson", "Taylor", "Thomas", "Jackson", "White",
    "Harris", "Martin", "Thompson", "Young", "Robinson", "Lewis", "Walker",
    "Hall", "Allen", "Wright", "Scott", "Green", "Baker", "Adams", "Nelson",
    "Carter", "Mitchell", "Perez", "Roberts", "Turner", "Phillips", "Campbell",
    "Parker", "Evans", "Edwards", "Collins", "Stewart", "Morris", "Rogers",
    "Peterson", "Cook", "Morgan", "Cooper", "Reed", "Bailey", "Bell",
    "Patel", "Singh", "Kumar", "Sharma", "Gupta", "Shah", "Mehta", "Chopra",
    "Chen", "Wang", "Liu", "Zhang", "Yang", "Huang", "Wu", "Li",
    "Tremblay", "Gagnon", "Côté", "Bouchard", "Gauthier", "Morin", "Lavoie",
    "MacDonald", "MacLeod", "MacKenzie", "Murray", "Campbell", "Robertson",
    "O'Brien", "Murphy", "Kelly", "Walsh", "Ryan", "Byrne", "Kennedy"
]

# Corporate name parts
CORP_PREFIXES = [
    "Alpha", "Beta", "Apex", "Summit", "Northern", "Pacific", "Atlantic",
    "Canadian", "Global", "National", "Premier", "Elite", "Pinnacle",
    "Sterling", "Maple", "Cedar", "Horizon", "Vertex", "Nexus", "Vantage",
    "Granite", "Ironwood", "Lakeside", "Ridgeline", "Westshore", "Northgate",
    "Dominion", "Royal", "Crown", "Heritage", "Centennial", "Frontier",
    "Cascade", "Meridian", "Pathfinder", "Bridgewater", "Clearwater", "Keystone"
]

CORP_SUFFIXES = [
    "Capital", "Holdings", "Ventures", "Group", "Partners", "Industries",
    "Enterprises", "Solutions", "Resources", "Properties", "Investments",
    "Management", "Corporation", "Associates", "Consulting", "Services",
    "Technologies", "Energy", "Developments", "Realty", "Fund", "Asset Management"
]

CORP_TYPES = ["Inc.", "Ltd.", "Corp.", "LP", "LLC"]

# Canadian cities
CITIES = [
    "Toronto", "Vancouver", "Montreal", "Calgary", "Edmonton", "Ottawa",
    "Winnipeg", "Quebec City", "Hamilton", "Kitchener", "London", "Halifax",
    "Victoria", "Windsor", "Saskatoon", "Regina", "Kelowna", "Barrie",
    "Mississauga", "Brampton", "Markham", "Richmond Hill", "Oakville", "Burlington"
]

PROVINCES = {
    "Toronto": "ON", "Mississauga": "ON", "Brampton": "ON",
    "Markham": "ON", "Richmond Hill": "ON", "Oakville": "ON",
    "Burlington": "ON", "Hamilton": "ON", "Kitchener": "ON",
    "London": "ON", "Barrie": "ON", "Windsor": "ON",
    "Vancouver": "BC", "Victoria": "BC", "Kelowna": "BC",
    "Montreal": "QC", "Quebec City": "QC",
    "Calgary": "AB", "Edmonton": "AB",
    "Ottawa": "ON", "Winnipeg": "MB",
    "Halifax": "NS", "Saskatoon": "SK", "Regina": "SK"
}

# Segments
SEGMENTS = {
    'RETAIL':          0.35,
    'WEALTH':          0.25,
    'CORPORATE':       0.20,
    'SMALL_BUSINESS':  0.12,
    'PRIVATE_BANKING': 0.08
}

# Portfolio types per segment
PORTFOLIO_TYPES = {
    'RETAIL':          ['RRSP', 'TFSA', 'Non-Registered'],
    'WEALTH':          ['RRSP', 'TFSA', 'Non-Registered', 'RESP', 'LIRA'],
    'CORPORATE':       ['Corporate Investment', 'Operating Account Portfolio', 'Pension Fund'],
    'SMALL_BUSINESS':  ['Business Investment', 'RRSP', 'TFSA'],
    'PRIVATE_BANKING': ['Private Portfolio', 'RRSP', 'TFSA', 'Non-Registered', 'RESP', 'Trust Account']
}

# Canadian securities universe
SECURITIES = [
    # Big 6 Banks
    {"ticker": "RY.TO",   "name": "Royal Bank of Canada",          "asset_class": "EQUITIES",    "sector": "FINANCIALS",  "price_range": (120, 145)},
    {"ticker": "TD.TO",   "name": "Toronto-Dominion Bank",         "asset_class": "EQUITIES",    "sector": "FINANCIALS",  "price_range": (75, 92)},
    {"ticker": "BNS.TO",  "name": "Bank of Nova Scotia",           "asset_class": "EQUITIES",    "sector": "FINANCIALS",  "price_range": (58, 74)},
    {"ticker": "BMO.TO",  "name": "Bank of Montreal",              "asset_class": "EQUITIES",    "sector": "FINANCIALS",  "price_range": (115, 138)},
    {"ticker": "CM.TO",   "name": "CIBC",                          "asset_class": "EQUITIES",    "sector": "FINANCIALS",  "price_range": (55, 72)},
    {"ticker": "NA.TO",   "name": "National Bank of Canada",       "asset_class": "EQUITIES",    "sector": "FINANCIALS",  "price_range": (95, 118)},
    # Energy
    {"ticker": "SU.TO",   "name": "Suncor Energy",                 "asset_class": "EQUITIES",    "sector": "ENERGY",      "price_range": (45, 62)},
    {"ticker": "ENB.TO",  "name": "Enbridge Inc.",                 "asset_class": "EQUITIES",    "sector": "ENERGY",      "price_range": (48, 58)},
    {"ticker": "CNQ.TO",  "name": "Canadian Natural Resources",    "asset_class": "EQUITIES",    "sector": "ENERGY",      "price_range": (72, 92)},
    {"ticker": "CVE.TO",  "name": "Cenovus Energy",                "asset_class": "EQUITIES",    "sector": "ENERGY",      "price_range": (18, 28)},
    {"ticker": "TRP.TO",  "name": "TC Energy Corp",                "asset_class": "EQUITIES",    "sector": "ENERGY",      "price_range": (52, 68)},
    # Tech
    {"ticker": "SHOP.TO", "name": "Shopify Inc.",                  "asset_class": "EQUITIES",    "sector": "TECHNOLOGY",  "price_range": (85, 130)},
    {"ticker": "CSU.TO",  "name": "Constellation Software",        "asset_class": "EQUITIES",    "sector": "TECHNOLOGY",  "price_range": (3200, 4100)},
    {"ticker": "OTEX.TO", "name": "Open Text Corporation",         "asset_class": "EQUITIES",    "sector": "TECHNOLOGY",  "price_range": (38, 52)},
    # Telecom
    {"ticker": "BCE.TO",  "name": "BCE Inc.",                      "asset_class": "EQUITIES",    "sector": "TELECOM",     "price_range": (42, 56)},
    {"ticker": "T.TO",    "name": "TELUS Corporation",             "asset_class": "EQUITIES",    "sector": "TELECOM",     "price_range": (20, 28)},
    {"ticker": "RCI-B.TO","name": "Rogers Communications",         "asset_class": "EQUITIES",    "sector": "TELECOM",     "price_range": (55, 72)},
    # Rail & Transport
    {"ticker": "CNR.TO",  "name": "Canadian National Railway",     "asset_class": "EQUITIES",    "sector": "INDUSTRIAL",  "price_range": (155, 185)},
    {"ticker": "CP.TO",   "name": "Canadian Pacific Kansas City",  "asset_class": "EQUITIES",    "sector": "INDUSTRIAL",  "price_range": (98, 125)},
    # Mining
    {"ticker": "ABX.TO",  "name": "Barrick Gold Corporation",      "asset_class": "EQUITIES",    "sector": "MATERIALS",   "price_range": (22, 32)},
    {"ticker": "WPM.TO",  "name": "Wheaton Precious Metals",       "asset_class": "EQUITIES",    "sector": "MATERIALS",   "price_range": (58, 82)},
    {"ticker": "NTR.TO",  "name": "Nutrien Ltd.",                  "asset_class": "EQUITIES",    "sector": "MATERIALS",   "price_range": (65, 85)},
    # Real Estate
    {"ticker": "REI-UN.TO","name": "RioCan REIT",                  "asset_class": "REAL_ESTATE", "sector": "REITS",       "price_range": (17, 22)},
    {"ticker": "HR-UN.TO", "name": "H&R REIT",                     "asset_class": "REAL_ESTATE", "sector": "REITS",       "price_range": (10, 15)},
    {"ticker": "CAR-UN.TO","name": "Canadian Apartment REIT",      "asset_class": "REAL_ESTATE", "sector": "REITS",       "price_range": (45, 58)},
    # ETFs
    {"ticker": "XIU.TO",  "name": "iShares S&P/TSX 60 ETF",       "asset_class": "ETF",         "sector": "BROAD_MARKET","price_range": (30, 38)},
    {"ticker": "XBB.TO",  "name": "iShares Core Canadian Bond ETF","asset_class": "BONDS",       "sector": "FIXED_INCOME","price_range": (28, 33)},
    {"ticker": "VCN.TO",  "name": "Vanguard FTSE Canada ETF",      "asset_class": "ETF",         "sector": "BROAD_MARKET","price_range": (38, 46)},
    {"ticker": "XSP.TO",  "name": "iShares Core S&P 500 ETF (CAD)","asset_class": "ETF",        "sector": "US_EQUITY",   "price_range": (58, 78)},
    {"ticker": "ZAG.TO",  "name": "BMO Aggregate Bond ETF",        "asset_class": "BONDS",       "sector": "FIXED_INCOME","price_range": (14, 17)},
    # Fixed Income
    {"ticker": "CGB.TO",  "name": "Canada Government Bond 10Y",    "asset_class": "BONDS",       "sector": "GOVERNMENT",  "price_range": (95, 105)},
    {"ticker": "CGOV.TO", "name": "Canada Government Bond 5Y",     "asset_class": "BONDS",       "sector": "GOVERNMENT",  "price_range": (97, 103)},
    # Insurance
    {"ticker": "MFC.TO",  "name": "Manulife Financial",            "asset_class": "EQUITIES",    "sector": "FINANCIALS",  "price_range": (28, 38)},
    {"ticker": "SLF.TO",  "name": "Sun Life Financial",            "asset_class": "EQUITIES",    "sector": "FINANCIALS",  "price_range": (65, 82)},
    # Consumer
    {"ticker": "L.TO",    "name": "Loblaw Companies",              "asset_class": "EQUITIES",    "sector": "CONSUMER",    "price_range": (145, 185)},
    {"ticker": "MRU.TO",  "name": "Metro Inc.",                    "asset_class": "EQUITIES",    "sector": "CONSUMER",    "price_range": (75, 92)},
    {"ticker": "ATD.TO",  "name": "Alimentation Couche-Tard",      "asset_class": "EQUITIES",    "sector": "CONSUMER",    "price_range": (75, 92)},
]

# AUM ranges by segment
AUM_RANGES = {
    'RETAIL':          (5_000,     150_000),
    'WEALTH':          (250_000,   2_000_000),
    'CORPORATE':       (1_000_000, 50_000_000),
    'SMALL_BUSINESS':  (50_000,    500_000),
    'PRIVATE_BANKING': (5_000_000, 100_000_000)
}

# Holdings count per portfolio by segment
HOLDINGS_COUNT = {
    'RETAIL':          (2, 5),
    'WEALTH':          (5, 12),
    'CORPORATE':       (8, 18),
    'SMALL_BUSINESS':  (3, 8),
    'PRIVATE_BANKING': (12, 25)
}

# =============================================================
# HELPER FUNCTIONS
# =============================================================

def weighted_choice(choices_dict):
    """Pick a key from dict where values are weights"""
    keys   = list(choices_dict.keys())
    weights = list(choices_dict.values())
    return random.choices(keys, weights=weights, k=1)[0]

def random_date(years_back=5):
    """Random date within last N years"""
    days = random.randint(0, years_back * 365)
    return datetime.now() - timedelta(days=days)

def generate_phone():
    area = random.choice([
        '416','647','437','905','289','365',  # Toronto area
        '604','778','236',                     # Vancouver
        '514','438','450',                     # Montreal
        '403','587','825',                     # Calgary
        '780','587',                           # Edmonton
        '613','343',                           # Ottawa
    ])
    return f"+1 ({area}) {random.randint(200,999)}-{random.randint(1000,9999)}"

def generate_email(name, company=None):
    name_clean = name.lower().replace(' ', '.').replace("'", '')
    domains = ['gmail.com','outlook.com','hotmail.com','yahoo.ca','rogers.com','bell.net']
    if company:
        domain = company.lower().replace(' ', '').replace('.','')[:12] + '.ca'
    else:
        domain = random.choice(domains)
    return f"{name_clean}@{domain}"

def get_portfolio_names(segment):
    """Return 1-3 portfolio names for a customer"""
    options = PORTFOLIO_TYPES[segment]
    count   = random.choices(
        [1, 2, 3],
        weights=[
            0.4 if segment == 'RETAIL' else 0.2,
            0.4,
            0.2 if segment == 'RETAIL' else 0.4
        ]
    )[0]
    return random.sample(options, min(count, len(options)))

def get_securities_for_portfolio(segment, asset_class_hint=None):
    """Pick realistic securities for a portfolio"""
    n_min, n_max = HOLDINGS_COUNT[segment]
    count = random.randint(n_min, n_max)

    # Weight securities by segment preference
    if segment in ('RETAIL',):
        # Retail prefers ETFs and blue chip
        pool = [s for s in SECURITIES if s['asset_class'] in ('ETF', 'BONDS', 'EQUITIES')]
        weights = [3 if s['asset_class'] == 'ETF' else
                   2 if s['sector'] == 'FINANCIALS' else 1 for s in pool]
    elif segment == 'PRIVATE_BANKING':
        # Private banking: diversified across everything
        pool    = SECURITIES
        weights = [1] * len(pool)
    elif segment == 'CORPORATE':
        # Corporate: bonds + blue chip equities
        pool = [s for s in SECURITIES if s['asset_class'] in ('BONDS', 'EQUITIES', 'ETF')]
        weights = [3 if s['asset_class'] == 'BONDS' else 1 for s in pool]
    elif segment == 'WEALTH':
        # Wealth: mix of equities and ETFs
        pool    = [s for s in SECURITIES if s['asset_class'] in ('EQUITIES', 'ETF', 'BONDS', 'REAL_ESTATE')]
        weights = [1] * len(pool)
    else:
        pool    = [s for s in SECURITIES if s['asset_class'] in ('EQUITIES', 'ETF', 'BONDS')]
        weights = [1] * len(pool)

    selected = random.choices(pool, weights=weights, k=count * 3)
    # Deduplicate
    seen = set()
    unique = []
    for s in selected:
        if s['ticker'] not in seen:
            seen.add(s['ticker'])
            unique.append(s)
        if len(unique) >= count:
            break
    return unique

# =============================================================
# STEP 1 — CLEAR EXISTING MOCK DATA
# =============================================================
print("\n🗑️  Clearing existing internal data...")

cursor.execute("DELETE FROM BANK_POC.INTERNAL_DATA.HOLDINGS")
cursor.execute("DELETE FROM BANK_POC.INTERNAL_DATA.PORTFOLIOS")
cursor.execute("DELETE FROM BANK_POC.INTERNAL_DATA.CUSTOMERS")
conn.commit()
print("   ✅ Cleared CUSTOMERS, PORTFOLIOS, HOLDINGS")

# =============================================================
# STEP 2 — GENERATE CUSTOMERS
# =============================================================
print("\n👥 Generating 1,000 customers...")

customers   = []
TOTAL_CUSTOMERS = 1000

# Split by segment
segment_counts = {
    'RETAIL':          350,
    'WEALTH':          250,
    'CORPORATE':       200,
    'SMALL_BUSINESS':  120,
    'PRIVATE_BANKING':  80
}

for segment, count in segment_counts.items():
    for i in range(count):
        customer_id = str(uuid.uuid4())
        city        = random.choice(CITIES)
        province    = PROVINCES.get(city, 'ON')

        if segment == 'CORPORATE':
            # Corporate customer — company name
            name = (
                random.choice(CORP_PREFIXES) + " " +
                random.choice(CORP_SUFFIXES) + " " +
                random.choice(CORP_TYPES)
            )
            contact_name = random.choice(FIRST_NAMES) + " " + random.choice(LAST_NAMES)
            email        = generate_email(
                contact_name.lower().replace(' ', '.'),
                name
            )
        elif segment == 'SMALL_BUSINESS':
            # Small business — owner name + business
            owner = random.choice(FIRST_NAMES) + " " + random.choice(LAST_NAMES)
            biz_types = [
                "Consulting", "Services", "Solutions", "Enterprises",
                "Group", "Professional Corp.", "Contracting", "Trading"
            ]
            name         = owner + " " + random.choice(biz_types)
            contact_name = owner
            email        = generate_email(owner.lower().replace(' ', '.'))
        else:
            # Individual
            first = random.choice(FIRST_NAMES)
            last  = random.choice(LAST_NAMES)
            name  = first + " " + last
            contact_name = name
            email        = generate_email(name)

        aum_min, aum_max = AUM_RANGES[segment]
        total_aum        = round(random.uniform(aum_min, aum_max), 2)
        onboard_date     = random_date(years_back=12)

        risk_profiles = {
            'RETAIL':          ['CONSERVATIVE', 'MODERATE'],
            'WEALTH':          ['MODERATE', 'GROWTH', 'AGGRESSIVE'],
            'CORPORATE':       ['CONSERVATIVE', 'MODERATE'],
            'SMALL_BUSINESS':  ['MODERATE', 'GROWTH'],
            'PRIVATE_BANKING': ['GROWTH', 'AGGRESSIVE', 'MODERATE']
        }
        risk = random.choice(risk_profiles[segment])

        relationship_mgrs = [
            "Sarah Mitchell", "David Chen", "Jennifer Walsh",
            "Michael Patel", "Amanda Torres", "Robert MacLeod",
            "Christine Dubois", "Kevin Sharma", "Lisa Tremblay",
            "James O'Brien", "Rachel Kim", "Andrew Singh"
        ]

        customers.append((
            customer_id,
            name,
            segment,
            email,
            generate_phone(),
            city + ", " + province,
            total_aum,
            risk,
            contact_name,
            random.choice(relationship_mgrs),
            onboard_date.strftime('%Y-%m-%d')
        ))

# Batch insert customers
print(f"   Inserting {len(customers)} customers into Snowflake...")
cursor.executemany("""
    INSERT INTO BANK_POC.INTERNAL_DATA.CUSTOMERS
        (CUSTOMER_ID, CUSTOMER_NAME, SEGMENT, EMAIL, PHONE,
         CITY, TOTAL_AUM, RISK_PROFILE, CONTACT_NAME,
         RELATIONSHIP_MANAGER, ONBOARDING_DATE)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
""", customers)
conn.commit()
print(f"   ✅ Inserted {len(customers)} customers")

# =============================================================
# STEP 3 — GENERATE PORTFOLIOS
# =============================================================
print("\n💼 Generating portfolios...")

portfolios       = []
portfolio_lookup = {}  # customer_id → [(portfolio_id, portfolio_name, aum)]

for cust in customers:
    customer_id  = cust[0]
    segment      = cust[2]
    total_aum    = cust[6]

    port_names = get_portfolio_names(segment)
    # Split AUM across portfolios
    splits     = [random.random() for _ in port_names]
    total_split = sum(splits)
    splits     = [s / total_split for s in splits]

    port_list = []
    for j, pname in enumerate(port_names):
        portfolio_id  = str(uuid.uuid4())
        port_aum      = round(total_aum * splits[j], 2)
        inception_date = random_date(years_back=10)

        portfolios.append((
            portfolio_id,
            customer_id,
            pname,
            segment,
            port_aum,
            inception_date.strftime('%Y-%m-%d')
        ))
        port_list.append((portfolio_id, pname, port_aum))

    portfolio_lookup[customer_id] = port_list

# Batch insert portfolios
print(f"   Inserting {len(portfolios)} portfolios into Snowflake...")
cursor.executemany("""
    INSERT INTO BANK_POC.INTERNAL_DATA.PORTFOLIOS
        (PORTFOLIO_ID, CUSTOMER_ID, PORTFOLIO_NAME,
         PORTFOLIO_TYPE, TOTAL_VALUE, INCEPTION_DATE)
    VALUES (%s, %s, %s, %s, %s, %s)
""", portfolios)
conn.commit()
print(f"   ✅ Inserted {len(portfolios)} portfolios")

# =============================================================
# STEP 4 — GENERATE HOLDINGS
# =============================================================
print("\n📊 Generating holdings...")

holdings = []

for cust in customers:
    customer_id = cust[0]
    segment     = cust[2]

    for (portfolio_id, pname, port_aum) in portfolio_lookup[customer_id]:
        securities = get_securities_for_portfolio(segment)

        # Split portfolio AUM across holdings
        if not securities:
            continue

        splits      = [random.random() for _ in securities]
        total_split = sum(splits)
        splits      = [s / total_split for s in splits]

        for k, sec in enumerate(securities):
            holding_id   = str(uuid.uuid4())
            price        = round(random.uniform(*sec['price_range']), 2)
            holding_value = round(port_aum * splits[k], 2)
            quantity     = max(1, int(holding_value / price))
            avg_cost     = round(price * random.uniform(0.75, 1.15), 2)
            mkt_value    = round(quantity * price, 2)
            unrealized   = round(mkt_value - (quantity * avg_cost), 2)
            weight_pct   = round(splits[k] * 100, 2)

            holdings.append((
                holding_id,
                portfolio_id,
                sec['ticker'],
                sec['name'],
                sec['asset_class'],
                sec['sector'],
                quantity,
                avg_cost,
                price,
                mkt_value,
                unrealized,
                weight_pct
            ))

# Batch insert in chunks of 500
print(f"   Inserting {len(holdings)} holdings into Snowflake...")
CHUNK = 500
for i in range(0, len(holdings), CHUNK):
    batch = holdings[i:i + CHUNK]
    cursor.executemany("""
        INSERT INTO BANK_POC.INTERNAL_DATA.HOLDINGS
            (HOLDING_ID, PORTFOLIO_ID, TICKER, SECURITY_NAME,
             ASSET_CLASS, SECTOR, QUANTITY, AVERAGE_COST,
             CURRENT_PRICE, CURRENT_VALUE, UNREALIZED_PNL, WEIGHT_PCT)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    """, batch)
    conn.commit()
    print(f"   ...inserted {min(i + CHUNK, len(holdings))}/{len(holdings)}")

print(f"   ✅ Inserted {len(holdings)} holdings")

# =============================================================
# STEP 5 — VERIFY
# =============================================================
print("\n📋 Verification:")

cursor.execute("SELECT COUNT(*) FROM BANK_POC.INTERNAL_DATA.CUSTOMERS")
print(f"   CUSTOMERS  : {cursor.fetchone()[0]:,}")

cursor.execute("SELECT COUNT(*) FROM BANK_POC.INTERNAL_DATA.PORTFOLIOS")
print(f"   PORTFOLIOS : {cursor.fetchone()[0]:,}")

cursor.execute("SELECT COUNT(*) FROM BANK_POC.INTERNAL_DATA.HOLDINGS")
print(f"   HOLDINGS   : {cursor.fetchone()[0]:,}")

# Breakdown by segment
cursor.execute("""
    SELECT SEGMENT, COUNT(*) AS CNT,
           TO_CHAR(SUM(TOTAL_AUM), '999,999,999,999') AS TOTAL_AUM
    FROM BANK_POC.INTERNAL_DATA.CUSTOMERS
    GROUP BY SEGMENT ORDER BY CNT DESC
""")
print("\n   Customers by Segment:")
for row in cursor.fetchall():
    print(f"   {row[0]:<20} {row[1]:>5} customers   AUM: ${row[2]}")

cursor.execute("""
    SELECT RISK_PROFILE, COUNT(*) AS CNT
    FROM BANK_POC.INTERNAL_DATA.CUSTOMERS
    GROUP BY RISK_PROFILE ORDER BY CNT DESC
""")
print("\n   Customers by Risk Profile:")
for row in cursor.fetchall():
    print(f"   {row[0]:<20} {row[1]:>5} customers")

cursor.execute("""
    SELECT ASSET_CLASS, COUNT(*) AS CNT,
           TO_CHAR(SUM(CURRENT_VALUE), '999,999,999,999') AS TOTAL_VALUE
    FROM BANK_POC.INTERNAL_DATA.HOLDINGS
    GROUP BY ASSET_CLASS ORDER BY CNT DESC
""")
print("\n   Holdings by Asset Class:")
for row in cursor.fetchall():
    print(f"   {row[0]:<20} {row[1]:>6} holdings   Value: ${row[2]}")

# =============================================================
cursor.close()
conn.close()
print("\n🎉 Mock data generation complete!")
print("   Restart Streamlit and refresh the dashboard.")
