from google.oauth2 import service_account
from google.auth.transport.requests import AuthorizedSession
from google.auth.transport.requests import Request
import json
import logging
import sys
import os

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)

file_dir = os.path.dirname(__file__)
SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
SPREADSHEET_API_ENDPOINT = "https://sheets.googleapis.com/v4/spreadsheets"
SERVICE_ACCOUNT_FILE = os.getenv('GOOGLE_SERVICE_ACCOUNT_PATH')
if not SERVICE_ACCOUNT_FILE:
    raise RuntimeError('GOOGLE_SERVICE_ACCOUNT_PATH environment variable not set')

creds = service_account.Credentials.from_service_account_file(
    SERVICE_ACCOUNT_FILE, scopes=SCOPES
)
creds.refresh(Request())

session = AuthorizedSession(creds)


def read_range_from_google_sheet(sheet_id, data_range):
    return session.get(
        f"{SPREADSHEET_API_ENDPOINT}/{sheet_id}/values/{data_range}"
    ).json()


def read_row_from_google_sheet_as_dict(
    sheet_id, sheet_name, rn_start, header_row_number=1
):
    headers_range = f"{sheet_name}!A{header_row_number}:L{header_row_number}"
    headers = read_range_from_google_sheet(sheet_id, headers_range)

    data_range = f"{sheet_name}!A{rn_start}:L{rn_start}"
    data_rows = read_range_from_google_sheet(sheet_id, data_range)

    header_names = headers.get("values", [])[0]
    row_values = data_rows.get("values", [])

    if len(row_values) < 1:
        return None

    row_values = row_values[0]

    v = dict()
    for header, row in zip(header_names, row_values):
        v[header] = row

    # logging.info(f'Row data: {json.dumps(values)}')

    return v


# Example Usage:
# SPREADSHEET_ID = "<your-google-spreadsheet-id>"
# row_json = read_row_from_google_sheet_as_dict(SPREADSHEET_ID, "Pipeline", row_number=4)
# print(row_json)
