import os
import logging
import json
import requests
import base64
from datetime import datetime
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
import io
from googleapiclient.http import MediaIoBaseDownload

# --- Configuration ---
# These are now loaded from environment variables or GitHub Secrets
FACEBOOK_PAGE_TOKEN = os.getenv('FACEBOOK_PAGE_TOKEN')
FACEBOOK_PAGE_ID = os.getenv('FACEBOOK_PAGE_ID')
GDRIVE_FOLDER_ID = os.getenv('GDRIVE_FOLDER_ID')
HASHTAGS = os.getenv('HASHTAGS', '#video #upload')
GDRIVE_TOKEN_BASE64 = os.getenv('GDRIVE_TOKEN_BASE64') # <<< MODIFIED: For server auth

# --- Constants ---
SCOPES = ['https://www.googleapis.com/auth/drive.readonly']
TOKEN_FILE = 'token.pickle'
CREDENTIALS_FILE = 'credentials.json'
UPLOADED_VIDEOS_FILE = 'uploaded_videos.json'

# --- Logging Setup ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def authenticate_google_drive():
    """Authenticate and return Google Drive service."""
    creds = None
    
    # <<< MODIFIED: Server-friendly authentication flow
    # On a server, we'll create the token file from a Base64 environment variable
    if GDRIVE_TOKEN_BASE64:
        logger.info("Found Base64 token. Decoding to token.pickle file.")
        try:
            decoded_token = base64.b64decode(GDRIVE_TOKEN_BASE64)
            with open(TOKEN_FILE, 'wb') as token:
                token.write(decoded_token)
        except Exception as e:
            logger.error(f"Could not decode or write the Base64 token: {e}")
            return None

    if os.path.exists(TOKEN_FILE):
        try:
            creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
        except Exception as e:
            logger.error(f"Error loading token from file: {e}")

    # If credentials are not valid or don't exist, fall back to local flow
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            logger.info("Refreshing expired credentials.")
            creds.refresh(Request())
        else:
            # This part will only run if you execute it locally without a token.pickle
            logger.info("No valid credentials found. Starting local authentication flow.")
            if not os.path.exists(CREDENTIALS_FILE):
                logger.error(f"{CREDENTIALS_FILE} not found. This file is required for the initial authentication.")
                return None
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
            creds = flow.run_local_server(port=0)
        
        # Save the credentials for the next run
        with open(TOKEN_FILE, 'w') as token:
            token.write(creds.to_json())
    
    return build('drive', 'v3', credentials=creds)

def get_uploaded_videos():
    """Load the list of already uploaded videos."""
    if os.path.exists(UPLOADED_VIDEOS_FILE):
        with open(UPLOADED_VIDEOS_FILE, 'r') as f:
            try:
                return json.load(f)
            except json.JSONDecodeError:
                logger.warning("uploaded_videos.json is corrupted or empty. Starting fresh.")
                return []
    return []

def save_uploaded_video(video_id, video_name):
    """Save video ID to uploaded list."""
    uploaded_videos = get_uploaded_videos()
    uploaded_videos.append({
        'id': video_id,
        'name': video_name,
        'uploaded_at': datetime.now().isoformat()
    })
    with open(UPLOADED_VIDEOS_FILE, 'w') as f:
        json.dump(uploaded_videos, f, indent=2)

def get_videos_from_drive(service, folder_id):
    """Get list of videos from Google Drive folder."""
    try:
        logger.info(f"Searching for videos in folder ID: {folder_id}")
        query = f"'{folder_id}' in parents and mimeType contains 'video/'"
        results = service.files().list(
            q=query,
            pageSize=100, # Get a decent number of files
            fields="nextPageToken, files(id, name, createdTime)"
        ).execute()
        videos = results.get('files', [])
        logger.info(f"Found {len(videos)} videos in Drive folder.")
        return videos
    except HttpError as error:
        logger.error(f"An error occurred with the Drive API: {error}")
        return []

def download_video_from_drive(service, video_id, video_name):
    """Download video from Google Drive into memory."""
    try:
        logger.info(f"Downloading video: {video_name} (ID: {video_id})")
        request = service.files().get_media(fileId=video_id)
        file_buffer = io.BytesIO()
        downloader = MediaIoBaseDownload(file_buffer, request)
        done = False
        while not done:
            status, done = downloader.next_chunk()
            if status:
                logger.info(f"Download progress: {int(status.progress() * 100)}%")
        video_data = file_buffer.getvalue()
        logger.info(f"Successfully downloaded {video_name}, size: {len(video_data) / 1e6:.2f} MB")
        return video_data
    except Exception as e:
        logger.error(f"Error downloading video: {e}")
        return None

def upload_video_to_facebook(video_data, video_name, page_token, page_id, hashtags):
    """Upload video to Facebook page."""
    try:
        logger.info(f"Uploading {video_name} to Facebook...")
        url = f"https://graph-video.facebook.com/v19.0/{page_id}/videos" # Use graph-video endpoint
        post_data = {
            'access_token': page_token,
            'title': os.path.splitext(video_name)[0], # Use filename without extension as title
            'description': hashtags,
        }
        files = {
            'source': (video_name, video_data, 'video/mp4')
        }
        response = requests.post(url, data=post_data, files=files, timeout=900) # Increased timeout
        
        logger.info(f"Facebook API Response Status: {response.status_code}")
        response_json = response.json()

        if response.status_code == 200:
            logger.info(f"✅ Successfully uploaded {video_name} to Facebook! Video ID: {response_json.get('id', 'N/A')}")
            return True
        else:
            logger.error(f"❌ Failed to upload {video_name}. Response: {response_json}")
            return False
            
    except Exception as e:
        logger.error(f"An error occurred while uploading to Facebook: {e}")
        return False

def main():
    """Main function to process and upload one new video."""
    logger.info("--- Starting video upload process ---")

    if not all([GDRIVE_FOLDER_ID, FACEBOOK_PAGE_TOKEN, FACEBOOK_PAGE_ID]):
        logger.critical("FATAL: Missing one or more required environment variables. Exiting.")
        return

    drive_service = authenticate_google_drive()
    if not drive_service:
        logger.critical("FATAL: Could not authenticate with Google Drive. Exiting.")
        return

    all_videos = get_videos_from_drive(drive_service, GDRIVE_FOLDER_ID)
    if not all_videos:
        logger.info("No videos found in Drive folder. Exiting.")
        return

    uploaded_video_ids = {v['id'] for v in get_uploaded_videos()}
    
    new_videos = [v for v in all_videos if v['id'] not in uploaded_video_ids]
    
    if not new_videos:
        logger.info("No new videos to upload. All are already processed. Exiting.")
        return
        
    # Sort by creation time to upload the oldest video first
    new_videos.sort(key=lambda x: x.get('createdTime', ''))
    
    video_to_upload = new_videos[0]
    video_id = video_to_upload['id']
    video_name = video_to_upload['name']
    
    logger.info(f"Selected oldest new video to upload: {video_name}")

    video_data = download_video_from_drive(drive_service, video_id, video_name)
    
    if video_data:
        success = upload_video_to_facebook(video_data, video_name, FACEBOOK_PAGE_TOKEN, FACEBOOK_PAGE_ID, HASHTAGS)
        if success:
            save_uploaded_video(video_id, video_name)
            logger.info("✅ Process completed successfully!")
        else:
            logger.error("❌ Process failed during Facebook upload.")
    else:
        logger.error("❌ Process failed during video download.")
    logger.info("--- Video upload process finished ---")

if __name__ == "__main__":
    main()
