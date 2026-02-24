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
        /* Main background */
        .stApp {{
            background-image: url("data:image/png;base64,{encoded}");
            background-size: cover;
            background-repeat: no-repeat;
            background-position: center center;
            background-attachment: fixed;
        }}

        /* Glassmorphism Card Effect */
        section.main > div {{
            background: rgba(255, 255, 255, 0.94); 
            padding: 3rem !important;
            border-radius: 24px !important;
            box-shadow: 0 8px 32px 0 rgba(31, 38, 135, 0.37);
            border: 1px solid rgba(255, 255, 255, 0.18);
        }}

        /* Typography & Colors */
        h1, h2, h3 {{
            color: #0F172A !important; /* Slate Dark */
            font-family: 'Inter', sans-serif;
            font-weight: 800 !important;
        }}

        .stMarkdown p, .stText {{
            color: #334155 !important; /* Slate Gray */
            line-height: 1.6;
        }}

        /* Elegant Question Styling */
        .question-box {{
            background-color: #F8FAFC;
            padding: 20px;
            border-left: 5px solid #1E3A8A;
            border-radius: 8px;
            margin-bottom: 10px;
        }}

        /* Custom Button */
        .stButton>button {{
            background: linear-gradient(135deg, #1E3A8A 0%, #3B82F6 100%);
            color: white !important;
            border: none;
            padding: 12px 24px;
            border-radius: 12px;
            font-weight: 600;
            transition: all 0.3s ease;
        }}
        
        .stButton>button:hover {{
            transform: translateY(-2px);
            box-shadow: 0 5px 15px rgba(30, 58, 138, 0.4);
        }}

        /* Metric Styling */
        [data-testid="stMetricValue"] {{
            color: #1E3A8A !important;
            font-size: 2.5rem !important;
        }}
        </style>
        """
        st.markdown(css, unsafe_allow_html=True)
    except:
        pass

set_background("BodhaImage.png")

# 🏷️ Elegant App Title
st.markdown("<h1 style='text-align: center; margin-bottom: 0;'>BodhaAI</h1>", unsafe_allow_html=True)
st.markdown("<p style='text-align: center; color: #64748B; font-size: 1.2rem;'>Generate. Evaluate. Elevate.</p>", unsafe_allow_html=True)
st.write("")

# 🧠 Session State Init
if 'quiz_data' not in st.session_state:
    st.session_state.quiz_data = []
if 'chapters' not in st.session_state:
    st.session_state.chapters = {}
if 'full_text' not in st.session_state:
    st.session_state.full_text = ""

# 📤 Upload Section
with st.container():
    st.subheader("📑 Step 1: Upload Material")
    uploaded_file = st.file_uploader("Choose a PDF file", type=["pdf"], label_visibility="collapsed")

# ⚙️ Config Section
if uploaded_file:
    st.divider()
    st.subheader("⚙️ Step 2: Configure Quiz")
    col1, col2 = st.columns(2)
    with col1:
        question_type = st.selectbox("Format", ["MCQ", "True/False"])
        difficulty = st.selectbox("Difficulty", ["Easy", "Medium", "Hard"])
    with col2:
        num_questions = st.select_slider("Quantity", options=range(1, 21), value=5)
    
    # Text Extraction Logic
    if not st.session_state.full_text:
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            tmp.write(uploaded_file.read())
            # (Assuming your extract_chapters_from_pdf function is defined)
            from pypdf import PdfReader # Fallback suggestion if pdfplumber is slow
            # Your existing extraction logic here...
            # For brevity, reusing your logic:
            def clean_text(text):
                return re.sub(r'\s+', ' ', text).strip()
            
            with pdfplumber.open(tmp.name) as pdf:
                full_text = "\n".join([p.extract_text() for p in pdf.pages if p.extract_text()])
                st.session_state.full_text = clean_text(full_text)

    if st.button("✨ Generate My Quiz"):
        with st.spinner("AI is crafting your questions..."):
            # Your generate_questions logic here
            model = genai.GenerativeModel("gemini-1.5-flash")
            prompt = f"Generate {num_questions} {difficulty} {question_type} questions. Text: {st.session_state.full_text[:3000]}. Format: Q: <text> A) <text> B) <text> C) <text> D) <text> Answer: <letter>"
            response = model.generate_content(prompt)
            
            # Simplified Parse (reusing your parser)
            raw_text = response.text
            questions = []
            blocks = re.split(r'Q\d*[:.]\s*', raw_text)
            for b in blocks:
                if not b.strip(): continue
                lines = [l.strip() for l in b.split('\n') if l.strip()]
                q_text = lines[0]
                opts = [l for l in lines if re.match(r'^[A-D][\)\.]', l) or l in ["True", "False"]]
                ans = [l for l in lines if "Answer:" in l or "Correct:" in l]
                if q_text and ans:
                    correct = re.search(r'[A-D]|True|False', ans[0]).group()
                    questions.append({"question": q_text, "options": opts, "answer": correct})
            st.session_state.quiz_data = questions

# 📝 Quiz Display
if st.session_state.quiz_data:
    st.markdown("---")
    with st.form("elegant_exam"):
        st.markdown("<h3 style='text-align: center;'>Knowledge Assessment</h3>", unsafe_allow_html=True)
        user_responses = {}
        
        for i, item in enumerate(st.session_state.quiz_data):
            st.markdown(f"""<div class="question-box"><strong>Question {i+1}</strong><br>{item['question']}</div>""", unsafe_allow_html=True)
            user_responses[i] = st.radio("Select Answer:", item['options'], key=f"q{i}", label_visibility="collapsed")
            st.write("")
            
        submitted = st.form_submit_button("Submit Assessment")
        
        if submitted:
            score = 0
            for i, item in enumerate(st.session_state.quiz_data):
                if user_responses[i].startswith(item['answer']):
                    score += 1
                    st.success(f"Question {i+1}: Correct")
                else:
                    st.error(f"Question {i+1}: Expected {item['answer']}")
            
            percent = (score / len(st.session_state.quiz_data)) * 100
            st.divider()
            st.metric("Final Proficiency", f"{percent:.0f}%", f"{score}/{len(st.session_state.quiz_data)} Score")
            if percent >= 70: st.balloons()
