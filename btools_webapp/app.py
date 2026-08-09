import os
import re
import sys
import json
import time
import tempfile
import urllib.parse
import requests
from fastapi import FastAPI, Form, Request, HTTPException
from fastapi.responses import HTMLResponse, FileResponse
from pydantic import BaseModel
from typing import Optional

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

def call_gemini_api(raw_text: str, api_key: str) -> dict:
    models_to_try = [
        "gemini-2.5-pro",
        "gemini-2.0-pro-exp-0205",
        "gemini-1.5-pro",
        "gemini-2.0-flash",
        "gemini-1.5-flash"
    ]
    
    prompt = """
    วิเคราะห์และแยกโครงสร้างข้อมูลหลักสูตร (Course Outline) จากข้อความต่อไปนี้ให้อยู่ในรูปแบบ JSON ที่มีโครงสร้างดังนี้:
    {
      "course_title_th": "ชื่อหลักสูตรภาษาไทย (ตัดคำว่า หลักสูตร ออก)",
      "course_title_en": "ชื่อหลักสูตรภาษาอังกฤษ",
      "instructor": "ชื่อวิทยากร (ถ้ามี)",
      "duration_info": "รายละเอียดความยาวหลักสูตร เช่น 1 วัน (09.00-16.00 น.)",
      "sections_order": ["rationale", "objectives", "agenda", "learning_methods", "target_audience"],
      "rationale": [{"text": "ย่อหน้าบรรยาย"}, {"bullets": ["ข้อย่อย 1", "ข้อย่อย 2"]}],
      "objectives": [
        {
          "title": "หัวข้อรอง H3 (เช่น รู้ คิด ทำ)",
          "sub_bullets": [
            "ข้อย่อย H4 (ห้ามใส่ a. b. c. นำหน้า ให้ลบตัวอักษรนำออกทั้งหมด)"
          ]
        }
      ],
      "agenda": [
        {
          "time": "09.00 - 10.30 น.",
          "module_title": "ชื่อหัวข้อหลัก (เช่น ส่วนที่ 1 : ...)",
          "topics": [
            "หัวข้อย่อยระดับแรก (เช่น พฤติกรรมและความคาดหวังของลูกค้ายุคนี้)",
            {
              "title": "หัวข้อที่มีข้อย่อยซ้อน (เช่น ความคาดหวังขององค์กรต่อพนักงานด้านคุณภาพ...)",
              "sub_topics": [
                "ข้อย่อยซ้อน 1 (เช่น นิยามของจิตสำนึกคุณภาพ (Quality Awareness)...)",
                "ข้อย่อยซ้อน 2 (เช่น ผลกระทบและต้นทุนของจิตสำนึกคุณภาพ...)"
              ]
            }
          ],
          "workshop": "รายละเอียด Workshop (ถ้ามี)"
        }
      ],
      "learning_methods": ["รูปแบบ 1", "รูปแบบ 2"],
      "target_audience": ["กลุ่มเป้าหมาย 1"]
    }
    
    กฎเหล็กในการแยกโครงสร้างเนื้อหา (Strict Formatting Rules):
    1. อย่าสร้างข้อความหรือเนื้อหาขึ้นมาเอง ให้อิงตามข้อความต้นฉบับที่ส่งให้เป็นหลัก (แต่สามารถช่วยแก้ไขคำผิด หรือพิมพ์ตกหล่นได้)
    2. ห้ามใช้ตัวอักษรนำภาษาอังกฤษ a. b. c. หรือ a) b) c) นำหน้าข้อความเด็ดขาด! ให้ใช้รูปแบบ bullet หรือ ตัวเลข แทนการใช้ a. b. c. (โดยใน JSON ให้ตัดตัวอักษรนำออก ระบบจัดหน้าจะแปลงเป็น bullet ให้เอง)
    3. ลำดับหัวข้อ: H2 คือชื่อหมวดหลัก -> H3 คือหัวข้อรอง (เช่น รู้ คิด ทำ) -> H4 คือข้อย่อยใต้ H3 (เช่น เพื่อให้ผู้เข้าอบรม...)
    4. ตรวจสอบความซ้อนของหัวข้อใน Agenda อย่างละเอียดที่สุด:
       - หากมีหัวข้อหลักแล้วมีข้อย่อยซ้อนลงไปอีกชั้น (เช่น "ความคาดหวัง..." แล้วมีข้อย่อย "นิยาม..." และ "ผลกระทบ...") **ต้องจัดให้อยู่ในรูปแบบวัตถุ {"title": "ความคาดหวัง...", "sub_topics": ["นิยาม...", "ผลกระทบ..."]}** ห้ามดึงออกมาวางเป็นหัวข้อเรียงระนาบเดียวกันเด็ดขาด!
    5. รูปแบบผลลัพธ์ต้องเป็น JSON ที่ valid เท่านั้น
    
    ข้อความต้นฉบับ:
    """ + raw_text

    last_error = None
    
    for model in models_to_try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "responseMimeType": "application/json",
                "temperature": 0.1
            }
        }
        
        try:
            print(f"กำลังส่งข้อมูลหา {model}...")
            response = requests.post(url, json=payload, timeout=30)
            
            if response.status_code == 429:
                print(f"ติด Rate Limit สำหรับ {model} รอ 8 วินาที...")
                time.sleep(8)
                response = requests.post(url, json=payload, timeout=30)
                
            if response.status_code == 200:
                data = response.json()
                text = data["candidates"][0]["content"]["parts"][0]["text"]
                return json.loads(text)
            else:
                error_msg = response.text
                print(f"เกิดข้อผิดพลาดกับ {model}: {response.status_code} - {error_msg}")
                last_error = f"{model} failed: {response.status_code}"
                
        except Exception as e:
            print(f"Exception with {model}: {e}")
            last_error = str(e)
            
    raise ValueError(f"ไม่สามารถประมวลผลด้วย Gemini API ได้ครบทุกโมเดล: {last_error}")

class FormatTextRequest(BaseModel):
    raw_text: str
    api_key: Optional[str] = None

@app.post("/api/format_text")
def format_course_text(req: FormatTextRequest):
    try:
        if not req.raw_text.strip():
            raise HTTPException(status_code=400, detail="raw_text is empty")
            
        api_key = req.api_key or os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise HTTPException(status_code=400, detail="Gemini API Key is required")
            
        data = call_gemini_api(req.raw_text, api_key)
        
        title = data.get("course_title_en") or data.get("course_title_th") or "Course Outline"
        title_clean = re.sub(r'[\r\n\t/\\:*?"<>|]', ' ', str(title)).replace("หลักสูตร", "").strip()
        title_clean = re.sub(r'\s+', ' ', title_clean)
        if not title_clean:
            title_clean = "Course Outline"
        filename = f"B Tools_{title_clean}.docx"
        
        tmp_dir = tempfile.mkdtemp()
        output_filepath = os.path.join(tmp_dir, filename)
        template_docx = get_template_docx_path()
        
        generate_doc(data, output_filepath, template_path=template_docx)
        
        if not os.path.exists(output_filepath):
            raise RuntimeError(f"FATAL: generate_doc finished but {output_filepath} DOES NOT EXIST on disk!")
            
        file_size = os.path.getsize(output_filepath)
        print(f"✅ Document generated successfully: {output_filepath} (Size: {file_size} bytes)")
        
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
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    return HTMLResponse(content="", status_code=204)

@app.get("/", response_class=HTMLResponse)
def index():
    if os.path.exists(INDEX_HTML_PATH):
        with open(INDEX_HTML_PATH, "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    return HTMLResponse(content="<h1>B Tools Web App</h1><p>UI Template file not found.</p>")

def extract_doc_id(url: str) -> str:
    match = re.search(r'/d/([a-zA-Z0-9_-]+)', url)
    if match:
        return match.group(1)
    raise ValueError("ไม่พบ ID ของ Google Doc ในลิงก์ที่ระบุ กรุณาตรวจสอบลิงก์อีกครั้ง")

def fetch_doc_text(doc_id: str) -> str:
    export_url = f"https://docs.google.com/document/d/{doc_id}/export?format=txt"
    resp = requests.get(export_url, timeout=15, allow_redirects=True)
    if resp.status_code != 200:
        raise ValueError(f"ไม่สามารถเข้าถึง Google Doc ได้ (HTTP Status {resp.status_code})")
    
    text = resp.text
    if "<html" in text.lower() or "accounts.google.com" in resp.url.lower():
        raise ValueError("Google Doc นี้ยังไม่ได้เปิดสิทธิ์การเข้าถึงเป็น 'ทุกคนที่มีลิงก์'")
    
    return text

@app.post("/format")
def format_course(doc_url: str = Form(...)):
    try:
        doc_id = extract_doc_id(doc_url)
        raw_text = fetch_doc_text(doc_id)
        
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise HTTPException(status_code=400, detail="Gemini API Key is missing on the server")
            
        data = call_gemini_api(raw_text, api_key)
        
        title = data.get("course_title_en") or data.get("course_title_th") or "Course Outline"
        title_clean = re.sub(r'[\r\n\t/\\:*?"<>|]', ' ', str(title)).replace("หลักสูตร", "").strip()
        title_clean = re.sub(r'\s+', ' ', title_clean)
        if not title_clean:
            title_clean = "Course Outline"
        filename = f"B Tools_{title_clean}.docx"
        
        tmp_dir = tempfile.mkdtemp()
        output_filepath = os.path.join(tmp_dir, filename)
        template_docx = get_template_docx_path()
        
        generate_doc(data, output_filepath, template_path=template_docx)
        
        if not os.path.exists(output_filepath):
            raise RuntimeError(f"FATAL: generate_doc finished but {output_filepath} DOES NOT EXIST on disk!")
            
        file_size = os.path.getsize(output_filepath)
        print(f"✅ Document generated successfully: {output_filepath} (Size: {file_size} bytes)")
        
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
