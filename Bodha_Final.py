import streamlit as st
import pdfplumber
import google.generativeai as genai
import tempfile
import re
import os
from PIL import Image
from pathlib import Path
import base64

# 🔐 Gemini API key
genai.configure(api_key=st.secrets["gemini_api_key"])

# 📘 Streamlit Config
st.set_page_config(page_title="BodhaAI - Smart Exam", layout="centered")

def set_background(image_file):
    try:
        image_path = Path(__file__).parent / image_file
        with open(image_path, "rb") as f:
            encoded = base64.b64encode(f.read()).decode()

        css = f"""
        <style>
        .stApp {{
            background-image: url("data:image/png;base64,{encoded}");
            background-size: cover;
            background-repeat: no-repeat;
            background-position: center center;
            background-attachment: fixed;
        }}
        [data-testid="stHeader"], header, .block-container {{
            background-color: transparent !important;
        }}
        section.main > div {{
            background-color: rgba(255, 255, 255, 0.85); /* Slight white overlay for readability */
            padding: 2rem !important;
            border-radius: 15px !important;
        }}
        </style>
        """
        st.markdown(css, unsafe_allow_html=True)
    except:
        pass

set_background("BodhaImage.png")

# 🏷️ App Title
st.markdown("<h1 style='text-align: center; color: #1E3A8A;'>BodhaAI – Generate. Evaluate. Elevate.</h1>", unsafe_allow_html=True)

# 🧠 Session State Init
if 'quiz_data' not in st.session_state:
    st.session_state.quiz_data = []
if 'chapters' not in st.session_state:
    st.session_state.chapters = {}
if 'full_text' not in st.session_state:
    st.session_state.full_text = ""

# 📤 Upload & UI
uploaded_file = st.file_uploader("Upload your textbook or PDF:", type=["pdf"])
question_type = st.selectbox("Select Question Type:", ["MCQ", "True/False"])
difficulty = st.selectbox("Select Difficulty Level:", ["Easy", "Medium", "Hard"])
num_questions = st.slider("Questions per selection:", 1, 20, 5)

# 🧹 Clean text utility
def clean_text(text):
    text = re.sub(r'\n+', '\n', text)
    text = re.sub(r'\s{2,}', ' ', text)
    return text.strip()

def extract_chapters_from_pdf(file_path):
    full_text = ""
    with pdfplumber.open(file_path) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text()
            if page_text: full_text += page_text + "\n"
    
    full_text = clean_text(full_text)
    pattern = re.compile(r'(Chapter\s+(\d+))\b', re.IGNORECASE)
    matches = list(pattern.finditer(full_text))
    chapter_map = {}

    for i in range(len(matches)):
        start = matches[i].start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(full_text)
        chapter_map[matches[i].group(1)] = full_text[start:end].strip()

    return chapter_map, full_text

def parse_generated_questions(raw_text):
    """Parses Gemini output into a list of structured dictionaries."""
    questions = []
    # Split by Q: followed by any number
    blocks = re.split(r'Q\d*[:.]\s*', raw_text)
    
    for block in blocks:
        if not block.strip(): continue
        lines = [l.strip() for l in block.split('\n') if l.strip()]
        
        # Logic to find Question, Options, and Answer
        q_text = lines[0]
        options = [l for l in lines if re.match(r'^[A-D][\)\.]', l) or l in ["True", "False"]]
        answer_line = [l for l in lines if "Answer:" in l or "Correct:" in l]
        
        if q_text and answer_line:
            correct_ans = answer_line[0].split(":")[-1].strip()
            # If MCQ, just get the letter (A, B, C, D)
            if question_type == "MCQ":
                correct_ans = re.search(r'[A-D]', correct_ans).group()
                
            questions.append({
                "question": q_text,
                "options": options,
                "answer": correct_ans
            })
    return questions

# 🤖 Gemini Generator
def generate_questions(text, difficulty, num, q_type):
    model = genai.GenerativeModel("gemini-2.5-flash")
    prompt = f"""
    Generate {num} {difficulty} level {q_type} questions based on this text.
    
    FORMAT RULES:
    1. Start each question with "Q: "
    2. For MCQ, provide 4 options starting with A), B), C), D).
    3. For True/False, provide True and False as options.
    4. End each question block with "Answer: <correct letter or word>"
    
    TEXT: {text[:4000]} 
    """
    response = model.generate_content(prompt)
    return response.text

# 📜 Main Logic
if uploaded_file:
    if not st.session_state.full_text:
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            tmp.write(uploaded_file.read())
            chapters, full_text = extract_chapters_from_pdf(tmp.name)
            st.session_state.chapters = chapters
            st.session_state.full_text = full_text

    selected_ch = st.multiselect("Select Chapters:", list(st.session_state.chapters.keys()))
    
    if st.button("Generate Interactive Quiz"):
        source_text = "\n".join([st.session_state.chapters[c] for c in selected_ch]) if selected_ch else st.session_state.full_text
        raw_output = generate_questions(source_text, difficulty, num_questions, question_type)
        st.session_state.quiz_data = parse_generated_questions(raw_output)

# 📝 Display Quiz
if st.session_state.quiz_data:
    st.divider()
    with st.form("exam_form"):
        st.subheader("Final Examination")
        user_responses = {}
        
        for i, item in enumerate(st.session_state.quiz_data):
            st.write(f"**Question {i+1}:** {item['question']}")
            user_responses[i] = st.radio("Choose one:", item['options'], key=f"q{i}", label_visibility="collapsed")
            st.write("---")
            
        submitted = st.form_submit_button("Submit Exam")
        
        if submitted:
            score = 0
            for i, item in enumerate(st.session_state.quiz_data):
                # Check if first letter of choice matches answer
                if user_responses[i].startswith(item['answer']):
                    score += 1
                    st.success(f"Q{i+1}: Correct!")
                else:
                    st.error(f"Q{i+1}: Wrong. Correct answer was: {item['answer']}")
            
            percent = (score / len(st.session_state.quiz_data)) * 100
            st.metric("Final Score", f"{percent}%", f"{score}/{len(st.session_state.quiz_data)}")
            if percent >= 70: st.balloons()
