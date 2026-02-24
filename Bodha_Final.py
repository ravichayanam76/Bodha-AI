import streamlit as st
import pdfplumber
import google.generativeai as genai
import tempfile
import re
import os
from pathlib import Path
import base64

# 🔐 Gemini API key
genai.configure(api_key=st.secrets["gemini_api_key"])

# 📘 Streamlit Config
st.set_page_config(page_title="BodhaAI - Smart Exam", layout="centered")

# --- UI STYLING ---
def set_background(image_file):
    try:
        # Assuming the image is in the same directory
        encoded = base64.b64encode(open(image_file, "rb").read()).decode()
        css = f"""
        <style>
        .stApp {{ background-image: url("data:image/png;base64,{encoded}"); background-size: cover; }}
        .stMarkdown, p, label {{ color: #FFFFFF !important; }}
        /* --- CHANGE STARTS HERE: SIDEBAR BLACK TEXT --- */
        [data-testid="stSidebar"] .stMarkdown, 
        [data-testid="stSidebar"] p, 
        [data-testid="stSidebar"] label,
        [data-testid="stSidebar"] .stRadio div {{
            color: #000000 !important;
        }}
        /* --- CHANGE ENDS HERE --- */
        .stButton>button {{ width: 100%; background: linear-gradient(90deg, #1E3A8A 0%, #3B82F6 100%); color: white; }}
        div[data-testid="stForm"] {{ background: rgba(0,0,0,0.6); padding: 20px; border-radius: 15px; }}
        </style>
        """
        st.markdown(css, unsafe_allow_html=True)
    except: pass

set_background("BodhaImage.png")

# --- SESSION STATE ---
if 'quiz_data' not in st.session_state: st.session_state.quiz_data = []
if 'chapters' not in st.session_state: st.session_state.chapters = {}
if 'full_text' not in st.session_state: st.session_state.full_text = ""
if 'role' not in st.session_state: st.session_state.role = "Examiner"

# --- UTILS ---
def clean_text(text):
    text = re.sub(r'\n+', '\n', text)
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

    if not matches:
        chapter_map["Full Content"] = full_text
    else:
        for i in range(len(matches)):
            start = matches[i].start()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(full_text)
            chapter_map[matches[i].group(1)] = full_text[start:end].strip()
    return chapter_map, full_text

def parse_generated_questions(raw_text, q_type):
    questions = []
    blocks = re.split(r'Q\d*[:.]\s*', raw_text)
    for block in blocks:
        if not block.strip(): continue
        lines = [l.strip() for l in block.split('\n') if l.strip()]
        q_text = lines[0]
        options = [l for l in lines if re.match(r'^[A-D][\)\.]', l) or l in ["True", "False"]]
        answer_line = [l for l in lines if any(x in l for x in ["Answer:", "Correct:"])]
        
        if q_text and answer_line:
            correct_ans = answer_line[0].split(":")[-1].strip()
            if q_type == "MCQ":
                match = re.search(r'[A-D]', correct_ans)
                correct_ans = match.group() if match else correct_ans
            questions.append({"question": q_text, "options": options, "answer": correct_ans})
    return questions

def generate_questions(text, difficulty, num, q_type):
    model = genai.GenerativeModel("gemini-2.5-flash") # Updated to 1.5
    prompt = f"Generate {num} {difficulty} level {q_type} questions. Format: Q: [Question] \n Options (A,B,C,D or True/False) \n Answer: [Correct Letter/Word]. Text: {text[:4000]}"
    try:
        response = model.generate_content(prompt)
        return response.text
    except Exception as e: return f"ERROR: {str(e)}"

# --- UI LAYOUT ---
st.markdown("<h1 style='text-align: center;'>BodhaAI Exam Portal</h1>", unsafe_allow_html=True)

# Role Switcher in Sidebar
st.sidebar.title("Navigation")
st.session_state.role = st.sidebar.radio("Select Role:", ["Examiner", "Student"])

# --- EXAMINER VIEW ---
if st.session_state.role == "Examiner":
    st.subheader("🛠️ Examiner Dashboard")
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
            chapters, full_text = extract_chapters_from_pdf(tmp.name)
            st.session_state.chapters = chapters
            st.session_state.full_text = full_text
        
        raw_output = generate_questions(full_text, diff, num_q, q_type)
        if "ERROR" not in raw_output:
            st.session_state.quiz_data = parse_generated_questions(raw_output, q_type)
            st.success("✅ Exam generated! Switch to Student mode to begin.")
        else:
            st.error(raw_output)

# --- STUDENT VIEW ---
elif st.session_state.role == "Student":
    st.subheader("✍️ Student Examination")
    
    if not st.session_state.quiz_data:
        st.info("No exam is currently available. Please wait for the examiner to upload.")
    else:
        with st.form("exam_form"):
            user_responses = {}
            for i, item in enumerate(st.session_state.quiz_data):
                st.markdown(f"**Q{i+1}: {item['question']}**")
                user_responses[i] = st.radio(f"Select answer for Q{i+1}", item['options'], key=f"sq{i}")
                st.write("---")
            
            submitted = st.form_submit_button("Submit Final Answers")
            
            if submitted:
                score = 0
                for i, item in enumerate(st.session_state.quiz_data):
                    # Check if answer letter is in the selected option
                    if item['answer'] in user_responses[i]:
                        score += 1
                
                percent = (score / len(st.session_state.quiz_data)) * 100
                st.metric("Your Result", f"{percent}%", f"{score}/{len(st.session_state.quiz_data)}")
                
                if percent >= 70:
                    st.balloons()
                    st.success("Congratulations! You passed.")
                else:
                    st.warning("Keep studying and try again!")
