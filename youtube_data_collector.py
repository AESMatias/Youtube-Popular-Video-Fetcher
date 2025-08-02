import os
import json
import requests
import time
from googleapiclient.discovery import build
from youtube_transcript_api import YouTubeTranscriptApi
from tqdm import tqdm
from dotenv import load_dotenv
from PIL import Image
from io import BytesIO

load_dotenv()

API_KEY = os.getenv('YOUTUBE_API_KEY')

if not API_KEY:
    raise ValueError("YOUTUBE_API_KEY not found. Make sure it is present in your .env file")

youtube = build('youtube', 'v3', developerKey=API_KEY)

COUNTRY_CODES = ['AR', 'BO', 'CL', 'CO', 'CR', 'DO', 'EC', 'GT', 'HN', 'MX', 'NI', 'PA', 'PE', 'PY', 'SV', 'UY', 'VE', 'US']
MAX_RESULTS_PER_COUNTRY = 50
MAX_COMMENTS = 200

OUTPUT_THUMBNAILS_DIR = 'public/thumbnails'
OUTPUT_METADATA_PATH = 'src/data/videos_metadata.json'

# Create directories if they do not exist
os.makedirs(OUTPUT_THUMBNAILS_DIR, exist_ok=True)
os.makedirs(os.path.dirname(OUTPUT_METADATA_PATH), exist_ok=True)

def get_popular_videos(region_code, max_results=50):
    videos = []
    next_page_token = None

    while len(videos) < max_results:
        response = youtube.videos().list(
            part='snippet,statistics,contentDetails',
            chart='mostPopular',
            regionCode=region_code,
            maxResults=min(50, max_results - len(videos)),
            pageToken=next_page_token
        ).execute()

        items = response.get('items', [])
        videos.extend(items)

        next_page_token = response.get('nextPageToken')
        if not next_page_token:
            break

    return videos[:max_results]

def get_transcript(video_id):
    try:
        transcript = YouTubeTranscriptApi.get_transcript(video_id, languages=['es', 'en'])
        return ' '.join([seg['text'] for seg in transcript])
    except Exception:
        return None

def get_comments(video_id, max_comments=200):
    comments = []
    next_page_token = None

    while len(comments) < max_comments:
        response = youtube.commentThreads().list(
            part='snippet',
            videoId=video_id,
            maxResults=100,
            textFormat='plainText',
            pageToken=next_page_token
        ).execute()

        for item in response.get('items', []):
            comment = item['snippet']['topLevelComment']['snippet']['textDisplay']
            comments.append(comment)

        next_page_token = response.get('nextPageToken')
        if not next_page_token:
            break

    return comments[:max_comments]

def download_thumbnail(video_id, thumbnails_dict):
    # We prioritize the medium quality thumbnail
    best_quality = thumbnails_dict.get('medium') or thumbnails_dict.get('default')

    if best_quality and 'url' in best_quality:
        url = best_quality['url']
        path = os.path.join(OUTPUT_THUMBNAILS_DIR, f'{video_id}.jpg')
        try:
            r = requests.get(url, timeout=10)
            if r.status_code == 200:
                # Use Pillow to resize and compress the image
                image_data = BytesIO(r.content)
                with Image.open(image_data) as img:
                    resized_img = img.resize((640, 360), Image.Resampling.LANCZOS)
                    resized_img.save(path, 'JPEG', quality=85)
                return f'/thumbnails/{video_id}.jpg'
        except Exception as e:
            print(f'❌ Error downloading and processing thumbnail {url}: {e}')
    return None

def extract_video_info(video, region_code):
    video_id = video['id']
    snippet = video['snippet']
    statistics = video.get('statistics', {})
    content = video.get('contentDetails', {})

    # Download thumbnail
    thumbnails_dict = snippet.get('thumbnails', {})
    thumbnail_path = download_thumbnail(video_id, thumbnails_dict)

    data = {
        'video_id': video_id,
        'title': snippet.get('title'),
        'description': snippet.get('description'),
        'channel_title': snippet.get('channelTitle'),
        'channel_id': snippet.get('channelId'),
        'published_at': snippet.get('publishedAt'),
        'tags': snippet.get('tags', []),
        'view_count': statistics.get('viewCount'),
        'like_count': statistics.get('likeCount'),
        'comment_count': statistics.get('commentCount'),
        'duration': content.get('duration'),
        'youtube_url': f'https://www.youtube.com/watch?v={video_id}',
        'region_code': region_code,
        'thumbnails': thumbnails_dict,
        'thumbnail_file': thumbnail_path,
        'transcript': get_transcript(video_id),
        'comments': get_comments(video_id, MAX_COMMENTS)
    }

    return data

def main_collector():
    all_data = []

    if os.path.exists(OUTPUT_METADATA_PATH):
        user_choice = input(f"'{OUTPUT_METADATA_PATH}' already exists. Do you want to (o)verwrite, (a)ppend to existing, or (s)kip this step? (o/a/s): ").lower()
        if user_choice == 'a':
            with open(OUTPUT_METADATA_PATH, 'r', encoding='utf-8') as f:
                all_data = json.load(f)
            print(f"Appending to the existing {len(all_data)} videos.")
        elif user_choice == 's':
            print("Skipping YouTube data collection phase.")
            return
        elif user_choice == 'o':
            print("Option: Overwriting existing data.")
        else:
            print("Invalid option. Defaulting to overwrite.")

    try:
        for country in tqdm(COUNTRY_CODES, desc='Countries'):
            videos = get_popular_videos(country, MAX_RESULTS_PER_COUNTRY)
            for video in tqdm(videos, desc=f'📼 {country}', leave=False):
                video_id = video['id']
                
                # Avoid duplicates
                if any(d.get('video_id') == video_id for d in all_data):
                    continue
                
                try:
                    info = extract_video_info(video, country)
                    all_data.append(info)
                except Exception as e:
                    print(f'⚠️ Error processing video {video_id}: {e}')
            time.sleep(1)  # Pause to avoid API rate BAN!

        # we save the final JSON
        with open(OUTPUT_METADATA_PATH, 'w', encoding='utf-8') as f:
            json.dump(all_data, f, ensure_ascii=False, indent=2)
        print(f"\nData collection complete. Saved to '{OUTPUT_METADATA_PATH}' and thumbnails to '{OUTPUT_THUMBNAILS_DIR}/'")

    except KeyboardInterrupt:
        print("\nData collection process interrupted by user.")
        with open(OUTPUT_METADATA_PATH, 'w', encoding='utf-8') as f:
            json.dump(all_data, f, ensure_ascii=False, indent=2)
        print(f"Progress saved to '{OUTPUT_METADATA_PATH}'.")
    except Exception as e:
        print(f"\n ERROR: An unexpected error occurred during data collection: {e}")

if __name__ == "__main__":
    main_collector()
