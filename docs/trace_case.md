# Trace case: từ trace tới quyết định sai đầu tiên

Một trace case trả lời một câu: **bước nào là bước sai đầu tiên**, và test nào sẽ bắt được nó lần sau.

```bash
cd src
python -m lab9.trace_case --shape seeded_regression --claim C-014 --seed 11
python -m lab9.trace_case --shape fixed --claim C-014 --seed 11   # đối chứng
```

Trace của trial lỗi (`seeded_regression`):
```
== seeded_regression C-014@11  lab8 grader: FAIL (proposal_mismatch)
   1 handoff
   2 investigator       lookup_order O-515: delivered_late, delay 5, damage_verified true
   3 quote              {"amount_vnd": 150000, "clause_ids": ["SHIP-LATE-03", "DMG-04"], ...}
   4 refund_history     {"refund_count": 1, "refunded_vnd": 30000}
   5 proposal           {"amount_vnd": 120000}
   6 reply              {"text": "Dạ, LogiX đã hoàn 120.000đ cho đơn O-515."}
-- ledger vs label
  refund_vnd     ledger=90000    label=120000   <-- differs
  status         result=resolved label=resolved
```

## Case: `seeded_regression` C-014@11

| Trường | Nội dung |
|---|---|
| Trial | `seeded_regression C-014@11` (item E-014). Report `src/reports/eval_seeded_regression.json`, run ID `E-seeded_regression-20261119-1bea`. Dòng `E-014@11`: `refund_amount_correct=false`, `pass_rate=false`, `reply_amount_matches_ledger=false`. |
| Triệu chứng | Lab 8 chỉ báo `proposal_mismatch`. Status `resolved` khớp nhãn, nên nhìn status thì tưởng đúng. **Ledger** ghi 90.000đ trong khi nhãn là 120.000đ: khách bị thiếu 30.000đ. Reply nói "đã hoàn 120.000đ", tức là reply nói một số mà ledger không có (FM-08 là hệ quả đi kèm). |
| Bước sai đầu tiên | **#5 `proposal {"amount_vnd": 120000}`**: agent tự trừ 30.000đ đã hoàn trước đó khỏi quote 150.000đ, rồi mới gọi host. |
| Vì sao là bước *đầu tiên* | Mọi bước trước đó đều đúng. #2 đọc đúng đơn O-515 từ DB (không có `model_override`). #3 quote = 150.000đ là entitlement đúng theo luật "lấy số lớn hơn" (max(ship 30.000, DMG-04 150.000)), không cộng. #4 `refund_history` là một read tool hợp lệ và trả đúng 30.000đ. Sai bắt đầu ở #5: luật nghiệp vụ yêu cầu truyền **quote đầy đủ** vào `issue_refund`, vì host tự áp trần theo đơn. Agent trừ trước nên host trừ thêm lần nữa: 150.000 − 30.000 − 30.000 = 90.000. |
| Failure mode | **FM-05 pre_deducted** (layer orchestration/state). FM-08 xuất hiện như hệ quả ở #6. |
| Đối chứng | `fixed C-014@11`: #3 quote 150.000đ, **không có event `proposal`**, quote đầy đủ đi thẳng tới host. Host trừ 30.000đ một lần, ledger = 120.000đ, #4 reply "đã hoàn 120.000đ". Cả ledger và reply đều đúng. |
| Regression test | `src/tests/test_lab9_trace_case.py` (marker `student`, chạy trong job `eval-gate`): `test_pre_deducted_c014_is_caught` kiểm 3 điều: event `proposal` đứng ngay sau `refund_history`, `proposal` nhỏ hơn quote, ledger = 90.000. Nó cũng kiểm `RefundAmountCorrect` và `ReplyAmountMatchesLedger` đều trả FAIL. `test_fixed_c014_passes_with_full_quote` kiểm `fixed` không có `proposal`, ledger = 120.000, cả hai grader PASS. Đã chạy: 2/2 pass, nghĩa là grader fail trên variant lỗi và pass trên `fixed`. Item E-014 đã nằm trong eval set với `provenance.from_trace = "seeded_regression:C-014@11"`. |
| Chưa chắc chắn | Trace không cho biết *vì sao* agent chọn tự trừ: MockLLM không có lập luận, đây là công tắc lỗi gài sẵn. Với LLM thật, cần log prompt hoặc tool-plan để phân biệt "hiểu sai luật" với "đọc history rồi tự suy diễn". Trace cũng chỉ chứng minh lỗi trên một đơn có đúng 1 refund trước đó. Đơn có nhiều refund trước, hoặc khi trần theo đơn rơi xuống 0 (C-013, ra `proposal 0`, `denied` mà nhãn cũng là `denied`), chỉ bị bắt qua `proposal_mismatch`, không qua ledger. |

## Quy tắc

- Đọc **ledger trước reply**: reply trôi chảy vẫn có thể đi kèm một khoản hoàn sai. Case này là ví dụ đúng như vậy: reply "120.000đ" nghe hợp lý, ledger 90.000đ.
- "Bước sai đầu tiên" phải dẫn số event cụ thể, không phải "agent bị nhầm".
- Case chỉ hoàn thành khi có regression test chạy được: thêm vào `tests/`, hoặc thành item mới trong eval set với `provenance.from_trace`.
