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
st.set_page_config(page_title="Smart Exam Generator", layout="centered")

def set_background(image_file):
    image_path = Path(__file__).parent / image_file
    with open(image_path, "rb") as f:
        encoded = base64.b64encode(f.read()).decode()

    css = f"""
    <style>
    /* Full-page background */
    .stApp {{
        background-image: url("data:image/png;base64,{encoded}");
        background-size: cover;
        background-repeat: no-repeat;
        background-position: center center;
        background-attachment: fixed;
    }}

    html, body, [data-testid="stAppViewContainer"] {{
        height: 100%;
        margin: 0;
        padding: 0;
        background-color: transparent !important;
    }}

    /* Remove Streamlit white box */
    [data-testid="stHeader"], header, .block-container {{
        background-color: transparent !important;
    }}

    section.main > div {{
        background-color: rgba(0, 0, 0, 0); /* transparent */
        padding: 0rem !important;
        border-radius: 0rem !important;
        box-shadow: none !important;
    }}

    [data-testid="stVerticalBlock"] {{
        background-color: transparent !important;
        }}


    </style>
    """
    st.markdown(css, unsafe_allow_html=True)



set_background("BodhaImage.png")  # ✅ Must be above st.title



# 🏷️ App Title
st.markdown("""
<div style='
    width: 100vw;
    position: relative;
    left: calc(-50vw + 50%);
    text-align: center;
    margin-bottom: 1rem;
'>
    <h1 style='
        display: inline-block;
        white-space: nowrap;
        font-size: clamp(1.5rem, 4vw, 3rem);
        font-weight: 800;
        color: white;
        text-shadow: 1px 1px 4px rgba(0,0,0,0.7);
        margin: 0 auto;
    '>
        BodhaAI – Generate. Evaluate. Elevate.
    </h1>
</div>
""", unsafe_allow_html=True)




# 📤 Upload
uploaded_file = st.file_uploader("Upload your textbook or PDF:", type=["pdf"])

# 🧠 UI Selections
question_type = st.selectbox("Select Question Type:", ["MCQ", "Fill in the blanks", "True/False", "Short Answer"])
difficulty = st.selectbox("Select Difficulty Level:", ["Easy", "Medium", "Hard"])
num_questions = st.slider("Number of Questions PER CHAPTER:", min_value=1, max_value=20, value=4)

# 🧹 Clean text utility
def clean_text(text):
    text = re.sub(r'\n+', '\n', text)
    text = re.sub(r'\s{2,}', ' ', text)
    return text.strip()

# 📄 Extract chapters and fallback full text
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
        chapter_num = int(matches[i].group(2))
        chapter_title = f"Chapter {chapter_num}"
        start = matches[i].start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(full_text)
        content = full_text[start:end].strip()
        chapter_map[chapter_title] = content

    return dict(sorted(chapter_map.items(), key=lambda x: int(x[0].split()[-1]))), full_text

# 🤖 Gemini Generator
def generate_questions_with_gemini(text, difficulty, num_questions, q_type):
    if q_type == "MCQ":
        prompt = f"""
You are a question paper generator.

Given the following study material, generate {num_questions} {difficulty} level **MCQ questions** with **four options** each (A, B, C, D) and clearly indicate the **correct option** for each question.

---CONTENT START---
{text}
---CONTENT END---

Provide output in the following format (with spacing between lines):

Q1. <Question text>

A. Option A  
B. Option B  
C. Option C  
D. Option D  

Answer: <Correct Option Letter>

Q2. ...
"""

    elif q_type == "True/False":
        prompt = f"""
You are a question paper generator.

From the following content, generate {num_questions} {difficulty} level **True/False** questions and clearly indicate the **correct option** for each question.


Each question should be followed by the options:

True  
False


---CONTENT START---
{text}
---CONTENT END---

Provide output in the following format (with spacing between lines):

Q1. <Question text>

True  
False  

Answer: <Answer>

Q2. ...
"""
        
    else:
        prompt = f"""
You are a question paper generator.

From the following content, generate {num_questions} {difficulty} level questions of type "{q_type}".

---CONTENT START---
{text}
---CONTENT END---

Provide output in the following format (with spacing between lines):

Q1. <Question text>

Answer: <Answer>

Q2. ...
"""
    model = genai.GenerativeModel("models/gemini-1.5-flash-latest")
    response = model.generate_content(prompt)
    return response.text

# 🧠 Session State Init
if 'questions' not in st.session_state:
    st.session_state.questions = None
    st.session_state.answers = None
    st.session_state.chapters = {}
    st.session_state.full_text = ""
    st.session_state.selected_chapters = []

# 📜 Main Logic
if uploaded_file is not None:
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp_file:
        tmp_file.write(uploaded_file.read())
        pdf_path = tmp_file.name

    st.success("✅ PDF uploaded successfully!")

    if not st.session_state.chapters:
        with st.spinner("📖 Extracting chapters..."):
            chapters, full_text = extract_chapters_from_pdf(pdf_path)
            st.session_state.chapters = chapters
            st.session_state.full_text = full_text

    chapter_options = list(st.session_state.chapters.keys())

    if "select_all" not in st.session_state:
        st.session_state.select_all = False
    if "selected_chapters" not in st.session_state:
        st.session_state.selected_chapters = []

    st.session_state.select_all = st.checkbox("Select All Chapters", value=st.session_state.select_all)

    

    # 1. Show the dropdown first (with current session state)
    if st.session_state.select_all:
        selected_chapters = chapter_options
    else:
        selected_chapters = []

    # 2. Below it: checkbox to select all
    selected_chapters = st.multiselect(
        "Select Chapters to Generate Questions From (or leave empty to use full content):",
        chapter_options,
        default=selected_chapters,
        key="chapter_select"
        )

    st.session_state.selected_chapters = selected_chapters


    if st.button("Generate Questions"):
        if selected_chapters:
            selected_text = "\n\n".join([st.session_state.chapters[ch] for ch in selected_chapters])
            total_questions = num_questions * len(selected_chapters)
        else:
            selected_text = st.session_state.full_text
            total_questions = num_questions

        try:
            combined_output = generate_questions_with_gemini(selected_text, difficulty, total_questions, question_type)
        except Exception as e:
            st.error(f"⚠️ Gemini failed: {e}")
            combined_output = ""

        # 🔍 Parse Output
        question_lines = []
        answer_lines = []
        buffer = []
        answer_count = 1

        for line in combined_output.splitlines():
            if line.strip().lower().startswith("answer:"):
                answer_text = line.strip().split("Answer:", 1)[-1].strip()
                answer_lines.append(f"Answer {answer_count}: {answer_text}")
                answer_count += 1
                buffer.append("")
                question_lines.append("")
            elif line.strip():
                buffer.append(line.strip())
                if question_type == "MCQ" and re.match(r'^[A-Da-d][\.\)]', line.strip()):
                    buffer.append("")
            else:
                buffer.append("")

        question_lines = [line for line in buffer if not line.strip().lower().startswith("answer")]
        st.session_state.questions = "\n".join(question_lines)
        st.session_state.answers = "\n".join(answer_lines)

# 📥 Display Outputs
if st.session_state.questions:
    st.success("✅ Question Paper Generated Successfully")
    st.text_area("📄 View the Question Paper", st.session_state.questions, height=500,disabled = True)

    st.download_button("📥 Download Question Paper", st.session_state.questions.encode("utf-8"), "Question_Paper.txt")

if st.session_state.answers:
    st.download_button("📥 Download Answer Key", st.session_state.answers.encode("utf-8"), "Answer_Key.txt")
