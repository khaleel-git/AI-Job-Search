import smtplib
import ssl
import time
import random
import os
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders

# ==========================================
# CONFIGURATION
# ==========================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def load_env_file(env_file=".env"):
    """Loads KEY=VALUE pairs from a local .env file into os.environ if not already set."""
    env_path = os.path.join(BASE_DIR, env_file)
    if not os.path.exists(env_path):
        return

    with open(env_path, "r", encoding="utf-8") as f:
        for raw_line in f:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue

            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")

            if key and key not in os.environ:
                os.environ[key] = value


load_env_file()


def normalize_sender_email(value):
    if not value:
        return value
    return value.strip()


def normalize_app_password(value):
    if not value:
        return value
    # Google displays app passwords in groups; SMTP expects a continuous string.
    return value.strip().replace(" ", "").replace("-", "")


SENDER_EMAIL = normalize_sender_email(os.getenv("SENDER_EMAIL"))
SENDER_NAME = "Khaleel Ahmad"
APP_PASSWORD = normalize_app_password(os.getenv("APP_PASSWORD"))

SUBJECT = "[Seeking] a Working Student Opportunity"

# Exact filenames of your attachments. They must be in the same folder as this script.
ATTACHMENTS = [
    "Khaleel_Resume.pdf",
    "Certificate of Enrolment [PDF].pdf",
    "Khaleel_Certifications.pdf"
]

# File to track who we have already emailed
SENT_LOG_FILE = "sent_log.txt"


def validate_config():
    """Ensures required secrets are loaded from environment variables."""
    missing = []
    if not SENDER_EMAIL:
        missing.append("SENDER_EMAIL")
    if not APP_PASSWORD:
        missing.append("APP_PASSWORD")

    if missing:
        print("❌ Missing required environment variables:", ", ".join(missing))
        print("Set them in your shell or add them to a local .env file (never commit .env).")
        return False

    return True

# ==========================================
# EMAIL CONTENT (Plain Text & HTML)
# ==========================================
# Plain text fallback for strict spam filters
TEXT_BODY = """\
Dear Engineering & Recruiting Team,

I am reaching out to see if you are looking for a highly technical Working Student to support your Data, AI, or Cloud Infrastructure workflows.

Currently pursuing my M.Sc. in Artificial Intelligence at BTU Cottbus, I bring over 3.5 years of enterprise experience as a Data & Platform Engineer at Ericsson. I am looking for a dynamic environment where I can add immediate, hands-on value to your engineering teams for up to 20 hours per week.

Additionally, while I work with full professional proficiency in English, I have completed my A2 German certificate and am currently enrolled in B1 classes to ensure smooth communication and integration into local teams.

My core technical stack includes:
• Data & Backend: Python, SQL, and Apache Airflow (engineered robust ETL pipelines processing 30k+ complex files daily).
• DevOps & Cloud: Certified Kubernetes Administrator (CKA), Docker, AWS/Azure, and automating CI/CD pipelines (GitHub Actions).
• AI & MLOps: Strong academic foundation in modern ML frameworks, with the operational skills to reliably deploy and scale models in production.

I have attached my CV and university enrollment certificate for your review. If my stack aligns with your current technology roadmap, I would welcome the opportunity for a brief chat to see if there is a mutual fit.

Best regards,

Khaleel Ahmad | Data Engineer
Mobile: +49 15563 611714
Web: www.khaleel.eu | Email: khaleel.eu@gmail.com
Oderberger Str. 13, 10435 Berlin, Germany
"""

# HTML version for clean, professional formatting
HTML_BODY = """\
<html>
  <body>
    <p>Dear Engineering &amp; Recruiting Team,</p>
    
    <p>I am reaching out to see if you are looking for a highly technical Working Student to support your Data, AI, or Cloud Infrastructure workflows.</p>
    
    <p>Currently pursuing my M.Sc. in Artificial Intelligence at BTU Cottbus, I bring over 3.5 years of enterprise experience as a Data &amp; Platform Engineer at Ericsson. I am looking for a dynamic environment where I can add immediate, hands-on value to your engineering teams for up to 20 hours per week.</p>
    
    <p>Additionally, while I work with full professional proficiency in English, I have completed my A2 German certificate and am currently enrolled in B1 classes to ensure smooth communication and integration into local teams.</p>
    
    <p>My core technical stack includes:</p>
    <ul>
      <li><strong>Data &amp; Backend:</strong> Python, SQL, and Apache Airflow (engineered robust ETL pipelines processing 30k+ complex files daily).</li>
      <li><strong>DevOps &amp; Cloud:</strong> Certified Kubernetes Administrator (CKA), Docker, AWS/Azure, and automating CI/CD pipelines (GitHub Actions).</li>
      <li><strong>AI &amp; MLOps:</strong> Strong academic foundation in modern ML frameworks, with the operational skills to reliably deploy and scale models in production.</li>
    </ul>
    
    <p>I have attached my CV and university enrollment certificate for your review. If my stack aligns with your current technology roadmap, I would welcome the opportunity for a brief chat to see if there is a mutual fit.</p>
    
    <p>Best regards,</p>
    
    <p>
      <strong>Khaleel Ahmad</strong> | Data Engineer<br>
      Mobile: +49 15563 611714<br>
      Web: <a href="http://www.khaleel.eu">www.khaleel.eu</a> | Email: <a href="mailto:khaleel.eu@gmail.com">khaleel.eu@gmail.com</a><br>
      Oderberger Str. 13, 10435 Berlin, Germany
    </p>
  </body>
</html>
"""

def create_email(recipient_email):
    """Constructs a multipart email with HTML, Plain Text, and PDF attachments."""
    msg = MIMEMultipart("mixed")
    msg["Subject"] = SUBJECT
    msg["From"] = f"{SENDER_NAME} <{SENDER_EMAIL}>"
    msg["To"] = recipient_email

    # Add Plain text and HTML body (Spam filters prefer having both)
    body_part = MIMEMultipart("alternative")
    body_part.attach(MIMEText(TEXT_BODY, "plain"))
    body_part.attach(MIMEText(HTML_BODY, "html"))
    msg.attach(body_part)

    # Process and attach files
    for filename in ATTACHMENTS:
        if not os.path.exists(filename):
            print(f"⚠️ Warning: File '{filename}' not found. Skipping attachment.")
            continue
            
        with open(filename, "rb") as attachment:
            part = MIMEBase("application", "octet-stream")
            part.set_payload(attachment.read())
        
        # Encode file in base64
        encoders.encode_base64(part)
        
        # Add header as key/value pair to attachment part
        part.add_header(
            "Content-Disposition",
            f"attachment; filename= {filename}",
        )
        msg.attach(part)
        
    return msg

def get_recipients(txt_file="contacts.txt"):
    """Reads email addresses from a TXT file (one email per line)."""
    recipients = []
    try:
        with open(txt_file, mode="r", encoding="utf-8-sig") as file:
            for line in file:
                email = line.strip()
                if email:
                    recipients.append(email)
    except FileNotFoundError:
        print(f"❌ Error: Could not find {txt_file}. Please create it with one email per line.")
    return recipients

def get_already_sent_emails(log_file):
    """Reads the log file to get a set of already emailed addresses."""
    if not os.path.exists(log_file):
        return set()
    with open(log_file, "r", encoding="utf-8") as f:
        # Normalize to lowercase to avoid case-sensitive duplicate issues
        return set(line.strip().lower() for line in f if line.strip())

def log_sent_email(log_file, email):
    """Appends a successfully sent email to the log file."""
    with open(log_file, "a", encoding="utf-8") as f:
        f.write(f"{email.strip().lower()}\n")

def main():
    if not validate_config():
        return

    all_recipients = get_recipients()
    if not all_recipients:
        print("No recipients found in your TXT file. Exiting.")
        return

    # Check who we've already emailed
    already_sent = get_already_sent_emails(SENT_LOG_FILE)
    
    # Filter down to only those we haven't emailed yet
    pending_recipients = [r for r in all_recipients if r.lower() not in already_sent]

    if not pending_recipients:
        print(f"✅ All {len(all_recipients)} recipients in your list have already been emailed. Exiting.")
        return

    print(f"Found {len(all_recipients)} total recipients in TXT file.")
    print(f"Skipping {len(already_sent)} already emailed.")
    print(f"Preparing to send to {len(pending_recipients)} NEW recipients...\n")
    
    # Connect to Google SMTP server
    context = ssl.create_default_context()
    
    try:
        # Using context management ensures the connection closes cleanly
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=context) as server:
            server.login(SENDER_EMAIL, APP_PASSWORD)
            print("✅ Successfully logged into Gmail SMTP server.")
            
            for index, recipient in enumerate(pending_recipients):
                print(f"[{index + 1}/{len(pending_recipients)}] Sending to {recipient}...")
                
                try:
                    # Create the message
                    msg = create_email(recipient)
                    
                    # Send the email
                    server.sendmail(SENDER_EMAIL, recipient, msg.as_string())
                    
                    # LOG the success immediately so we don't email them again if the script crashes
                    log_sent_email(SENT_LOG_FILE, recipient)
                    print(f"   -> 🚀 Sent and logged successfully")
                
                except Exception as e:
                    print(f"   -> ❌ Failed to send to {recipient}: {e}")
                    continue # Skip delay on failure and move to next
                
                # Anti-Spam human delay (skip delay after the very last email)
                if index < len(pending_recipients) - 1:
                    # Random delay between 60 and 150 seconds (1 to 2.5 minutes)
                    delay = random.uniform(60, 150)
                    print(f"   -> ⏳ Pausing for {int(delay)} seconds to mimic human sending...\n")
                    time.sleep(delay)
                    
    except smtplib.SMTPAuthenticationError as auth_error:
        details = ""
        if hasattr(auth_error, "smtp_error") and auth_error.smtp_error:
            try:
                details = auth_error.smtp_error.decode("utf-8", errors="ignore")
            except Exception:
                details = str(auth_error.smtp_error)

        print("❌ Authentication Error: Gmail rejected the login.")
        print("   Check that SENDER_EMAIL is the Gmail account that generated the App Password.")
        print("   Check that 2-Step Verification is enabled for that same account.")
        print("   Check that APP_PASSWORD is the 16-character app password (no spaces).")
        if details:
            print(f"   Gmail says: {details}")
    except Exception as e:
        print(f"❌ A critical error occurred: {e}")

    print("\n🎉 Process completed!")

if __name__ == "__main__":
    main()
