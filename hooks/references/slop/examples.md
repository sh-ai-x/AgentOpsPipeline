# slop-detector v2 — before/after examples (regression fixtures)

These exist as `tests/fixtures/slop/sample-with-slop.md` and `tests/fixtures/slop/sample-clean.md` (committed by `tests/test_slop_detector.py`). Kept here as canonical examples for human review.

## 1. Throat-clearing + Binary contrast

**Before:**
> "Here's the thing: building products is hard. Not because the technology is complex. Because people are complex. Let that sink in."

**After:**
> "Building products is hard. Technology is manageable. People aren't."

## 2. Filler + unnecessary reassurance

**Before:**
> "It turns out that most teams struggle with alignment. The uncomfortable truth is that nobody wants to admit they're confused. And that's okay."

**After:**
> "Teams struggle with alignment. Nobody admits confusion."

## 3. Business jargon stack

**Before:**
> "In today's fast-paced landscape, we need to lean into discomfort and navigate uncertainty with clarity. This matters because your competition isn't waiting."

**After:**
> "Move faster. Your competition is."

## 4. False agency (inanimate thing acting human)

**Before:**
> "The complaint becomes a fix within days. The data tells us the bet lives or dies quickly. The decision emerges from the culture."

**After:**
> "The team fixed it within days. The data shows shipping teams beat concept teams two to one. The PM called it on Thursday and shipped Friday."

## 5. Lazy extremes + passive voice

**Before:**
> "Everyone always wants a robust, comprehensive solution. It is widely believed that decisions are reached by committee. Nobody designed this to be slow."

**After:**
> "Most teams want a working fix. The platform committee approved this last quarter. We never set out to be slow."

## 6. Korean structural crutches

**Before:**
> "오늘날의 빠르게 변하는 시대에 우리는 강력한 기능을 도입했습니다. 종합적인 분석 결과 다양한 이점을 제공합니다. 중요한 것은 핵심적으로 성능입니다."

**After:**
> "새 기능을 출시했습니다. 분석 결과 속도가 2배 빨라졌습니다."

## 7. Clean baseline (0 findings)

> "We added webhook signing yesterday. The HMAC secret lives in env, the SDK wraps it on serialize, and the verify endpoint rejects mismatches in 2 ms. PR is up; review by EOD."
