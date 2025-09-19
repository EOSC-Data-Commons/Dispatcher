#!/usr/bin/env python3
"""
Main test script for VREScienceMesh class.
This script loads the RO-Crate metadata, creates a VREScienceMesh instance,
and sends the OCM share request to the Flask receiver for testing.
"""

import os
import sys
import time
import requests
from rocrate.rocrate import ROCrate

# Add the app directory to Python path to import VREScienceMesh
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../app'))

from app.vres.base_vre import vre_factory
from app.vres import base_vre
from app.vres.sciencemesh import VREScienceMesh

def main():
    """Main test function."""
    print("Testing VREScienceMesh with RO-Crate")
    print("=" * 50)

    # Get the path to the RO-Crate metadata
    script_dir = os.path.dirname(os.path.abspath(__file__))
    metadata_path = os.path.join(script_dir, "ro-crate-metadata.json")

    # Load RO-Crate
    print(f"Loading RO-Crate from: {metadata_path}")
    try:
        crate_dir = os.path.dirname(metadata_path)
        crate = ROCrate(crate_dir)
    except Exception as e:
        print(f"Error loading RO-Crate: {e}")
        return

    # Create VREScienceMesh instance
    try:
        vre = vre_factory(crate)
        print(f"Service URL: {vre.service['url']}")
    except Exception as e:
        print(f"Error creating VREScienceMesh: {e}")
        return

    try:
        vre.post()

        # Verify the share was received
        time.sleep(1)
        shares_response = requests.get("http://localhost:5000/shares")
        if shares_response.status_code == 200:
            shares_data = shares_response.json()
            print(f"Flask receiver now has {shares_data['total_shares']} shares")
            if shares_data['shares']:
                latest = shares_data['shares'][-1]
                print(f"   Latest share: {latest['name']} (ID: {latest['share_id']})")

    except Exception as e:
        print(f"Error sending request: {e}")
        return


if __name__ == "__main__":
    main()
