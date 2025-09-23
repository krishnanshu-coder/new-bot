import os
import subprocess
import requests
import json
import random
from datetime import datetime, timezone
import time
import logging
import tempfile
import shutil

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

class AutomatedVideoShortsBot:
    def __init__(self):
        # Load configuration from environment variables
        self.page_access_token = os.getenv('FACEBOOK_PAGE_TOKEN')
        self.page_id = os.getenv('FACEBOOK_PAGE_ID')
        self.video_urls = self.load_video_urls()
        self.facebook_api_base = "https://graph.facebook.com/v18.0"
        self.temp_dir = tempfile.mkdtemp()
        
        # Validate configuration
        if not self.page_access_token or not self.page_id:
            raise ValueError("Missing Facebook credentials in environment variables")
        
        logging.info("Bot initialized successfully")
    
    def load_video_urls(self):
        # First try environment variable
        urls_env = os.getenv('VIDEO_URLS')
        if urls_env:
            urls = [url.strip() for url in urls_env.split(',') if url.strip()]
           logging.info(f"Loaded {len(urls)} video URLs from env")
           return urls
        
        # Otherwise load from video_list.txt
        elif os.path.exists("video_list.txt"):
            with open("video_list.txt", "r") as f:
                urls = [line.strip() for line in f if line.strip()]
                logging.info(f"Loaded {len(urls)} video URLs from video_list.txt")
                return urls

        else:
            logging.error("No VIDEO_URLS env or video_list.txt found")
            return []
    
    def download_video(self, video_url):
        """Download video from URL to temporary directory"""
        try:
            logging.info(f"Downloading video from: {video_url}")
            
            # Create temporary file
            temp_file = os.path.join(self.temp_dir, f"input_{int(time.time())}.mp4")
            
            # Handle Google Drive links
            if "drive.google.com" in video_url and "export=download" in video_url:
                # For Google Drive direct download links
                response = requests.get(video_url, stream=True, timeout=600, allow_redirects=True)
            else:
                response = requests.get(video_url, stream=True, timeout=600)
            
            response.raise_for_status()
            
            with open(temp_file, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:  # Filter out keep-alive chunks
                        f.write(chunk)
            
            # Check if file was downloaded properly
            if os.path.getsize(temp_file) < 1000:  # Less than 1KB might be an error page
                logging.error("Downloaded file seems too small, might be an error")
                return None
            
            logging.info(f"Video downloaded successfully: {temp_file} ({os.path.getsize(temp_file)} bytes)")
            return temp_file
        except Exception as e:
            logging.error(f"Error downloading video: {e}")
            return None
    
    def get_video_duration(self, video_path):
        """Get video duration using ffprobe"""
        try:
            cmd = [
                'ffprobe', '-v', 'quiet', '-print_format', 'json',
                '-show_format', '-show_streams', video_path
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if result.returncode != 0:
                logging.error(f"ffprobe failed: {result.stderr}")
                return None
            
            data = json.loads(result.stdout)
            duration = float(data['format']['duration'])
            logging.info(f"Video duration: {duration} seconds")
            return duration
        except Exception as e:
            logging.error(f"Error getting video duration: {e}")
            return None
    
    def create_vertical_short(self, input_video, start_time, duration=60):
        """Create a vertical short from landscape video"""
        timestamp = int(time.time())
        output_file = os.path.join(self.temp_dir, f"short_{timestamp}.mp4")
        
        try:
            # Fixed FFmpeg command - split the input properly
            cmd = [
                'ffmpeg', '-i', input_video,
                '-ss', str(start_time),
                '-t', str(duration),
                '-filter_complex', (
                    # Split input into two streams
                    '[0:v]split=2[main][bg];'
                    # Create blurred background
                    '[bg]scale=1080:1920:force_original_aspect_ratio=increase,'
                    'crop=1080:1920,boxblur=20[blurred];'
                    # Scale main video to fit
                    '[main]scale=1080:1920:force_original_aspect_ratio=decrease[scaled];'
                    # Overlay scaled video on blurred background
                    '[blurred][scaled]overlay=(W-w)/2:(H-h)/2[out]'
                ),
                '-map', '[out]',
                '-map', '0:a?',  # Include audio if present
                '-c:a', 'aac', '-b:a', '128k',
                '-c:v', 'libx264', '-preset', 'fast', '-crf', '28',
                '-r', '30', '-movflags', '+faststart',
                '-y', output_file
            ]
            
            logging.info(f"Creating vertical short: {output_file}")
            logging.info("Processing video... This may take a few minutes.")
            
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
            
            if result.returncode == 0:
                logging.info(f"Short created successfully: {output_file}")
                return output_file
            else:
                logging.error(f"Error creating short: {result.stderr}")
                return None
                
        except Exception as e:
            logging.error(f"Error in create_vertical_short: {e}")
            return None
    
    def generate_hashtags(self, post_time):
        """Generate engaging hashtags for the post"""
        base_hashtags = ["#viral", "#shorts", "#trending"]
        
        time_based = {
            "morning": ["#GoodMorning", "#MorningVibes", "#StartYourDay", "#MotivationMonday"],
            "evening": ["#EveningVibes", "#Unwind", "#AfterWork", "#ChillTime"],
            "default": ["#Daily", "#Content", "#Entertainment", "#Fun"]
        }
        
        growth_hashtags = [
            "#Explore", "#ForYou", "#Viral", "#Share", "#Like", "#Follow",
            "#Entertainment", "#Fun", "#Amazing", "#MustWatch", "#DontMiss",
            "#Awesome", "#Epic", "#Cool", "#Incredible", "#Wow"
        ]
        
        # Select hashtags
        selected = base_hashtags.copy()
        selected.extend(random.sample(time_based.get(post_time, time_based["default"]), 2))
        selected.extend(random.sample(growth_hashtags, 4))
        
        return " ".join(selected)
    
    def upload_to_facebook(self, video_path, description=""):
        """Upload video to Facebook page with retry logic"""
        max_retries = 3
        
        for attempt in range(max_retries):
            try:
                logging.info(f"Uploading {video_path} to Facebook (attempt {attempt + 1})")
                
                url = f"{self.facebook_api_base}/{self.page_id}/videos"
                
                with open(video_path, 'rb') as video_file:
                    files = {'source': video_file}
                    data = {
                        'access_token': self.page_access_token,
                        'description': description,
                        'published': True
                    }
                    
                    response = requests.post(url, files=files, data=data, timeout=900)
                    response.raise_for_status()
                    
                    result = response.json()
                    video_id = result.get('id')
                    
                    if video_id:
                        logging.info(f"✅ Video uploaded successfully! Video ID: {video_id}")
                        return video_id
                    else:
                        logging.error(f"Upload failed: {result}")
                        
            except Exception as e:
                logging.error(f"Error uploading to Facebook (attempt {attempt + 1}): {e}")
                if attempt < max_retries - 1:
                    time.sleep(10)  # Wait before retry
        
        return None
    
    def create_and_upload_short(self, video_url, post_time="scheduled"):
        """Create and upload a single short"""
        try:
            logging.info(f"🚀 Starting {post_time} upload process...")
            
            # Download video
            input_video = self.download_video(video_url)
            if not input_video:
                logging.error("❌ Failed to download video")
                return False
            
            # Get video duration
            total_duration = self.get_video_duration(input_video)
            if not total_duration or total_duration < 60:
                logging.error(f"❌ Video too short or invalid duration: {total_duration}")
                self.cleanup_file(input_video)
                return False
            
            # Calculate random start time
            max_start_time = total_duration - 60
            start_time = random.uniform(0, max_start_time)
            
            logging.info(f"📹 Creating {post_time} short from {start_time:.2f}s")
            
            # Create vertical short
            short_file = self.create_vertical_short(input_video, start_time, 60)
            if not short_file:
                logging.error("❌ Failed to create short")
                self.cleanup_file(input_video)
                return False
            
            # Generate description with hashtags
            current_time = datetime.now().strftime('%Y-%m-%d %H:%M')
            hashtags = self.generate_hashtags(post_time)
            
            description = f"""🔥 Daily Short #{post_time.title()} - {current_time}

{hashtags}

🎬 Like & Follow for more amazing content!
📱 Turn on notifications to never miss our shorts!"""
            
            # Upload to Facebook
            video_id = self.upload_to_facebook(short_file, description)
            
            # Cleanup files
            self.cleanup_file(input_video)
            self.cleanup_file(short_file)
            
            return video_id is not None
            
        except Exception as e:
            logging.error(f"❌ Error in create_and_upload_short: {e}")
            return False
    
    def cleanup_file(self, file_path):
        """Safely remove a file"""
        try:
            if os.path.exists(file_path):
                os.remove(file_path)
                logging.info(f"🧹 Cleaned up: {file_path}")
        except Exception as e:
            logging.error(f"Error cleaning up {file_path}: {e}")
    
    def run_scheduled_upload(self):
        """Run the scheduled upload process"""
        try:
            current_hour = datetime.now().hour
            current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            
            logging.info(f"🕐 Current time: {current_time} (Hour: {current_hour})")
            
            # Determine if it's morning (5 AM) or evening (5 PM) post
            if current_hour == 5 or current_hour == 23:  # 5 AM IST or 11 PM UTC (5 AM IST next day)
                post_time = "morning"
            elif current_hour == 17 or current_hour == 11:  # 5 PM IST or 11 AM UTC
                post_time = "evening"
            else:
                # For manual testing, always run
                post_time = "manual"
                logging.info(f"🧪 Running manual test at hour {current_hour}")
            
            logging.info(f"🎯 Starting {post_time} upload process")
            
            if not self.video_urls:
                logging.error("❌ No video URLs available")
                return
            
            # Select a random video URL (or use the single one provided)
            selected_url = random.choice(self.video_urls)
            logging.info(f"🎬 Selected video: {selected_url}")
            
            # Create and upload short
            success = self.create_and_upload_short(selected_url, post_time)
            
            if success:
                logging.info(f"✅ {post_time.title()} upload completed successfully! 🎉")
            else:
                logging.error(f"❌ {post_time.title()} upload failed!")
            
        except Exception as e:
            logging.error(f"💥 Error in run_scheduled_upload: {e}")
        finally:
            # Clean up temp directory
            self.cleanup_temp_dir()
    
    def cleanup_temp_dir(self):
        """Clean up temporary directory"""
        try:
            if os.path.exists(self.temp_dir):
                shutil.rmtree(self.temp_dir)
                self.temp_dir = tempfile.mkdtemp()
                logging.info("🧹 Temporary directory cleaned up")
        except Exception as e:
            logging.error(f"Error cleaning temp directory: {e}")

def main():
    """Main function to run the automated bot"""
    try:
        logging.info("🤖 Starting Automated Video Shorts Bot...")
        bot = AutomatedVideoShortsBot()
        bot.run_scheduled_upload()
    except Exception as e:
        logging.error(f"💥 Fatal error: {e}")

if __name__ == "__main__":
    main()


