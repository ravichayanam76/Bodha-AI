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
            try: return json.load(f)
            except: return []
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
            background-repeat: no-repeat;
            background-position: center center;
            background-attachment: fixed;
        }}

        section.main > div {{
            background-color: rgba(255, 255, 255, 0.85); /* Slight white overlay for readability */
            padding: 2rem !important;
            border-radius: 15px !important;
        }}

        /* FIX 1: Navigation and Radio Button text to Black */
        [data-testid="stSidebar"] .stMarkdown p, 
        [data-testid="stSidebar"] label, 
        [data-testid="stSidebar"] div[data-testid="stWidgetLabel"] p,
        [data-testid="stWidgetLabel"] p {{
            color: #000000 !important;
        }}

        /* 1. FORCE SIDEBAR TEXT TO BLACK */
        /* Targets 'Select Role', 'Student', and 'Examiner' */
        [data-testid="stSidebar"] {{
            color: #000000 !important;
        }}
        
        [data-testid="stSidebar"] .stMarkdown p, 
        [data-testid="stSidebar"] label, 
        [data-testid="stSidebar"] span,
        [data-testid="stSidebar"] div[data-testid="stWidgetLabel"] p {{
            color: #000000 !important;
            -webkit-text-fill-color: #000000 !important;
        }}

        /* 2. FORCE SUBMIT BUTTON TEXT TO BLACK */
        /* Targets the text inside the button */
        .stButton button div p, 
        .stButton button {{
            color: #000000 !important;
            -webkit-text-fill-color: #000000 !important;
        }}

        /* 2. ALL TEXT: Force global text, labels, and markdown to White */
        .stMarkdown, p, label, .stText, [data-testid="stMarkdownContainer"] p {{
            color: #FFFFFF !important;
        }}

        .stButton>button {{
            width: 100%;
            background: linear-gradient(90deg, #1E3A8A 0%, #3B82F6 100%);
            color: white !important;
            font-weight: bold;
        }}

/* Timer Styling */
.timer-container {
    background-color: #f0f2f6;
    padding: 10px;
    border-radius: 10px;
    border-left: 5px solid #1E3A8A;
    text-align: center;
    margin-bottom: 20px;
}
.timer-text {
    font-size: 24px;
    font-weight: bold;
    color: #1E3A8A;
}
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
    # Split by double newline or Q: indicators
    blocks = re.split(r'\n(?=Q[:\d\.\s]+)', raw_text)
    
    for block in blocks:
        if "Answer:" not in block and "CORRECT:" not in block.upper():
            continue
        
        lines = [l.strip() for l in block.split('\n') if l.strip()]
        if len(lines) < 2: continue
        
        # Robustly find Question, Options, and Answer
        q_text = ""
        opts = []
        ans = ""
        
        for line in lines:
            if re.match(r'^Q[:\d\.\s]+', line):
                q_text = re.sub(r'^Q[:\d\.\s]+', '', line).strip()
            elif re.match(r'^[A-D][\)\.\s]', line):
                opts.append(line)
            elif "Answer:" in line or "CORRECT:" in line.upper():
                ans = line.split(":")[-1].strip()
        
        # Fallback for True/False if no options found
        if not opts and q_type == "True/False":
            opts = ["True", "False"]
        
        if q_text and ans:
            questions.append({"question": q_text, "options": opts, "answer": ans})
            
    return questions

@st.cache_data(show_spinner="AI is generating questions...")
def generate_questions(text, difficulty, num, q_type):
    if not text.strip(): return "ERROR: PDF is empty."
    model = genai.GenerativeModel("gemini-2.5-flash") 
    
    prompt = f"""Generate {num} {difficulty} level {q_type} questions based on this text.
    STRICT FORMAT:
    Q: [Question text]
    A) [Option]
    B) [Option]
    C) [Option]
    D) [Option]
    Answer: [Correct Letter Only]
    
    TEXT: {text[:10000]}"""
    
    try:
        response = model.generate_content(prompt)
        return response.text if response.text else "ERROR"
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
        pwd_input = st.text_input("Enter Password:", type="password")
        if st.button("Login"):
            if pwd_input == "admin123":
                st.session_state.is_authenticated = True
                st.rerun()
            else:
                st.error("Incorrect password!")
    else:
        st.subheader("🛠️ Examiner Dashboard")
        
        if st.sidebar.button("🔄 Clear Current Exam"):
            if os.path.exists(DB_FILE): os.remove(DB_FILE)
            st.cache_data.clear()
            st.success("Exam deleted from server.")
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
            
            raw_ai_output = generate_questions(txt, "Medium", num_q, q_type)
            
            # For debugging (Optional: remove in production)
            # st.text_area("Raw AI Response", raw_ai_output) 
            
            data = parse_generated_questions(raw_ai_output, q_type)
            if data:
                save_quiz_to_disk(data)
                st.success(f"✅ Exam Published with {len(data)} questions!")
            else: 
                st.error("Failed to parse AI output. AI output didn't follow the Q/A format.")

        st.write("---")
        st.subheader("📊 Student Submissions")
        res = load_all_results()
        if res: st.table(res)
        else: st.info("No submissions yet.")
            
            if raw_output == "ERROR_429":
                st.error("⚠️ Quota Exceeded. Please wait 60 seconds.")
            elif "ERROR" in raw_output:
                st.error(raw_output)
            else:
                quiz_data = parse_generated_questions(raw_output, q_type)
                if quiz_data:
                    save_quiz_to_disk(quiz_data) # SAVE TO PERSISTENT STORAGE
                    st.success(f"✅ Exam with {len(quiz_data)} questions published globally!")
                else:
                    st.error("AI generated content but failed to parse. Try again.")

# --- NEW: DOWNLOAD SECTION ---
        current_quiz = load_quiz_from_disk()
        if current_quiz:
            st.write("---")
            st.write("### 📥 Manage Current Exam")
            
            # Format quiz data into a readable string for the download file
            report_text = "BODHA AI - EXAM QUESTIONS & ANSWERS\n" + "="*40 + "\n\n"
            for i, item in enumerate(current_quiz):
                report_text += f"Q{i+1}: {item['question']}\n"
                for opt in item['options']:
                    report_text += f"   {opt}\n"
                report_text += f"CORRECT ANSWER: {item['answer']}\n"
                report_text += "-"*20 + "\n"
            
            st.download_button(
                label="Download Questions & Answers (TXT)",
                data=report_text,
                file_name="quiz_answer_key.txt",
                mime="text/plain"
            )

# --- STUDENT VIEW ---
elif st.session_state.role == "Student":
    st.subheader("✍️ Student Examination")
    quiz = load_quiz_from_disk()
    
    if not quiz: st.info("No exam available.")
    elif st.session_state.exam_submitted:
        st.success("✅ Exam submitted. You have already completed this session.")
    else:
        name = st.text_input("Full Name:", placeholder="Required to submit")
        if 'start_time' not in st.session_state: st.session_state.start_time = time.time()
        
        timer_box = st.empty()
        with st.form("exam_form"):
            user_ans = {}
            for i, item in enumerate(quiz):
                st.write(f"**Q{i+1}: {item['question']}**")
                user_ans[i] = st.radio("Select:", item['options'], key=f"q{i}", label_visibility="collapsed")
            
            sub_btn = st.form_submit_button("Submit Final Answers")
            if sub_btn:
                if not name:
                    st.error("Enter your name first!")
                else:
                    st.session_state.exam_submitted = True
                    score = 0
                    report = f"BODHA AI RESULT\nStudent: {name}\n" + "="*20 + "\n"
                    for i, item in enumerate(quiz):
                        is_correct = item['answer'].strip().upper() in user_ans[i].upper()
                        if is_correct: score += 1
                        status = "✅" if is_correct else "❌"
                        report += f"Q{i+1}: {status}\n"
                    
                    final_score_str = f"{score}/{len(quiz)}"
                    save_student_score(name, score, len(quiz))
                    st.session_state.last_score = final_score_str
                    st.session_state.last_report = report
                    st.rerun()

        # Update Timer
        rem = max(0, 1800 - (time.time() - st.session_state.start_time))
        timer_box.markdown(f'<div class="timer-container"><span class="timer-text">⏳ {int(rem//60):02d}:{int(rem%60):02d}</span></div>', unsafe_allow_html=True)

if st.session_state.get('exam_submitted') and st.session_state.role == "Student":
    st.metric("Final Score", st.session_state.get('last_score'))
    st.download_button("📊 Download Report", st.session_state.get('last_report'), file_name="result.txt")
