import os
from dotenv import load_dotenv
import firebase_admin
from firebase_admin import credentials, firestore
from flask import Flask, render_template, request, send_file, flash, redirect, url_for, jsonify
import requests
import base64
import json
import io

load_dotenv()

app = Flask(__name__, template_folder="templates")
app.secret_key = os.getenv("FLASK_SECRET_KEY")
if not app.secret_key:
    raise ValueError("FLASK_SECRET_KEY not found in .env file")

cred = credentials.Certificate(os.getenv("FIREBASE_CREDENTIALS_PATH"))
firebase_admin.initialize_app(cred)
db = firestore.client()

UPLOAD_FOLDER = 'static/uploads'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if not GEMINI_API_KEY:
    raise ValueError("GEMINI_API_KEY not found in .env file")

GEMINI_API_BASE_URL = "https://vision.googleapis.com/v1/images:annotate?key="
if not GEMINI_API_BASE_URL:
    raise ValueError("GEMINI_API_BASE_URL not found in .env file")

GEMINI_API_URL = f"{GEMINI_API_BASE_URL}{GEMINI_API_KEY}"

app.secret_key = os.getenv("FLASK_SECRET_KEY")
if not app.secret_key:
    raise ValueError("FLASK_SECRET_KEY not found in .env file")

firebase_credentials_path = os.getenv("FIREBASE_CREDENTIALS_PATH")
if not firebase_credentials_path:
    raise ValueError("FIREBASE_CREDENTIALS_PATH not found in .env file")
cred = credentials.Certificate(firebase_credentials_path)

def get_image_metadata(image_path): #image_path is now passed in.
    try:
        with open(image_path, "rb") as image_file: #open the image that was saved.
            img_base64 = base64.b64encode(image_file.read()).decode("utf-8")
        payload = {
            "requests": [{"image": {"content": img_base64}, "features": [{"type": "LABEL_DETECTION"}, {"type": "OBJECT_LOCALIZATION"}, {"type": "TEXT_DETECTION"}, {"type": "LOGO_DETECTION"}, {"type": "LANDMARK_DETECTION"}, {"type": "IMAGE_PROPERTIES"}, {"type": "SAFE_SEARCH_DETECTION"}]}]
        }
        response = requests.post(GEMINI_API_URL, json=payload)
        if response.status_code == 200:
            return response.json()
        else:
            return {"error": f"API Request Failed - Status {response.status_code}", "details": response.text}
    except FileNotFoundError:
        return {"error": "File not found"}
    except Exception as e:
        return {"error": f"An error occurred: {str(e)}"}

@app.route('/', methods=['GET', 'POST'])
def home():
    metadata = None
    tags = []
    image_name = None
    image_url = None

    if request.method == 'POST' and 'image' in request.files:
        image = request.files['image']

        # Ensure the upload folder exists
        if not os.path.exists(app.config["UPLOAD_FOLDER"]):
            os.makedirs(app.config["UPLOAD_FOLDER"])

        # Save the uploaded image
        image_path = os.path.join(app.config["UPLOAD_FOLDER"], image.filename)
        image.save(image_path)

        # Process image metadata
        metadata = get_image_metadata(image_path) #pass in the image path.
        if "error" in metadata: #check for errors.
            flash(metadata["error"], "error")
            return render_template('index_.html', metadata=metadata, tags=tags, image_name=image_name, image_url=image_url)

        labels = metadata.get("responses", [{}])[0].get("labelAnnotations", [])
        tags = [label.get("description", "") for label in labels]
        image_name = image.filename

        # Store metadata in Firestore
        db.collection("image_metadata").document(image_name).set({
            "image_name": image_name,
            "metadata": metadata,
            "tags": tags
        })

        image_url = url_for('uploaded_file', filename=image_name)

    return render_template('index_.html', metadata=metadata, tags=tags, image_name=image_name, image_url=image_url)

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

@app.route('/download_metadata/<image_name>', methods=['GET', 'POST'])
def download_metadata(image_name):
    try:
        doc_ref = db.collection("image_metadata").document(image_name)
        doc = doc_ref.get()
        if doc.exists:
            metadata = doc.to_dict().get("metadata", {})
            json_data = json.dumps(metadata, indent=2)
            filename = request.args.get('filename') #changed line
            if filename is None:
                filename = f"{image_name}_metadata.json"

            return send_file(io.BytesIO(json_data.encode()), as_attachment=True, download_name=filename, mimetype="application/json")

    except Exception as e:
        flash(f"Error downloading metadata: {str(e)}", "error")
    return redirect(url_for('home'))

@app.route('/delete_image/<image_name>', methods=['POST'])
def delete_image(image_name):
    try:
        db.collection("image_metadata").document(image_name).delete()
        flash(f"Deleted {image_name} successfully!", "success")
    except Exception as e:
        flash(f"Error deleting {image_name}: {str(e)}", "error")
    return redirect(url_for('history'))

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


@app.route('/uploads/<filename>')
def uploaded_file(filename):
    file_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
    if os.path.exists(file_path):
        return send_file(file_path)
    else:
        return "File not found", 404



if __name__ == '__main__':
    app.run(debug=True)