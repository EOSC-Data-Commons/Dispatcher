import os
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)
PORT = int(os.environ.get("PORT", 7475))

# Store session cookies per backend URL
sessions = {}

# Helper to get a requests session for a backend URL
def get_session(backend_url):
    if backend_url not in sessions:
        sessions[backend_url] = requests.Session()
    return sessions[backend_url]

# Generic proxy request
def proxy_request(req, method, path_suffix, data=None):
    backend_url = req.headers.get('X-Backend-Url')
    if not backend_url:
        return jsonify({"error": "Missing X-Backend-Url header"}), 400

    session = get_session(backend_url)
    url = f"{backend_url.rstrip('/')}{path_suffix}"

    try:
        response = session.request(
            method,
            url,
            json=data,
            verify=False  # Allow self-signed certs in dev
        )

        # Return JSON or raw text
        try:
            content = response.json()
        except ValueError:
            content = response.text

        headers = {}
        if 'Location' in response.headers:
            headers['Location'] = response.headers['Location']

        return (content, response.status_code, headers)

    except requests.RequestException as e:
        return jsonify({"error": "Backend request failed", "details": str(e)}), 502

# Login endpoint
@app.route("/api/login", methods=["POST"])
def login():
    r = proxy_request(request, "POST", "/api/login/credentials", request.json)
    return r

# Logout endpoint
@app.route("/api/logout", methods=["POST"])
def logout():
    backend_url = request.headers.get('X-Backend-Url')
    if backend_url and backend_url in sessions:
        del sessions[backend_url]
    return jsonify({"message": "Logged out"}), 200

# Create project
@app.route("/api/projects", methods=["POST"])
def create_project():
    return proxy_request(request, "POST", "/api/projects", request.json)

# Project commands (start, etc.)
@app.route("/api/projects/<code>", methods=["POST"])
def project_command(code):
    return proxy_request(request, "POST", f"/api/projects/{code}", request.json)

# Get project status
@app.route("/api/projects/<code>", methods=["GET"])
def get_project_status(code):
    return proxy_request(request, "GET", f"/api/projects/{code}")

if __name__ == "__main__":
    print(f"Dispatcher dev tool running at http://localhost:{PORT}")
    app.run(port=PORT)
