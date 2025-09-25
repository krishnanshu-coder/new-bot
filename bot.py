# upload_video.py
import os
import json
import requests
import pickle
from datetime import datetime
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
import io
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Scopes for Google Drive API
SCOPES = ['https://www.googleapis.com/auth/drive.readonly']

class FacebookVideoUploader:
    def __init__(self):
        self.facebook_token = os.getenv('FACEBOOK_ACCESS_TOKEN')
        self.page_id = os.getenv('FACEBOOK_PAGE_ID')
        self.drive_folder_id = os.getenv('GOOGLE_DRIVE_FOLDER_ID')
        self.uploaded_videos_file = 'uploaded_videos.json'
        
        # Load previously uploaded videos
        self.uploaded_videos = self.load_uploaded_videos()
        
    def authenticate_google_drive(self):
        """Authenticate with Google Drive API"""
        creds = None
        
        # Check if token.pickle exists
        if os.path.exists('token.pickle'):
            with open('token.pickle', 'rb') as token:
                creds = pickle.load(token)
                
        # If there are no valid credentials, get them
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(
                    'credentials.json', SCOPES)
                creds = flow.run_local_server(port=0)
                
            # Save credentials for next run
            with open('token.pickle', 'wb') as token:
                pickle.dump(creds, token)
                
        return build('drive', 'v3', credentials=creds)
    
    def load_uploaded_videos(self):
        """Load the list of previously uploaded videos"""
        try:
            with open(self.uploaded_videos_file, 'r') as f:
                return json.load(f)
        except FileNotFoundError:
            return []
    
    def save_uploaded_videos(self):
        """Save the list of uploaded videos"""
        with open(self.uploaded_videos_file, 'w') as f:
            json.dump(self.uploaded_videos, f)
    
    def get_videos_from_drive(self, service):
        """Get video files from Google Drive folder"""
        try:
            # Query for video files in the specified folder
            query = f"'{self.drive_folder_id}' in parents and (mimeType contains 'video/')"
            results = service.files().list(
                q=query,
                fields="nextPageToken, files(id, name, mimeType, createdTime)"
            ).execute()
            
            videos = results.get('files', [])
            
            # Filter out already uploaded videos
            new_videos = [v for v in videos if v['id'] not in self.uploaded_videos]
            
            # Sort by creation time (oldest first)
            new_videos.sort(key=lambda x: x['createdTime'])
            
            return new_videos
            
        except Exception as e:
            logger.error(f"Error getting videos from Drive: {e}")
            return []
    
    def download_video(self, service, file_id, filename):
        """Download video from Google Drive"""
        try:
            request = service.files().get_media(fileId=file_id)
            file_path = f"temp_{filename}"
            
            with open(file_path, 'wb') as f:
                downloader = MediaIoBaseDownload(f, request)
                done = False
                while done is False:
                    status, done = downloader.next_chunk()
                    
            return file_path
            
        except Exception as e:
            logger.error(f"Error downloading video {filename}: {e}")
            return None
    
    def upload_to_facebook(self, video_path, title):
        """Upload video to Facebook page"""
        try:
            # Step 1: Initialize upload
            init_url = f"https://graph.facebook.com/v18.0/{self.page_id}/videos"
            init_params = {
                'access_token': self.facebook_token,
                'upload_phase': 'start',
                'file_size': os.path.getsize(video_path)
            }
            
            init_response = requests.post(init_url, params=init_params)
            init_data = init_response.json()
            
            if 'video_id' not in init_data:
                logger.error(f"Failed to initialize upload: {init_data}")
                return False
            
            video_id = init_data['video_id']
            upload_session_id = init_data['upload_session_id']
            
            # Step 2: Upload video file
            upload_url = f"https://graph.facebook.com/v18.0/{self.page_id}/videos"
            
            with open(video_path, 'rb') as video_file:
                upload_params = {
                    'access_token': self.facebook_token,
                    'upload_phase': 'transfer',
                    'upload_session_id': upload_session_id,
                    'start_offset': 0
                }
                
                files = {'video_file_chunk': video_file}
                upload_response = requests.post(upload_url, params=upload_params, files=files)
                upload_data = upload_response.json()
                
                if not upload_data.get('success'):
                    logger.error(f"Failed to upload video chunk: {upload_data}")
                    return False
            
            # Step 3: Finish upload and publish
            finish_url = f"https://graph.facebook.com/v18.0/{self.page_id}/videos"
            finish_params = {
                'access_token': self.facebook_token,
                'upload_phase': 'finish',
                'upload_session_id': upload_session_id,
                'title': title,
                'description': f'Auto-uploaded video: {title}',
                'published': True
            }
            
            finish_response = requests.post(finish_url, params=finish_params)
            finish_data = finish_response.json()
            
            if 'success' in finish_data and finish_data['success']:
                logger.info(f"Successfully uploaded video: {title}")
                return True
            else:
                logger.error(f"Failed to finish upload: {finish_data}")
                return False
                
        except Exception as e:
            logger.error(f"Error uploading to Facebook: {e}")
            return False
    
    def run(self):
        """Main execution function"""
        try:
            # Authenticate with Google Drive
            service = self.authenticate_google_drive()
            
            # Get available videos
            videos = self.get_videos_from_drive(service)
            
            if not videos:
                logger.info("No new videos found to upload")
                return
            
            # Upload one video (oldest first)
            video = videos[0]
            logger.info(f"Processing video: {video['name']}")
            
            # Download video
            video_path = self.download_video(service, video['id'], video['name'])
            
            if not video_path:
                logger.error("Failed to download video")
                return
            
            # Upload to Facebook
            success = self.upload_to_facebook(video_path, video['name'])
            
            if success:
                # Mark as uploaded
                self.uploaded_videos.append(video['id'])
                self.save_uploaded_videos()
                logger.info(f"Successfully processed video: {video['name']}")
            
            # Clean up temporary file
            if os.path.exists(video_path):
                os.remove(video_path)
                
        except Exception as e:
            logger.error(f"Error in main execution: {e}")

if __name__ == "__main__":
    uploader = FacebookVideoUploader()
    uploader.run()
