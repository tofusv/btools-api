# การกู้คืนงานบนแผนฟรี

รุ่นนี้ใช้ Render Free เดิม, Google Drive เดิม และ trigger ทุก 5 นาที ไม่ต้องเพิ่ม disk, database หรือบริการแบบเสียเงิน

## วิธีทำงาน

1. Apps Script เก็บสำเนาต้นฉบับที่ใช้ประมวลผลในโฟลเดอร์ `_BTools_Recovery` ภายใน Output ก่อนส่งงาน สำเนาไม่มี API key
2. Render วิเคราะห์ด้วย AI แล้วส่งสถานะ `checkpoint_ready` โดยยังไม่สร้าง Word
3. Apps Script บันทึก checkpoint ที่มีลายเซ็นลง Drive ก่อนส่งงานสร้าง Word ด้วย request ID ใหม่
4. เมื่อ Render รีสตาร์ต ระบบส่งสำเนาและ checkpoint เดิมกลับไปสร้าง Word ได้โดยไม่เรียก Gemini ซ้ำ
5. บันทึกรายงานตรวจและ Word ด้วย marker กันไฟล์ซ้ำ เมื่อเปลี่ยนต้นฉบับเป็น DONE/REVIEW และล้างสถานะแล้ว จึงย้ายสำเนากู้คืนของงานนั้นไปถังขยะ

ไฟล์กู้คืนอยู่ภายใต้สิทธิ์โฟลเดอร์ Output เดิม ไม่มีการเปิดแชร์เพิ่ม งานที่พักหรือผิดพลาดยังเก็บสำเนาไว้ ส่วนไฟล์ที่อยู่ในถังขยะยังใช้พื้นที่ Drive จนกว่าจะถูกลบตามวงจรของ Drive

## เมื่อเกิดข้อผิดพลาด

- Render ยังไม่พร้อม / HTTP 503 / คิวเต็ม: เก็บ request ID เดิมและเว้นช่วงลองใหม่แบบเพิ่มระยะ พร้อม jitter
- Gemini 429: พักอย่างน้อย 15 นาที เพิ่มได้ถึงประมาณ 6 ชั่วโมง โดยไม่ใช้สิทธิ์ retry ของเอกสาร ไม่คาดเดาเวลาที่โควต้าบัญชีจะ reset
- Key หรือสิทธิ์ผิด / checkpoint ไม่ตรง / AI ตอบถูกตัด: ใช้สถานะ ATTENTION เพื่อให้แก้เหตุ ไม่วนเรียกซ้ำ
- งานประมวลผลผิดพลาดอื่น: ลองเพิ่มไม่เกิน 3 รอบ แล้วพักเป็น ATTENTION โดยยังเก็บ checkpoint
- Worker มีเพดานเวลาจริง 1,500 วินาทีต่อขั้น ระบบ kill และรอ process จบก่อนปล่อยช่องคิว จึงไม่ส่งงานทับ worker ที่ยังทำอยู่

เลือก `showJobStatus` ใน Apps Script แล้ว Run เพื่อดูขั้นตอนล่าสุด เวลา retry และเหตุที่พัก เลือก `resumePausedJobs` หลังแก้ configuration เพื่อกลับมาทำต่อโดยรักษาสำเนาไว้

## ข้อจำกัด

- หาก Render หยุดก่อน Apps Script ดาวน์โหลด checkpoint ลง Drive สำเร็จ ยังต้องวิเคราะห์ AI ใหม่
- เวลาเสร็จขึ้นกับ cold start, trigger, Gemini และโควต้าของบัญชี ไม่มี SLA
- checkpoint ผูกกับเนื้อหาต้นฉบับและ `BTOOLS_API_TOKEN` เดิม หากเปลี่ยน token checkpoint เก่าจะใช้ไม่ได้
- การเปลี่ยนต้นฉบับระหว่างประมวลผลไม่เปลี่ยน snapshot ของงานที่รับแล้ว
- Worker เป็น process ย่อยในบริการ Free เดิม ไม่ใช่บริการ Background Worker เพิ่ม
- คง uvicorn `--workers 1` และหนึ่ง instance: SQLite/คิวนี้ยังไม่ได้ออกแบบสำหรับหลาย process ที่รับงานพร้อมกัน
- ตรึงเวอร์ชัน dependency หลักใน requirements.txt; dependency ทางอ้อมยังใช้ resolver ของ pip

## อัปเดตและย้อนกลับ

Deploy backend ก่อน แล้วอัปเดต Code.gs โดยรักษาค่าตั้งค่า 5 ค่าและ manifest เดิม ไม่ต้องสร้าง trigger เพิ่มหรือเปลี่ยนแพ็กเกจ

Backend รองรับ client รุ่นเดิมด้วย หากต้องย้อนกลับ ให้นำ Apps Script รุ่นเดิมกลับก่อน แล้วจึง rollback backend งาน checkpoint ที่ค้างควรเก็บสำเนาไว้และตรวจ Output ก่อนส่งใหม่

## ทดสอบ

ใช้เฉพาะ tests/test_background_jobs.py, tests/test_reference_parser.py, tests/test_processing_failures.py, tests/test_free_recovery.py และ ../google_drive_automation/tests/test_automation.js

ห้ามใช้ discovery รวมสคริปต์ legacy ที่เรียก Gemini จริง ชุดทดสอบเอกสารจริงต้องมีไฟล์ DOCX ใน workspace และ verification_reference/source.docx ตามชุดทดสอบเดิม
