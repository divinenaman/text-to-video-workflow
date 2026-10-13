#!/usr/bin/python
"""Uploads a video to YouTube."""

import argparse
from http import client
import httplib2

import logging
import os
import random
import time
from dataclasses import dataclass
from collections import namedtuple
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload
from google_auth_oauthlib.flow import InstalledAppFlow
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request

# Explicitly tell the underlying HTTP transport library not to retry, since
# we are handling retry logic ourselves.
httplib2.RETRIES = 1

# Maximum number of times to retry before giving up.
MAX_RETRIES = 10

# Always retry when these exceptions are raised.
RETRIABLE_EXCEPTIONS = (
    httplib2.HttpLib2Error,
    IOError,
    client.NotConnected,
    client.IncompleteRead,
    client.ImproperConnectionState,
    client.CannotSendRequest,
    client.CannotSendHeader,
    client.ResponseNotReady,
    client.BadStatusLine,
)

# Always retry when an apiclient.errors.HttpError with one of these status
# codes is raised.
RETRIABLE_STATUS_CODES = [500, 502, 503, 504]

file_dir = os.path.join(os.path.dirname(__file__), "..")

# The CLIENT_SECRETS_FILE variable specifies the name of a file that contains
# the OAuth 2.0 information for this application, including its client_id and
# client_secret. You can acquire an OAuth 2.0 client ID and client secret from
# the {{ Google Cloud Console }} at
# {{ https://cloud.google.com/console }}.
# Please ensure that you have enabled the YouTube Data API for your project.
# For more information about using OAuth2 to access the YouTube Data API, see:
#   https://developers.google.com/youtube/v3/guides/authentication
# For more information about the client_secrets.json file format, see:
#   https://developers.google.com/api-client-library/python/guide/aaa_client_secrets
CLIENT_SECRETS_FILE = os.path.join(
    file_dir, "client_secret.json"
)  #'%s/client_secret.json' %

# This OAuth 2.0 access scope allows an application to upload files to the
# authenticated user's YouTube channel, but doesn't allow other types of access.
SCOPES = ["https://www.googleapis.com/auth/youtube.force-ssl"]
API_SERVICE_NAME = "youtube"
API_VERSION = "v3"

VALID_PRIVACY_STATUSES = ("public", "private", "unlisted")

DEFAULT_TOKEN_PATH = os.path.join(file_dir, "token.json")


@dataclass
class YtUploadInput:
    file: str
    title: str
    description: str
    category: str
    keywords: str
    privacyStatus: str
    channelId: str

    def __post_init__(self):
        k = list(filter(lambda x: x != "", self.keywords.split()))
        self.keywords = " ".join(k[0 : min(16, len(k))])


# Authorize the request and store authorization credentials.
def get_authenticated_service(channel_id: str):

    TOKEN_PATH = DEFAULT_TOKEN_PATH

    if channel_id != None and channel_id != "":
        TOKEN_PATH = os.path.join(file_dir, f"{channel_id}_token.json")

    creds = None

    if os.path.exists(TOKEN_PATH):
        creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                CLIENT_SECRETS_FILE, SCOPES
            )
            creds = flow.run_local_server(port=8899)

        with open(TOKEN_PATH, "w") as token:
            token.write(creds.to_json())

    return build(API_SERVICE_NAME, API_VERSION, credentials=creds)


def initialize_upload(youtube, options):
    tags = None
    if options.keywords:
        tags = options.keywords.split(",")

    body = dict(
        snippet=dict(
            title=options.title,
            description=options.description,
            tags=tags,
            categoryId=options.category,
        ),
        status=dict(privacyStatus=options.privacyStatus),
        # channelId=options.channelId
    )

    # Call the API's videos.insert method to create and upload the video.
    insert_request = youtube.videos().insert(
        part=",".join(body.keys()),
        body=body,
        # The chunksize parameter specifies the size of each chunk of data, in
        # bytes, that will be uploaded at a time. Set a higher value for
        # reliable connections as fewer chunks lead to faster uploads. Set a lower
        # value for better recovery on less reliable connections.
        #
        # Setting 'chunksize' equal to -1 in the code below means that the entire
        # file will be uploaded in a single HTTP request. (If the upload fails,
        # it will still be retried where it left off.) This is usually a best
        # practice, but if you're using Python older than 2.6 or if you're
        # running on App Engine, you should set the chunksize to something like
        # 1024 * 1024 (1 megabyte).
        media_body=MediaFileUpload(options.file, chunksize=-1, resumable=True),
    )

    return resumable_upload(insert_request)


# This method implements an exponential backoff strategy to resume a
# failed upload.


def resumable_upload(request):
    response = None
    error = None
    retry = 0
    while response is None:
        try:
            print("Uploading file...")
            status, response = request.next_chunk()
            if response is not None:
                if "id" in response:
                    print(
                        'Video id "%s" was successfully uploaded.' % response["id"],
                        response,
                    )
                    idx = response["id"]
                    link = f"https://www.youtube.com/shorts/{idx}"
                    print(f"VIDEO LINK: {link}")
                    return link
                else:
                    exit("The upload failed with an unexpected response: %s" % response)
        except HttpError as hex:
            if hex.resp.status in RETRIABLE_STATUS_CODES:
                error = "A retriable HTTP error %d occurred:\n%s" % (
                    hex.resp.status,
                    hex.content,
                )
            else:
                raise
        except RETRIABLE_EXCEPTIONS as rex:
            error = "A retriable error occurred: %s" % rex

        if error is not None:
            print(error)
            retry += 1
            if retry > MAX_RETRIES:
                exit("No longer attempting to retry.")

            max_sleep = 2**retry
            sleep_seconds = random.random() * max_sleep
            print("Sleeping %f seconds and then retrying..." % sleep_seconds)
            time.sleep(sleep_seconds)


def post_youtube_shorts_video(path, title, description, tags, privacy_status="public"):
    YTArgs = namedtuple(
        "YTArgs",
        {"file", "title", "description", "category", "privacyStatus", "keywords"},
    )
    try:
        yt = get_authenticated_service()
        initialize_upload(
            yt,
            YTArgs(
                file=path,
                title=title,
                description=description,
                category="22",
                privacyStatus=privacy_status,
                keywords=",".join(tags),
            ),
        )
    except HttpError as ex:
        print("An HTTP error %d occurred:\n%s" % (ex.resp.status, ex.content))


def get_youtube_arg_parser():
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--file", required=True, help="Video file to upload")
    argument_parser.add_argument("--title", help="Video title", default="Test Title")
    argument_parser.add_argument(
        "--description", help="Video description", default="Test Description"
    )
    argument_parser.add_argument(
        "--category",
        default="22",
        help="Numeric video category. "
        + "See https://developers.google.com/youtube/v3/docs/videoCategories/list",
    )
    argument_parser.add_argument(
        "--keywords", help="Video keywords, comma separated", default=""
    )
    argument_parser.add_argument(
        "--privacyStatus",
        choices=VALID_PRIVACY_STATUSES,
        default="private",
        help="Video privacy status.",
    )
    return argument_parser


if __name__ == "__main__":
    parser = get_youtube_arg_parser()
    args = parser.parse_args()
    youtube = get_authenticated_service()
    try:
        print("good")
        # initialize_upload(youtube, args)
    except HttpError as e:
        print("An HTTP error %d occurred:\n%s" % (e.resp.status, e.content))


# Example usage via import:
# from youtube_uploader import post_youtube_shorts_video
# path = "/path/to/video/file.mp4"
# post_youtube_shorts_video(path, "Test video 0", "sample video 0", ["test", "first"], privacy_status='public')
