from .models import *
from django.conf import settings
from django.template.loader import render_to_string
from django.core.mail import EmailMessage
from datetime import datetime
import requests
import re


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
        

def get_youtube_embed_url(video_url):
    """
    Intelligently extracts the YouTube video ID from various URL formats
    and returns a clean, reliable embed URL.
    """
    if not video_url:
        return None

    # Regex to find the YouTube video ID in various URL formats
    regex = r'(?:https?:\/\/)?(?:www\.)?(?:youtube\.com\/(?:[^\/\n\s]+\/\S+\/|(?:v|e(?:mbed)?)\/|\S*?[?&]v=)|youtu\.be\/)([a-zA-Z0-9_-]{11})'
    
    match = re.search(regex, video_url)

    if match:
        video_id = match.group(1)
        return f'https://www.youtube.com/embed/{video_id}'
    
    # Return None if no valid YouTube ID is found
    return None


def send_enrollment_confirmation_email(enrollment):
    """
    Sends a confirmation email to a student after they enroll in a course.
    """
    subject = f"You're enrolled in: {enrollment.course.title}"
    context = {
        'enrollment': enrollment,
        'course': enrollment.course,
        'student': enrollment.student,
    }
    # Find the associated transaction, if it exists
    transaction = Transaction.objects.filter(student=enrollment.student, course=enrollment.course, status='success').first()
    context['transaction'] = transaction

    send_templated_email(
        'emails/enrollment_confirmation.html',
        subject,
        [enrollment.student.email],
        context
    )


def send_completion_certificate_email(enrollment):
    """
    Sends a course completion certificate email to a student.
    """
    subject = f"Congratulations on completing {enrollment.course.title}!"
    context = {
        'enrollment': enrollment,
        'course': enrollment.course,
        'student': enrollment.student,
        'completion_date': timezone.now(),
    }
    send_templated_email(
        'emails/completion_certificate.html',
        subject,
        [enrollment.student.email],
        context
    )