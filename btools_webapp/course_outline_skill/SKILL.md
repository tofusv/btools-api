---
name: course-outline-generator
description: Generate standardized, professionally formatted Course Outline documents (.docx) based on B Tools prototype template, complete with official Header, Footer, Page Numbers, exact Margins, and 2-line Expected Outcomes section.
---

# Course Outline Generator Skill

This skill provides standard formatting, guidelines, and an automated generator script for creating Course Outline documents (`.docx`) following the official prototype design (`B Tools_หลักสูตร Data Analysis for Better Results.docx`).

> [!IMPORTANT]
> **Strict Styling & Layout Rules**:
> 1. **Font**: All text, headings, titles, bullet points, and tables MUST strictly use the **`Sarabun`** font ONLY.
> 2. **Margins**:
>    - Top Margin: 0.787 in (~2.0 cm)
>    - Bottom Margin: 0.59 in (~1.5 cm)
>    - Left Margin: 0.787 in (~2.0 cm)
>    - Right Margin: 0.787 in (~2.0 cm)
>    - Header Distance: 1.378 in (~3.5 cm)
>    - Footer Distance: 0.787 in (~2.0 cm)
> 3. **Header (หัวกระดาษ)**: Includes the official B Tools top graphic banner (`header_banner.jpg`).
> 4. **Footer (ท้ายกระดาษ)**:
>    - Left: Official Website URL (`www.btoolstraining.com`)
>    - Right: Dynamic Page Number field (`PAGE`)
>    - Bottom: Official B Tools bottom graphic banner (`footer_banner.jpg`)
> 5. **Heading Font Hierarchy**:
>    - **H1**: 13pt Bold (เฉพาะชื่อหลักสูตรตอนเริ่มต้น `หลักสูตร: ...` เท่านั้น)
>    - **H2**: 12pt Bold (หัวข้อหลักประจำ Section เช่น `หลักการและเหตุผล`, `วัตถุประสงค์`, ` Agenda`, `ผลลัพธ์ที่คาดว่าจะได้รับ` ฯลฯ)
>    - **Subhead หลัง H2**: 10pt Regular (`เมื่อจบหลักสูตร ผู้เข้าอบรมจะสามารถ`, `เมื่อสิ้นสุดการอบรม ผู้เข้าอบรมจะสามารถ`)
>    - **H3**: 10pt Bold (หัวข้อย่อย เช่น Header ตาราง `เวลา/รายละเอียด`, ชื่อ Module `Module 1: ...`, ชื่อ Workshop `Workshop 1: ...`)
>    - **Body & Bullets**: 10pt Regular
> 6. **Native Word Bullet List (<w:numPr>)**:
>    - All bullet points MUST strictly use Word's native bullet list structure (`<w:numPr><w:ilvl w:val="0"/><w:numId w:val="1"/></w:numPr>`) instead of plain text bullet characters (`• `).
>    - **Bullet Alignment with Paragraph Indent**: รายการ Bullet ที่ต่อจากย่อหน้าบรรยาย ให้ตั้งค่าระยะร่น `left_indent = 0.5 in` และ `first_line_indent = -0.25 in` เพื่อให้ตัวข้อความเริ่มต้นที่แนวระยะ 0.5 นิ้ว ตรงตามแนว Tab ย่อหน้าของเนื้อหาบรรยายด้านบนอย่างสวยงาม
>    - Bullets inside table cells MUST be flush left with minimal indentation (`left_indent = 0.12 in`, `first_line_indent = -0.12 in`) so they do not have the large indent of standard body bullets.
> 7. **Table Margin Alignment & Column Formatting (การจัดแนวตารางพอดีขอบหน้ากระดาษ)**:
>    - **ระยะย่อหน้าตาราง (tblInd & tblW)**: ขอบตารางฝั่งซ้ายและฝั่งขวา ต้องจัดวางพอดีกับแนวเส้นขอบหน้ากระดาษ (Page Margins) 100% โดยกำหนด Table Left Indent (`tblInd`) เป็น `0 dxa` และความกว้างรวมของตาราง (`tblW`) เป็น **6.65 นิ้ว** (9576 dxa)
>    - **ตาราง 2 คอลัมน์ (เวลา | รายละเอียด)**: คอลัมน์ 1 (เวลา) กว้าง **1.55 นิ้ว** (2232 dxa) จัดกึ่งกลาง (Center) เพื่อไม่ให้คำว่า `น.` ตกบรรทัด และ คอลัมน์ 2 กว้าง **5.10 นิ้ว** (7344 dxa)
>    - **ตาราง 1 คอลัมน์ (รายละเอียด)**: คอลัมน์ 1 กว้าง **6.65 นิ้ว** (9576 dxa) เต็มความกว้างพื้นที่พิมพ์พอดี
> 8. **Workshop Formatting in Agenda Table**:
>    - In Agenda Col 2, Workshop heading `Workshop (ชื่อเรื่อง): ` MUST be **Bold**, while the following normal description text MUST be **Regular (Not bold)**.
> 9. **Strict Source Content & Structure Rules**:
>    - **ลำดับหัวข้อ H2 ตามต้นฉบับ (Exact H2 Section Sequence)**: ลำดับหัวข้อ H2 ทั้งหมดในเอกสาร ต้องเรียงลำดับจากบนลงล่างตามต้นฉบับ 100% **ห้ามสลับตำแหน่งหัวข้อโดยเด็ดขาด** (เช่น หากต้นฉบับเรียง Section 4 เป็น "ประโยชน์ที่ได้รับ" และ Section 5 เป็น "คอร์สนี้เหมาะสำหรับ" ต้องจัดวาง Section 4 ก่อน Section 5 เสมอ)
>    - **ห้ามสร้างไฟล์ที่ถูกลบไปแล้วใหม่ (No Recreating Deleted Files)**: เมื่อทำการประมวลผลหรือจัดหน้า ให้สร้างหรืออัปเดตเฉพาะ **ไฟล์คอร์สที่ผู้ใช้งานสั่งล่าสุด** เท่านั้น ห้ามรันสคริปต์ย้อนหลังเพื่อสร้างไฟล์คอร์สเก่าที่ผู้ใช้งานลบทิ้งจากเครื่องหรือ Google Drive ไปแล้วขึ้นมาใหม่เด็ดขาด
>    - **รูปแบบชื่อไฟล์ผลลัพธ์ (Output Filename Rule)**: ชื่อไฟล์ทั้งหมดต้องใช้รูปแบบ **`B Tools_[ชื่อหลักสูตร].docx`** โดยให้สิทธิ์ **ชื่อหลักสูตรภาษาอังกฤษ (EN) ก่อนเสมอ** หากไม่มีภาษาอังกฤษ จึงใช้ชื่อหลักสูตรภาษาไทย (ตัดคำว่า `หลักสูตร` และอัญประกาศออก)
>    - **Footer Formatting**: ข้อความ `www.btoolstraining.com` ใน Footer ต้องเป็นฟอนต์ **Sarabun 12pt ตัวหนา (Bold)** และเลขหน้าเป็นฟิลด์อัตโนมัติ (`PAGE`) ขนาด **Sarabun 10pt** จัดวางตำแหน่ง **ชิดขวาล่าง (Right Aligned)** พอดีกับขอบขวาของหน้ากระดาษ (ด้วย Right Tab Stop 6.92 นิ้ว) อย่างสวยงาม
>    - **ระยะห่างบรรทัดว่าง (Blank Lines Font & Size)**: บรรทัดว่าง/บรรทัดเว้นระยะห่างทั้งหมดในเอกสาร ต้องกำหนดฟอนต์และขนาดเป็น **Sarabun 10pt** ทั้งหมด ห้ามปล่อยให้เป็น Noto Sans หรือ 12pt เด็ดขาด
>    - **การทำตารางสำหรับ Module (Module Table Rule)**: หากหมวดเนื้อหาหลักสูตรประกอบด้วย เลขที่ Module, ชื่อ Module และเนื้อหาใน Module ให้จัดทำเป็น **ตารางเนื้อหาหลักสูตร (Module Table)** โดยหัวข้อ Module เป็นตัวหนา (10pt Bold) และเนื้อหาย่อยเป็น Native Word Bullet (`<w:numPr>`) 10pt Regular ชิดขอบซ้ายช่องตาราง
>    - **การสร้างตารางและหมวดหมู่ (Table vs List Rule)**: หากต้นฉบับไม่ได้จัดทำเป็นตาราง หรือไม่ได้มีองค์ประกอบของ Module/Part ไว้ ห้ามสร้างตารางขึ้นเอง ให้จัดทำเป็นรายการ Native Word Bullet (`<w:numPr>`) โดยตรงตามต้นฉบับ
>    - **Rationale Formatting**: หมวด `หลักการและเหตุผล` ให้จัดรูปแบบเป็น **ย่อหน้าบรรยายปกติ** (ย่อหน้าบรรทัดแรก 0.5 นิ้ว, ระยะห่างบรรทัด 1.5 เท่า) เป็นหลัก โดยหากมีหัวข้อย่อยย่อยภายในเนื้อหา ให้จัดเป็นรายการ **Native Word Bullet (`<w:numPr>`)**
>    - **Subhead หลัง H2**: ห้ามเติมคำหรือข้อความต่อใต้ H2 เอง (เช่น `เมื่อจบหลักสูตร...`) หากในต้นฉบับไม่มีข้อความนั้น
>    - **การแก้ไขคำผิด (Typo Correction)**: ช่วยแก้ไขคำที่พิมพ์ตกหล่น/สะกดผิดจากต้นฉบับได้ แต่ต้องสรุปแจ้งรายการคำที่แก้ไขให้ผู้ใช้งานทราบเสมอทุกครั้ง

## Key Sections Required

1. **Course Titles**:
   - `course_title_th`: Thai Course Title (Prefix: `หลักสูตร: `)
   - `course_title_en`: English Course Title & Subtitle
2. **หลักการและเหตุผล (Rationale)**: 3-4 structured paragraphs with 0.5in indent and 1.5x spacing.
3. **วัตถุประสงค์ (Objectives)**: 
   - Heading: `วัตถุประสงค์`
   - Subhead: `เมื่อจบหลักสูตร ผู้เข้าอบรมจะสามารถ`
   - Bullet points.
4. **กลุ่มเป้าหมาย / ผู้เข้าอบรม (Target Audience)**: Bullet points listing target roles.
5. **รูปแบบการเรียนรู้ (Learning Methods)**: Ratios and methods.
6. **Framework ที่ใช้ (Frameworks)**: List of key frameworks taught.
7. **Agenda (Table Format)**:
   - 2 Columns: `เวลา` (Time) and `รายละเอียด` (Details).
   - Time slots: `09.00 - 10.30 น.`, `10.30 - 12.00 น.`, `13.00 - 14.30 น.`, `14.30 - 16.00 น.`.
   - Table padding and 1.35x line spacing inside cells with explicit 1pt black borders.
8. **Workshop Activities**: Detailed title and summary of each hands-on workshop session.
9. **ผลลัพธ์ที่คาดว่าจะได้รับ (Expected Outcomes)**: 2-line header structure followed by actionable bullet points.

## Automated Generation Script

```bash
python C:/Users/Sert-windows/.gemini/antigravity/scratch/skills/course_outline_generator/scripts/generate_course_outline.py data.json output.docx
```
