
import os
from google import genai
from dotenv import load_dotenv

load_dotenv()

def list_models():
    api_key = os.environ.get("GOOGLE_API_KEY", "").strip()
    if api_key:
        client = genai.Client(api_key=api_key)
    else:
        client = genai.Client()

    try:
        # The SDK might have a different way to list models, but let's try the standard way if possible
        # or just try to generate content with a few known models to see which one doesn't 404.
        # The google-genai SDK is new, let's check if it has models.list
        
        # Based on common patterns in this SDK:
        print("Attempting to list models...")
        # Note: The new SDK might not have a direct list_models on the client root or models namespace in the same way.
        # But let's try to iterate if it supports it.
        
        # If we can't list, we will probe.
        models_to_probe = [
            "gemini-2.0-flash-lite",
            "gemini-2.0-flash-exp",
            "gemini-1.5-flash",
            "gemini-1.5-flash-001",
            "gemini-1.5-flash-002",
            "gemini-1.5-pro",
            "gemini-1.5-pro-001",
            "gemini-1.5-pro-002",
            "gemini-1.0-pro",
            "gemini-pro"
        ]
        
        for m in models_to_probe:
            print(f"Probing {m}...", end=" ")
            try:
                client.models.generate_content(
                    model=m,
                    contents="Hello",
                )
                print("OK")
            except Exception as e:
                print(f"FAILED: {e}")

    except Exception as e:
        print(f"Error initializing or listing: {e}")

if __name__ == "__main__":
    list_models()
