#!/usr/bin/env python3
import os, subprocess, requests, sys, json
from pathlib import Path

FB_TOKEN = os.getenv("EAAJq1ClJ4EIBPZAseW52XzY1OAXUDqTZAdJvdoMd9tkK5t3xPMxLJxAyh0Sr7homIZAmRNfoMsv2xOIYXlZA39g2sTNMOjh0MX9USfFrEOyGBMRbZBD7AbDvwa7PtFPq6ZB3yXiqDABzh2PLGkIRGzEr7PjcP8QEiIBG5FyIufFLcu91nJKhAStB4TjywY")
FB_PAGE_ID = os.getenv("602232142981417")
VIDEO_URL = os.getenv("https://drive.google.com/uc?export=download&id=1xbS3izoiBAln57ePZxGoTOBT94rStaX_")
HASHTAGS = os.getenv("HASHTAGS", "#viral #shorts #trending")
STATE_FILE = "state.json"
VIDEO_FILE = "input.mp4"

def download_video(url, dest):
    if os.path.exists(dest):
        print("Input video already present.")
        return
    print("Downloading video from:", url)
    r = requests.get(url, stream=True, timeout=120)
    r.raise_for_status()
    with open(dest, "wb") as f:
        for chunk in r.iter_content(1024*1024):
            if chunk:
                f.write(chunk)
    print("Download finished.")

def split_video(input_file):
    # remove any existing clips in workspace
    for p in Path('.').glob('clip_*.mp4'):
        p.unlink()
    print("Splitting into 1-minute clips (9:16)...")
    cmd = [
        "ffmpeg", "-y", "-i", input_file,
        "-vf", "scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2:black",
        "-c:a", "aac", "-ar", "44100", "-ac", "2",
        "-f", "segment", "-segment_time", "60", "-reset_timestamps", "1",
        "clip_%03d.mp4"
    ]
    subprocess.run(cmd, check=True)
    clips = sorted([str(p) for p in Path('.').glob('clip_*.mp4')])
    print(f"Created {len(clips)} clips.")
    return clips

def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            return json.load(f)
    else:
        return {"next_index": 0}

def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f)

def upload_clip(clip_path, caption):
    url = f"https://graph-video.facebook.com/v17.0/{FB_PAGE_ID}/videos"
    print(f"Uploading {clip_path} to Facebook...")
    with open(clip_path, "rb") as f:
        files = {"source": f}
        data = {"access_token": FB_TOKEN, "description": caption}
        r = requests.post(url, files=files, data=data, timeout=300)
    print("FB response:", r.status_code, r.text)
    r.raise_for_status()
    return r.json()

def git_commit_state(next_index):
    try:
        subprocess.run(["git", "config", "user.name", "github-actions"], check=True)
        subprocess.run(["git", "config", "user.email", "actions@github.com"], check=True)
        subprocess.run(["git", "add", STATE_FILE], check=True)
        subprocess.run(["git", "commit", "-m", f"Update state: next_index={next_index}"], check=False)
        subprocess.run(["git", "push"], check=False)
        print("Committed new state back to repo.")
    except Exception as e:
        print("Warning: failed to commit state:", e)

def main():
    if not FB_TOKEN or not FB_PAGE_ID or not VIDEO_URL:
        print("Missing env vars. Please set FB_PAGE_TOKEN, FB_PAGE_ID and VIDEO_URL in repository Secrets.")
        sys.exit(1)

    download_video(VIDEO_URL, VIDEO_FILE)
    clips = split_video(VIDEO_FILE)
    if not clips:
        print("No clips found, exiting.")
        sys.exit(1)

    state = load_state()
    idx = int(state.get("next_index", 0))
    if idx >= len(clips):
        idx = 0
    clip_to_upload = clips[idx]
    caption = f"{HASHTAGS}"

    result = upload_clip(clip_to_upload, caption)
    print("Upload result:", result)

    state["next_index"] = (idx + 1) % len(clips)
    save_state(state)
    git_commit_state(state["next_index"])

if __name__ == "__main__":
    main()
