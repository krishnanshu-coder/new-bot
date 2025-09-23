from googleapiclient.discovery import build
from google.oauth2 import service_account
import os

def main():
    folder_id = os.getenv("GDRIVE_FOLDER_ID")
    if not folder_id:
        raise ValueError("GDRIVE_FOLDER_ID is missing")

    # Authenticate with credentials.json (created from GitHub secret)
    creds = service_account.Credentials.from_service_account_file(
        "credentials.json",
        scopes=["https://www.googleapis.com/auth/drive.readonly"]
    )
    service = build("drive", "v3", credentials=creds)

    # Fetch all video files in the folder
    results = service.files().list(
        q=f"'{folder_id}' in parents and mimeType contains 'video/'",
        fields="files(id, name)"
    ).execute()
    files = results.get("files", [])

    if not files:
        print("No videos found in folder.")
        return

    # Write video URLs to video_list.txt
    with open("video_list.txt", "w") as f:
        for file in files:
            f.write(f"https://drive.google.com/uc?export=download&id={file['id']}\n")

    print(f"✅ video_list.txt created with {len(files)} videos.")

if __name__ == "__main__":
    main()
