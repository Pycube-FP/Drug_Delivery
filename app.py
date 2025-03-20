from flask import Flask, request, jsonify, render_template
import random
import sqlite3
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import os
from dotenv import load_dotenv
from datetime import datetime

load_dotenv()

app = Flask(__name__, static_folder='static')

# AWS SMTP Configuration
SMTP_SERVER = 'email-smtp.us-east-2.amazonaws.com'
SMTP_PORT = 587
SMTP_USERNAME = os.getenv('SMTP_USERNAME')
SMTP_PASSWORD = os.getenv('SMTP_PASSWORD')
SENDER_EMAIL = 'thanmai.p@pycube.com'

def init_db():
    conn = sqlite3.connect('delivery.db')
    c = conn.cursor()
    
    # First, check if the table exists
    c.execute('''SELECT name FROM sqlite_master WHERE type='table' AND name='deliveries' ''')
    table_exists = c.fetchone() is not None
    
    if not table_exists:
        # Create table with all columns if it doesn't exist
        c.execute('''
            CREATE TABLE deliveries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                patient_name TEXT,
                phone_number TEXT,
                email TEXT,
                address TEXT,
                medicine TEXT,
                otp TEXT,
                phone_verified BOOLEAN DEFAULT 0,
                otp_verified BOOLEAN DEFAULT 0,
                status TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
    else:
        # Add new columns if they don't exist
        try:
            c.execute('ALTER TABLE deliveries ADD COLUMN phone_verified BOOLEAN DEFAULT 0')
        except sqlite3.OperationalError:
            pass  # Column already exists
        
        try:
            c.execute('ALTER TABLE deliveries ADD COLUMN otp_verified BOOLEAN DEFAULT 0')
        except sqlite3.OperationalError:
            pass  # Column already exists
        
        try:
            c.execute('ALTER TABLE deliveries ADD COLUMN email TEXT')
        except sqlite3.OperationalError:
            pass  # Column already exists
        
        try:
            c.execute('ALTER TABLE deliveries ADD COLUMN created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP')
        except sqlite3.OperationalError:
            pass  # Column already exists

    conn.commit()
    conn.close()

def send_email(to_email, otp):
    try:
        if not SMTP_USERNAME or not SMTP_PASSWORD:
            print("SMTP credentials not configured")
            return False

        msg = MIMEMultipart()
        msg['From'] = SENDER_EMAIL
        msg['To'] = to_email
        msg['Subject'] = 'Medicine Delivery OTP Verification'

        body = f"""
        Your medicine delivery OTP is: {otp}
        
        This is an automated message, please do not reply.
        """
        msg.attach(MIMEText(body, 'plain'))

        try:
            server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
            server.starttls()
            server.login(SMTP_USERNAME, SMTP_PASSWORD)
            
            text = msg.as_string()
            server.sendmail(SENDER_EMAIL, to_email, text)
            server.quit()
            return True
        except Exception as smtp_error:
            print(f"SMTP Error: {smtp_error}")
            return False

    except Exception as e:
        print(f"Error sending email: {e}")
        return False

def generate_otp():
    return str(random.randint(100000, 999999))

@app.route('/')
def index():
    return dashboard()  # Redirect to dashboard

@app.route('/dashboard')
def dashboard():
    conn = sqlite3.connect('delivery.db')
    c = conn.cursor()
    
    # Get counts for different statuses
    c.execute('''
        SELECT 
            COUNT(*) as total,
            SUM(CASE WHEN status = 'pending' THEN 1 ELSE 0 END) as pending,
            SUM(CASE WHEN status = 'delivered' THEN 1 ELSE 0 END) as delivered,
            SUM(CASE WHEN otp_verified = 1 THEN 1 ELSE 0 END) as otp_verified,
            SUM(CASE WHEN phone_verified = 1 THEN 1 ELSE 0 END) as phone_verified,
            SUM(CASE WHEN status = 'in_progress' THEN 1 ELSE 0 END) as in_progress
        FROM deliveries
    ''')
    stats = c.fetchone()
    
    # Get recent deliveries with all details
    c.execute('''
        SELECT 
            id, 
            patient_name,
            status,
            created_at,
            otp_verified,
            phone_verified,
            medicine,
            phone_number,
            email,
            address
        FROM deliveries 
        ORDER BY created_at DESC 
        LIMIT 10
    ''')
    recent_deliveries = [dict(zip([
        'id', 'patient_name', 'status', 'created_at', 
        'otp_verified', 'phone_verified', 'medicine',
        'phone_number', 'email', 'address'
    ], row)) for row in c.fetchall()]
    
    conn.close()
    
    return render_template('dashboard.html', 
                         stats=stats, 
                         recent_deliveries=recent_deliveries)

@app.route('/new-delivery')
def new_delivery():
    return render_template('index.html')

@app.route('/create_delivery', methods=['POST'])
def create_delivery():
    data = request.json
    
    conn = sqlite3.connect('delivery.db')
    c = conn.cursor()
    c.execute('''
        INSERT INTO deliveries (
            patient_name, phone_number, email, address, 
            medicine, status, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', (
        data['patient_name'],
        data['phone_number'],
        data['email'],
        data['address'],
        data['medicine'],
        'pending',
        datetime.now()
    ))
    delivery_id = c.lastrowid
    conn.commit()
    conn.close()

    return jsonify({
        "delivery_id": delivery_id, 
        "status": "created",
        "message": "Order placed successfully"
    })

@app.route('/verify_otp', methods=['POST'])
def verify_otp():
    data = request.json
    delivery_id = data['delivery_id']
    provided_otp = data['otp']

    conn = sqlite3.connect('delivery.db')
    c = conn.cursor()
    c.execute('SELECT otp FROM deliveries WHERE id = ?', (delivery_id,))
    result = c.fetchone()
    
    if not result:
        return jsonify({"status": "error", "message": "Delivery not found"})
    
    if result[0] == provided_otp:
        c.execute('UPDATE deliveries SET otp_verified = 1 WHERE id = ?', (delivery_id,))
        conn.commit()
        status = "success"
        message = "OTP verified successfully"
    else:
        status = "error"
        message = "Invalid OTP"

    conn.close()
    return jsonify({"status": status, "message": message})

@app.route('/verify_phone', methods=['POST'])
def verify_phone():
    data = request.json
    delivery_id = data['delivery_id']
    phone_last_four = data['phone_last_four']

    conn = sqlite3.connect('delivery.db')
    c = conn.cursor()
    c.execute('SELECT phone_number FROM deliveries WHERE id = ?', (delivery_id,))
    result = c.fetchone()
    
    if not result:
        return jsonify({"status": "error", "message": "Delivery not found"})
    
    actual_last_four = result[0][-4:]
    
    if phone_last_four == actual_last_four:
        c.execute('UPDATE deliveries SET phone_verified = 1 WHERE id = ?', (delivery_id,))
        
        # Check if both verifications are complete
        c.execute('''
            UPDATE deliveries 
            SET status = 'delivered' 
            WHERE id = ? AND otp_verified = 1 AND phone_verified = 1
        ''', (delivery_id,))
        
        conn.commit()
        status = "success"
        message = "Phone number verified successfully"
    else:
        status = "error"
        message = "Invalid phone number"

    conn.close()
    return jsonify({"status": status, "message": message})

@app.route('/get_delivery_status/<int:delivery_id>')
def get_delivery_status(delivery_id):
    conn = sqlite3.connect('delivery.db')
    c = conn.cursor()
    c.execute('''
        SELECT status, otp_verified, phone_verified 
        FROM deliveries 
        WHERE id = ?
    ''', (delivery_id,))
    result = c.fetchone()
    conn.close()
    
    if result:
        return jsonify({
            "status": result[0],
            "otp_verified": bool(result[1]),
            "phone_verified": bool(result[2])
        })
    return jsonify({"error": "Delivery not found"}), 404

@app.route('/delivery-boy')
def delivery_boy_dashboard():
    conn = sqlite3.connect('delivery.db')
    c = conn.cursor()
    
    # Get all deliveries for delivery boy (not just pending)
    c.execute('''
        SELECT id, patient_name, address, status, created_at 
        FROM deliveries 
        ORDER BY created_at DESC
    ''')
    deliveries = c.fetchall()
    
    # Print debug information
    print(f"Number of deliveries found: {len(deliveries)}")
    for delivery in deliveries:
        print(f"Delivery: {delivery}")
    
    conn.close()
    return render_template('delivery_boy.html', deliveries=deliveries)

@app.route('/start-delivery/<int:delivery_id>', methods=['POST'])
def start_delivery(delivery_id):
    otp = generate_otp()
    
    conn = sqlite3.connect('delivery.db')
    c = conn.cursor()
    
    try:
        # Get delivery details including email
        c.execute('SELECT email, patient_name FROM deliveries WHERE id = ?', (delivery_id,))
        delivery = c.fetchone()
        
        if not delivery:
            return jsonify({"status": "error", "message": "Delivery not found"})
        
        email, patient_name = delivery
        
        if not email:
            return jsonify({"status": "error", "message": "No email found for this delivery"})
        
        # First try to send the email
        if send_email(email, otp):
            # Only update database if email was sent successfully
            c.execute('''
                UPDATE deliveries 
                SET status = 'in_progress', otp = ?
                WHERE id = ?
            ''', (otp, delivery_id))
            conn.commit()
            
            return jsonify({
                "status": "success",
                "message": f"Verification code sent to patient's email ({email})"
            })
        else:
            return jsonify({
                "status": "error",
                "message": "Failed to send verification code to patient's email"
            }), 500
            
    except Exception as e:
        print(f"Error in start_delivery: {e}")
        return jsonify({
            "status": "error",
            "message": "An error occurred while processing the request"
        }), 500
    finally:
        conn.close()

@app.route('/complete-delivery/<int:delivery_id>', methods=['POST'])
def complete_delivery(delivery_id):
    data = request.json
    provided_otp = data.get('otp')
    
    conn = sqlite3.connect('delivery.db')
    c = conn.cursor()
    
    # Verify OTP
    c.execute('SELECT otp FROM deliveries WHERE id = ?', (delivery_id,))
    result = c.fetchone()
    
    if not result:
        return jsonify({"status": "error", "message": "Delivery not found"})
    
    if result[0] == provided_otp:
        # Update delivery status to delivered
        c.execute('''
            UPDATE deliveries 
            SET status = 'delivered', 
                otp_verified = 1,
                phone_verified = 1
            WHERE id = ?
        ''', (delivery_id,))
        conn.commit()
        status = "success"
        message = "Delivery completed successfully"
    else:
        status = "error"
        message = "Invalid OTP"

    conn.close()
    return jsonify({"status": status, "message": message})

if __name__ == '__main__':
    init_db()
    app.run(debug=True) 