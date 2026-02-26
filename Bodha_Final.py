import streamlit as st
import pdfplumber
import google.generativeai as genai
import tempfile
import re
import os
import json
import base64
import time  # Ensure this is at the very top of your file
from pathlib import Path
from dotenv import load_dotenv

# 1. Load local .env file (for local development only)
load_dotenv()
# --- CONFIG & API ---
api_key = st.secrets.get("GEMINI_API_KEY") or os.getenv("GEMINI_API_KEY")

if not api_key:
    st.error("Missing Gemini API Key. Please configure it in your Secrets or .env file.")
    st.stop()

genai.configure(api_key=api_key)

st.set_page_config(page_title="BodhaAI - Smart Exam", layout="centered")

# File paths for shared database
DB_FILE = "global_quiz_data.json"
RESULTS_FILE = "student_submissions.json"

# --- SHARED DATA PERSISTENCE ---
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
            return json.load(f)
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
            background-repeat: no-repeat;
            background-position: center center;
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
        [data-testid="stSidebar"] {{ color: #000000 !important; }}
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
    blocks = re.split(r'Q\d*[:.]\s*', raw_text)
    for block in blocks:
        if not block.strip(): continue
        lines = [l.strip() for l in block.split('\n') if l.strip()]
        if len(lines) < 2: continue
        q_text = lines[0]
        options = [l for l in lines if re.match(r'^[A-D][\)\.]', l) or l in ["True", "False"]]
        answer_line = [l for l in lines if any(x in l.lower() for x in ["answer:", "correct:"])]
        if q_text and answer_line:
            correct_ans = answer_line[0].split(":")[-1].strip()
            if q_type == "MCQ":
                match = re.search(r'[A-D]', correct_ans.upper())
                correct_ans = match.group() if match else correct_ans
            questions.append({"question": q_text, "options": options, "answer": correct_ans})
    return questions

@st.cache_data(show_spinner="AI is generating questions...")
def generate_questions(text, difficulty, num, q_type):
    model = genai.GenerativeModel("gemini-1.5-flash") # Use stable model
    prompt = f"Generate {num} {difficulty} level {q_type} questions...\nText: {text[:8000]}"
    try:
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        return f"ERROR: {str(e)}"

# --- UI LAYOUT ---
st.markdown("<h1 style='text-align: center; color: #1E3A8A;'>BodhaAI Exam Portal</h1>", unsafe_allow_html=True)

st.sidebar.title("Navigation")
new_role = st.sidebar.radio("Select Role:", ["Student", "Examiner"])
st.session_state.role = new_role

# --- EXAMINER VIEW ---
if st.session_state.role == "Examiner":
    if not st.session_state.is_authenticated:
        st.subheader("🔒 Examiner Login")
        pwd_input = st.text_input("Enter Password:", type="password")
        if st.button("Login"):
            if pwd_input == "admin123":
                st.session_state.is_authenticated = True
                st.rerun()
            else: st.error("Incorrect password!")
    else:
        st.subheader("🛠️ Examiner Dashboard")
        
        if st.sidebar.button("🔄 Clear All Data"):
            if os.path.exists(DB_FILE): os.remove(DB_FILE)
            if os.path.exists(RESULTS_FILE): os.remove(RESULTS_FILE)
            st.cache_data.clear()
            st.rerun()

        uploaded_file = st.file_uploader("Upload Exam PDF", type=["pdf"])
        col1, col2 = st.columns(2)
        with col1:
            q_type = st.selectbox("Type", ["MCQ", "True/False"])
            diff = st.selectbox("Difficulty", ["Easy", "Medium", "Hard"])
        with col2:
            num_q = st.slider("Number of Questions", 1, 50, 5)

        if uploaded_file and st.button("Generate & Publish Exam"):
            with tempfile.NamedTemporaryFile(delete=False) as tmp:
                tmp.write(uploaded_file.read())
                full_text = extract_chapters_from_pdf(tmp.name)
            raw_output = generate_questions(full_text, diff, num_q, q_type)
            quiz_data = parse_generated_questions(raw_output, q_type)
            if quiz_data:
                save_quiz_to_disk(quiz_data)
                st.success("✅ Exam published!")

        # TRACKER FEATURE
        st.write("---")
        st.subheader("📊 Student Submission Tracker")
        results = load_all_results()
        if results:
            st.table(results)
        else: st.info("No submissions yet.")

# --- STUDENT VIEW ---
elif st.session_state.role == "Student":
    st.subheader("✍️ Student Examination")
    current_quiz = load_quiz_from_disk()
    
    if not current_quiz:
        st.info("No exam is currently available.")
    elif st.session_state.exam_submitted:
        st.success("✅ Your exam has been submitted. Multiple attempts are not allowed.")
    else:
        # Require name for tracking
        student_name = st.text_input("Enter Your Full Name to start:", placeholder="John Doe")
        
        exam_duration_min = 30 
        if 'start_time' not in st.session_state: st.session_state.start_time = time.time()
        timer_placeholder = st.empty()

        with st.form("exam_form"):
            user_responses = {}
            for i, item in enumerate(current_quiz):
                st.markdown(f"**Q{i+1}: {item['question']}**")
                user_responses[i] = st.radio(f"Select answer", item['options'], key=f"sq{i}", label_visibility="collapsed")
                st.write("---")
            submitted = st.form_submit_button("Submit Final Answers")

        if not submitted:
            rem = max(0, (exam_duration_min * 60) - (time.time() - st.session_state.start_time))
            m, s = divmod(int(rem), 60)
            timer_placeholder.markdown(f'<div class="timer-container"><span class="timer-text">⏳ Time Remaining: {m:02d}:{s:02d}</span></div>', unsafe_allow_html=True)
        
        if submitted:
            if not student_name:
                st.error("Please enter your name before submitting.")
            else:
                st.session_state.exam_submitted = True
                timer_placeholder.empty()
                score = 0
                for i, item in enumerate(current_quiz):
                    if item['answer'].strip().upper() in user_responses[i].upper(): score += 1
                
                save_student_score(student_name, score, len(current_quiz))
                st.metric("Final Score", f"{(score/len(current_quiz))*100:.1f}%", f"{score}/{len(current_quiz)}")
                st.rerun()
