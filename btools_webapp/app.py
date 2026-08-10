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
        "gemini-3.6-flash",
        "gemini-3.5-flash",
        "gemini-3.5-flash-lite"
    ]
    
    prompt = """
    วิเคราะห์และแยกโครงสร้างข้อมูลหลักสูตร (Course Outline) จากข้อความต่อไปนี้ให้อยู่ในรูปแบบ JSON ที่มีโครงสร้างดังนี้:
    {
      "course_title_th": "ชื่อหลักสูตรภาษาไทย (ตัดคำว่า หลักสูตร ออก)",
      "course_title_en": "ชื่อหลักสูตรภาษาอังกฤษ",
      "instructor": "ชื่อวิทยากร (ถ้ามี)",
      "duration_info": "รายละเอียดความยาวหลักสูตร เช่น 1 วัน (09.00-16.00 น.)",
      "sections_order": ["rationale", "objectives", "agenda", "learning_methods", "workshop_activities", "target_audience", "duration", "equipment", "additional_sections", "expected_outcomes"],
      "rationale": [{"text": "ย่อหน้าบรรยาย"}, {"bullets": ["ข้อย่อย 1", "ข้อย่อย 2"]}],
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
          "bullets": ["ข้อย่อย 1", "ข้อย่อย 2"]
        }
      ]
    }
    
    กฎเหล็กในการแยกโครงสร้างเนื้อหา (Strict Formatting Rules - MUST FOLLOW):
    1. บทบาทของคุณคือ "ตัวแยกแยะข้อมูล" (Data Parser) ไม่ใช่ผู้แต่งเนื้อหาใหม่ ให้ใช้วิธี **"คัดลอก (Copy) และ วาง (Paste)"** ข้อความจากต้นฉบับเป๊ะๆ ห้ามสรุปความ ห้ามตัดตอน ห้ามเรียบเรียงประโยคใหม่เด็ดขาด! (อนุญาตให้แก้แค่คำที่สะกดผิดเท่านั้น)
    2. วิทยากรแต่ละคนจะมีสไตล์การเขียนไม่เหมือนกัน หน้าที่ของคุณคือมองหาว่าข้อความไหนคือ "วัตถุประสงค์" ข้อความไหนคือ "หัวข้อ (Agenda)" แล้วจับข้อความนั้นยัดลง JSON โครงสร้างของเราให้ถูกต้อง โดยที่เนื้อหาต้องคงเดิมทุกตัวอักษร
    3. ห้ามใช้สัญลักษณ์ขีด (-) หรือจุด (•) นำหน้าข้อความเด็ดขาด ให้ตัดทิ้งไปเลย (ระบบจัดหน้าจะใส่ Bullet ให้อัตโนมัติ) แต่หากต้นฉบับใช้ "ตัวเลข" (เช่น 1. 2. 3.) หรือ "ตัวอักษร" (เช่น a. b. c.) ให้นำหน้า ให้คุณคงตัวเลข/ตัวอักษรนั้นไว้ ห้ามตัดทิ้ง!
    4. ลำดับหัวข้อ: H2 คือชื่อหมวดหลัก -> H3 คือหัวข้อรอง (เช่น รู้ คิด ทำ) -> H4 คือข้อย่อยใต้ H3
    5. ตรวจสอบความซ้อนของหัวข้อใน Agenda อย่างละเอียดที่สุด:
       - หากมีหัวข้อหลักแล้วมีข้อย่อยซ้อนลงไปอีกชั้น (เช่น "ความคาดหวัง..." แล้วมีข้อย่อย "นิยาม..." และ "ผลกระทบ...") **ต้องจัดให้อยู่ในรูปแบบวัตถุ {"title": "ความคาดหวัง...", "sub_topics": ["นิยาม...", "ผลกระทบ..."]}** ห้ามดึงออกมาวางเป็นหัวข้อเรียงระนาบเดียวกันเด็ดขาด!
    6. รูปแบบผลลัพธ์ต้องเป็น JSON ที่ valid เท่านั้น
    7. **การตีความหัวข้อ (Semantic Mapping):** วิทยากรแต่ละคนอาจใช้คำเรียกหัวข้อไม่เหมือนกัน ให้คุณจับคู่ความหมายให้เข้ากับ Key ใน JSON โดยอัตโนมัติ เช่น:
       - `objectives` = วัตถุประสงค์, เป้าหมาย, สิ่งที่ผู้เรียนจะทำได้
       - `expected_outcomes` = ประโยชน์ที่ได้รับ, ผลลัพธ์ที่คาดหวัง, สิ่งที่องค์กรจะได้
       - `learning_methods` = รูปแบบการอบรม, วิธีการสอน, สัดส่วนการเรียนรู้
       - `target_audience` = ผู้เข้าอบรม, กลุ่มเป้าหมาย, ผู้ที่เหมาะสม
       - `workshop_activities` = กิจกรรมกลุ่ม, ฝึกปฏิบัติ, Workshop, กรณีศึกษา
       หากเจอหัวข้อชื่อแปลกๆ แต่ความหมายตรงกับหมวดไหน ให้ดึงเนื้อหาไปใส่หมวดนั้นได้เลย ห้ามทิ้ง!

    *** คำเตือนขั้นเด็ดขาด (CRITICAL INSTRUCTIONS) ***
    - ZERO TRUNCATION: คุณต้องอ่านต้นฉบับตั้งแต่บรรทัดแรกจนบรรทัดสุดท้าย และคัดลอกมาให้ครบทั้ง "ชื่อหัวข้อ" และ "เนื้อหา/ข้อย่อยด้านใน" ทุกตัวอักษรแบบ 100% ห้ามดึงมาแค่ชื่อหัวข้อแล้วทิ้งเนื้อหาข้างในเด็ดขาด! ห้ามย่อ ห้ามตัดจบ ห้ามข้าม ห้ามละไว้ในฐานที่เข้าใจ การตัดเนื้อหาทิ้งแม้แต่ประโยคเดียวถือเป็นความล้มเหลวร้ายแรง!
    - NO HALLUCINATION: ห้ามแต่งเติมเนื้อหาหรือคิดหัวข้อขึ้นมาเองเด็ดขาด ให้ดึงเฉพาะข้อความที่มีอยู่จริงในต้นฉบับเท่านั้น! หากหมวดใดไม่มีเนื้อหา ให้เว้นว่างเป็น Array ว่าง []
    
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
            
            for attempt in range(2): # ลองใหม่สูงสุด 2 ครั้งต่อ Key
                try:
                    print(f"กำลังส่งข้อมูลหา {model} (Key {key_idx+1}/{len(api_keys_list)} - ครั้งที่ {attempt+1})...")
                    response = requests.post(url, json=payload, timeout=60)
                    
                    if response.status_code == 200:
                        data = response.json()
                        text_out = data["candidates"][0]["content"]["parts"][0]["text"]
                        
                        # ลบ Markdown backticks เผื่อ AI ตอบกลับมาพร้อมฟอร์แมต
                        text_out = text_out.strip()
                        if text_out.startswith("```json"):
                            text_out = text_out[7:]
                        elif text_out.startswith("```"):
                            text_out = text_out[3:]
                        if text_out.endswith("```"):
                            text_out = text_out[:-3]
                        text_out = text_out.strip()
                            
                        parsed_data = json.loads(text_out)
                        parsed_data["_ai_model_used"] = model  # Inject the model name
                        parsed_data["_keys_loaded"] = len(api_keys_list)
                        if model != models_to_try[0] and last_error:
                            parsed_data["_fallback_reason"] = last_error
                        return parsed_data
                    else:
                        error_msg = response.text
                        last_error = f"{model} (Key {key_idx+1}) failed: {response.status_code}"
                        
                        if response.status_code in (404, 403, 400):
                            print(f"ข้าม {model} เนื่องจากไม่มีสิทธิ์ใช้งานหรือไม่มีโมเดลนี้ ({response.status_code})")
                            break # ข้ามไปโมเดลถัดไป
                        elif response.status_code == 429:
                            if len(api_keys_list) > 1 and key_idx < len(api_keys_list) - 1:
                                print(f"ติด Rate Limit 429 สำหรับ Key {key_idx+1}: สลับไปใช้ Key {key_idx+2} ทันที!")
                            else:
                                print(f"Key ทั้งหมดของ {model} โควต้าเต็ม (429) แล้ว! กำลังข้ามไปใช้โมเดลถัดไป...")
                            break # ข้ามไป Key หรือ Model ถัดไปทันที
                            
                        print(f"เกิดข้อผิดพลาดกับ {model} ({response.status_code}): รอ 8 วินาทีแล้วลองใหม่... - {error_msg}")
                        time.sleep(8)
                        
                except Exception as e:
                    print(f"Exception with {model} Key {key_idx+1}: {e}")
                    last_error = str(e)
                    time.sleep(5)

            
    raise ValueError(f"ไม่สามารถประมวลผลด้วย Gemini API ได้ครบทุกโมเดล: {last_error}")

class FormatTextRequest(BaseModel):
    raw_text: str
    api_key: Optional[str] = None

@app.post("/api/format_text")
def format_course_text(req: FormatTextRequest):
    try:
        if not req.raw_text.strip():
            raise HTTPException(status_code=400, detail="raw_text is empty")
            
        # Merge API keys from request and environment variables
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
        fallback_reason = data.get("_fallback_reason", "")
        if fallback_reason:
            err_code = re.search(r'failed: (\d+)', fallback_reason)
            err_code_str = err_code.group(1) if err_code else "ERR"
            filename = f"B Tools_{title_clean} ({ai_model_used} x {err_code_str}).docx"
        else:
            filename = f"B Tools_{title_clean} ({ai_model_used}).docx"
        
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
            
        ai_model_used = data.get("_ai_model_used", "gemini-unknown")
        fallback_reason = data.get("_fallback_reason", "")
        if fallback_reason:
            err_code = re.search(r'failed: (\d+)', fallback_reason)
            err_code_str = err_code.group(1) if err_code else "ERR"
            filename = f"B Tools_{title_clean} ({ai_model_used} x {err_code_str}).docx"
        else:
            filename = f"B Tools_{title_clean} ({ai_model_used}).docx"
        
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
