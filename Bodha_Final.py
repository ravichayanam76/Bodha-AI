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
from fpdf import FPDF
import io

# --- CONFIG & PERSISTENCE ---
load_dotenv()
api_key = st.secrets.get("GEMINI_API_KEY") or os.getenv("GEMINI_API_KEY")

if not api_key:
    st.error("Missing Gemini API Key. Please configure it in your Secrets or .env file.")
    st.stop()

genai.configure(api_key=api_key)

st.set_page_config(page_title="ABAP on HANA Assessment - Smart Exam", layout="centered")

DB_FILE = "global_quiz_data.json"
RESULTS_FILE = "student_submissions.json"

def save_quiz_to_disk(data):
    with open(DB_FILE, "w") as f:
        json.dump(data, f)

def _quiz_from_disk():
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
# --- ADD THIS HELPER FUNCTION BELOW load_all_results() ---
def create_pdf_report(results_data):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", "B", 16)
    pdf.cell(190, 10, "Student Assessment Submissions", ln=True, align="C")
    pdf.ln(10)

# Table Header
    pdf.set_font("Arial", "B", 10)
    pdf.set_fill_color(200, 220, 255)
    pdf.cell(50, 10, "Student Name", 1, 0, 'C', True)
    pdf.cell(30, 10, "Score", 1, 0, 'C', True)
    pdf.cell(30, 10, "Percentage", 1, 0, 'C', True)
    pdf.cell(80, 10, "Timestamp", 1, 1, 'C', True)
    
    # Table Body
    pdf.set_font("Arial", "", 10)
    for res in results_data:
        pdf.cell(50, 10, str(res["Student Name"]), 1)
        pdf.cell(30, 10, str(res["Score"]), 1, 0, 'C')
        pdf.cell(30, 10, str(res["Percentage"]), 1, 0, 'C')
        pdf.cell(80, 10, str(res["Timestamp"]), 1, 1, 'C')
    
    # Return as bytes
    return pdf.output(dest='S').encode('latin-1')
    
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
    # Improved regex to catch Q:, 1., Question: etc.
    blocks = re.split(r'\n(?=(?:Q|Question|\d+)\s*[:\).])', raw_text)
    
    for block in blocks:
        # Check if block contains an answer indicator
        if not re.search(r'(Answer|CORRECT):', block, re.IGNORECASE):
            continue
        
        lines = [l.strip() for l in block.split('\n') if l.strip()]
        if len(lines) < 2: continue
        
        q_text = ""
        opts = []
        ans = ""
        
        for line in lines:
            # Match Question
            if re.match(r'^(?:Q|Question|\d+)\s*[:\).]', line, re.IGNORECASE):
                q_text = re.sub(r'^(?:Q|Question|\d+)\s*[:\).]', '', line).strip()
            # Match Options A) B) C) D) or A. B. C. D.
            elif re.match(r'^[A-D][\)\.\s]', line, re.IGNORECASE):
                opts.append(line)
            # Match Answer
            elif re.search(r'(Answer|CORRECT):', line, re.IGNORECASE):
                ans = line.split(":")[-1].strip().upper()
        
        if not opts and q_type == "True/False":
            opts = ["True", "False"]
        
        # Validation: Only add if we have a question and at least 2 options (or T/F)
        if q_text and (len(opts) >= 2):
            questions.append({"question": q_text, "options": opts, "answer": ans})
            
    return questions

@st.cache_data(show_spinner="AI is generating questions...")
def generate_questions(text, difficulty, num, q_type):
    if not text.strip(): return "ERROR: PDF is empty."
    
    # Use the stable model name
    model = genai.GenerativeModel("gemini-2.5-flash") 
    
    # Updated prompt to enforce the number of questions strictly
    prompt = f"""You are an expert examiner. Generate EXACTLY {num} {difficulty} level {q_type} questions based on the text below.
    
    STRICT RULES:
    1. You must output exactly {num} questions.
    2. Use this format for every single question:
       Q: [Question text]
       A) [Option]
       B) [Option]
       C) [Option]
       D) [Option]
       Answer: [Correct Letter Only]

    TEXT:
    {text[:15000]}""" # Increased text limit slightly
    
    try:
        response = model.generate_content(prompt)
        if response.text:
            return response.text
        else:
            return "ERROR: AI returned empty response."
    except Exception as e:
        return f"ERROR: {str(e)}"
# --- UI LAYOUT ---
st.markdown("<h1 style='text-align: center; color: #1E3A8A;'>ABAP on HANA Assessment</h1>", unsafe_allow_html=True)
st.sidebar.title("Navigation")
st.session_state.role = st.sidebar.radio("Select Role:", ["Student", "Examiner"])

# --- EXAMINER VIEW ---
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
        
        # CLEAR SYSTEM BUTTON
        if st.sidebar.button("🔄 Clear All Data"):
            for f in [DB_FILE, RESULTS_FILE]:
                if os.path.exists(f): os.remove(f)
            st.cache_data.clear()
            st.success("System reset successfully.")
            st.rerun()

        # New Radio Button for Generation Mode
        gen_mode = st.radio("Generation Mode", ["Generate Questions", "Generate Question as Is"], horizontal=True)

        uploaded_file = st.file_uploader("Upload Exam PDF", type=["pdf"])
        col1, col2 = st.columns(2)
        with col1:
            q_type = st.selectbox("Type", ["MCQ", "True/False"])
            diff = st.selectbox("Difficulty", ["Easy", "Medium", "Hard"])
        with col2:
            num_q = st.slider("Number of Questions", 1, 50, 5)

        # --- FIXED GENERATION LOGIC ---
        if uploaded_file and st.button("Publish Exam"):
            with tempfile.NamedTemporaryFile(delete=False) as tmp:
                tmp.write(uploaded_file.read())
                temp_path = tmp.name

            final_quiz = []
            seen_questions = set()  # To prevent duplicates

            if gen_mode == "Generate Question as Is":
                with pdfplumber.open(temp_path) as pdf:
                    # HEADER VALIDATION: Only on the first page
                    first_page_table = pdf.pages[0].extract_table()
                    
                    if first_page_table and "Questions" in str(first_page_table[0]):
                        for page in pdf.pages:
                            table_data = page.extract_table()
                            if not table_data: continue
                            
                            # Skip header only if it appears at the top of the current page
                            start_idx = 0
                            if "Questions" in str(table_data[0]):
                                start_idx = 1
                            
                            for row in table_data[start_idx:]:
                                # Clean data and check for 6 columns + unique question text
                                if len(row) >= 6 and row[0]:
                                    q_text = str(row[0]).strip()
                                    if q_text not in seen_questions:
                                        final_quiz.append({
                                            "question": q_text,
                                            "options": [f"A) {row[1]}", f"B) {row[2]}", f"C) {row[3]}", f"D) {row[4]}"],
                                            "answer": str(row[5]).strip().upper()
                                        })
                                        seen_questions.add(q_text)
                        st.success(f"✅ Extracted {len(final_quiz)} unique questions from PDF.")
                    else:
                        st.error("❌ Header Validation Failed: First page must contain 'Questions' header.")
            
            else:
                # AI Batch Generation Logic
                full_text = extract_chapters_from_pdf(temp_path)
                batch_size = 25
                total_needed = num_q
                progress_bar = st.progress(0)
                
                while len(final_quiz) < total_needed:
                    current_batch = min(batch_size, total_needed - len(final_quiz))
                    raw_output = generate_questions(full_text, diff, current_batch, q_type)
                    
                    if "ERROR" not in raw_output:
                        batch_data = parse_generated_questions(raw_output, q_type)
                        for item in batch_data:
                            if item['question'] not in seen_questions:
                                final_quiz.append(item)
                                seen_questions.add(item['question'])
                        
                        progress_bar.progress(min(len(final_quiz) / total_needed, 1.0))
                    else:
                        break
                    time.sleep(1)

            if final_quiz:
                save_quiz_to_disk(final_quiz[:num_q] if gen_mode == "Generate Questions" else final_quiz)
                st.success("✅ Exam Published!")
                st.rerun()
        # --- DOWNLOAD & RESULTS SECTION ---
        # This part runs regardless of whether you just clicked generate
        current_quiz = load_quiz_from_disk()
        if current_quiz:
            st.write("---")
            st.write("### 📥 Manage Current Exam")
            
            report_text = "ABAP Assessment AI - EXAM KEY\n" + "="*20 + "\n"
            for i, item in enumerate(current_quiz):
                report_text += f"Q{i+1}: {item['question']}\nAns: {item['answer']}\n\n"
            
            st.download_button(
                label="Download Answer Key (TXT)",
                data=report_text,
                file_name="quiz_key.txt"
            )

        st.write("---")
        st.subheader("📊 Student Submissions")
        all_results = load_all_results()
        if all_results:
            st.table(all_results)
            
            # PDF Download Logic
            pdf_bytes = create_pdf_report(all_results)
            st.download_button(
                label="📄 Download Results as PDF",
                data=pdf_bytes,
                file_name="student_results.pdf",
                mime="application/pdf"
            )
        else:
            st.info("No students have submitted yet.")
# --- STUDENT VIEW ---
# --- STUDENT VIEW ---
elif st.session_state.role == "Student":
    st.subheader("✍️ Student Examination")
    quiz = load_quiz_from_disk()
    
    if not quiz:
        st.info("No exam available.")
    
    # CASE 1: Exam already submitted (CHECK INDENTATION HERE)
    elif st.session_state.get('exam_submitted'):
        st.success("✅ Exam submitted successfully!")
        
        if 'last_score' in st.session_state:
            col1, col2 = st.columns(2)
            with col1:
                st.metric("Total Score", st.session_state.last_score)
            with col2:
                # Color coded Pass/Fail
                color = "#28a745" if st.session_state.last_status == "PASS" else "#dc3545"
                st.markdown(f"### Status: <span style='color:{color};'>{st.session_state.last_status}</span>", unsafe_allow_html=True)
            
            st.write(f"**Overall Performance: {st.session_state.last_pct:.1f}%**")
            st.progress(st.session_state.last_pct / 100)

            st.download_button(
                label="📊 Download Detailed Report", 
                data=st.session_state.get('last_report', ''), 
                file_name="result.txt",
                key="student_download_final" 
            )
            
    # CASE 2: Taking the exam (CHECK INDENTATION HERE)
    else:
        name = st.text_input("Full Name:", placeholder="Required to submit")
        
        # Timer Logic
        if 'start_time' not in st.session_state: 
            st.session_state.start_time = time.time()
        
        timer_box = st.empty()
        rem = max(0, 1800 - (time.time() - st.session_state.start_time))
        timer_box.markdown(f'<div class="timer-container"><span class="timer-text">⏳ {int(rem//60):02d}:{int(rem%60):02d}</span></div>', unsafe_allow_html=True)

        with st.form("exam_form"):
            user_ans = {}
            for i, item in enumerate(quiz):
                st.write(f"**Q{i+1}: {item['question']}**")
                # RADIO FIX: index=None removes default selection
                user_ans[i] = st.radio(
                    "Select:", 
                    item['options'], 
                    key=f"q{i}_{name.replace(' ', '_')}", 
                    index=None, 
                    label_visibility="collapsed"
                )
            
            sub_btn = st.form_submit_button("Submit Final Answers")
            
            if sub_btn:
                if not name:
                    st.error("Enter your name first!")
                elif None in user_ans.values():
                    st.error("Please answer all questions before submitting.")
                else:
                    score = 0
                    # HEADER FOR REPORT
                    report = f"ABAP Assessment RESULT\nStudent: {name}\n"
                    report += f"Date: {time.strftime('%Y-%m-%d %H:%M:%S')}\n"
                    report += "="*30 + "\n\n"
                    
                    for i, item in enumerate(quiz):
                        correct_letter = item['answer'].strip().upper()
                        selected_option = user_ans[i]
                        
                        # Check correctness
                        if selected_option and selected_option.strip().upper().startswith(correct_letter):
                            score += 1
                            status = "CORRECT ✅"
                        else:
                            status = "INCORRECT ❌"
                        
                        # --- ADDING DETAIL TO REPORT ---
                        report += f"Question {i+1}: {item['question']}\n"
                        report += f"Your Selection: {selected_option}\n"
                        report += f"Correct Answer: {item['answer']}\n"
                        report += f"Result: {status}\n"
                        report += "-"*20 + "\n"
                    
                    # --- CALCULATE TOTALS ---
                    pct = (score / len(quiz)) * 100
                    status_text = "PASS" if pct >= 70 else "FAIL"
                    
                    # Update Session State
                    st.session_state.exam_submitted = True
                    st.session_state.last_score = f"{score}/{len(quiz)}"
                    st.session_state.last_pct = pct
                    st.session_state.last_status = status_text
                    
                    # Finalize Report Text
                    report += f"\nSUMMARY\n"
                    report += f"Total Score: {score}/{len(quiz)}\n"
                    report += f"Percentage: {pct:.1f}%\n"
                    report += f"Status: {status_text}\n"
                    st.session_state.last_report = report
                    
                    save_student_score(name, score, len(quiz))
                    st.rerun()
        st.download_button(
            label="📊 Download Detailed Report", 
            data=st.session_state.get('last_report', ''), 
            file_name="result.txt",
            key="student_download_final" 
        )
        # st.session_state.last_score = final_score_str
        # st.session_state.last_report = report
        # st.rerun()
        # Update Timer
        rem = max(0, 2400 - (time.time() - st.session_state.start_time))
        timer_box.markdown(f'<div class="timer-container"><span class="timer-text">⏳ {int(rem//60):02d}:{int(rem%60):02d}</span></div>', unsafe_allow_html=True)

# if st.session_state.get('exam_submitted') and st.session_state.role == "Student":
   # st.metric("Final Score", st.session_state.get('last_score'))
  #  st.download_button("📊 Download Report", st.session_state.get('last_report'), file_name="result.txt")
