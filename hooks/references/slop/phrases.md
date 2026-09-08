# slop-detector v2 — PHRASE bank (SSOT, line-delimited ERE)
#
# Format: one POSIX ERE per non-comment line. `# ` and blank lines are skipped
# at load time via `grep -vE '^[[:space:]]*#|^[[:space:]]*$'`.
#
# Categories mirror hardikpandya/stop-slop reference (CC BY Hardik Pandya, MIT).
# Patterns are detection-only; the deliverable is the marker, not the fix.

# === Throat-clearing openers (KO + EN) ===
Here's the thing[,:]
Here's what
Here's this
Here's that
Here's why
(?:The )?uncomfortable truth is(?: that)?
It turns out(?: that)?
(?:The )?real [a-z]+ is
Let me be clear
(?:The )?truth is[,:]
I'll say it again
(?:I'm going to be|I'm being) honest
Can we talk about
Here's what I find interesting
Here's the problem though
At the end of the day
(?:The )?bottom line is
(?:Let me|Let's) (?:explain|break this down|walk you through)
In today's [^.]+ landscape
In the (?:modern|current|today's) [^.]+
오늘날의 [^,]+ 시대에
한마디로 말하면
솔직히 말하면
(?:핵심은|핵심 )입니다

# === Emphasis crutches ===
(?:Full stop|Period)\.
Let that sink in
This matters because
Make no mistake
Here's why that matters
(?:It's|That is) worth (?:noting|saying|mentioning|emphasizing)
(?:Importantly|Crucially|Importantly,|Crucially,)
(?:It is important to note|Notably,)
(?:And|But) here's the (?:thing|real issue|reality)
잊지 마세요
주목할 (?:점은|만한 점은|필요가 있습니다)
눈여겨볼 (?:점이|만합니다)

# === Business jargon ===
navigate (?:the )?(?:challenges?|complexities?|uncertainties?|landscape)
unpack(?:ing)?
lean into
game-?changer
double down
deep dive
take a step back
moving forward
in the (?:fast-paced|ever-evolving|rapidly changing|modern) (?:landscape|world|era|environment)
a (?:paradigm|framework|holistic|robust) (?:shift|approach|solution|methodology)
synerg(?:y|ies)
synergistic(?:ally)?
best-?in-?class
cutting-?edge
best practices?
leverage
robust
comprehensive(?:ly)?
seamlessly
unleash
empower(?:ing|ment)?
revolutioniz(?:e|ing|ed)
elevat(?:e|ing|ed)
landscape
tapestry
across (?:the )?(?:board|industry|globe)
[[:space:]]+시대를 (?:열다|이끌다|주도하다)
종합적인 (?:[[:alnum:]_]+ )?(?:분석|검토|이해)
강력한 (?:[[:alnum:]_]+ )?(?:기능|역량|효과)
세련된 (?:[[:alnum:]_]+ )?(?:솔루션|접근|전략)
(?:최첨단|혁신적인) (?:[[:alnum:]_]+ )?(?:기술|솔루션|접근)

# === Adverbs / softeners / intensifiers (kill -ly words + named offenders) ===
(?:really|just|literally|genuinely|honestly|simply|actually|deeply|truly|fundamentally|inherently|basically|essentially|absolutely|completely|totally|definitely|certainly|clearly|obviously|evidently|apparently|presumably|undeniably|undoubtedly)
(?:very|quite|rather|pretty|fairly|somewhat|kind of|sort of|a bit)
(?:너무|매우|아주|되게|진짜|굉장히|상당히|꾹꾹|꼼꼼하게|철저히|완전히|확실히|분명히|당연히|실로|과연)

# === Sentence-final permission / hand-holding ===
(?:And|But) that's (?:okay|fine|alright|alright|expected|normal)\.
(?:That is|It's) (?:okay|fine|alright|expected|normal)\.
(?:Don't worry|No worries|Fear not|Fret not)[,!.]
(?:No need to worry|No need to fear)(?:\.|[[:space:]])
걱정하지 마세요
(?:그러면|그럼) (?:됩니다|되겠죠)

# === Meta-joiners (essay-leak) ===
(?:In this (?:article|post|essay|section|chapter),? (?:we |I )?(?:will|shall|going to))
(?:The rest of (?:this|the) (?:article|post|essay|section)|Going forward)
(?:As (?:we|one) (?:can )?see|as (?:we|one) (?:can )?(?:imagine|envision)|as mentioned earlier|as previously stated)
(?:In conclusion,?|To (?:summarize|conclude|wrap up),?)

# === Cleanup obituaries / vague declaratives ===
(?:Hope|This) helps?!
(?:Hopefully|Idealistically),(?: this| that| it)?
(?:It is|It's) (?:important|essential|crucial|paramount|imperative|vital) (?:to )?(?:note|remember|understand|recognize|acknowledge) that
(?:The |A )(?:implications?|consequences?|outcomes?|considerations?|takeaways?) (?:are|is) (?:significant|profound|substantial|far-?reaching|enormous)\.

# === Wh-starters (sentence-level — first word) ===
^[ ]*(?:What|When|Where|Which|Who|Why|How)

# === Em-dash overuse (count separately as rhythm signal) ===
—
–
