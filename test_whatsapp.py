import os
import time
from twilio.rest import Client
from dotenv import load_dotenv

# Load environment variables from .env
load_dotenv()

account_sid = os.environ.get('TWILIO_ACCOUNT_SID')
auth_token = os.environ.get('TWILIO_AUTH_TOKEN')
from_number = os.environ.get('TWILIO_WHATSAPP_FROM')
to_number = 'whatsapp:+2347031090186'

print(f"Using sender: {from_number}")
print(f"Sending to: {to_number}")

client = Client(account_sid, auth_token)

try:
    message = client.messages.create(
        from_=from_number,
        to=to_number,
        body="Hello! This is a test message from the Funtel platform."
    )
    print(f"Message SID: {message.sid}")
    print(f"Initial Status: {message.status}")
    
    print("\nWaiting 5 seconds to check updated delivery status...")
    time.sleep(5)
    
    updated_message = client.messages(message.sid).fetch()
    print(f"Updated Status: {updated_message.status}")
    
    if updated_message.error_code:
        print(f"Error Code: {updated_message.error_code}")
        print(f"Error Message: {updated_message.error_message}")
    
    if updated_message.status == "failed" and updated_message.error_code == 63015:
        print("\nNOTE: Error 63015 means the recipient has not joined the Twilio Sandbox yet.")
        print("To fix this, send a WhatsApp message with your sandbox keyword to +1 415 523 8886 from the recipient's phone.")

except Exception as e:
    print(f"An error occurred: {e}")
