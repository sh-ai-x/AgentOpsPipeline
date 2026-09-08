# slop-detector v2 — STRUCTURE bank (SSOT, line-delimited ERE)
#
# Loaded as `grep -oE -f <(grep -vE '^[[:space:]]*#|^[[:space:]]*$' structures.md)`.
# Each pattern catches a *shape* — not just a phrase. Severity is medium by default;
# the `audit --slop-only` mode (inlined into skills/inspect/SKILL.md (--slop)) re-weights them.
#
# Categories mirror hardikpandya/stop-slop reference (MIT).

# === Binary contrasts (negation-then-assertion crutch) ===
[Nn]ot (?:just|only|merely) [a-z]+ but (?:also )?
[Nn]ot because
[Nn]ot (?:a|an|the) [^.,;]{1,40}\.[[:space:]]+(?:But|It's|It is|Actually)
The answer (?:isn't|is not) [^.,;]{1,60}\.[[:space:]]*(?:It's|It is|It’s|Its)
(?:The |A )?(?:real |actual )?(?:question|problem|issue|secret|truth|challenge) (?:isn't|is not|wasn't|was not) [^.,;]{1,60}\.[[:space:]]*(?:It's|It is|It’s|Its)
(?:It|That) (?:feels like|seems like|looks like) [^.,;]{1,40}\.[[:space:]]*(?:It's|It is|It’s|Actually|But)
(?:stops|stopped) being [^.,;]{1,40} and (?:starts|started) being
(?:doesn't|does not|don't|do not) mean [^.,;]{1,40},?[[:space:]]*(?:but|it means|but actually|but actually it means)
(?:is|are|was|were) (?:about|not about) [^.,;]{1,40} (?:but (?:not )?)
(?:isn't|is not|ain't) (?:a |an |the )?[A-Za-z]+\.[[:space:]]*(?:It's|It is|It's a|It’s a)

# === Negative listing / rhetorical striptease ===
(?:[Nn]ot (?:a |an )?[A-Za-z]+\.[[:space:]]*){2,}[Aa] [A-Za-z]
(?:[Ii]t wasn't (?:a |an )?[A-Za-z]+\.[[:space:]]*){2,}[Ii]t was [A-Za-z]

# === Dramatic fragmentation ===
[A-Za-z]+\.[[:space:]]+That's it\.[[:space:]]+That's the
(?:^|[.!?][[:space:]]+)[A-Z][^.!?]{1,20}\.[[:space:]]+(?:And|Then)[^.!?]{1,20}\.[[:space:]]+(?:And|Then)[^.!?]{1,20}\.
This unlocks something
(?:And|But|So)[[:space:]]+(?:then|here's)[[:space:]]+(?:the thing|what happened)

# === Rhetorical setups ===
What if [a-z]+\?
Here's what I mean
Think about it[,.:!]
(?:Now |So )?imagine (?:a |the )?
Consider (?:this|that|the following)
(?:여러분도|혹시|생각해) (?:알고 계시(?:나요|죠)|보셨나요|계시죠)

# === False agency (inanimate thing doing a human verb) ===
(?:the )?(?:complaint|bug|issue|ticket|feature|design|architecture|process|system|culture|conversation|decision|strategy|trend|shift|change|update|movement) (?:becomes?|became|lives?|emerges?|shifts?|moves?|feels?|sounds?|wants?|needs?|tells?|speaks?|responds?|rewards?|punishes?|drives?|invites?|asks?|admits?|insists?|imagines?|dreams?)
(?:the )?data (?:tells|shows|says|reveals|confirms)
(?:the )?market (?:rewards|punishes|chooses|decides|demands|signals)
(?:the )?code (?:tells|shows|says|reveals|breaks|fixes)
(?:the )?future (?:becomes?|holds?|brings?|is|means|belongs)

# === Passive voice markers (low-confidence — only flag suspicious combos) ===
(?:[a-z]+ed|[a-z]+en) (?:by |through |via )?(?:the |a |an )?(?:system|team|committee|board|community|stakeholder|user|customer|developer|engineer|manager|company|organization)
It (?:is|was) (?:said|believed|thought|known|assumed|argued|noted|observed|reported|claimed|suggested|expected|estimated|seen|found) that
(?:Mistakes|Errors|Decisions|Trade-?offs|Problems|Issues|Solutions|Features|Tickets) (?:were|are) (?:made|taken|raised|caught|found|identified|solved|resolved|mishandled|overlooked|ignored|discovered)
(?:was|were) (?:created|built|designed|developed|implemented|shipped|deployed|launched|introduced|removed|deleted|migrated|consolidated|merged|split|broken|fixed|refactored|rewritten)[[:space:]]+(?:by|in|at|on)

# === Narrator-from-a-distance ===
[Nn]o one (?:designed|planned|intended|meant|wanted) this
(?:This|That|It) happens? because
This is why
People tend to
Some (?:say|argue|believe|claim|think)
There are (?:some|many|many|many|many|many)? (?:who|people|teams|developers|users|customers) (?:who )?(?:say|believe|argue|claim|think)

# === Lazy extremes (false authority) ===
(?:every|every single|every single one of the|all|each|each and every)[[:space:]]+(?:[a-z]+ ?){0,3}(?:in (?:the|this))?
(?:always|never|invariably|constantly|forever|endlessly)
(?:everyone|everything|everywhere|everybody|nobody|nothing|nowhere|nobody|anyone|anything|anywhere|anybody)

# === Three-item lists (verbose AI cadence) ===
(?:^|[.!?][[:space:]]+|\n)(?:[A-Za-z][A-Za-z' -]{1,30},[[:space:]]+){2}[A-Za-z][A-Za-z' -]{1,30}\.

# === Rhythm: em-dash density (count, not single match) ===
(?:—|--|–)

# === KO structural crutches ===
(?:것이 아니라|것이 아닌|것이 아니라|것이 아니다)[[:space:]]+(?:것[[:space:]]*입니다|것[[:space:]]*입니다|것[[:space:]]*이오|것이오)\.
(?:중요한 것은|핵심은)[[:space:]]+[^.]+[[:space:]]*(?:것입니다|것이다|것이오)\.
(?:다양한|여러|각종)[[:space:]]+[^.]+(?:등(?:을|이)|등등)\.
(?:이것|저것)[[:space:]]+때문입니다?
(?:반드시|꼭)[[:space:]]+(?:기억|생각|염두|명심)하시(?:기 바랍니다|어 주세요|기를 바랍니다)\.
