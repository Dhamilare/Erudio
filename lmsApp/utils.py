from .models import *
from django.conf import settings
from django.template.loader import render_to_string
from django.core.mail import EmailMessage
from datetime import datetime
import requests


def send_templated_email(template_name, subject, recipient_list, context, attachments=None):
    context['current_year'] = datetime.now().year
    
    html_content = render_to_string(template_name, context)
    
    email = EmailMessage(
        subject,
        html_content,
        settings.DEFAULT_FROM_EMAIL,
        recipient_list
    )
    
    email.content_subtype = "html" 
    
    if attachments:
        for filename, content, mimetype in attachments:
            email.attach(filename, content, mimetype)
    
    try:
        email.send()
        return True
    except Exception as e:
        import traceback
        print(f"Error sending email: {e}\n{traceback.format_exc()}")
        return False


# --- PAYSTACK API INTEGRATION ---

class PaystackAPI:
    """
    A wrapper class for the Paystack API.
    It handles transaction initialization and verification.
    """
    def __init__(self):
        self.secret_key = settings.PAYSTACK_SECRET_KEY
        self.base_url = 'https://api.paystack.co'
        self.headers = {
            'Authorization': f'Bearer {self.secret_key}',
            'Content-Type': 'application/json',
        }

    def initialize_transaction(self, email, amount, reference, callback_url):
        """
        Initializes a transaction and returns the authorization URL.
        Amount should be in the lowest currency unit (e.g., kobo).
        """
        url = f'{self.base_url}/transaction/initialize'
        payload = {
            'email': email,
            'amount': str(amount),
            'reference': reference,
            'callback_url': callback_url,
        }
        try:
            response = requests.post(url, headers=self.headers, json=payload, timeout=15)
            response.raise_for_status()  # Raises an HTTPError for bad responses (4xx or 5xx)
            return response.json()
        except requests.exceptions.RequestException as e:
            # Handle connection errors, timeouts, etc.
            print(f"An error occurred while initializing transaction with Paystack: {e}")
            return None

    def verify_transaction(self, reference):
        """
        Verifies the status of a transaction using its reference.
        """
        url = f'{self.base_url}/transaction/verify/{reference}'
        try:
            response = requests.get(url, headers=self.headers, timeout=15)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            print(f"An error occurred while verifying transaction with Paystack: {e}")
            return None