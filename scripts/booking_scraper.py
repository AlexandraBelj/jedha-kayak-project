from playwright.sync_api import sync_playwright
import pandas as pd
from pathlib import Path
import re
import time


# ============================================================
# 1. PROJECT PATHS
# ============================================================

PROJECT_DIR = Path(__file__).resolve().parents[1]

PROCESSED_DATA_DIR = PROJECT_DIR / "data" / "processed"

RAW_BOOKING_DIR = (
    PROJECT_DIR
    / "data"
    / "raw"
)

RAW_BOOKING_DIR.mkdir(
    parents=True,
    exist_ok=True
)

PROCESSED_DATA_DIR.mkdir(
    parents=True,
    exist_ok=True
)


# ============================================================
# 2. SETTINGS
# ============================================================

# Maximum number of hotels collected per destination
MAX_HOTELS_PER_CITY = 20

# None = enrich every hotel collected
MAX_HOTELS_TO_ENRICH = None


# ============================================================
# 3. LOAD TOP 5 DESTINATIONS
# ============================================================

top_5_path = (
    PROCESSED_DATA_DIR
    / "top_5_destinations.csv"
)

top_5_df = pd.read_csv(top_5_path)

print("Top 5 destinations:")

print(
    top_5_df[
        ["city_id", "city"]
    ]
)


# ============================================================
# 4. PHASE 1 — SCRAPE BOOKING SEARCH RESULTS
# ============================================================

hotel_records = []

with sync_playwright() as p:

    browser = p.chromium.launch(
        headless=False
    )

    page = browser.new_page()

    for _, destination in top_5_df.iterrows():

        city_id = destination["city_id"]
        city = destination["city"]

        print(
            f"\nScraping search results for {city}..."
        )

        search_url = (
            "https://www.booking.com/searchresults.html"
            f"?ss={city.replace(' ', '+')}%2C+France"
        )

        try:

            page.goto(
                search_url,
                wait_until="domcontentloaded",
                timeout=60000
            )

            page.wait_for_timeout(5000)

            cards = page.locator(
                '[data-testid="property-card"]'
            )

            card_count = cards.count()

            print(
                f"{city}: {card_count} hotels found"
            )

            number_to_scrape = min(
                card_count,
                MAX_HOTELS_PER_CITY
            )

            for i in range(number_to_scrape):

                card = cards.nth(i)

                # --------------------------------------------
                # HOTEL NAME
                # --------------------------------------------

                name_locator = card.locator(
                    '[data-testid="title"]'
                )

                name = (
                    name_locator
                    .inner_text()
                    .strip()
                    if name_locator.count() > 0
                    else None
                )


                # --------------------------------------------
                # RATING
                # --------------------------------------------

                rating_locator = card.locator(
                    '[data-testid="review-score"]'
                )

                rating_text = (
                    rating_locator
                    .inner_text()
                    .strip()
                    if rating_locator.count() > 0
                    else None
                )

                rating = None

                if rating_text:

                    match = re.search(
                        r"\d+[.,]\d+",
                        rating_text
                    )

                    if match:

                        rating = float(
                            match
                            .group()
                            .replace(",", ".")
                        )


                # --------------------------------------------
                # HOTEL URL
                # --------------------------------------------

                link_locator = card.locator(
                    "a[href*='/hotel/']"
                ).first

                hotel_url = (
                    link_locator.get_attribute("href")
                    if link_locator.count() > 0
                    else None
                )


                # --------------------------------------------
                # STORE SEARCH RESULT
                # --------------------------------------------

                hotel_records.append({

                    "city_id":
                        city_id,

                    "city":
                        city,

                    "name":
                        name,

                    "rating":
                        rating,

                    "url":
                        hotel_url
                })


        except Exception as e:

            print(
                f"ERROR while scraping {city}: {e}"
            )


        # Small pause between cities
        time.sleep(2)

    browser.close()


# ============================================================
# 5. CREATE SEARCH RESULTS DATAFRAME
# ============================================================

hotels_df = pd.DataFrame(
    hotel_records
)

hotels_df = (
    hotels_df
    .drop_duplicates(
        subset=["name", "city"]
    )
    .reset_index(drop=True)
)

print("\nSearch results collected:")
print(hotels_df.head())

print(
    "\nTotal hotels collected:",
    len(hotels_df)
)

print(
    "\nHotels per city:"
)

print(
    hotels_df["city"].value_counts()
)


# ============================================================
# 6. SAVE INTERMEDIATE SEARCH RESULTS
# ============================================================

search_output_path = (
    RAW_BOOKING_DIR
    / "booking_search_results.csv"
)

hotels_df.to_csv(
    search_output_path,
    index=False
)

print(
    "\nSearch results saved to:",
    search_output_path
)


# ============================================================
# 7. SELECT HOTELS TO ENRICH
# ============================================================

if MAX_HOTELS_TO_ENRICH is None:

    hotels_to_enrich = hotels_df.copy()

else:

    hotels_to_enrich = hotels_df.head(
        MAX_HOTELS_TO_ENRICH
    ).copy()


# ============================================================
# 8. PHASE 2 — HOTEL DETAIL PAGES
# ============================================================

enriched_records = []

with sync_playwright() as p:

    browser = p.chromium.launch(
        headless=False
    )

    page = browser.new_page()

    total_hotels = len(
        hotels_to_enrich
    )

    for position, (_, hotel) in enumerate(
        hotels_to_enrich.iterrows(),
        start=1
    ):

        print(
            f"\n{position}/{total_hotels}"
            f" - {hotel['name']}"
        )

        hotel_url = hotel["url"]

        if pd.isna(hotel_url):

            print(
                "Missing hotel URL. Skipping."
            )

            continue

        try:

            page.goto(
                hotel_url,
                wait_until="domcontentloaded",
                timeout=60000
            )

            page.wait_for_timeout(3000)


            # ==================================================
            # DESCRIPTION
            # ==================================================

            description = None

            description_selectors = [

                '[data-testid="property-description"]',

                "#property_description_content",

                ".hp-description"
            ]

            for selector in description_selectors:

                locator = page.locator(
                    selector
                )

                if locator.count() > 0:

                    try:

                        text = (
                            locator
                            .first
                            .inner_text()
                            .strip()
                        )

                        if text:

                            description = text
                            break

                    except Exception:

                        pass


            # ==================================================
            # ADDRESS
            # ==================================================

            address = None

            address_selectors = [

                '[data-testid="address"]',

                ".hp_address_subtitle",

                "#showMap2 span",

                '[class*="address"]',

                '[id*="address"]'
            ]

            for selector in address_selectors:

                locator = page.locator(
                    selector
                )

                if locator.count() > 0:

                    try:

                        text = (
                            locator
                            .first
                            .inner_text()
                            .strip()
                        )

                        if text:

                            address = text
                            break

                    except Exception:

                        pass


            # ==================================================
            # PAGE HTML
            # ==================================================

            html = page.content()


            # ==================================================
            # LATITUDE
            # ==================================================

            latitude = None

            latitude_patterns = [

                r'"latitude"\s*:\s*"?(-?\d+\.\d+)"?',

                r'"lat"\s*:\s*"?(-?\d+\.\d+)"?',

                r'data-atlas-latlng="(-?\d+\.\d+),',

                r'center=([-]?\d+\.\d+)%2C'
            ]

            for pattern in latitude_patterns:

                matches = re.findall(
                    pattern,
                    html
                )

                if matches:

                    try:

                        latitude = float(
                            matches[0]
                        )

                        break

                    except ValueError:

                        pass


            # ==================================================
            # LONGITUDE
            # ==================================================

            longitude = None

            longitude_patterns = [

                r'"longitude"\s*:\s*"?(-?\d+\.\d+)"?',

                r'"lng"\s*:\s*"?(-?\d+\.\d+)"?',

                r'"lon"\s*:\s*"?(-?\d+\.\d+)"?',

                r'data-atlas-latlng="-?\d+\.\d+,(-?\d+\.\d+)',

                r'center=-?\d+\.\d+%2C([-]?\d+\.\d+)'
            ]

            for pattern in longitude_patterns:

                matches = re.findall(
                    pattern,
                    html
                )

                if matches:

                    try:

                        longitude = float(
                            matches[0]
                        )

                        break

                    except ValueError:

                        pass


            # ==================================================
            # DISPLAY EXTRACTION RESULT
            # ==================================================

            print(
                "Rating:",
                hotel["rating"]
            )

            print(
                "Address:",
                address
            )

            print(
                "Latitude:",
                latitude
            )

            print(
                "Longitude:",
                longitude
            )


            # ==================================================
            # STORE ENRICHED HOTEL
            # ==================================================

            enriched_records.append({

                "city_id":
                    hotel["city_id"],

                "city":
                    hotel["city"],

                "name":
                    hotel["name"],

                "rating":
                    hotel["rating"],

                "description":
                    description,

                "address":
                    address,

                "url":
                    hotel["url"],

                "latitude":
                    latitude,

                "longitude":
                    longitude
            })


        except Exception as e:

            print(
                f"ERROR for "
                f"{hotel['name']}: {e}"
            )


        # Small pause between hotel pages
        time.sleep(1)


    browser.close()


# ============================================================
# 9. CREATE RAW BOOKING DATAFRAME
# ============================================================

booking_df = pd.DataFrame(
    enriched_records
)

booking_df = (
    booking_df
    .drop_duplicates(
        subset=["name", "city"]
    )
    .reset_index(drop=True)
)


# ============================================================
# 10. CREATE HOTEL ID
# ============================================================

booking_df.insert(
    0,
    "hotel_id",
    range(
        1,
        len(booking_df) + 1
    )
)


# ============================================================
# 11. ORGANIZE COLUMN ORDER
# ============================================================

booking_df = booking_df[
    [
        "hotel_id",
        "city_id",
        "name",
        "rating",
        "description",
        "address",
        "url",
        "city",
        "latitude",
        "longitude"
    ]
]


# ============================================================
# 12. SAVE RAW BOOKING DATA
# ============================================================

raw_output_path = (
    RAW_BOOKING_DIR
    / "booking_data.csv"
)

booking_df.to_csv(
    raw_output_path,
    index=False
)

print(
    "\nRaw Booking data saved to:",
    raw_output_path
)


# ============================================================
# 13. CREATE CLEANED DATASET
# ============================================================

hotels_cleaned_df = (
    booking_df
    .copy()
)


# ------------------------------------------------------------
# Convert numeric columns explicitly
# ------------------------------------------------------------

numeric_columns = [
    "rating",
    "latitude",
    "longitude"
]

for column in numeric_columns:

    hotels_cleaned_df[column] = (
        pd.to_numeric(
            hotels_cleaned_df[column],
            errors="coerce"
        )
    )


# ------------------------------------------------------------
# Remove records without essential fields
# ------------------------------------------------------------

hotels_cleaned_df = (
    hotels_cleaned_df
    .dropna(
        subset=[
            "name",
            "city",
            "url"
        ]
    )
)


# ------------------------------------------------------------
# Keep missing ratings as NaN
# DO NOT replace missing rating with 0
# ------------------------------------------------------------


# ------------------------------------------------------------
# Drop address if Booking provided no addresses at all
# ------------------------------------------------------------

if (
    "address"
    in hotels_cleaned_df.columns
    and hotels_cleaned_df["address"].isna().all()
):

    hotels_cleaned_df = (
        hotels_cleaned_df
        .drop(
            columns=["address"]
        )
    )

    print(
        "\nAddress column removed "
        "because all values were missing."
    )


# ------------------------------------------------------------
# Remove duplicates again
# ------------------------------------------------------------

hotels_cleaned_df = (
    hotels_cleaned_df
    .drop_duplicates(
        subset=["name", "city"]
    )
    .reset_index(drop=True)
)


# ------------------------------------------------------------
# Rebuild hotel_id after cleaning
# ------------------------------------------------------------

hotels_cleaned_df["hotel_id"] = (
    range(
        1,
        len(hotels_cleaned_df) + 1
    )
)


# ============================================================
# 14. SAVE CLEANED DATASET
# ============================================================

cleaned_output_path = (
    PROCESSED_DATA_DIR
    / "hotels_cleaned.csv"
)

hotels_cleaned_df.to_csv(
    cleaned_output_path,
    index=False
)


# ============================================================
# 15. FINAL QUALITY CHECKS
# ============================================================

print("\n================================")
print("BOOKING SCRAPING COMPLETED")
print("================================")


print(
    "\nRaw dataset:",
    raw_output_path
)

print(
    "Cleaned dataset:",
    cleaned_output_path
)


print(
    "\nRaw shape:",
    booking_df.shape
)

print(
    "Cleaned shape:",
    hotels_cleaned_df.shape
)


print(
    "\nHotels per city:"
)

print(
    hotels_cleaned_df[
        "city"
    ].value_counts()
)


print(
    "\nMissing values:"
)

print(
    hotels_cleaned_df
    .isna()
    .sum()
)


print(
    "\nDuplicate hotels:"
)

print(
    hotels_cleaned_df
    .duplicated(
        subset=[
            "name",
            "city"
        ]
    )
    .sum()
)


print(
    "\nPreview:"
)

preview_columns = [
    "hotel_id",
    "city_id",
    "name",
    "rating",
    "city",
    "latitude",
    "longitude"
]

print(
    hotels_cleaned_df[
        preview_columns
    ].head(10)
)