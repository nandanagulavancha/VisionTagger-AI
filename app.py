import firebase_admin
from firebase_admin import credentials, firestore
from flask import Flask, render_template, request, send_file, flash, redirect, url_for, jsonify
import requests
import base64
import json
import io
import os
# from dotenv import load_dotenv

# load_dotenv()  # Load environment variables from .env file directly

# app = Flask(__name__, template_folder="templates")
# app.secret_key = os.getenv("FLASK_SECRET_KEY")

# if not app.secret_key:
#     raise ValueError("Missing FLASK_SECRET_KEY in .env")

# # Initialize Firebase
# cred = credentials.Certificate(os.getenv("FIREBASE_CREDENTIALS_PATH"))
# firebase_admin.initialize_app(cred)
# db = firestore.client()

# # Configure API Key and URL
# GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
# GEMINI_API_URL = f"{os.getenv("GEMINI_API_URL")}"

# if not GEMINI_API_KEY or not os.getenv("GEMINI_API_URL") or not os.getenv("FIREBASE_CREDENTIALS_PATH"):
#     raise ValueError("Missing API keys or paths in .env")

app = Flask(__name__, template_folder="templates")
app.secret_key = 'your_secret_key'  # Required for flash messages

# Initialize Firebase
cred = credentials.Certificate("visiontagger-ai-firebase-adminsdk-fbsvc-017d602915.json")  # Make sure this file exists
firebase_admin.initialize_app(cred)
db = firestore.client()  # Firestore Database

# Configure API Key (Replace with your actual API key)
GEMINI_API_KEY = "AIzaSyAacJhRJUT-ipRDgCVJxe_Kb-3bmPMKgK4"
GEMINI_API_URL = f"https://vision.googleapis.com/v1/images:annotate?key={GEMINI_API_KEY}"

# Function to send image to Google Vision API without saving it
def get_image_metadata(image_file):
    img_base64 = base64.b64encode(image_file.read()).decode("utf-8")  # Read file directly from memory

    payload = {
        "requests": [{
            "image": {"content": img_base64},
            "features": [
                {"type": "LABEL_DETECTION"},
                {"type": "OBJECT_LOCALIZATION"},
                {"type": "TEXT_DETECTION"},
                {"type": "LOGO_DETECTION"},
                {"type": "LANDMARK_DETECTION"},
                {"type": "IMAGE_PROPERTIES"},
                {"type": "SAFE_SEARCH_DETECTION"}
            ]
        }]
    }

    response = requests.post(GEMINI_API_URL, json=payload)

    if response.status_code == 200:
        return response.json()
    else:
        return {"error": f"API Request Failed - Status {response.status_code}", "details": response.text}

# Route for home page
@app.route('/', methods=['GET', 'POST'])
def home():
    metadata = None
    tags = []

    if request.method == 'POST' and 'image' in request.files:
        image = request.files['image']

        metadata = get_image_metadata(image)  # Process image directly

        # Extract tags from metadata
        labels = metadata.get("responses", [{}])[0].get("labelAnnotations", [])
        tags = [label.get("description", "") for label in labels]

        # Save metadata to Firestore (using image filename as document ID)
        image_name = image.filename
        db.collection("image_metadata").document(image_name).set({
            "image_name": image_name,
            "metadata": metadata,
            "tags": tags
        })

    return render_template('index.html', metadata=metadata, tags=tags)

# Route to Edit Metadata in Firestore
@app.route('/edit_metadata/<image_name>', methods=['POST'])
def edit_metadata(image_name):
    try:
        edited_metadata = request.form.get("edited_json")

        if edited_metadata:
            parsed_metadata = json.loads(edited_metadata)
            db.collection("image_metadata").document(image_name).update({"metadata": parsed_metadata})
            flash(f"Metadata for {image_name} updated successfully!", "success")
        else:
            flash("No metadata provided!", "error")

    except Exception as e:
        flash(f"Error updating metadata: {str(e)}", "error")

    return redirect(url_for('home'))

# Route to Download Metadata as JSON (No File Storage)
@app.route('/download_metadata/<image_name>')
def download_metadata(image_name):
    try:
        doc_ref = db.collection("image_metadata").document(image_name)
        doc = doc_ref.get()

        if doc.exists:
            metadata = doc.to_dict().get("metadata", {})
            json_data = json.dumps(metadata, indent=2)

            return send_file(
                io.BytesIO(json_data.encode()),
                as_attachment=True,
                download_name=f"{image_name}_metadata.json",
                mimetype="application/json"
            )

    except Exception as e:
        flash(f"Error downloading metadata: {str(e)}", "error")

    return redirect(url_for('home'))

# Route to Delete Image Metadata
@app.route('/delete_image/<image_name>', methods=['POST'])
def delete_image(image_name):
    try:
        db.collection("image_metadata").document(image_name).delete()
        flash(f"Deleted {image_name} successfully!", "success")
    except Exception as e:
        flash(f"Error deleting {image_name}: {str(e)}", "error")

    return redirect(url_for('history'))

# Route to View Searchable History
@app.route('/history', methods=['GET', 'POST'])
def history():
    search_query = request.form.get("search_tag")
    past_metadata = []

    try:
        docs = db.collection("image_metadata").stream()

        for doc in docs:
            data = doc.to_dict()
            image_name = data.get("image_name", "Unknown")
            tags = data.get("tags", [])

            if search_query:
                if any(search_query.lower() in tag.lower() for tag in tags):
                    past_metadata.append({"image_name": image_name, "tags": tags})
            else:
                past_metadata.append({"image_name": image_name, "tags": tags})

    except Exception as e:
        return f"Error fetching history: {str(e)}"

    return render_template('history.html', past_metadata=past_metadata, search_query=search_query)

if __name__ == '__main__':
    app.run(debug=True)
