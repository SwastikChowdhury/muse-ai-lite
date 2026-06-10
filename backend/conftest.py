import os
import sys

os.environ.setdefault("GEMINI_API_KEY", "test")
os.environ.setdefault("GROQ_API_KEY", "test")
os.environ.setdefault("MONGODB_URI", "mongodb://localhost:27017")

sys.path.insert(0, os.path.dirname(__file__))