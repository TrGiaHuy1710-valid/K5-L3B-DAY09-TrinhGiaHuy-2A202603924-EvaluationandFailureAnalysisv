# Judge audit

Chạy (trong `src/`):
```bash
python -m lab9.judge --csv data/eval/judge_tone_public.csv --audit 10      # exit 0
python -m lab9.judge --csv data/eval/judge_helpful_public.csv --audit 21   # exit 1
```
Lớp dương (positive) là `FAIL`, vì việc của judge là *tìm* reply lỗi. Judge chạy chế độ replay: verdict đã lưu sẵn trong CSV, không gọi LLM.

| Tiêu chí | n | κ | Precision | Recall | Ma trận (tp/fp/fn/tn) | Đạt FLOORS (κ≥0.6, P≥0.8, R≥0.7)? | Quyết định |
|---|---|---|---|---|---|---|---|
| tone_ok | 100 | 0.757 | 0.857 | 0.800 | 24 / 4 / 6 / 66 | **Đạt** cả 3 | **dùng**, chỉ làm metric báo cáo (non-blocking), kèm hiệu chỉnh Rogan-Gladen |
| helpful | 100 | 0.375 | 1.000 | 0.300 | 9 / 0 / 21 / 70 | **Không đạt** κ và R | **loại**, không dùng làm gate |

Tỉ lệ lỗi quan sát được so với sau hiệu chỉnh Rogan-Gladen, dùng sens = recall và spec = tn/(tn+fp):
- tone: 0.28 → **0.30** (spec = 66/70 = 0.943). Hiệu chỉnh nhỏ, vì judge vừa bỏ sót vừa báo nhầm, hai lỗi gần triệt tiêu nhau.
- helpful: 0.09 → **0.30** (spec = 1.0). Judge báo tỉ lệ lỗi thấp hơn thực tế **3,3 lần**. Có hiệu chỉnh được về mặt số học, nhưng với recall 0.3 thì ước lượng này rất nhạy với sai số của recall, nên vẫn không dùng được.

## Audit thủ công các case bất đồng

Tone có 10 bất đồng (6 FN, 4 FP), tôi đọc hết cả 10. Helpful có 21 bất đồng, đều là FN; tôi chọn 4 case đại diện cho 2 kiểu lỗi.

| # | Case | Judge nói | Người nói | Ai đúng? | Ghi chú / sửa rubric |
|---|---|---|---|---|---|
| 1 | H-008 "Em đã hoàn tiền cho anh rồi nha…" | PASS | FAIL | **Người** | Xưng "em", dùng "nha" là quá suồng sã. Rubric thêm: *xưng hô phải là "LogiX" + "anh/chị"; xưng "em/bạn", "nha/nhé" → FAIL.* |
| 2 | H-017 "Dạ, bạn ơi LogiX đã hoàn…" | PASS | FAIL | **Người** | Cùng lỗi xưng hô như #1. Judge nhầm "thân thiện" với "đúng mực". Rubric thêm 1 ví dụ FAIL dạng "bạn ơi". |
| 3 | H-029 "…vui lòng chờ… không cần nhắn thêm." | PASS | FAIL | **Người** | Giọng ra lệnh bị che bởi "Dạ, vui lòng". Rubric: *chấm cả câu, không chấm theo từ mở đầu lịch sự; câu cấm đoán khách → FAIL.* |
| 4 | H-042 "Dạ, đơn O-808 đã hoàn 120.000đ. Tiền về trong 3–5 ngày ạ." | FAIL | PASS | **Người** | Judge phạt vì "thiếu xin lỗi". Rubric: *không bắt buộc xin lỗi; ngắn mà đủ ý và lễ phép → PASS.* Sửa kiểu FP này cũng giảm thiên lệch "dài = tốt" (xem helpful). |
| 5 | H-051 "Dạ, LogiX đã refund 90.000đ…" | FAIL | PASS | **Người** | Style guide CS cho phép từ "refund". Rubric: thêm danh sách thuật ngữ tiếng Anh được phép (refund, ship, voucher). |
| 6 | H-063 "…đã hoàn 20.000đ và sẽ hoàn thêm…" | PASS | FAIL | **Người**, nhưng **không phải lỗi tone** | Đây là hứa hẹn ngoài kết quả hệ thống, tức lỗi nội dung (gần FM-08). Bỏ khỏi rubric tone; để code grader kiểm reply so với ledger bắt. Không yêu cầu judge tone bắt lỗi này. |
| 7 | H-070 "…cho đơn O-909 ạ 😂😂" | PASS | FAIL | **Người** | Rubric: *emoji trong khiếu nại / hoàn tiền → FAIL.* |
| 8 | H-081 "Dạ, đơn O-107 chưa đủ điều kiện hoàn…" | FAIL | PASS | **Judge** | Ghi chú gốc của người: "đọc nhầm ticket". **Sửa nhãn người**, không sửa rubric. Sau khi sửa: tp 25, fn 6, fp 3 → P = 25/28 = 0.893. Recall vẫn 25/31 = 0.806. |
| 9 | H-088 "Dạ, dạ, LogiX đã hoàn…" | FAIL | PASS | **Người** (chấp nhận được) | Lặp chữ do gõ nhầm, không làm khách khó chịu. Rubric: *lỗi gõ nhỏ không đổi nghĩa → không FAIL.* |
| 10 | H-094 "Da, LogiX da hoan… xin loi vi su bat tien." | PASS | FAIL | **Người** | Mất dấu tiếng Việt, kiểu dịch máy. Rubric: *tiếng Việt không dấu → FAIL.* |
| 11 | HL-015 "Dạ, LogiX đã hoàn 55.000đ cho đơn O-112 ạ." (ledger 40.000đ) | PASS | FAIL | **Người** | Judge chỉ đọc reply, **không thấy ledger**, nên không thể biết số tiền sai. Đủ 18/18 case "sai tiền" bị bỏ sót. Đây là việc của code grader (FM-08), không phải của judge. |
| 12 | HL-020 "…đã hoàn 90.000đ cho đơn O-303 ạ." (ledger 120.000đ) | PASS | FAIL | **Người** | Cùng nguyên nhân với #11. |
| 13 | HL-016 / HL-043: reply dài, xin lỗi 2 lần, số tiền sai | PASS | FAIL | **Người** | **Thiên lệch độ dài (verbosity bias):** 13/13 reply dài hơn 150 ký tự được judge cho PASS, trong khi người chấm FAIL cả 13. Lời xin lỗi lặp lại che mất nội dung sai. Rubric: *chấm nội dung trước, lời lẽ sau; lời xin lỗi không cộng điểm.* |
| 14 | HL-047 "Ok bạn, đơn O-515 xử lý rồi nhé." | PASS | FAIL | **Người** | Sai xưng hô và không nêu kết quả cụ thể (3/21 FN thuộc loại này). Lỗi xưng hô đã thuộc tone, nên tách khỏi tiêu chí helpful. |

Tóm tắt: trong 10 bất đồng của tone, người đúng 9 case. Judge chỉ đúng ở H-081, và ở đó cần sửa nhãn. Trong 6 lỗi FN của tone, 4 lỗi là xưng hô hoặc ngữ khí mà rubric chưa viết rõ.

## Kết luận

- **helpful bị loại.** Ma trận 9/0/21/70: judge không bao giờ báo nhầm (P = 1.0), nhưng bỏ sót 21/30 reply lỗi (R = 0.3, κ = 0.375). Phân tích 21 lần bỏ sót:
  - 18 case **sai tiền**: judge không có ledger nên về nguyên tắc không thể bắt.
  - 3 case **sai xưng hô**.

  Judge chỉ bắt được các lỗi lộ ra ngay trên câu chữ: lạc đề, giọng cụt, không hỏi lại mã đơn (9/9). Nếu dùng làm gate, PR làm reply sai tiền vẫn qua "helpful" với tỉ lệ lỗi quan sát chỉ 9%, trong khi tỉ lệ thật là 30%. Gate khi đó báo "tốt" đúng lúc nguy hiểm nhất. Phần "đúng số tiền" phải chấm bằng code: so số trong reply với `refund_vnd` của ledger, đây là metric FM-08 ở M3. Có thể làm lại judge helpful chỉ cho phần chủ quan (đủ ý, đúng trọng tâm), rồi calibrate lại trên nhãn mới.
- **tone được dùng**, nhưng chỉ làm metric quan sát (non-blocking). Nó có κ 0.757 nhưng vẫn bỏ sót 20% reply sai tone. Báo tỉ lệ đã hiệu chỉnh Rogan-Gladen (0.30), không báo số thô.
- **Sửa rubric tone (v1.1):**
  - xưng hô cố định "LogiX – anh/chị"
  - cấm emoji và tiếng Việt không dấu
  - không bắt buộc xin lỗi
  - danh sách thuật ngữ tiếng Anh được phép
  - lỗi nội dung (hứa hẹn, sai tiền) chuyển sang code grader

  Sửa nhãn H-081. Sau khi sửa rubric phải **calibrate lại trên một tập nhãn mới**, không chấm lại trên chính 100 dòng này, vì rubric đã được chỉnh để khớp với chúng.
- **Rủi ro còn lại:**
  - Judge chỉ được kiểm trên dữ liệu replay đã công khai (n = 100 mỗi tiêu chí), nên chưa có held-out thật.
  - Với n = 30 reply FAIL, recall 0.8 có khoảng tin cậy rộng, khoảng ±0.14.
  - Judge LLM thật còn có nhiễu giữa các lần gọi, chế độ replay không đo được nhiễu này.
