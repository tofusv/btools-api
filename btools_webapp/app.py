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
    from generate_course_outline import generate_doc
except ImportError:
    from .generate_course_outline import generate_doc

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
        "gemini-1.5-flash",
        "gemini-1.5-pro",
        "gemini-1.5-flash-8b"
    ]
    
    prompt = """
    วิเคราะห์และแยกโครงสร้างข้อมูลหลักสูตร (Course Outline) จากข้อความต่อไปนี้ให้อยู่ในรูปแบบ JSON ที่มีโครงสร้างดังนี้:
    {
      "course_title_th": "ชื่อหลักสูตรภาษาไทย (ตัดคำว่า หลักสูตร ออก)",
      "course_title_en": "ชื่อหลักสูตรภาษาอังกฤษ",
      "instructor": "ชื่อวิทยากร (ถ้ามี)",
      "duration_info": "รายละเอียดความยาวหลักสูตร เช่น 1 วัน (09.00-16.00 น.)",
      "sections_order": ["rationale", "objectives", "agenda", "learning_methods", "workshop_activities", "target_audience", "duration", "equipment", "additional_sections", "expected_outcomes"],
      "rationale": [
        {"text": "ย่อหน้าบรรยาย"}, 
        {"bullets": ["ข้อย่อย 1", "ข้อย่อย 2"]},
        {
          "table": {
            "headers": ["คอลัมน์ 1", "คอลัมน์ 2"],
            "rows": [["ข้อมูล 1", "ข้อมูล 2"]]
          }
        }
      ],
      "objectives": [
        {
          "title": "หัวข้อรอง H3 (เช่น รู้ คิด ทำ)",
          "sub_bullets": [
            "ข้อย่อย H4 (ห้ามใส่ a. b. c. นำหน้า ให้ลบตัวอักษรนำออกทั้งหมด)"
          ]
        }
      ],
      "expected_outcomes": [
        {
          "title": "หัวข้อรอง H3 (ถ้ามี)",
          "sub_bullets": [
            "ข้อย่อย H4"
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
      "workshop_activities": [
        {
          "title": "ชื่อกิจกรรม Workshop",
          "description": "ย่อหน้าบรรยาย (ถ้ามี)",
          "bullets": ["ข้อย่อย 1", "ข้อย่อย 2"]
        }
      ],
      "target_audience": ["กลุ่มเป้าหมาย 1"],
      "duration": ["ระยะเวลา 1 วัน (ถ้ามีเขียนแยกไว้)"],
      "equipment": ["อุปกรณ์ที่ต้องเตรียม (ถ้ามี)"],
      "additional_sections": [
        {
          "title": "ชื่อหัวข้ออื่นๆ ที่อยู่นอกเหนือจากหมวดหลัก (จับยัดมาไว้ในนี้ให้หมด ห้ามทิ้ง!)",
          "description": "เนื้อหาบรรยาย (ถ้ามี)",
          "bullets": ["ข้อย่อย 1", "ข้อย่อย 2"],
          "table": {
            "headers": ["คอลัมน์ 1", "คอลัมน์ 2"],
            "rows": [["ข้อมูล 1", "ข้อมูล 2"]]
          }
        }
      ]
    },
    "sections_order": [
      "rationale",
      "objectives",
      "topics",
      "agenda",
      "learning_methods",
      "target_audience",
      "duration",
      "equipment",
      "workshop_activities",
      "teaching_style",
      "expected_outcomes",
      "remarks",
      "additional_sections"
    ]
    
    กฎเหล็กในการแยกโครงสร้างเนื้อหา (Strict Formatting Rules - MUST FOLLOW):
    1. บทบาทของคุณคือ "ตัวแยกแยะข้อมูล" (Data Parser) หน้าที่ของคุณคือ "คัดลอก (Copy) และ วาง (Paste)" ข้อความจากต้นฉบับเป๊ะๆ ห้ามสรุปความ ห้ามตัดตอน ห้ามเรียบเรียงประโยคใหม่ และห้ามแต่งประโยคเติมเองเด็ดขาด!
    2. ห้ามใช้สัญลักษณ์ขีด (-) หรือจุด (•) นำหน้าข้อความเด็ดขาด ให้ตัดทิ้งไปเลย (ระบบจัดหน้าจะใส่ Bullet ให้อัตโนมัติ) แต่หากต้นฉบับใช้ตัวเลขหรือตัวอักษรนำหน้า ให้คุณคงตัวเลข/ตัวอักษรนั้นไว้
    3. ลำดับหัวข้อ: H2 คือชื่อหมวดหลัก -> H3 คือหัวข้อรอง -> H4 คือข้อย่อยใต้ H3
    4. ตรวจสอบความซ้อนของหัวข้อใน Agenda อย่างละเอียดที่สุด
    5. รูปแบบผลลัพธ์ต้องเป็น JSON ที่ valid เท่านั้น
    6. การตีความหัวข้อ (Semantic Mapping): ดึงเนื้อหาไปใส่หมวดที่ถูกต้องตามความหมาย ห้ามทิ้ง
    7. การเน้นข้อความ (Bold Text): ให้คุณใส่เครื่องหมายดอกจันคู่ครอบคำเพื่อทำตัวหนา เช่น **ข้อความ** โดยอิงตามต้นฉบับเป็นหลัก
    8. ห้ามแต่งหัวข้อใหม่ หรือพิมพ์ชื่อหมวดหมู่ซ้ำ
    9. ห้ามสร้างข้อมูลซ้ำซ้อน: ข้อมูลที่ดึงไปใส่ในตาราง Agenda แล้ว ห้ามนำไปสร้างเป็นหัวข้อ H2 ซ้ำอีก
    10. การเรียงลำดับหัวข้อ: ให้ส่งฟิลด์ sections_order เรียงลำดับตามต้นฉบับเป็นหลัก
    
    ข้อความต้นฉบับ:
    """ + raw_text

    api_keys_list = [k.strip() for k in api_key.split(",") if k.strip()]
    if not api_keys_list:
        api_keys_list = [api_key]

    last_error = None
    
    for model in models_to_try:
        for key_idx, current_key in enumerate(api_keys_list):
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={current_key}"
            payload = {
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {
                    "responseMimeType": "application/json",
                    "temperature": 0.0,
                    "maxOutputTokens": 8192
                }
            }
            
            try:
                print(f"กำลังส่งข้อมูลหา {model} (Key {key_idx+1}/{len(api_keys_list)})...", flush=True)
                response = requests.post(url, json=payload, timeout=60)
                
                if response.status_code == 200:
                    data = response.json()
                    text_out = data["candidates"][0]["content"]["parts"][0]["text"]
                    
                    text_out = text_out.strip()
                    if text_out.startswith("```json"):
                        text_out = text_out[7:]
                    elif text_out.startswith("```"):
                        text_out = text_out[3:]
                    if text_out.endswith("```"):
                        text_out = text_out[:-3]
                    text_out = text_out.strip()
                        
                    parsed_data = json.loads(text_out)
                    parsed_data["_ai_model_used"] = model
                    return parsed_data
                else:
                    error_msg = response.text
                    last_error = f"{model} (Key {key_idx+1}) failed: {response.status_code}"
                    print(f"Error {model} ({response.status_code}): {error_msg[:100]}")
                    continue
                    
            except Exception as e:
                print(f"Exception with {model} Key {key_idx+1}: {e}")
                last_error = str(e)
                continue
            
    raise ValueError(f"ไม่สามารถประมวลผลด้วย Gemini API ได้: {last_error}")

class FormatTextRequest(BaseModel):
    raw_text: str
    api_key: Optional[str] = None

@app.post("/api/format_text")
def format_course_text(req: FormatTextRequest):
    try:
        if not req.raw_text.strip():
            raise HTTPException(status_code=400, detail="raw_text is empty")
            
        api_keys_str = ""
        if req.api_key:
            api_keys_str += req.api_key + ","
        if os.getenv("GEMINI_API_KEY"):
            api_keys_str += os.getenv("GEMINI_API_KEY")
            
        if not api_keys_str.strip(", "):
            raise HTTPException(status_code=400, detail="Missing API Key in both Request and Environment")

        data = call_gemini_api(req.raw_text, api_keys_str)
        
        title = data.get("course_title_en") or data.get("course_title_th") or "Course Outline"
        title_clean = re.sub(r'[\r\n\t/\\:*?"<>|]', ' ', str(title)).replace("หลักสูตร", "").strip()
        title_clean = re.sub(r'\s+', ' ', title_clean)
        if not title_clean:
            title_clean = "Course Outline"
            
        ai_model_used = data.get("_ai_model_used", "gemini-unknown")
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
            "Content-Disposition": f"attachment; filename*=UTF-8''{encoded_filename}",
            "X-AI-Model-Used": str(ai_model_used),
            "Access-Control-Expose-Headers": "Content-Disposition, X-AI-Model-Used"
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
            
        ai_model_used = data.get("_ai_model_used", "gemini-unknown")
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
            "Content-Disposition": f"attachment; filename*=UTF-8''{encoded_filename}",
            "X-AI-Model-Used": str(ai_model_used),
            "Access-Control-Expose-Headers": "Content-Disposition, X-AI-Model-Used"
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
