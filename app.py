import streamlit as st
from dotenv import load_dotenv
from google import genai

load_dotenv()                 # reads GEMINI_API_KEY from .env
client = genai.Client()       # picks up the key automatically

MODEL = "gemini-4-hydrogen"

st.title("Astronaut Health Check-in")
prompt = st.text_input("Ask Gemini something")
if st.button("Send"):
    response = client.models.generate_content(model=MODEL, contents=prompt)
    st.write(response.text)