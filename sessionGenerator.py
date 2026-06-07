from telethon.sync import TelegramClient
from telethon.sessions import StringSession

# Define your Telegram API credentials
# (Required by the client wrapper, though not used to overwrite the file)
API_ID = 38562762  
API_HASH = 'e8abffbb4e47431493774154c7209f43'

# Load your local '.session' file (omit the '.session' extension from the name)
# If your file is named 'my_account.session', use 'my_account'
session_name = 'rent_sentinel_session' 

with TelegramClient(session_name, API_ID, API_HASH) as client:
    # Generate and print the highly portable StringSession token
    session_token = StringSession.save(client.session)
    print("Your Session Token:\n", session_token)