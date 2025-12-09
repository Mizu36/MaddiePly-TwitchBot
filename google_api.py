import gspread
import datetime
import random
from oauth2client.service_account import ServiceAccountCredentials
from db import get_setting
from tools import debug_print

GOOGLE_CLIENT = None

def start_google_sheets():
    global GOOGLE_CLIENT
    google_scope = ["https://spreadsheets.google.com/feeds",
            "https://www.googleapis.com/auth/drive"]
    google_creds = ServiceAccountCredentials.from_json_keyfile_name("credentials.json", google_scope)
    GOOGLE_CLIENT = gspread.authorize(google_creds)
    
def open_sheet(sheet_id):
    global GOOGLE_CLIENT
    if GOOGLE_CLIENT is None:
        try:
            start_google_sheets()
        except Exception as e:
            debug_print("GoogleAPI", f"Error initializing Google Sheets client: {e}")
            raise
    sheet = GOOGLE_CLIENT.open_by_key(sheet_id).sheet1
    return sheet

async def add_quote(user, quote_text: str, category = "Just Chatting"):
    # Get the last row index
    debug_print("GoogleAPI", f"Adding quote \"{quote_text}\" to google sheet.")
    quotes_sheet_id = await get_setting("Google Sheets Quotes Sheet ID")
    if not quotes_sheet_id:
        raise ValueError("Google Sheets Quotes Sheet ID is not set in the settings.")
    sheet = open_sheet(quotes_sheet_id)
    quotes = sheet.get_all_records()
    new_id = len(quotes) + 1  # unique number
    quote_text = quote_text.capitalize()
    if not quote_text.endswith(".") or not quote_text.endswith("!") or not quote_text.endswith("?"):
        quote_text += "."
    sheet.append_row([new_id, quote_text, datetime.datetime.now().strftime("%Y-%m-%d"), user, category])
    return new_id

async def get_quote(quote_id):
    debug_print("GoogleAPI", f"Getting quote {quote_id} from google sheet.")
    quotes_sheet_id = await get_setting("Google Sheets Quotes Sheet ID")
    sheet = open_sheet(quotes_sheet_id)
    quotes = sheet.get_all_records()
    for q in quotes:
        if q["ID"] == quote_id:
            return q
    return None

async def get_random_quote():
    debug_print("GoogleAPI", "Getting a random quote from google sheet.")
    quotes_sheet_id = await get_setting("Google Sheets Quotes Sheet ID")
    sheet = open_sheet(quotes_sheet_id)
    quotes = sheet.get_all_records()
    if not quotes:
        return None
    random_quote = random.choice(quotes)
    return random_quote

async def get_random_quote_containing_word(word):
    debug_print("GoogleAPI", f"Searching for a quote with the word '{word}' in the google sheet.")
    quotes_sheet_id = await get_setting("Google Sheets Quotes Sheet ID")
    sheet = open_sheet(quotes_sheet_id)
    quotes = sheet.get_all_records()
    filtered_quotes = [q for q in quotes if word.lower() in q["Quote"].lower()]
    if not filtered_quotes:
        return None
    random_quote = random.choice(filtered_quotes)
    return random_quote

if __name__ == "__main__":
    qid = add_quote("Mizu", "This is a test quote!")
    print(f"Added Quote #{qid}")

    quote = get_quote(qid)
    print("Retrieved:", quote)

    print("Random Quote:", get_random_quote())
