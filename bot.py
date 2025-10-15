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
FACEBOOK_PAGE_TOKEN = os.getenv('FACEBOOK_PAGE_TOKEN')
FACEBOOK_PAGE_ID = os.getenv('FACEBOOK_PAGE_ID')
GDRIVE_FOLDER_ID = os.getenv('GDRIVE_FOLDER_ID')
HASHTAGS = os.getenv('HASHTAGS', '#SouthIndianCinema #SouthMovies #IndianCinema #MovieClips #Cinema #WhatToWatch #FacebookVideo #FacebookReels #Tollywood #TeluguCinema #Telugu #TeluguMovie #Kollywood #TamilCinema #Tamil #TamilMovie #Mollywood #MalayalamCinema #Malayalam #MalayalamMovie #Sandalwood #KannadaCinema #Kannada #KannadaMovie #Prabhas #AlluArjun #Yash #RamCharan #JrNTR #ThalapathyVijay #AjithKumar #Rajinikanth #KamalHaasan #Suriya #MaheshBabu #DulquerSalmaan #FahadhFaasil #AlluArjunFans #VijayFans #PrabhasFC #KGF #Pushpa #Salaar #Leo #Vikram #Action #ActionMovies #FightScene #MassScene #Goosebumps #BGM #MassBGM #BackgroundMusic #MovieSongs #Anirudh #Comedy #ComedyClips #EmotionalScene #Love #Romantic #LoveSongs #Dialogue #MassDialogue #MovieQuotes #Viral #Trending #ViralVideo #Explore #ExplorePage #MustWatch #Reels')
GDRIVE_TOKEN_BASE64 = os.getenv('GDRIVE_TOKEN_BASE64')

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

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            logger.info("Refreshing expired credentials.")
            creds.refresh(Request())
        else:
            logger.info("No valid credentials found. Starting local authentication flow.")
            if not os.path.exists(CREDENTIALS_FILE):
                logger.error(f"{CREDENTIALS_FILE} not found for initial authentication.")
                return None
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
            creds = flow.run_local_server(port=0)
        
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
        query = f"'{folder_id}' in parents and mimeType contains 'video/'"
        results = service.files().list(
            q=query,
            pageSize=100,
            fields="files(id, name, createdTime)"
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
        url = f"https://graph-video.facebook.com/v19.0/{page_id}/videos"
        post_data = {
            'access_token': page_token,
            'title': os.path.splitext(video_name)[0],
            'description': hashtags,
        }
        files = {'source': (video_name, video_data, 'video/mp4/mkv')}
        response = requests.post(url, data=post_data, files=files, timeout=900)
        
        response_json = response.json()

        if response.status_code == 200:
            logger.info(f"✅ Successfully uploaded {video_name}! Video ID: {response_json.get('id', 'N/A')}")
            return True
        else:
            logger.error(f"❌ Failed to upload {video_name}. Response: {response_json}")
            return False
            
    except Exception as e:
        logger.error(f"An error occurred while uploading to Facebook: {e}")
        return False

def main():
    """Main function to process and upload one new video."""
    if not all([GDRIVE_FOLDER_ID, FACEBOOK_PAGE_TOKEN, FACEBOOK_PAGE_ID]):
        logger.critical("FATAL: Missing required environment variables.")
        return

    drive_service = authenticate_google_drive()
    if not drive_service:
        logger.critical("FATAL: Could not authenticate with Google Drive.")
        return

    all_videos = get_videos_from_drive(drive_service, GDRIVE_FOLDER_ID)
    if not all_videos:
        logger.info("No videos found in Drive folder.")
        return

    uploaded_video_ids = {v['id'] for v in get_uploaded_videos()}
    new_videos = [v for v in all_videos if v['id'] not in uploaded_video_ids]
    
    if not new_videos:
        logger.info("No new videos to upload.")
        return
        
    # --- THIS IS THE ORIGINAL SORTING LOGIC ---
    # Sort videos by creation time in ascending order (oldest first)
    new_videos.sort(key=lambda x: x.get('createdTime', ''))
    
    video_to_upload = new_videos[0]
    
    logger.info(f"Selected oldest video to upload: {video_to_upload['name']}")

    video_data = download_video_from_drive(drive_service, video_to_upload['id'], video_to_upload['name'])
    
    if video_data:
        success = upload_video_to_facebook(video_data, video_to_upload['name'], FACEBOOK_PAGE_TOKEN, FACEBOOK_PAGE_ID, HASHTAGS)
        if success:
            save_uploaded_video(video_to_upload['id'], video_to_upload['name'])
            logger.info("✅ Process completed successfully!")

if __name__ == "__main__":
    main()





