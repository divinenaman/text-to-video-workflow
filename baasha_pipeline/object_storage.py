#  https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/s3.html#client

import boto3
import os

from .configs import app_config
from . import errors
from .logger import logging


@errors.raise_ctx_errors
def object_storage_creds():
    auth_config = app_config.get().get("auth").get("object_storage")
    return {
        "access_key": auth_config.get("access_key"),
        "secret_key": auth_config.get("secret_key"),
        "cluster": auth_config.get("cluster"),
    }


@errors.raise_ctx_errors
def get_assets_bucket_name():
    return app_config.get().get("auth").get("object_storage").get("assets_bucket", "baasha-assets")


@errors.raise_ctx_errors
def get_bgm_bucket_name():
    return app_config.get().get("auth").get("object_storage").get("bgm_bucket", "baasha-bgm")


@errors.raise_ctx_errors
def get_protocol():
    return app_config.get().get("auth").get("object_storage").get("protocol", "https")


@errors.raise_ctx_errors
def get_cluster():
    return object_storage_creds().get("cluster")


@errors.raise_ctx_errors
def build_asset_url(path: str = "") -> str:
    """Build a URL for an asset in the assets bucket."""
    bucket = get_assets_bucket_name()
    cluster = get_cluster()
    protocol = get_protocol()
    if path:
        return f"{protocol}://{bucket}.{cluster}/{path}"
    return f"{protocol}://{bucket}.{cluster}"


@errors.raise_ctx_errors
def build_bgm_url(path: str = "") -> str:
    """Build a URL for an asset in the BGM bucket."""
    bucket = get_bgm_bucket_name()
    cluster = get_cluster()
    protocol = get_protocol()
    if path:
        return f"{protocol}://{bucket}.{cluster}/{path}"
    return f"{protocol}://{bucket}.{cluster}"


# (bucket-name, folder-path)
def BGM_BUCKET():
    return (get_bgm_bucket_name(), "")


def ASSETS_IMG_BUCKET():
    return (get_assets_bucket_name(), "images/")


def ASSETS_AUDIO_BUCKET():
    return (get_assets_bucket_name(), "audios/")


def ASSETS_VIDEO_CONFIG():
    return (get_assets_bucket_name(), "video-configs/")


def ASSETS_VIDEO_BUCKET():
    return (get_assets_bucket_name(), "videos/")


def ASSETS_PROMPT_IMAGE_GEN():
    return (get_assets_bucket_name(), "prompts/image_gen/")


def ASSETS_PROMPT_SCRIPT_GEN():
    return (get_assets_bucket_name(), "prompts/script_gen/")


# private'|'public-read'|'public-read-write'|'authenticated-read'|'aws-exec-read'|'bucket-owner-read'|'bucket-owner-full-control'
ACL_PUBLIC = "public-read"
ACL_PRIVATE = "private"


@errors.raise_ctx_errors
def create_connection(client):
    if client:
        return client

    creds = object_storage_creds()
    cluster = creds["cluster"]
    protocol = get_protocol()
    config = {
        "aws_access_key_id": creds["access_key"],
        "aws_secret_access_key": creds["secret_key"],
        "endpoint_url": f"{protocol}://{cluster}",
    }
    conn = boto3.client("s3", **config)
    return (conn, cluster)


@errors.raise_ctx_errors
def mk_url(cluster, bucket_name, key):
    protocol = get_protocol()
    return f"{protocol}://{bucket_name}.{cluster}/{key}"


@errors.raise_ctx_errors
def mk_url_from_bucket(bucket_name, key):
    cluster = get_cluster()
    protocol = get_protocol()
    return f"{protocol}://{bucket_name}.{cluster}/{key}"


@errors.raise_ctx_errors
def list_bucket_names(client=None):
    conn, _ = create_connection(client)
    res = conn.list_buckets()
    for bucket in res["Buckets"]:
        print("{name}\t".format(name=bucket["Name"]))


@errors.raise_ctx_errors
def upload_file(bucket, filepath, name, acl=ACL_PRIVATE, client=None):
    bucket_name, folder_path = bucket
    conn, cluster = create_connection(client)
    key = f"{folder_path}{name}"

    conn.upload_file(
        Filename=filepath, Bucket=bucket_name, Key=key, ExtraArgs={"ACL": acl}
    )

    return mk_url(cluster, bucket_name, key)


@errors.raise_ctx_errors
def upload_data(bucket, data, name, acl=ACL_PRIVATE, client=None):
    bucket_name, folder_path = bucket
    conn, cluster = create_connection(client)
    key = f"{folder_path}{name}"

    conn.put_object(Body=data, Bucket=bucket_name, Key=key, ACL=acl)

    return mk_url(cluster, bucket_name, key)


@errors.log_ctx_errors
def get_object_url_from_key(bucket, name, client=None):
    bucket_name, folder_path = bucket
    conn, cluster = create_connection(client)
    skey = f"{folder_path}{name}"
    res = conn.list_objects(Bucket=bucket_name, Prefix=skey)
    content = res.get("Contents")
    if content != None and len(content) > 0:
        key = content[0]["Key"]
        return mk_url(cluster, bucket_name, key)

    return None


if __name__ == "__main__":
    list_bucket_names()

    filepath = os.path.join(os.path.dirname(__file__), "..", "README.md")
    # res = upload_file(ASSETS_AUDIO_BUCKET, filepath, "d", ACL_PUBLIC)
    # data = bytearray("Hello!", 'utf-8')
    # res = upload_data(ASSETS_AUDIO_BUCKET, data, "data.txt", ACL_PUBLIC)
    # print(res)

    res = get_object_url_from_key(ASSETS_AUDIO_BUCKET, "data.txt")
    print(res)
