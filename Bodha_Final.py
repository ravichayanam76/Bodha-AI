import streamlit as st
import pdfplumber
import google.generativeai as genai
import tempfile
import re
import os
import json
import base64
from pathlib import Path
from dotenv import load_dotenv

# 1. Load local .env file (for local development only)
load_dotenv()
# --- CONFIG & API ---
# 2. Fetch the API Key
# This looks for 'GEMINI_API_KEY' in your OS or GitHub Secrets
api_key = st.secrets.get("GEMINI_API_KEY") or os.getenv("GEMINI_API_KEY")

if not api_key:
    st.error("Missing Gemini API Key. Please configure it in your Secrets or .env file.")
    st.stop()

genai.configure(api_key=api_key)

st.set_page_config(page_title="BodhaAI - Smart Exam", layout="centered")

# File path for shared database
DB_FILE = "global_quiz_data.json"

# --- SHARED DATA PERSISTENCE ---
def save_quiz_to_disk(data):
    with open(DB_FILE, "w") as f:
        json.dump(data, f)

def load_quiz_from_disk():
    if os.path.exists(DB_FILE):
        with open(DB_FILE, "r") as f:
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

# --- SESSION STATE (Local to User) ---
if 'role' not in st.session_state: st.session_state.role = "Student"
if 'is_authenticated' not in st.session_state: st.session_state.is_authenticated = False

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
    # Improved regex to split questions more reliably
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
    # FIXED: Using gemini-1.5-flash (2.5 does not exist yet)
    model = genai.GenerativeModel("gemini-2.5-flash") 
    prompt = f"""Generate {num} {difficulty} level {q_type} questions based on the text below.
    Format exactly like this:
    Q: [Question Text]
    A) Option 1
    B) Option 2
    C) Option 3
    D) Option 4
    Answer: [Correct Letter]
    
    Text: {text[:8000]}"""
    
    try:
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        if "429" in str(e) or "quota" in str(e).lower(): return "ERROR_429"
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
            
            raw_output = generate_questions(full_text, diff, num_q, q_type)
            
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
            
import time  # Ensure this is at the very top of your file

# --- STUDENT VIEW ---
elif st.session_state.role == "Student":
    st.subheader("✍️ Student Examination")
    
    current_quiz = load_quiz_from_disk()
    
    if not current_quiz:
        st.info("No exam is currently available.")
    else:
        # --- TIMER CONFIGURATION ---
        exam_duration_min = 30  # Set exam duration here
        if 'start_time' not in st.session_state:
            st.session_state.start_time = time.time()
        
        # Create a placeholder for the timer
        timer_placeholder = st.empty()
        
        # Calculate time remaining
        elapsed_time = time.time() - st.session_state.start_time
        remaining_time = max(0, (exam_duration_min * 60) - elapsed_time)

        # Display Timer
        mins, secs = divmod(int(remaining_time), 60)
        timer_placeholder.markdown(
            f'<div class="timer-container"><span class="timer-text">⏳ Time Remaining: {mins:02d}:{secs:02d}</span></div>', 
            unsafe_allow_html=True
        )

        if remaining_time <= 0:
            st.error("⚠️ Time is up! Please submit your answers immediately.")

        # --- EXAM FORM ---
        with st.form("exam_form"):
            user_responses = {}
            for i, item in enumerate(current_quiz):
                st.markdown(f"**Q{i+1}: {item['question']}**")
                user_responses[i] = st.radio(f"Select answer", item['options'], key=f"sq{i}", label_visibility="collapsed")
                st.write("---")
            
            submitted = st.form_submit_button("Submit Final Answers")
        
        if submitted:
            # Clear start_time so it resets for the next exam
            del st.session_state.start_time 
            
            score = 0
            result_report = "BODHA AI - PERFORMANCE REPORT\n" + "="*40 + "\n\n"
            
            for i, item in enumerate(current_quiz):
                u_ans = user_responses[i]
                is_correct = item['answer'].strip().upper() in u_ans.upper()
                if is_correct: score += 1
                
                status = "✅ CORRECT" if is_correct else "❌ INCORRECT"
                result_report += f"Q{i+1}: {item['question']}\nYour Answer: {u_ans}\nStatus: {status}\n"
                result_report += "-"*20 + "\n"
            
            percent = (score / len(current_quiz)) * 100
            st.metric("Your Result", f"{percent:.1f}%", f"{score}/{len(current_quiz)}")
            
            if percent >= 70:
                st.balloons()
                st.success("Congratulations!")
            
            # Re-display the download button outside the form
            st.download_button(
                label="📊 Download My Result Report (TXT)",
                data=result_report + f"\nScore: {score}/{len(current_quiz)}",
                file_name="my_results.txt"
            )
