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
    Eres un escritor profesional y un experto en creación de contenido para sitios web.
    Has visto el siguiente video de YouTube y toda la información disponible (título, descripción, transcripción y comentarios).
    Tu tarea es escribir una descripción larga, creativa y detallada sobre el video,
    que refleje su esencia y contenido de forma atractiva, para que los visitantes del
    sitio se interesen y comprendan claramente de qué trata.
    Eres un escritor profesional especializado en contenido SEO para sitios web.
    No copies literalmente la descripción, letras o enlaces del video. En lugar de eso, escribe un resumen original, creativo y descriptivo del video.

    Información del video:
    Título: {video_info['title']}
    Descripción: {video_info['description']}
    Transcripción: {video_info.get('transcript', 'No disponible')}
    Primeros comentarios:
    {json.dumps(video_info.get('comments', [])[:20], ensure_ascii=False)}
    """

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