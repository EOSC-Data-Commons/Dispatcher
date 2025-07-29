#!/usr/bin/env python3
"""
Simple Flask app to receive OCM share requests from ScienceMesh dispatcher.
This simulates a ScienceMesh service endpoint that can receive RO-Crate shares.
"""

from flask import Flask, request, jsonify
import logging
import json
from datetime import datetime

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Store received shares in memory
received_shares = []


@app.route('/', methods=['GET'])
def home():
    """Home endpoint showing basic information about the service."""
    return jsonify({
        "service": "ScienceMesh OCM Share Receiver",
        "version": "1.0.0",
        "description": "Simple Flask app to receive OCM share requests",
        "endpoints": {
            "health": "/health",
            "ocm_share": "/ocm/share",
            "list_shares": "/shares"
        }
    })


@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint."""
    return jsonify({
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "received_shares_count": len(received_shares)
    })


@app.route('/ocm/shares', methods=['POST'])
def receive_ocm_share():
    """
    Receive OCM share requests from ScienceMesh dispatcher.
    """
    try:
        # Get JSON data from request
        share_data = request.get_json()

        if not share_data:
            logger.error("No JSON data received in request")
            return jsonify({"error": "No JSON data provided"}), 400

        # Validate required fields
        required_fields = [
            "shareWith", "name", "owner", "sender",
            "resourceType", "shareType", "protocols"
        ]

        missing_fields = [field for field in required_fields if field not in share_data]
        if missing_fields:
            logger.error(f"Missing required fields: {missing_fields}")
            return jsonify({
                "error": "Missing required fields",
                "missing_fields": missing_fields
            }), 400

        # Validate resource type
        if share_data.get("resourceType") != "ro-crate":
            logger.error(f"Unsupported resource type: {share_data.get('resourceType')}")
            return jsonify({
                "error": "Unsupported resource type",
                "supported_types": ["ro-crate"]
            }), 400

        # Validate protocols
        protocols = share_data.get("protocols", {})
        if "rocrate" not in protocols:
            logger.error("Missing RO-Crate data in protocols")
            return jsonify({"error": "Missing RO-Crate data in protocols"}), 400

        # Process the share request
        share_id = f"share_{len(received_shares) + 1}_{int(datetime.now().timestamp())}"

        processed_share = {
            "share_id": share_id,
            "received_at": datetime.now().isoformat(),
            "status": "received",
            "share_data": share_data
        }


        # Store the share (in production, save to database)
        received_shares.append(processed_share)

        # Extract RO-Crate info for logging
        rocrate_name = share_data.get("name")
        rocrate_description = share_data.get("description")

        logger.info(f"Received OCM share request:")
        logger.info(f"  Share ID: {share_id}")
        logger.info(f"  From: {share_data.get('sender')} ({share_data.get('senderDisplayName')})")
        logger.info(f"  To: {share_data.get('shareWith')}")
        logger.info(f"  Owner: {share_data.get('owner')}")
        logger.info(f"  RO-Crate: {rocrate_name}")
        logger.info(f"  Description: {rocrate_description}")

        # Return success response
        response = {
            "status": "success",
            "message": "OCM share request received successfully",
            "share_id": share_id,
            "received_at": processed_share["received_at"],
            "share_details": {
                "name": share_data.get("name"),
                "from": share_data.get("sender"),
                "to": share_data.get("shareWith"),
                "resource_type": share_data.get("resourceType")
            }
        }

        return jsonify(response), 200

    except json.JSONDecodeError:
        logger.error("Invalid JSON in request")
        return jsonify({"error": "Invalid JSON format"}), 400

    except Exception as e:
        logger.error(f"Error processing OCM share request: {str(e)}")
        return jsonify({
            "error": "Internal server error",
            "message": str(e)
        }), 500


@app.route('/shares', methods=['GET'])
def list_shares():
    """List all received shares."""
    return jsonify({
        "total_shares": len(received_shares),
        "shares": [
            {
                "share_id": share["share_id"],
                "received_at": share["received_at"],
                "status": share["status"],
                "from": share["share_data"].get("sender"),
                "to": share["share_data"].get("shareWith"),
                "name": share["share_data"].get("name"),
                "resource_type": share["share_data"].get("resourceType")
            }
            for share in received_shares
        ]
    })


@app.route('/shares/<share_id>', methods=['GET'])
def get_share_details(share_id):
    """Get detailed information about a specific share."""
    share = next((s for s in received_shares if s["share_id"] == share_id), None)

    if not share:
        return jsonify({"error": "Share not found"}), 404

    return jsonify(share)


@app.route('/shares/<share_id>/rocrate', methods=['GET'])
def get_share_rocrate(share_id):
    """Get the RO-Crate data for a specific share."""
    share = next((s for s in received_shares if s["share_id"] == share_id), None)

    if not share:
        return jsonify({"error": "Share not found"}), 404

    protocols = share["share_data"].get("protocols", {})
    rocrate = protocols.get("rocrate", {})

    if not rocrate:
        return jsonify({"error": "No RO-Crate data found for this share"}), 404

    return jsonify(rocrate)


if __name__ == '__main__':
    print("Starting ScienceMesh OCM Share Receiver...")
    print("Available endpoints:")
    print("  GET  /           - Service information")
    print("  GET  /health     - Health check")
    print("  POST /ocm/share  - Receive OCM share requests")
    print("  GET  /shares     - List all received shares")
    print("  GET  /shares/<id> - Get share details")
    print("  GET  /shares/<id>/rocrate - Get RO-Crate data")
    print()

    # Run the Flask app
    app.run(
        host='0.0.0.0',
        port=5000,
        debug=True
    )
