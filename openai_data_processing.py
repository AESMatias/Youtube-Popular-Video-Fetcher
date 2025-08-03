import os
import json
from tqdm import tqdm
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')

if not OPENAI_API_KEY:
    raise ValueError("OPENAI_API_KEY not found. Please ensure it is set in your .env file.")

client = OpenAI(api_key=OPENAI_API_KEY)

INPUT_METADATA_PATH = 'src/data/videos_metadata.json'
OUTPUT_SEO_DIR = 'src/data/sumarios_seo'

os.makedirs(OUTPUT_SEO_DIR, exist_ok=True) # If the output directory does not exist, create it

def generate_seo_summary(video_info, openai_client):
    prompt = f"""
        You are a professional writer and an expert in creating content for websites.
        You have watched the following YouTube video and reviewed all available information (title, description, transcript, and comments).
        Your task is to write a long, creative, and detailed description of the video,
        which reflects its essence and content in an engaging way, so that site visitors
        become interested and clearly understand what it is about.
        You are a professional writer specialized in SEO content for websites.
        Do not copy the description, lyrics, or links from the video literally. Instead, write an original, creative, and descriptive summary of the video.
        The text will be in English and you will not include an introduction such as "Here is the description:" but write the content directly.
        Do not mention, but the response should be formatted with line breaks for better readability (/n is inter).
        The complete response should be in english, not any other language.

        Video information:
        Title: {video_info['title']}
        Description: {video_info['description']}
        Transcript: {video_info.get('transcript', 'Not available')}
        Top comments:
        {json.dumps(video_info.get('comments', [])[:20], ensure_ascii=False)}"""

    try:
        response = openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
            max_tokens=1500
        )
        content = response.choices[0].message.content.strip()
        seo_data = {
            "seo_title": video_info.get("title", ""),
            "seo_description": content
        }
        return seo_data
    except Exception as e:
        print(f"Error generated for video with ID: {video_info.get('video_id')}: {e}")
        return {
            "seo_title": video_info.get('title', 'Video Title Not Available'),
            "seo_description": video_info.get('description', '')[:500]
        }

def main_openai_data_processing():
    if not os.path.exists(INPUT_METADATA_PATH):
        print(f"Error: There is no metadata file at '{INPUT_METADATA_PATH}'.")
        print("Please run the YouTube data collector script first to generate this file.")
        return

    with open(INPUT_METADATA_PATH, 'r', encoding='utf-8') as f:
        all_videos = json.load(f)

    print(f"\n✨ Starting the SEO summary generation for {len(all_videos)} videos.")

    try:
        for video in tqdm(all_videos, desc="✨ Generating SEO summaries", unit="video"):
            video_id = video['video_id']
            output_path = os.path.join(OUTPUT_SEO_DIR, f"{video_id}.json")

            if os.path.exists(output_path):
                continue # Then skip if the file already exists

            seo_summary = generate_seo_summary(video, client)

            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(seo_summary, f, ensure_ascii=False, indent=2)

    except KeyboardInterrupt:
        print("\nProcess interrupted by user.")
    except Exception as e:
        print(f"\n🚫 An unexpected error occurred during SEO summary generation: {e}")

    print(f"\n✅ SEO summary generation completed. The files are in '{OUTPUT_SEO_DIR}/'")

if __name__ == "__main__":
    main_openai_data_processing()