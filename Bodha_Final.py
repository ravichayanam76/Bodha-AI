import streamlit as st
import pdfplumber
import google.generativeai as genai
import tempfile
import re
import os
from pathlib import Path
import base64

# 🔐 Gemini API key configuration
try:
    genai.configure(api_key=st.secrets["gemini_api_key"])
except Exception as e:
    st.error("Missing API Key! Please add 'gemini_api_key' to your Streamlit Secrets.")

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
            background-attachment: fixed;
        }}
        section.main > div {{
            background-color: rgba(255, 255, 255, 0.96); 
            padding: 3rem !important;
            border-radius: 20px !important;
            box-shadow: 0 12px 40px rgba(0,0,0,0.4);
        }}
        .question-style {{
            background-color: #F1F5F9;
            padding: 15px;
            border-left: 6px solid #1E3A8A;
            border-radius: 8px;
            margin-bottom: 5px;
            color: #1E293B !important;
            font-weight: 600;
        }}
        .stButton>button {{
            width: 100%;
            background: linear-gradient(90deg, #1E3A8A 0%, #3B82F6 100%);
            color: white !important;
            font-weight: bold;
        }}
        </style>
        """
        st.markdown(css, unsafe_allow_html=True)
    except:
        st.warning("Background image not found. Proceeding with default theme.")

set_background("BodhaImage.png")

st.markdown("<h1 style='text-align: center; color: #1E3A8A;'>BodhaAI</h1>", unsafe_allow_html=True)
st.markdown("<p style='text-align: center; color: #475569;'>Generate • Evaluate • Elevate</p>", unsafe_allow_html=True)

if 'quiz_data' not in st.session_state: st.session_state.quiz_data = []
if 'chapters' not in st.session_state: st.session_state.chapters = {}
if 'full_text' not in st.session_state: st.session_state.full_text = ""

uploaded_file = st.file_uploader("Upload your PDF", type=["pdf"], label_visibility="collapsed")

def clean_text(text):
    return re.sub(r'\s+', ' ', text).strip()

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

def generate_questions(text, difficulty, num, q_type):
    # Using the most stable model name
    model = genai.GenerativeModel("gemini-1.5-flash") 
    prompt = f"Generate {num} {difficulty} {q_type} questions. Text: {text[:3500]}. Format: Q: <text> A) <text> B) <text> C) <text> D) <text> Answer: <letter>"
    try:
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        return f"ERROR_AI: {str(e)}"

def parse_generated_questions(raw_text, q_type):
    questions = []
    blocks = re.split(r'Q\d*[:.]\s*', raw_text)
    for block in blocks:
        if not block.strip(): continue
        lines = [l.strip() for l in block.split('\n') if l.strip()]
        q_text = lines[0]
        options = [l for l in lines if re.match(r'^[A-D][\)\.]', l) or l in ["True", "False"]]
        ans_line = [l for l in lines if "Answer:" in l or "Correct:" in l]
        if q_text and ans_line:
            correct_ans = re.search(r'[A-D]|True|False', ans_line[0]).group()
            questions.append({"question": q_text, "options": options, "answer": correct_ans})
    return questions

if uploaded_file:
    if not st.session_state.full_text:
        with st.spinner("Processing PDF..."):
            with tempfile.NamedTemporaryFile(delete=False) as tmp:
                tmp.write(uploaded_file.read())
                chaps, f_text = extract_chapters_from_pdf(tmp.name)
                st.session_state.chapters = chaps
                st.session_state.full_text = f_text

    col1, col2 = st.columns(2)
    with col1:
        question_type = st.selectbox("Type", ["MCQ", "True/False"])
        difficulty = st.selectbox("Difficulty", ["Easy", "Medium", "Hard"])
    with col2:
        num_questions = st.slider("Count", 1, 15, 5)
    
    selected_ch = st.multiselect("Select Chapters (Optional)", list(st.session_state.chapters.keys()))

    if st.button("🚀 Generate Exam"):
        with st.spinner("AI is thinking..."):
            source = "\n".join([st.session_state.chapters[c] for c in selected_ch]) if selected_ch else st.session_state.full_text
            raw_output = generate_questions(source, difficulty, num_questions, question_type)
            
            if "ERROR_AI" in raw_output:
                st.error(f"Failed to connect to AI. Details: {raw_output}")
            else:
                st.session_state.quiz_data = parse_generated_questions(raw_output, question_type)

if st.session_state.quiz_data:
    st.divider()
    with st.form("exam_form"):
        user_responses = {}
        for i, item in enumerate(st.session_state.quiz_data):
            st.markdown(f'<div class="question-style">Q{i+1}: {item["question"]}</div>', unsafe_allow_html=True)
            user_responses[i] = st.radio("Options", item['options'], key=f"q{i}", label_visibility="collapsed")
            st.write("")
        if st.form_submit_button("Submit"):
            score = 0
            for i, item in enumerate(st.session_state.quiz_data):
                if user_responses[i].startswith(item['answer']):
                    score += 1
                    st.success(f"✅ Q{i+1}: Correct!")
                else:
                    st.error(f"❌ Q{i+1}: Correct was {item['answer']}")
            percent = (score / len(st.session_state.quiz_data)) * 100
            st.metric("Score", f"{percent:.0f}%", f"{score}/{len(st.session_state.quiz_data)}")
            if percent >= 70: st.balloons()
