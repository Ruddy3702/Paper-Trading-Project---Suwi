# Import the required module from the fyers_apiv3 package
from fyers_apiv3 import fyersModel
from dotenv import load_dotenv
import os
load_dotenv()

# Replace these values with your actual API credentials
CLIENT_ID = os.getenv("FYERS_CLIENT_ID")          # e.g. "ABCD1234-100"
SECRET_KEY = os.getenv("FYERS_SECRET_KEY")
redirect_uri = os.getenv("FYERS_REDIRECT_URL")
response_type = "code"
state = "sample_state"

# Create a session model with the provided credentials
session = fyersModel.SessionModel(
    client_id=CLIENT_ID,
    secret_key=SECRET_KEY,
    redirect_uri=redirect_uri,
    response_type=response_type
)

# Generate the auth code using the session model
response = session.generate_authcode()

# Print the auth code received in the response
print(response)

