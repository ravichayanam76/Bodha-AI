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
        /* Main page setup */
        .stApp {{
            background-image: url("data:image/png;base64,{encoded}");
            background-size: cover;
            background-repeat: no-repeat;
            background-position: center center;
            background-attachment: fixed;
        }}
        
        /* The Content Card */
        section.main > div {{
            background-color: rgba(255, 255, 255, 0.96); 
            padding: 3rem !important;
            border-radius: 20px !important;
            box-shadow: 0 12px 40px rgba(0,0,0,0.4);
        }}

        /* Typography */
        h1, h2, h3 {{
            color: #1E3A8A !important;
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
        }}

        .stMarkdown p, label, .stText {{
            color: #2D3748 !important; /* Dark Slate Gray for best readability */
            font-size: 1.05rem !important;
            line-height: 1.6 !important;
        }}

        /* Question Box Styling */
        .question-style {{
            background-color: #F1F5F9;
            padding: 15px;
            border-left: 6px solid #1E3A8A;
            border-radius: 8px;
            margin-bottom: 5px;
            color: #1E293B !important;
            font-weight: 600 !important;
        }}

        /* Button Styling */
        .stButton>button {{
            width: 100%;
            background: linear-gradient(90deg, #1E3A8A 0%, #3B82F6 100%);
            color: white !important;
            border: none;
            padding: 0.6rem;
            border-radius: 10px;
            font-weight: bold;
            font-size: 1.1rem;
        }}

        /* Remove default streamlit header clutter */
        [data-testid="stHeader"], header {{
            background-color: transparent !important;
        }}
        </style>
        """
        st.markdown(css, unsafe_allow_html=True)
    except:
        pass

set_background("BodhaImage.png")

# 🏷️ App Title
st.markdown("<h1 style='text-align: center; margin-bottom: 0;'>BodhaAI</h1>", unsafe_allow_html=True)
st.markdown("<p style='text-align: center; color: #475569; margin-top: -10px;'>Generate • Evaluate • Elevate</p>", unsafe_allow_html=True)

# 🧠 Session State Init
if 'quiz_data' not in st.session_state:
    st.session_state.quiz_data = []
if 'chapters' not in st.session_state:
    st.session_state.chapters = {}
if 'full_text' not in st.session_state:
    st.session_state.full_text = ""

# 📤 Step 1: Upload
st.write("### 📁 Upload Study Material")
uploaded_file = st.file_uploader("Upload your textbook (PDF)", type=["pdf"], label_visibility="collapsed")

# 🧹 Clean text utility
def clean_text(text):
    text = re.sub(r'\n+', '\n', text)
    text = re.sub(r'\s{2,}', ' ', text)
    return text.strip()

# 📄 Extraction using original pdfplumber logic
def extract_chapters_from_pdf(file_path):
    full_text = ""
    with pdfplumber.open(file_path) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text()
            if page_text:
                full_text += page_text + "\n"
    
    full_text = clean_text(full_text)
    pattern = re.compile(r'(Chapter\s+(\d+))\b', re.IGNORECASE)
    matches = list(pattern.finditer(full_text))
    chapter_map = {}

    for i in range(len(matches)):
        start = matches[i].start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(full_text)
        chapter_map[matches[i].group(1)] = full_text[start:end].strip()

    return chapter_map, full_text

# 🤖 Gemini Generator logic
def generate_questions(text, difficulty, num, q_type):
    model = genai.GenerativeModel("gemini-2.0-flash") # Updated to latest stable
    prompt = f"""
    Generate {num} {difficulty} level {q_type} questions based on this text.
    FORMAT: Start with 'Q: ', use A), B), C), D) for options. End with 'Answer: <letter>'.
    TEXT: {text[:4000]} 
    """
    response = model.generate_content(prompt)
    return response.text

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
            correct_ans = ans_line[0].split(":")[-1].strip()
            if q_type == "MCQ":
                match = re.search(r'[A-D]', correct_ans)
                correct_ans = match.group() if match else correct_ans
            questions.append({"question": q_text, "options": options, "answer": correct_ans})
    return questions

# 📜 Step 2: Configuration
if uploaded_file:
    if not st.session_state.full_text:
        with st.spinner("Analyzing PDF content..."):
            with tempfile.NamedTemporaryFile(delete=False) as tmp:
                tmp.write(uploaded_file.read())
                chaps, f_text = extract_chapters_from_pdf(tmp.name)
                st.session_state.chapters = chaps
                st.session_state.full_text = f_text

    st.write("### ⚙️ Quiz Settings")
    col1, col2 = st.columns(2)
    with col1:
        question_type = st.selectbox("Type", ["MCQ", "True/False"])
        difficulty = st.selectbox("Difficulty", ["Easy", "Medium", "Hard"])
    with col2:
        num_questions = st.slider("Number of Questions", 1, 20, 5)
    
    selected_ch = st.multiselect("Select Specific Chapters (Optional):", list(st.session_state.chapters.keys()))

    if st.button("🚀 Generate My Exam"):
        with st.spinner("AI is crafting your questions..."):
            source = "\n".join([st.session_state.chapters[c] for c in selected_ch]) if selected_ch else st.session_state.full_text
            raw_output = generate_questions(source, difficulty, num_questions, question_type)
            st.session_state.quiz_data = parse_generated_questions(raw_output, question_type)

# 📝 Step 3: Interactive Quiz
if st.session_state.quiz_data:
    st.markdown("---")
    with st.form("exam_form"):
        st.markdown("<h2 style='text-align: center;'>Knowledge Check</h2>", unsafe_allow_html=True)
        user_responses = {}
        
        for i, item in enumerate(st.session_state.quiz_data):
            st.markdown(f'<div class="question-style">Q{i+1}: {item["question"]}</div>', unsafe_allow_html=True)
            user_responses[i] = st.radio("Select an option:", item['options'], key=f"q{i}", label_visibility="collapsed")
            st.write("")
            
        submitted = st.form_submit_button("Submit Exam & View Results")
        
        if submitted:
            score = 0
            for i, item in enumerate(st.session_state.quiz_data):
                if user_responses[i].startswith(item['answer']):
                    score += 1
                    st.success(f"✅ Question {i+1}: Correct!")
                else:
                    st.error(f"❌ Question {i+1}: Incorrect. The correct answer was: {item['answer']}")
            
            percent = (score / len(st.session_state.quiz_data)) * 100
            st.divider()
            st.metric("Final Performance", f"{percent:.0f}%", f"{score}/{len(st.session_state.quiz_data)} Correct")
            if percent >= 70: st.balloons()
