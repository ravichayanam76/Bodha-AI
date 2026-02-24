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
        
        /* The main content container */
        section.main > div {{
            background-color: rgba(255, 255, 255, 0.92); /* Bright white with high opacity */
            padding: 3rem !important;
            border-radius: 20px !important;
            box-shadow: 0 10px 30px rgba(0,0,0,0.3);
            margin-top: 20px;
            margin-bottom: 20px;
        }}

        /* Global Text Color for readability */
        h1, h2, h3, p, span, label, .stMarkdown {{
            color: #1a1a1a !important; /* Deep Charcoal/Black */
            font-weight: 500;
        }}

        /* Styling Question Text specifically */
        .question-text {{
            color: #003366 !important; /* Deep Navy Blue */
            font-size: 1.1rem !important;
            font-weight: 700 !important;
            margin-bottom: 10px;
        }}

        /* Styling Radio Button Choices */
        div[data-testid="stMarkdownContainer"] p {{
            color: #1a1a1a !important;
            font-size: 1rem !important;
        }}
        
        /* Fix for white labels on some themes */
        .stWidgetLabel p {{
            color: #1a1a1a !important;
            font-weight: bold !important;
        }}

        /* Buttons */
        .stButton>button {{
            width: 100%;
            background-color: #1E3A8A !important;
            color: white !important;
            border-radius: 10px;
            height: 3em;
            font-weight: bold;
        }}
        </style>
        """
        st.markdown(css, unsafe_allow_html=True)
    except:
        pass

set_background("BodhaImage.png")

# 🏷️ App Title (White with shadow for the background, but the rest is on the white card)
st.markdown("<h1 style='text-align: center; color: white; text-shadow: 2px 2px 4px #000;'>BodhaAI – Generate. Evaluate. Elevate.</h1>", unsafe_allow_html=True)

# 🧠 Session State Init
if 'quiz_data' not in st.session_state:
    st.session_state.quiz_data = []
if 'chapters' not in st.session_state:
    st.session_state.chapters = {}
if 'full_text' not in st.session_state:
    st.session_state.full_text = ""

# 📤 Upload & UI (These appear on the white card)
st.subheader("📁 Prepare Your Exam")
uploaded_file = st.file_uploader("Upload your textbook or PDF:", type=["pdf"])
col1, col2 = st.columns(2)
with col1:
    question_type = st.selectbox("Select Question Type:", ["MCQ", "True/False"])
with col2:
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
    questions = []
    blocks = re.split(r'Q\d*[:.]\s*', raw_text)
    
    for block in blocks:
        if not block.strip(): continue
        lines = [l.strip() for l in block.split('\n') if l.strip()]
        
        q_text = lines[0]
        options = [l for l in lines if re.match(r'^[A-D][\)\.]', l) or l in ["True", "False"]]
        answer_line = [l for l in lines if "Answer:" in l or "Correct:" in l]
        
        if q_text and answer_line:
            correct_ans = answer_line[0].split(":")[-1].strip()
            if question_type == "MCQ":
                match = re.search(r'[A-D]', correct_ans)
                correct_ans = match.group() if match else correct_ans
                
            questions.append({
                "question": q_text,
                "options": options,
                "answer": correct_ans
            })
    return questions

def generate_questions(text, difficulty, num, q_type):
    model = genai.GenerativeModel("gemini-1.5-flash") # Use stable version
    prompt = f"""
    Generate {num} {difficulty} level {q_type} questions.
    RULES: Start with 'Q: ', use A), B), C), D) for options. End with 'Answer: <letter>'.
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

    selected_ch = st.multiselect("Select Chapters (Optional):", list(st.session_state.chapters.keys()))
    
    if st.button("Generate Interactive Quiz"):
        with st.spinner("BodhaAI is thinking..."):
            source_text = "\n".join([st.session_state.chapters[c] for c in selected_ch]) if selected_ch else st.session_state.full_text
            raw_output = generate_questions(source_text, difficulty, num_questions, question_type)
            st.session_state.quiz_data = parse_generated_questions(raw_output)

# 📝 Display Quiz
if st.session_state.quiz_data:
    st.markdown("---")
    with st.form("exam_form"):
        st.markdown("<h2 style='text-align: center; color: #1E3A8A;'>Interactive Exam</h2>", unsafe_allow_html=True)
        user_responses = {}
        
        for i, item in enumerate(st.session_state.quiz_data):
            # Applying the custom question-text class
            st.markdown(f"<p class='question-text'>Question {i+1}: {item['question']}</p>", unsafe_allow_html=True)
            user_responses[i] = st.radio("Choose the correct option:", item['options'], key=f"q{i}", label_visibility="collapsed")
            st.write("")
            
        submitted = st.form_submit_button("Submit Exam & Calculate Score")
        
        if submitted:
            score = 0
            for i, item in enumerate(st.session_state.quiz_data):
                if user_responses[i].startswith(item['answer']):
                    score += 1
                    st.success(f"✅ Q{i+1}: Correct!")
                else:
                    st.error(f"❌ Q{i+1}: Incorrect. Correct answer: {item['answer']}")
            
            percent = (score / len(st.session_state.quiz_data)) * 100
            st.metric("Final Result", f"{percent:.1f}%", f"{score}/{len(st.session_state.quiz_data)} Correct")
            if percent >= 70: st.balloons()
