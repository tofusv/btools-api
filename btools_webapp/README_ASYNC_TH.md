# อัปเดตแก้ไฟล์ใหญ่ค้างที่ [PROCESSING]

> รุ่นปรับ parser ที่อยู่ในเครื่องล่าสุด: [คู่มือวิเคราะห์โครงสร้างด้วยข้อความอ้างอิง](README_REFERENCE_TH.md) ยังไม่ได้ deploy ออนไลน์ คิวและข้อจำกัด Render Free ด้านล่างยังใช้เหมือนเดิม

## เหตุผลที่ต้องเปลี่ยนทั้งสองฝั่ง

Google Apps Script ทำงานได้สูงสุด 6 นาทีต่อรอบ แต่โค้ดเดิมรอให้ Render เรียก Gemini และสร้าง Word เสร็จใน HTTP request เดียว เมื่อหมดเวลา Google จะหยุดทั้งรอบ การคืนชื่อไฟล์ใน catch จึงไม่ทันทำงาน

รุ่นนี้ส่งข้อความไป `/api/jobs` แล้วรับรหัสงานกลับทันที Render ประมวลผลในเบื้องหลัง ส่วน trigger รอบถัดไปตรวจสถานะ เมื่อสำเร็จจึงดาวน์โหลดและบันทึกลง Drive งานอาจใช้เวลาหลายรอบได้โดยไม่ต้องเปิดคอมพิวเตอร์รอ

## ติดตั้งบน Render ก่อน

1. อัปเดตไฟล์ `app.py` และเพิ่ม `job_store.py` ในโปรเจคที่ Render ใช้อยู่ เก็บ `generate_course_outline.py`, `templates/` และ `requirements.txt` ไว้ด้วย หากใช้ GitHub ให้อัปเดตใน repository เดิมแล้วรอ deploy
2. ถ้า Root Directory คือ `btools_webapp` ให้ใช้ Build Command `pip install -r requirements.txt` และ Start Command:

   ```sh
   uvicorn app:app --host 0.0.0.0 --port $PORT --workers 1
   ```

   ต้องใช้ **1 worker และ 1 instance** สำหรับคิวรุ่นนี้ เพราะงานประมวลผลอยู่ใน process เดียว หากต้องการหลาย instance ต้องใช้คิวและที่เก็บผลลัพธ์ภายนอกแทน
3. ในหน้า **Environment** ของบริการ Render เพิ่ม `BTOOLS_API_TOKEN` เป็นข้อความลับยาวที่คุณตั้งเอง เช่น รหัสสุ่มอย่างน้อย 32 ตัวอักษร จดไว้ใช้ค่าเดียวกันใน Apps Script รหัสนี้เป็นรหัสให้ Google ติดต่อเว็บ ไม่ใช่ Gemini API key
4. ไม่ต้องเพิ่ม library สำหรับคิว ใช้ SQLite และ thread ของ Python ซึ่งมีอยู่แล้ว

### ตัวเลือกสำหรับไฟล์ที่ประมวลผลนาน

| Environment variable | ค่าเริ่มต้น | ความหมาย |
| --- | --- | --- |
| `GEMINI_REQUEST_TIMEOUT_SECONDS` | `180` | เวลารออ่านคำตอบ Gemini ต่อครั้ง |
| `GEMINI_TOTAL_TIMEOUT_SECONDS` | `1200` | งบเวลารวมสำหรับการลอง key/model ของหนึ่งงาน ประมาณ 20 นาที |
| `GEMINI_MAX_OUTPUT_TOKENS` | `8192` | ความยาวคำตอบสูงสุด หากพบ `output was truncated` ให้เพิ่มภายในขีดจำกัดของโมเดลที่ใช้อยู่ หรือแบ่งเอกสารตามวัน/หมวด |
| `BTOOLS_JOB_DIR` | โฟลเดอร์ `job_data` ใกล้ `app.py` | ที่เก็บสถานะและ Word ที่เสร็จแล้ว |

สำหรับเอกสารยาวที่พบ `Gemini output was truncated` ให้ตั้ง `GEMINI_MAX_OUTPUT_TOKENS=65536` และ `GEMINI_REQUEST_TIMEOUT_SECONDS=300` บน Render แล้ว deploy การตั้งค่าใหม่ โดยตรวจขีดจำกัดของโมเดลที่ใช้อยู่ด้วย [Gemini 3.6 Flash รองรับ output สูงสุด 65,536 tokens](https://ai.google.dev/gemini-api/docs/models/gemini-3.6-flash) งานที่เสียไประหว่าง deploy จะถูกส่งใหม่โดย trigger รอบถัดไป

ระบบแก้การรอเกิน 6 นาที แต่ยังต้องอยู่ภายในขีดจำกัดของ Gemini และหน่วยความจำของ Render ไม่มีการตัดข้อความต้นฉบับเพื่อให้ไฟล์เล็กลง หาก Gemini ตอบไม่ครบเพราะ token limit งานจะแจ้งข้อผิดพลาดแทนการส่งไฟล์ที่ขาดเนื้อหา

### ใช้ได้ทั้ง Free และบริการที่มีพื้นที่เก็บถาวร

หากไม่ทราบแพ็กเกจ ให้เริ่มจากค่าเริ่มต้นได้ ระบบตรวจงานทุก 5 นาที และเมื่อ Render รีสตาร์ตจะลองส่งงานที่เสียไปใหม่ สูงสุด 3 รอบเพิ่มเติม ก่อนเปลี่ยนเป็น `[SKIP]`

Render Free มีพื้นที่ชั่วคราว สถานะและผลลัพธ์จะหายเมื่อ restart/redeploy ไม่สามารถรับประกันว่าทุกงานจะรอดทุกครั้งได้ ถ้าบริการมี Persistent Disk ให้ mount ที่ `/var/data` และตั้ง `BTOOLS_JOB_DIR=/var/data/btools_jobs` ผลลัพธ์ที่เสร็จแล้วจะอยู่ข้าม restart ส่วนงานที่ยังทำอยู่จะถูกระบุว่า failed และ Google ส่งใหม่ เพราะข้อความต้นฉบับกับ Gemini key ไม่ได้ถูกเก็บลงดิสก์

เก็บผลลัพธ์บน Render 7 วัน แล้วลบผลลัพธ์เก่าเมื่อมีการรับงานใหม่ ไฟล์ที่บันทึกใน Google Drive แล้วไม่ได้ถูกลบตาม

## อัปเดต Google Apps Script

1. คัดลอก `google_drive_automation/Code.gs` รุ่นใหม่ทั้งหมดแทนโค้ดเดิม
2. เติม 5 ค่าที่ต้นไฟล์:
   - `INPUT_FOLDER_ID`: โฟลเดอร์ขาเข้าเดิม
   - `OUTPUT_FOLDER_ID`: โฟลเดอร์ขาออกเดิม
   - `RENDER_API_URL`: URL เว็บ Render เช่น `https://ชื่อเว็บ.onrender.com` (URL เดิมที่ลงท้าย `/api/format_text` ใช้ได้เช่นกัน)
   - `GEMINI_API_KEY`: key เดิมของคุณ
   - `BTOOLS_API_TOKEN`: รหัสลับค่าเดียวกับ Environment บน Render
3. บันทึก แล้วเลือกฟังก์ชัน `recoverStuckFiles` กด **Run หนึ่งครั้ง** หลังอัปเดต Render เสร็จ เพื่อเอา `[PROCESSING]_` ออกจากไฟล์เก่าที่ไม่มีรหัสงาน ฟังก์ชันนี้ไม่แตะงานใหม่ที่ระบบกำลังติดตาม
4. รัน `processNewCourseOutlines` หนึ่งครั้งเพื่อทดสอบ คง trigger เดิม **ทุก 5 นาที** ไว้ ใช้ handler เดิม ไม่ต้องสร้าง trigger เพิ่ม
5. หากไฟล์ที่ค้างเคยถูกสร้างใน Output แล้ว ให้ตรวจ Output ก่อนกู้ไฟล์เก่า เพราะระบบเดิมไม่มีรหัสงานให้จับคู่ผลลัพธ์

## สิ่งที่ควรเห็นใน log

รอบแรก: `รับงานแล้ว: ... | Job ... | queued/processing` แล้วรอบนั้นจบ

รอบถัดไป: `ยังทำงานอยู่: ... | processing` หรือ `บันทึกสำเร็จ: ...` พร้อมชื่ออินพุตเปลี่ยนเป็น `[DONE]_`

ถ้าเซิร์ฟเวอร์หาย/รีสตาร์ต: log แจ้ง `เซิร์ฟเวอร์ไม่พบงานเดิม` หรือ `Server restarted` แล้วใช้ `[RETRY_1]_` เพื่อส่งใหม่

ถ้าเห็น HTTP 401/503: ตรวจว่าค่า `BTOOLS_API_TOKEN` ตรงกันและ Render deploy โค้ดใหม่แล้ว อย่าล้าง Script Properties ขณะมีงานกำลังทำ เพราะตรงนั้นเก็บรหัสสำหรับตรวจผล

รองรับงานค้างไม่เกิน 2 ไฟล์พร้อมกันและรับใหม่สูงสุด 1 ไฟล์ต่อรอบ เพื่อลดการชนโควต้า งานทั้งหมดประมวลผลทีละไฟล์ มี Script Lock ป้องกัน trigger สองรอบทำไฟล์เดียวกัน

## ทดสอบโดยไม่ใช้ Gemini จริง

```sh
pip install -r requirements.txt httpx
python tests/test_background_jobs.py
node ../google_drive_automation/tests/test_automation.js
```

ชุดทดสอบครอบคลุมการรับงานใหญ่โดยไม่รอ AI, ส่งซ้ำหลัง response หาย, คิวเต็ม, งานล้มเหลว, restart, ผลลัพธ์หมดอายุ, Word จริงจาก AI จำลอง, คำตอบถูกตัด, polling หลายรอบ, ไฟล์ว่าง, กู้ชื่อค้าง และหยุดกลางทางหลังบันทึกผลลัพธ์

อย่าใช้ test discovery รวมทั้งโปรเจค: `test_models.py` และ `test_user_keys.py` เดิมมีการเรียก Gemini จริง

เอกสารอ้างอิง: [Google Apps Script quotas](https://developers.google.com/apps-script/guides/services/quotas), [Render Free](https://render.com/docs/free), [Render Persistent Disks](https://render.com/docs/disks)
