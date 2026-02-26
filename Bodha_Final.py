import streamlit as st
import pdfplumber
import google.generativeai as genai
import tempfile
import re
import os
import json
import base64
import time  
from pathlib import Path
from dotenv import load_dotenv

# --- CONFIG & PERSISTENCE ---
load_dotenv()
api_key = st.secrets.get("GEMINI_API_KEY") or os.getenv("GEMINI_API_KEY")

if not api_key:
    st.error("Missing Gemini API Key. Please configure it in your Secrets or .env file.")
    st.stop()

genai.configure(api_key=api_key)

st.set_page_config(page_title="BodhaAI - Smart Exam", layout="centered")

DB_FILE = "global_quiz_data.json"
RESULTS_FILE = "student_submissions.json"

def save_quiz_to_disk(data):
    with open(DB_FILE, "w") as f:
        json.dump(data, f)

def load_quiz_from_disk():
    if os.path.exists(DB_FILE):
        with open(DB_FILE, "r") as f:
            return json.load(f)
    return []

def save_student_score(name, score, total):
    results = load_all_results()
    results.append({
        "Student Name": name,
        "Score": f"{score}/{total}",
        "Percentage": f"{(score/total)*100:.1f}%",
        "Timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
    })
    with open(RESULTS_FILE, "w") as f:
        json.dump(results, f)

def load_all_results():
    if os.path.exists(RESULTS_FILE):
        with open(RESULTS_FILE, "r") as f:
            try: return json.load(f)
            except: return []
    return []

# --- UI STYLING ---
def set_background(image_file):
    try:
        encoded = base64.b64encode(open(image_file, "rb").read()).decode()
        css = f"""
        <style>
        .stApp {{
            background-image: url("data:image/png;base64,{encoded}");
            background-size: cover;
            background-attachment: fixed;
        }}
        section.main > div {{
            background-color: rgba(255, 255, 255, 0.85);
            padding: 2rem !important;
            border-radius: 15px !important;
        }}
        [data-testid="stSidebar"] .stMarkdown p, 
        [data-testid="stSidebar"] label, 
        [data-testid="stSidebar"] div[data-testid="stWidgetLabel"] p,
        [data-testid="stWidgetLabel"] p {{ color: #000000 !important; }}
        
        .stButton button {{
            width: 100%;
            background: linear-gradient(90deg, #1E3A8A 0%, #3B82F6 100%);
            color: white !important;
            font-weight: bold;
        }}
        .timer-container {{
            background-color: #f0f2f6;
            padding: 10px;
            border-radius: 10px;
            border-left: 5px solid #1E3A8A;
            text-align: center;
            margin-bottom: 20px;
        }}
        .timer-text {{ font-size: 24px; font-weight: bold; color: #1E3A8A; }}
        </style>
        """
        st.markdown(css, unsafe_allow_html=True)
    except:
        pass

set_background("BodhaImage.png")

# --- SESSION STATE ---
if 'role' not in st.session_state: st.session_state.role = "Student"
if 'is_authenticated' not in st.session_state: st.session_state.is_authenticated = False
if 'exam_submitted' not in st.session_state: st.session_state.exam_submitted = False

# --- UTILS ---
def clean_text(text):
    return re.sub(r'\n+', '\n', text).strip()

@st.cache_data(show_spinner="Processing PDF...")
def extract_chapters_from_pdf(file_path):
    full_text = ""
    with pdfplumber.open(file_path) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text()
            if page_text: full_text += page_text + "\n"
    return clean_text(full_text)

def parse_generated_questions(raw_text, q_type):
    questions = []
    # More robust splitting to handle conversational AI filler
    blocks = re.split(r'\nQ[:\d\.\s]+', "\n" + raw_text)
    for block in blocks:
        if "Answer:" not in block: continue
        lines = [l.strip() for l in block.split('\n') if l.strip()]
        if not lines: continue
        
        q_text = lines[0]
        options = [l for l in lines if re.match(r'^[A-D][\)\.]', l)]
        ans_line = [l for l in lines if "Answer:" in l]
        
        if q_text and ans_line:
            correct_ans = ans_line[0].split(":")[-1].strip()
            if not options and q_type == "True/False":
                options = ["True", "False"]
            if options:
                questions.append({"question": q_text, "options": options, "answer": correct_ans})
    return questions

@st.cache_data(show_spinner="AI is generating questions...")
def generate_questions(text, difficulty, num, q_type):
    if not text.strip(): return "ERROR: PDF is empty or unscannable."
    # Fixed model ID for 2026 stability
    model = genai.GenerativeModel("gemini-1.5-flash") 
    prompt = f"""Generate exactly {num} {difficulty} level {q_type} questions based on this text.
    Format:
    Q: [Question]
    A) Option
    B) Option
    C) Option
    D) Option
    Answer: [Correct Letter]
    
    Text: {text[:10000]}"""
    try:
        response = model.generate_content(prompt)
        return response.text if response.text else "ERROR: No response"
    except Exception as e:
        return f"ERROR: {str(e)}"

# --- UI LAYOUT ---
st.markdown("<h1 style='text-align: center; color: #1E3A8A;'>BodhaAI Exam Portal</h1>", unsafe_allow_html=True)
st.sidebar.title("Navigation")
st.session_state.role = st.sidebar.radio("Select Role:", ["Student", "Examiner"])

# --- EXAMINER VIEW ---
if st.session_state.role == "Examiner":
    if not st.session_state.is_authenticated:
        st.subheader("🔒 Examiner Login")
        pwd = st.text_input("Password:", type="password")
        if st.button("Login") and pwd == "admin123":
            st.session_state.is_authenticated = True
            st.rerun()
    else:
        st.subheader("🛠️ Examiner Dashboard")
        if st.sidebar.button("🔄 Reset System"):
            for f in [DB_FILE, RESULTS_FILE]:
                if os.path.exists(f): os.remove(f)
            st.cache_data.clear()
            st.rerun()

        uploaded_file = st.file_uploader("Upload Exam PDF", type=["pdf"])
        c1, c2 = st.columns(2)
        with c1: q_type = st.selectbox("Type", ["MCQ", "True/False"])
        with c2: num_q = st.slider("Questions", 1, 50, 5)
        
        if uploaded_file and st.button("Generate & Publish"):
            with tempfile.NamedTemporaryFile(delete=False) as tmp:
                tmp.write(uploaded_file.read())
                txt = extract_chapters_from_pdf(tmp.name)
            raw = generate_questions(txt, "Medium", num_q, q_type)
            data = parse_generated_questions(raw, q_type)
            if data:
                save_quiz_to_disk(data)
                st.success("✅ Exam Published!")
            else: st.error("Failed to parse AI output. Try again.")

        st.write("---")
        st.subheader("📊 Student Submissions")
        res = load_all_results()
        if res: st.table(res)
        else: st.info("No submissions yet.")

# --- STUDENT VIEW ---
elif st.session_state.role == "Student":
    st.subheader("✍️ Student Examination")
    quiz = load_quiz_from_disk()
    
    if not quiz: st.info("No exam available.")
    elif st.session_state.exam_submitted:
        st.success("✅ Exam already submitted. You cannot take it again.")
    else:
        name = st.text_input("Full Name:", placeholder="Enter name to start")
        if 'start_time' not in st.session_state: st.session_state.start_time = time.time()
        
        timer_box = st.empty()
        with st.form("exam_form"):
            ans = {}
            for i, item in enumerate(quiz):
                st.write(f"**Q{i+1}: {item['question']}**")
                ans[i] = st.radio("Select:", item['options'], key=f"q{i}", label_visibility="collapsed")
            
            if st.form_submit_button("Submit Final Answers"):
                if not name: st.error("Please enter your name.")
                else:
                    st.session_state.exam_submitted = True
                    score = sum(1 for i, item in enumerate(quiz) if item['answer'].strip().upper() in ans[i].upper())
                    save_student_score(name, score, len(quiz))
                    
                    # Generate report for download
                    report = f"BODHA AI RESULT\nStudent: {name}\nScore: {score}/{len(quiz)}\n"
                    st.session_state.last_report = report
                    st.rerun()

        # Update Timer
        rem = max(0, 1800 - (time.time() - st.session_state.start_time))
        timer_box.markdown(f'<div class="timer-container"><span class="timer-text">⏳ {int(rem//60):02d}:{int(rem%60):02d}</span></div>', unsafe_allow_html=True)

if st.session_state.get('exam_submitted') and st.session_state.role == "Student":
    # Result display and download button outside the form
    st.metric("Your Score", st.session_state.get('last_score', 'Processed'))
    st.download_button("📊 Download Report", st.session_state.get('last_report', ''), file_name="result.txt")
