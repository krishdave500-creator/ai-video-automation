"""
Flask API Server for AI Video Pipeline
=======================================
Exposes /run endpoint to trigger video generation via HTTP POST.

OPTIONAL / LEGACY: the recommended way to run this project is the GitHub Actions
workflow. This server is only for people who want to trigger runs from n8n.
Security: it refuses to start without API_TOKEN, only listens on 127.0.0.1 by
default, and every request must send the header  X-API-Key: <API_TOKEN>.
"""

from flask import Flask, request, jsonify
import subprocess
import sys
import os
import threading

app = Flask(__name__)
API_TOKEN = os.getenv("API_TOKEN", "")

# Global lock to prevent concurrent pipeline executions
pipeline_lock = threading.Lock()


@app.route("/run", methods=["POST"])
def run_pipeline():
    if not API_TOKEN or request.headers.get("X-API-Key", "") != API_TOKEN:
        return jsonify({"status": "error", "message": "Unauthorized"}), 401
    # Try to acquire lock (non-blocking)
    if not pipeline_lock.acquire(blocking=False):
        return jsonify({
            "status": "busy",
            "message": "Pipeline already running"
        }), 429

    try:
        data = request.json
        
        # Handle if data comes as an array (extract first element)
        if isinstance(data, list):
            if len(data) == 0:
                return jsonify({
                    "status": "error",
                    "message": "Empty array received"
                }), 400
            data = data[0]
        
        # Log received data for debugging
        print(f"\n[API] Received request:")
        print(f"  Raw data: {data}")
        
        # Extract and validate fields - strip '=' prefix if present (Excel/n8n quirk)
        topic = str(data.get("topic", "")).strip()
        if topic.startswith("="):
            topic = topic[1:].strip()
            
        format_choice = str(data.get("format", "video")).strip().lower()
        if format_choice.startswith("="):
            format_choice = format_choice[1:].strip()
            
        upload_input = data.get("upload")
        if isinstance(upload_input, str) and upload_input.startswith("="):
            upload_input = upload_input[1:].strip()
            
        privacy = str(data.get("privacy", "private")).strip().lower()
        if privacy.startswith("="):
            privacy = privacy[1:].strip()
        
        # Convert upload to boolean properly
        if isinstance(upload_input, bool):
            upload = upload_input
        elif isinstance(upload_input, str):
            upload = upload_input.lower() in ["true", "yes", "1"]
        else:
            upload = False
        
        # Validate inputs
        if topic.startswith("-") or len(topic) > 200:
            return jsonify({"status": "error", "message": "Invalid topic"}), 400
        # empty topic is fine: the pipeline lets the AI pick a fresh one
        
        if format_choice not in ["short", "video"]:
            return jsonify({
                "status": "error",
                "message": f"Invalid format: {format_choice}. Must be 'short' or 'video'"
            }), 400
        
        print(f"  Parsed - Topic: {topic}")
        print(f"  Parsed - Format: {format_choice}")
        print(f"  Parsed - Upload: {upload}")
        print(f"  Parsed - Privacy: {privacy}")

        # Get the directory where server.py is located
        script_dir = os.path.dirname(os.path.abspath(__file__))
        main_py_path = os.path.join(script_dir, "main.py")
        
        subprocess.run(
            [
                sys.executable,  # Use the same Python interpreter running Flask
                main_py_path,
                topic,
                format_choice,
                "true" if upload else "false",
                privacy
            ],
            check=True,
            cwd=script_dir,  # Run from the project directory
            timeout=3600,
        )

        return jsonify({
            "status": "success",
            "message": "Pipeline executed successfully"
        }), 200

    except subprocess.TimeoutExpired:
        return jsonify({"status": "error", "message": "Pipeline timed out"}), 504

    except subprocess.CalledProcessError as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500
    
    except Exception as e:
        return jsonify({
            "status": "error",
            "message": f"Server error: {str(e)}"
        }), 500

    finally:
        # Always release the lock
        pipeline_lock.release()


if __name__ == "__main__":
    if not API_TOKEN:
        sys.exit("Set API_TOKEN first (a long random string), then start the server again.")
    app.run(host=os.getenv("HOST", "127.0.0.1"), port=int(os.getenv("PORT", "5000")))
