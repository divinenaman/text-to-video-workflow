#!/usr/bin/env python3
"""
Sanity check script for Local S3 container integration.
Validates credentials, bucket presence, file upload, and public URL accessibility.
"""

import os
import sys
import tempfile
import urllib.request
import configparser

# Add repository root to path
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

def main():
    print("=" * 60)
    print("  Testing Local S3 Container Integration")
    print("=" * 60)

    # 1. Read configuration
    config = configparser.ConfigParser()
    config.read(os.path.join(REPO_ROOT, "config.ini"))
    local_cfg = os.path.join(REPO_ROOT, "config.local.ini")
    if os.path.exists(local_cfg):
        config.read(local_cfg)

    access_key = config.get("OBJECT_STORAGE", "ACCESS_KEY", fallback="test")
    secret_key = config.get("OBJECT_STORAGE", "SECRET_KEY", fallback="test")
    cluster = config.get("OBJECT_STORAGE", "CLUSTER", fallback="localhost:9000")

    print(f"\n[1] Configuration:")
    print(f"    • Cluster / Endpoint : {cluster}")
    print(f"    • Access Key         : {access_key}")
    print(f"    • Secret Key         : {'*' * len(secret_key)}")

    # 2. Configure baasha_pipeline
    from baasha_pipeline.configs import app_config as baasha_pipeline_config
    baasha_pipeline_config.get()["auth"]["object_storage"] = {
        "access_key": access_key,
        "secret_key": secret_key,
        "cluster": cluster,
    }

    from baasha_pipeline import object_storage

    # 3. Connect to S3
    print(f"\n[2] Connecting to S3 via boto3...")
    try:
        conn, cl = object_storage.create_connection(None)
        res = conn.list_buckets()
        bucket_names = [b["Name"] for b in res.get("Buckets", [])]
        print(f"    ✓ Successfully connected to S3!")
        print(f"    ✓ Found buckets: {bucket_names}")
    except Exception as e:
        print(f"    ✗ Connection failed: {e}")
        print("\nEnsure the local S3 container is running by executing:")
        print("    bash scripts/start_local_s3.sh")
        sys.exit(1)

    # 4. Ensure required buckets exist
    required_buckets = ["baasha-assets", "baasha-bgm"]
    for req_bucket in required_buckets:
        if req_bucket not in bucket_names:
            print(f"    Creating missing bucket: {req_bucket}...")
            conn.create_bucket(Bucket=req_bucket)
            print(f"    ✓ Bucket '{req_bucket}' created.")
        else:
            print(f"    ✓ Bucket '{req_bucket}' exists.")

    # 5. Upload test file
    print(f"\n[3] Testing file upload via object_storage.upload_file()...")
    with tempfile.NamedTemporaryFile("w+", delete=False, suffix=".txt") as tmp:
        tmp.write("Local S3 integration verification payload: OK\n")
        tmp_path = tmp.name

    test_filename = f"health_check_{os.getpid()}.txt"
    try:
        uploaded_url = object_storage.upload_file(
            object_storage.ASSETS_IMG_BUCKET,
            tmp_path,
            test_filename,
            object_storage.ACL_PUBLIC,
        )
        print(f"    ✓ Upload succeeded!")
        print(f"    ✓ Public URL: {uploaded_url}")
    except Exception as e:
        print(f"    ✗ Upload failed: {e}")
        os.remove(tmp_path)
        sys.exit(1)
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)

    # 6. Verify HTTP download of the uploaded URL
    print(f"\n[4] Verifying HTTP download from generated URL...")
    try:
        req = urllib.request.Request(uploaded_url)
        with urllib.request.urlopen(req, timeout=5) as resp:
            content = resp.read().decode("utf-8")
            status = resp.status
        print(f"    ✓ HTTP Status: {status}")
        print(f"    ✓ Received content: '{content.strip()}'")
    except Exception as e:
        print(f"    ✗ HTTP download verification failed: {e}")
        sys.exit(1)

    # 7. Cleanup test object
    try:
        conn.delete_object(
            Bucket=object_storage.ASSETS_IMG_BUCKET[0],
            Key=f"{object_storage.ASSETS_IMG_BUCKET[1]}{test_filename}",
        )
        print(f"    ✓ Cleaned up test object from S3.")
    except Exception:
        pass

    print("\n" + "=" * 60)
    print("  ALL LOCAL S3 CHECKS PASSED! Ready for development. 🎉")
    print("=" * 60)

if __name__ == "__main__":
    main()
