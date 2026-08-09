import os
import re
import sys
import tempfile
import urllib.parse
import requests
from fastapi import FastAPI, Form, Request, HTTPException
from fastapi.responses import HTMLResponse, FileResponse

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

try:
    from course_outline_skill.scripts.generate_course_outline import generate_doc
except ImportError:
    from scripts.generate_course_outline import generate_doc

app = FastAPI(title="B Tools Course Outline Formatter", version="1.0.0")

INDEX_HTML_PATH = os.path.join(os.path.dirname(__file__), "templates", "index.html")

def get_template_docx_path():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        os.path.abspath(os.path.join(script_dir, "..", "course_outline_skill", "templates", "template.docx")),
        os.path.abspath(os.path.join(script_dir, "course_outline_skill", "templates", "template.docx")),
        os.path.abspath(os.path.join(script_dir, "templates", "template.docx")),
        os.path.abspath(os.path.join(script_dir, "..", "00_Reference_Template", "B Tools_หลักสูตร Data Analysis for Better Results.docx"))
    ]
    for path in candidates:
        if os.path.exists(path):
            return path
    return None

def extract_doc_id(url: str) -> str:
    match = re.search(r'/d/([a-zA-Z0-9_-]+)', url)
    if match:
        return match.group(1)
    raise ValueError("ไม่พบ ID ของ Google Doc ในลิงก์ที่ระบุ กรุณาตรวจสอบลิงก์อีกครั้ง")

def fetch_doc_text(doc_id: str) -> str:
    export_url = f"https://docs.google.com/document/d/{doc_id}/export?format=txt"
    resp = requests.get(export_url, timeout=15, allow_redirects=True)
    if resp.status_code != 200:
        raise ValueError(f"ไม่สามารถเข้าถึง Google Doc ได้ (HTTP Status {resp.status_code}) กรุณาตรวจสอบว่าเปิดสิทธิ์การเข้าถึงเป็น 'ทุกคนที่มีลิงก์' (Anyone with the link)")
    
    text = resp.text
    if "<html" in text.lower() or "accounts.google.com" in resp.url.lower():
        raise ValueError("Google Doc นี้ยังไม่ได้เปิดสิทธิ์การเข้าถึงเป็น 'ทุกคนที่มีลิงก์' (Anyone with the link) กรุณาเปิดสิทธิ์แชร์ใน Google Doc แล้วลองใหม่อีกครั้ง")
    
    return text

def parse_doc_text_to_json(raw_text: str) -> dict:
    cleaned_text = raw_text.replace('\ufeff', '')
    lines = [line.strip() for line in cleaned_text.splitlines() if line.strip() and not line.strip().startswith('___')]
    
    data = {
        'course_title_th': '',
        'course_title_en': '',
        'sections_order': [],
        'rationale': [],
        'objectives': [],
        'agenda': [],
        'learning_methods': [],
        'expected_outcomes': [],
        'target_audience': [],
        'duration': []
    }
    
    if not lines:
        return data

    title_line = lines[0].replace('หลักสูตร', '').replace(':', '').strip()
    if re.search(r'[a-zA-Z]', title_line) and not re.search(r'[\u0E00-\u0E7F]', title_line):
        data['course_title_en'] = title_line
    else:
        data['course_title_th'] = title_line

    idx = 1
    if len(lines) > 1 and re.search(r'[a-zA-Z]', lines[1]) and not any(k in lines[1] for k in ['หลักการ', 'วัตถุประสงค์', 'วิทยากร']):
        if not data['course_title_en']:
            data['course_title_en'] = lines[1].strip()
            idx = 2

    while idx < len(lines) and (lines[idx].startswith('วิทยากร') or lines[idx].startswith('โดย') or lines[idx].startswith('____')):
        if lines[idx].startswith('วิทยากร') or lines[idx].startswith('โดย'):
            data['instructor'] = lines[idx].replace('วิทยากร :', '').replace('วิทยากร:', '').replace('โดย', '').strip()
        idx += 1

    section_keywords = [
        ('rationale', ['หลักการและเหตุผล', 'หลักการ และเหตุผล', 'Principle']),
        ('objectives', ['วัตถุประสงค์', 'Objective']),
        ('agenda', ['กำหนดการอบรม', 'เนื้อหาของหลักสูตร', 'Course Outline', 'Agenda', 'เวลา']),
        ('learning_methods', ['รูปแบบการเรียนรู้', 'รูปแบบการอบรม', 'Learning Method']),
        ('expected_outcomes', ['ผลลัพธ์ที่คาดหวัง', 'สิ่งที่จะได้รับ', 'Expected Outcome']),
        ('target_audience', ['กลุ่มเป้าหมาย', 'Target Group', 'Target Audience']),
        ('duration', ['ระยะเวลา', 'Course Length', 'Duration'])
    ]

    sec_order = []
    current_sec = None
    
    for line in lines[idx:]:
        matched_sec = None
        matched_title = None
        
        for sec_key, keywords in section_keywords:
            if any(kw in line for kw in keywords):
                matched_sec = sec_key
                matched_title = line
                break
                
        if matched_sec:
            current_sec = matched_sec
            if current_sec not in sec_order:
                sec_order.append(current_sec)
            data[f'{current_sec}_title'] = matched_title
            continue

        if current_sec:
            if current_sec == 'rationale':
                if line.startswith('*') or line.startswith('•') or line.startswith('-'):
                    if data['rationale'] and isinstance(data['rationale'][-1], dict):
                        data['rationale'][-1].setdefault('bullets', []).append(line.lstrip('*•- ').strip())
                    else:
                        data['rationale'].append({'text': '', 'bullets': [line.lstrip('*•- ').strip()]})
                else:
                    data['rationale'].append({'text': line})
                    
            elif current_sec == 'objectives':
                if line.startswith('เมื่อจบ') or line.startswith('หลังจากการอบรม'):
                    data['objectives_subhead'] = line
                else:
                    clean_b = re.sub(r'^[\*•\-\d\.]+\s*', '', line).strip()
                    if clean_b:
                        data['objectives'].append(clean_b)
                        
            elif current_sec == 'agenda':
                time_match = re.search(r'(\d{1,2}\.\d{2}\s*[\–\-]\s*\d{1,2}\.\d{2})', line)
                if time_match:
                    t_str = time_match.group(1).replace('–', '-').strip()
                    if 'น.' not in t_str: t_str += ' น.'
                    data['agenda'].append({'time': t_str, 'module_title': '', 'topics': []})
                else:
                    if not data['agenda']:
                        data['agenda'].append({'module_title': line, 'topics': []})
                    else:
                        last_item = data['agenda'][-1]
                        if line.startswith('Module') or line.startswith('Part') or line.startswith('ส่วนที่') or line.startswith('หัวข้อ'):
                            if not last_item['module_title']:
                                last_item['module_title'] = line
                            else:
                                data['agenda'].append({'module_title': line, 'topics': []})
                        elif line.startswith('Workshop') or line.startswith('กิจกรรม'):
                            last_item['workshop'] = line
                        else:
                            clean_t = line.lstrip('*•- ').strip()
                            if clean_t:
                                last_item.setdefault('topics', []).append(clean_t)

            elif current_sec in ['learning_methods', 'expected_outcomes', 'target_audience', 'duration']:
                clean_item = re.sub(r'^[\*•\-\d\.]+\s*', '', line).strip()
                if clean_item:
                    data[current_sec].append(clean_item)

    data['sections_order'] = sec_order if sec_order else ['rationale', 'objectives', 'agenda']
    return data

@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    return HTMLResponse(content="", status_code=204)

@app.get("/", response_class=HTMLResponse)
def index():
    if os.path.exists(INDEX_HTML_PATH):
        with open(INDEX_HTML_PATH, "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    return HTMLResponse(content="<h1>B Tools Web App</h1><p>UI Template file not found.</p>")

@app.post("/format")
def format_course(doc_url: str = Form(...)):
    try:
        doc_id = extract_doc_id(doc_url)
        raw_text = fetch_doc_text(doc_id)
        data = parse_doc_text_to_json(raw_text)
        
        title = data.get("course_title_en") or data.get("course_title_th") or "Course Outline"
        title_clean = title.replace(":", " -").replace("หลักสูตร", "").strip()
        filename = f"B Tools_{title_clean}.docx"
        
        tmp_dir = tempfile.mkdtemp()
        output_filepath = os.path.join(tmp_dir, filename)
        template_docx = get_template_docx_path()
        
        generate_doc(data, output_filepath, template_path=template_docx)
        
        encoded_filename = urllib.parse.quote(filename)
        headers = {
            "Content-Disposition": f"attachment; filename*=UTF-8''{encoded_filename}"
        }
        return FileResponse(
            path=output_filepath,
            filename=filename,
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            headers=headers
        )
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=400, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)
